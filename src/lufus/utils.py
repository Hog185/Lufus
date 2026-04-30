import os
import re


def require_root() -> bool:
    """Check if running as root. Returns True if root, False otherwise (with log warning)."""
    if os.geteuid() == 0:
        return True
    import logging

    logging.getLogger("lufus").error("This operation requires root privileges (euid=%d).", os.geteuid())
    return False


def strip_partition_suffix(device: str) -> str:
    """Strip a partition number suffix to get the raw block device.

    Handles NVMe (/dev/nvme0n1p1 -> /dev/nvme0n1), MMC
    (/dev/mmcblk0p1 -> /dev/mmcblk0), and standard SCSI/SATA/USB
    (/dev/sdb1 -> /dev/sdb). Returns the input unchanged if no
    partition suffix is found.
    """
    m = re.match(r"^(/dev/nvme\d+n\d+)p\d+$", device)
    if m:
        return m.group(1)
    m = re.match(r"^(/dev/mmcblk\d+)p\d+$", device)
    if m:
        return m.group(1)
    m = re.match(r"^(/dev/sd[a-z]+)\d+$", device)
    if m:
        return m.group(1)
    return device


def get_mount_and_drive() -> tuple[str | None, str | None, dict]:
    """Resolve the current USB mount path, device node, and mount dict."""
    from lufus import state
    from lufus.drives.find_usb import find_usb, find_device_node

    drive = state.device_node
    mount_dict = find_usb()
    mount = next(iter(mount_dict)) if mount_dict else None
    if not drive:
        drive = find_device_node()
    return mount, drive, mount_dict
