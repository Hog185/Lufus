# due to some issues it's only working with linux don't add without proper changing
import hashlib
import re
import subprocess
import sys
import os
import shutil
import tempfile
import time
import urllib.request
import urllib.error
import glob

"""
   This script installs grub in a way that lets users to copy distro iso to the usb device and
   boot of any copied iso's in the usb.
"""

WIMBOOT_URL = "https://github.com/ipxe/wimboot/releases/latest/download/wimboot"
WIMBOOT_TIMEOUT = 60

# Pin the expected SHA-256 of the wimboot binary.
# UPDATE THIS HASH whenever you update the pinned wimboot version.
# Obtain it with: sha256sum wimboot
# An empty string disables verification and logs a security warning (dev only).
_WIMBOOT_SHA256 = ""

# Only permit canonical block-device paths to prevent sfdisk script injection.
_DEVICE_RE = re.compile(r"^/dev/[a-z][a-z0-9]*$")


def _verify_sha256(path: str, expected: str) -> bool:
    """Return True if the SHA-256 of *path* matches *expected*."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest().lower() == expected.strip().lower()


def download_wimboot(dest_path: str) -> bool:
    """Downloads wimboot, a bootloader necessary to boot into Windows.

    Args:
        dest_path: Download destination path.

    Returns:
        True on success, False on failure.
    """
    print("--- Downloading wimboot ---")
    try:
        req = urllib.request.urlopen(WIMBOOT_URL, timeout=WIMBOOT_TIMEOUT)
        with open(dest_path, "wb") as fh:
            fh.write(req.read())

        if _WIMBOOT_SHA256:
            if not _verify_sha256(dest_path, _WIMBOOT_SHA256):
                os.unlink(dest_path)
                print(
                    "ERROR: wimboot SHA-256 verification failed — file deleted. "
                    "Check the download source or update _WIMBOOT_SHA256."
                )
                return False
        else:
            print(
                "WARNING: wimboot downloaded without hash verification. "
                "Set _WIMBOOT_SHA256 before shipping to production."
            )

        print("wimboot downloaded successfully.")
        return True
    except urllib.error.URLError as e:
        print(f"WARNING: Could not download wimboot (network error): {e}")
        print("Windows ISO booting will not work.")
        return False
    except Exception as e:
        print(f"WARNING: Could not download wimboot: {e}")
        print("Windows ISO booting will not work.")
        return False


def _is_usb_device(device: str) -> bool:
    """Return True if *device* is on the USB bus, as reported by sysfs.

    This correctly handles USB NVMe SSDs and USB SD-card readers in addition
    to standard USB mass-storage drives, without blocking them based solely
    on their device-node prefix.
    """
    dev_name = os.path.basename(device)
    sys_block = f"/sys/class/block/{dev_name}"
    try:
        real_path = os.path.realpath(sys_block)
        return "/usb" in real_path
    except OSError:
        return False


def install_grub(target_device: str) -> bool:
    """Prepares the USB drive with a hybrid GRUB bootloader for multi-ISO booting.

    This function performs partitioning via sfdisk, formats partitions to
    FAT32 and exFAT, and installs GRUB to both the MBR and EFI partitions.

    Args:
        target_device: The system path to the disk (e.g., /dev/sdX).

    Returns:
        bool: True if the installation succeeded, False otherwise.

    Raises:
        subprocess.CalledProcessError: If a system command fails.
    """

    # Root check
    if os.geteuid() != 0:
        print("ERROR: This script must be run with sudo.")
        return False

    # Validate device path before it is interpolated into the sfdisk script.
    # This prevents newline injection and ensures we operate on a real block device.
    if not _DEVICE_RE.match(target_device):
        print(f"ERROR: Invalid device path: {target_device!r}")
        return False

    # Safety: only allow USB devices. This properly handles USB NVMe SSDs
    # (which were previously blocked by an overly broad nvme/mmcblk check).
    if not _is_usb_device(target_device):
        print(f"Aborting: {target_device} does not appear to be a USB device.")
        return False

    # Cleanup to avoid "Device Busy"
    print(f"--- Cleaning up {target_device} ---")
    for partition in glob.glob(f"{target_device}*"):
        subprocess.run(["umount", partition], check=False)

    # Partition separator: NVMe and MMC block devices use 'p' between the
    # disk name and the partition number (e.g. /dev/nvme0n1p1, /dev/mmcblk0p1).
    # Standard SCSI/SATA/USB drives use no separator (e.g. /dev/sdb1).
    sep = "p" if re.search(r"(nvme\d+n\d+|mmcblk\d+)$", target_device) else ""

    # Partitioning Definition
    sfdisk_input = f"""
label: gpt
device: {target_device}
unit: sectors

{target_device}{sep}1 : start=2048, size=2048, type=21686148-6449-6E6F-7444-6961676F6E61
{target_device}{sep}2 : start=4096, size=204800, type=C12A7328-F81F-11D2-BA4B-00A0C93EC93B
{target_device}{sep}3 : start=208896, type=EBD0A0A2-B9E5-4433-87C0-68B6B72699C7
    """

    # Use unique temp dirs instead of hardcoded /tmp paths to avoid stale-mount collisions.
    efi_mount = tempfile.mkdtemp(prefix="lufus_efi_")
    data_mount = tempfile.mkdtemp(prefix="lufus_data_")
    efi_mounted = False
    data_mounted = False

    try:
        print(f"--- Partitioning {target_device} ---")
        subprocess.run(["sfdisk", target_device], input=sfdisk_input.encode(), check=True)

        # Refresh kernel table
        subprocess.run(["partprobe", target_device], check=False)
        subprocess.run(["udevadm", "settle"], check=False)
        os.sync()

        # Wait for device nodes to be created by udev
        efi_part = f"{target_device}{sep}2"
        data_part = f"{target_device}{sep}3"
        for _ in range(10):
            if os.path.exists(data_part):
                break
            time.sleep(1)
        else:
            print(f"Error: {data_part} did not appear. Aborting.")
            return False

        # Formatting
        print(f"--- Formatting {efi_part} and {data_part} ---")
        subprocess.run(["mkfs.exfat", "-L", "OS_PART", data_part], check=True)

        # GRUB Installation
        subprocess.run(["mount", efi_part, efi_mount], check=True)
        efi_mounted = True

        print("--- Installing GRUB (Legacy + UEFI) ---")
        subprocess.run(
            ["grub-install", "--target=i386-pc", f"--boot-directory={efi_mount}/boot", target_device], check=True
        )
        subprocess.run(
            [
                "grub-install",
                "--target=x86_64-efi",
                f"--efi-directory={efi_mount}",
                f"--boot-directory={efi_mount}/boot",
                "--removable",
            ],
            check=True,
        )

        # Copy grub.cfg
        script_dir = os.path.dirname(os.path.abspath(__file__))
        cfg_path = os.path.join(script_dir, "grub.cfg")
        if not os.path.exists(cfg_path):
            print("ERROR: grub.cfg not found next to the script.")
            return False  # finally block will unmount because efi_mounted=True
        shutil.copy(cfg_path, f"{efi_mount}/boot/grub/grub.cfg")

        # Download wimboot
        subprocess.run(["mount", data_part, data_mount], check=True)
        data_mounted = True
        download_wimboot(f"{data_mount}/wimboot")

        print("\nSUCCESS: USB is ready. Copy .iso files to 'OS_PART'.")
        return True

    except Exception as e:
        print(f"\nCommand failed: {e}")
        return False
    finally:
        if efi_mounted:
            subprocess.run(["umount", efi_mount], check=False)
        if data_mounted:
            subprocess.run(["umount", data_mount], check=False)
        # Clean up temp dirs regardless of outcome
        for d in (efi_mount, data_mount):
            try:
                os.rmdir(d)
            except OSError:
                pass  # directory may be non-empty if unmount failed; ignore


# this part is for testing the script
if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: sudo python3 script.py /dev/sdX")
    else:
        if install_grub(sys.argv[1]):
            sys.exit(0)
        else:
            sys.exit(1)
