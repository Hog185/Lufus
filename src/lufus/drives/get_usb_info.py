import psutil
import os
import subprocess
from typing import TypedDict
from lufus.lufus_logging import get_logger

log = get_logger(__name__)


class USBDeviceInfo(TypedDict):
    device_node: str
    label: str
    mount_path: str


def get_usb_info(usb_path: str) -> USBDeviceInfo | None:
    try:
        normalized_usb_path = os.path.normpath(usb_path)

        for part in psutil.disk_partitions(all=True):
            if os.path.normpath(part.mountpoint) == normalized_usb_path:
                device_node = part.device
                break
        else:
            log.warning("Could not find device node for USB path: %s", usb_path)
            return None

        size_output = subprocess.check_output(
            ["lsblk", "-d", "-n", "-b", "-o", "SIZE", device_node],
            text=True,
            timeout=5,
        ).strip()

        usb_size = int(size_output) if size_output.isdigit() else 0
        if not size_output.isdigit():
            log.warning("Could not parse device size: %r", size_output)

        if usb_size > 32 * 1024**3:
            log.warning("USB device is large (%d bytes); confirm before flashing.", usb_size)

        label = subprocess.check_output(["lsblk", "-d", "-n", "-o", "LABEL", device_node], text=True, timeout=5).strip()
        if not label:
            label = os.path.basename(usb_path)

        usb_info = {
            "device_node": device_node,
            "label": label,
            "mount_path": normalized_usb_path,
        }
        log.info("USB Info: %s", usb_info)
        return usb_info
    except subprocess.TimeoutExpired as e:
        log.error("Timed out getting USB info for %s: %s", usb_path, e)
        return None
    except PermissionError:
        log.error("Permission denied when trying to get USB info: %s", usb_path)
        return None
    except subprocess.CalledProcessError as e:
        log.error("Error getting USB info: %s", e)
        return None
    except Exception as err:
        log.error("Unexpected error getting USB info: %s", err)
        return None
