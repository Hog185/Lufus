import subprocess
import os
import glob
import tempfile
import re
from typing import Optional, Callable

def run(cmd):
    subprocess.run(cmd, check=True)

def run_out(cmd) -> str:
    return subprocess.check_output(cmd, text=True).strip()

def _get_wim_size(data_mount) -> int:
    """Check actual install.wim/install.esd size"""
    for pattern in ["install.wim", "install.esd", "INSTALL.WIM", "INSTALL.ESD"]:
        matches = glob.glob(f"{data_mount}/sources/{pattern}")
        if matches:
            return os.path.getsize(matches[0])
    return 0

def _find_path_case_insensitive(base, *parts):
    current = [base]
    for part in parts:
        next_level = []
        for c in current:
            next_level += [
                p for p in glob.glob(os.path.join(c, "*"))
                if os.path.basename(p).lower() == part.lower()
            ]
        current = next_level
    return current[0] if current else None

def _fix_efi_bootloader(efi_mount):
    """
    Ensure /EFI/BOOT/BOOTX64.EFI exists — required by UEFI spec.
    Windows ISOs put the bootloader at efi/microsoft/boot/efisys.bin
    but UEFI firmware looks for /EFI/BOOT/BOOTX64.EFI as fallback.
    """
    found_boot_dir = _find_path_case_insensitive(efi_mount, "EFI", "BOOT")
    boot_dir = found_boot_dir or os.path.join(efi_mount, "EFI", "BOOT")
    existing_bootx64 = _find_path_case_insensitive(efi_mount, "EFI", "BOOT", "BOOTX64.EFI")
    if existing_bootx64:
        print("BOOTX64.EFI already in place")
        return

    bootx64 = os.path.join(boot_dir, "BOOTX64.EFI")
    run(["sudo", "mkdir", "-p", boot_dir])

    src = _find_path_case_insensitive(efi_mount, "EFI", "Microsoft", "Boot", "bootmgfw.efi")
    if src:
        run(["sudo", "cp", src, bootx64])
        print(f"Copied {src} -> {bootx64}")
        return

    print("WARNING: Could not find bootmgfw.efi — UEFI boot may fail")

def flash_windows(device, iso, progress_cb=None, status_cb=None):
    if not re.match(r"^/dev/(sd[a-z]|nvme[0-9]n[0-9])$", device):
        raise ValueError(f"Invalid device path: {device}")

    def _emit(pct):
        if progress_cb:
            progress_cb(pct)

    def _status(msg):
        print(msg)
        if status_cb:
            status_cb(msg)

    with tempfile.TemporaryDirectory() as mount_efi, \
         tempfile.TemporaryDirectory() as mount_data, \
         tempfile.TemporaryDirectory() as host_extract:

        _status("Wiping partition table...")
        run(["sudo", "wipefs", "-a", device])
        _emit(8)

        sfdisk_script = f"""label: gpt
device: {device}
{device}1 : size=512M, type=C12A7328-F81F-11D2-BA4B-00A0C93EC93B
{device}2 : type=EBD0A0A2-B9E5-4433-87C0-68B6B72699C7
"""
        _status("Writing partition table...")
        subprocess.run(["sudo", "sfdisk", device], input=sfdisk_script.encode(), check=True)
        run(["sudo", "partprobe", device])
        run(["sudo", "udevadm", "settle"])
        _emit(15)

        efi = f"{device}1"
        data = f"{device}2"

        _status("Formatting EFI partition (FAT32)...")
        run(["sudo", "mkfs.vfat", "-F32", "-n", "BOOT", efi])
        _status("Formatting data partition (NTFS)...")
        run(["sudo", "mkfs.ntfs", "-f", "-L", "WINDOWS", data])
        _emit(22)

        run(["sudo", "mount", efi, mount_efi])
        run(["sudo", "mount", data, mount_data])

        try:
            _status("Extracting ISO contents...")
            run(["7z", "x", iso, f"-o{host_extract}", "-y"])
            _emit(60)

            _status("Copying files to USB data partition...")
            items = [os.path.join(host_extract, i) for i in os.listdir(host_extract)]
            run(["sudo", "cp", "-r"] + items + [mount_data])
            _emit(75)

            wim_size = _get_wim_size(mount_data)
            print(f"install.wim size: {wim_size / (1024**3):.2f} GB")

            _status("Copying EFI boot files...")

            efi_src = _find_path_case_insensitive(host_extract, "EFI")
            if efi_src:
                efi_items = [os.path.join(efi_src, i) for i in os.listdir(efi_src)]
                run(["sudo", "cp", "-r"] + efi_items + [mount_efi])
                print("Copied EFI/ to EFI partition")
            else:
                print("WARNING: No EFI directory found — may not be UEFI bootable")

            boot_src = _find_path_case_insensitive(host_extract, "boot")
            if boot_src:
                boot_items = [os.path.join(boot_src, i) for i in os.listdir(boot_src)]
                run(["sudo", "cp", "-r"] + boot_items + [mount_efi])
                print("Copied boot/ to EFI partition")

            for f in ["bootmgr", "bootmgr.efi"]:
                src = _find_path_case_insensitive(host_extract, f)
                if src:
                    run(["sudo", "cp", src, f"{mount_efi}/{f}"])
                    print(f"Copied {f} to EFI partition root")

            _fix_efi_bootloader(mount_efi)
            _emit(88)

            _status("Syncing to disk...")
            run(["sudo", "sync"])
            _emit(97)
        finally:
            run(["sudo", "umount", mount_efi])
            run(["sudo", "umount", mount_data])

        print("Windows USB ready")
        return True