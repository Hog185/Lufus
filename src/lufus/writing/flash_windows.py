import subprocess
import os
import glob
import tempfile
import re
from lufus.drives import states
from lufus.lufus_logging import get_logger

log = get_logger(__name__)


def run(cmd):
    log.debug("run: %s", cmd)
    subprocess.run(cmd, check=True)


def _get_wim_size(data_mount: str) -> int:
    """Return size in bytes of install.wim/esd, or 0 if not found."""
    sources_dir = os.path.join(data_mount, "sources")
    for entry in glob.glob(os.path.join(sources_dir, "*")):
        if os.path.basename(entry).lower() in ("install.wim", "install.esd"):
            size = os.path.getsize(entry)
            log.info("Found %s (%d bytes / %.2f GiB)", entry, size, size / (1024**3))
            return size
    log.warning("install.wim/install.esd not found in data partition sources/")
    return 0


def _find_path_case_insensitive(base, *parts):
    current = [base]
    for part in parts:
        next_level = []
        for c in current:
            next_level += [
                p
                for p in glob.glob(os.path.join(c, "*"))
                if os.path.basename(p).lower() == part.lower()
            ]
        current = next_level
    result = current[0] if current else None
    return result


def _fix_efi_bootloader(efi_mount):
    """
    Ensure /EFI/BOOT/BOOTX64.EFI exists - required by UEFI spec.
    Windows ISOs put the bootloader at efi/microsoft/boot/efisys.bin
    but UEFI firmware looks for /EFI/BOOT/BOOTX64.EFI as fallback.
    """
    log.info("EFI bootloader fix: checking %s", efi_mount)
    found_boot_dir = _find_path_case_insensitive(efi_mount, "EFI", "BOOT")
    boot_dir = found_boot_dir or os.path.join(efi_mount, "EFI", "BOOT")
    existing_bootx64 = _find_path_case_insensitive(
        efi_mount, "EFI", "BOOT", "BOOTX64.EFI"
    )
    if existing_bootx64:
        log.info("EFI bootloader fix: BOOTX64.EFI already present at %s", existing_bootx64)
        return

    log.info(
        "EFI bootloader fix: BOOTX64.EFI not found, will attempt to create at %s", boot_dir
    )
    bootx64 = os.path.join(boot_dir, "BOOTX64.EFI")
    run(["sudo", "mkdir", "-p", boot_dir])
    log.info("EFI bootloader fix: created directory %s", boot_dir)

    src = _find_path_case_insensitive(
        efi_mount, "EFI", "Microsoft", "Boot", "bootmgfw.efi"
    )
    if src:
        run(["sudo", "cp", src, bootx64])
        log.info("EFI bootloader fix: copied %s -> %s", src, bootx64)
        return

    log.warning(
        "EFI bootloader fix: could not find bootmgfw.efi, UEFI boot may fail"
    )


def flash_windows(device: str, iso: str, progress_cb=None, status_cb=None) -> bool:
    if not re.match(r"^/dev/(sd[a-z]+|nvme[0-9]+n[0-9]+|mmcblk[0-9]+)$", device):
        raise ValueError(f"Invalid device path: {device}")

    def _emit(pct):
        if progress_cb:
            progress_cb(pct)

    def _status(msg):
        log.info(msg)
        if status_cb:
            status_cb(msg)

    _status(f"flash_windows: starting for device={device}, iso={iso}")

    try:
        iso_size = os.path.getsize(iso)
    except OSError as e:
        log.error("flash_windows: cannot read ISO file: %s", e)
        _status(f"flash_windows: cannot read ISO file: {e}")
        return False

    _status(
        f"flash_windows: ISO size = {iso_size:,} bytes ({iso_size / (1024**3):.2f} GiB)"
    )

    try:
        with (
            tempfile.TemporaryDirectory() as mount_efi,
            tempfile.TemporaryDirectory() as mount_data,
            tempfile.TemporaryDirectory() as host_extract,
        ):
            _status(
                f"flash_windows: temp dirs -> EFI mount={mount_efi}, data mount={mount_data}, extract={host_extract}"
            )

            _status(f"Wiping existing partition table on {device}...")
            run(["sudo", "wipefs", "-a", device])
            _emit(8)

            p_prefix = "p" if "nvme" in device or "mmcblk" in device else ""
            efi = f"{device}{p_prefix}1"
            data = f"{device}{p_prefix}2"

            scheme = getattr(states, "partition_scheme", 0)
            if scheme == 0:
                sfdisk_script = f"""label: gpt
device: {device}
{efi} : size=512M, type=C12A7328-F81F-11D2-BA4B-00A0C93EC93B
{data} : type=EBD0A0A2-B9E5-4433-87C0-68B6B72699C7
"""
                scheme_name = "GPT"
            else:
                sfdisk_script = f"""label: dos
device: {device}
{efi} : size=512M, type=ef, bootable
{data} : type=7
"""
                scheme_name = "MBR"

            _status(
                f"Writing {scheme_name} partition table to {device}: 512MiB EFI (FAT32) + remainder data (NTFS)..."
            )
            subprocess.run(
                ["sudo", "sfdisk", device], input=sfdisk_script.encode(), check=True
            )
            run(["sudo", "partprobe", device])
            _status("partprobe notified kernel of new partition table")
            run(["sudo", "udevadm", "settle"])
            _status("udevadm settled")
            _emit(15)

            _status(f"Partitions: EFI={efi}, data={data}")

            _status(f"Formatting {efi} as FAT32 with label BOOT...")
            run(["sudo", "mkfs.vfat", "-F32", "-n", "BOOT", efi])
            _status(f"Formatting {data} as NTFS with label WINDOWS...")
            ntfs_cmd = None
            for candidate in ["mkfs.ntfs", "mkntfs"]:
                if subprocess.run(["which", candidate], capture_output=True).returncode == 0:
                    ntfs_cmd = candidate
                    break
            if ntfs_cmd is None:
                log.warning("ntfs-3g not found, attempting to install...")
                _status("ntfs-3g not found, attempting to install...")
                pkg_managers = [
                    ["apt-get", "install", "-y", "ntfs-3g"],
                    ["dnf", "install", "-y", "ntfs-3g"],
                    ["pacman", "-S", "--noconfirm", "ntfs-3g"],
                    ["zypper", "install", "-y", "ntfs-3g"],
                ]
                for pm_cmd in pkg_managers:
                    if subprocess.run(["which", pm_cmd[0]], capture_output=True).returncode == 0:
                        subprocess.run(["sudo"] + pm_cmd, check=True)
                        break
                for candidate in ["mkfs.ntfs", "mkntfs"]:
                    if subprocess.run(["which", candidate], capture_output=True).returncode == 0:
                        ntfs_cmd = candidate
                        break
            if ntfs_cmd is None:
                log.error("mkfs.ntfs / mkntfs not found. Install ntfs-3g: sudo pacman -S ntfs-3g")
                raise FileNotFoundError("mkfs.ntfs / mkntfs not found. Install ntfs-3g: sudo pacman -S ntfs-3g")
            run(["sudo", ntfs_cmd, "-f", "-L", "WINDOWS", data])
            _emit(22)

            _status(f"Mounting {efi} -> {mount_efi}")
            run(["sudo", "mount", efi, mount_efi])
            _status(f"Mounting {data} -> {mount_data}")
            run(["sudo", "mount", data, mount_data])

            try:
                if subprocess.run(["which", "7z"], capture_output=True).returncode != 0:
                    log.warning("7z not found, attempting to install...")
                    _status("7z not found, attempting to install...")
                    pkg_managers = [
                        ["apt-get", "install", "-y", "p7zip-full"],
                        ["dnf", "install", "-y", "p7zip-plugins"],
                        ["pacman", "-S", "--noconfirm", "p7zip"],
                        ["zypper", "install", "-y", "p7zip-full"],
                    ]
                    for pm_cmd in pkg_managers:
                        if subprocess.run(["which", pm_cmd[0]], capture_output=True).returncode == 0:
                            subprocess.run(["sudo"] + pm_cmd, check=True)
                            break
                    if subprocess.run(["which", "7z"], capture_output=True).returncode != 0:
                        log.error("7z not found. Install p7zip: sudo pacman -S p7zip")
                        raise FileNotFoundError("7z not found. Install p7zip: sudo pacman -S p7zip")
                _status(f"Extracting ISO {iso} to {host_extract} with 7z...")
                run(["7z", "x", iso, f"-o{host_extract}", "-y"])
                extracted = os.listdir(host_extract)
                _status(
                    f"Extraction complete: {len(extracted)} top-level items: {extracted}"
                )
                _emit(60)

                _status(f"Copying {len(extracted)} items to data partition {mount_data}...")
                items = [os.path.join(host_extract, i) for i in extracted]
                run(["sudo", "cp", "-r"] + items + [mount_data])
                _emit(75)

                wim_size = _get_wim_size(mount_data)
                _status(
                    f"install.wim/esd on data partition: {wim_size / (1024**3):.2f} GiB"
                )

                _status("Copying EFI boot files to EFI partition...")
                efi_src = _find_path_case_insensitive(host_extract, "EFI")
                if efi_src:
                    efi_items = os.listdir(efi_src)
                    _status(
                        f"Found EFI/ directory with {len(efi_items)} items: {efi_items}"
                    )
                    run(
                        ["sudo", "cp", "-r"]
                        + [os.path.join(efi_src, i) for i in efi_items]
                        + [mount_efi]
                    )
                    _status("Copied EFI/ tree to EFI partition")
                else:
                    log.warning("No EFI directory found in ISO - drive may not be UEFI bootable")
                    _status(
                        "WARNING: No EFI directory found in ISO - drive may not be UEFI bootable"
                    )

                boot_src = _find_path_case_insensitive(host_extract, "boot")
                if boot_src:
                    boot_items = os.listdir(boot_src)
                    _status(f"Found boot/ directory with {len(boot_items)} items")
                    run(
                        ["sudo", "cp", "-r"]
                        + [os.path.join(boot_src, i) for i in boot_items]
                        + [mount_efi]
                    )
                    _status("Copied boot/ tree to EFI partition")
                else:
                    _status("No boot/ directory found in ISO extract")

                for fname in ["bootmgr", "bootmgr.efi"]:
                    src = _find_path_case_insensitive(host_extract, fname)
                    if src:
                        run(["sudo", "cp", src, f"{mount_efi}/{fname}"])
                        _status(f"Copied {fname} to EFI partition root")
                    else:
                        _status(f"{fname} not found in ISO extract (may be fine)")

                _fix_efi_bootloader(mount_efi)
                _emit(88)

                _status("Syncing all writes to disk (this may take a moment)...")
                run(["sudo", "sync"])
                _emit(97)
                _status("Sync complete")
            except Exception as e:
                log.error("flash_windows: ERROR - %s: %s", type(e).__name__, e)
                _status(f"flash_windows: ERROR - {type(e).__name__}: {e}")
                raise
            finally:
                _status(f"Unmounting {mount_efi} and {mount_data}...")
                subprocess.run(["sudo", "umount", mount_efi], capture_output=True)
                subprocess.run(["sudo", "umount", mount_data], capture_output=True)
                _status("Unmount complete")

            _status("flash_windows: finished successfully, Windows USB is ready")
            return True

    except (OSError, subprocess.CalledProcessError) as e:
        log.error("flash_windows: failed: %s", e)
        _status(f"flash_windows: failed: {e}")
        return False
