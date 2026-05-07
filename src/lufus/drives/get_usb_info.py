import psutil
import os
import pyudev
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

        context = pyudev.Context()
        # Using os.stat to get device number as per requirements
        st = os.stat(device_node)
        device = pyudev.Devices.from_device_number(context, "block", st.st_rdev)
        
        # Size in bytes: udev attributes 'size' is in 512-byte sectors
        size_attr = device.attributes.get("size")
        usb_size = int(size_attr) * 512 if size_attr else 0
        
        label = device.get("ID_FS_LABEL")

        if usb_size > 32 * 1024**3:
            log.warning("USB device is large (%d bytes); confirm before flashing.", usb_size)

        if not label:
            label = os.path.basename(usb_path)

        usb_info = {
            "device_node": device_node,
            "label": label,
            "mount_path": normalized_usb_path,
        }
        log.info("USB Info: %s", usb_info)
        return usb_info
    except PermissionError:
        log.error("Permission denied when trying to get USB info: %s", usb_path)
        return None
    except Exception as err:
        log.error("Unexpected error getting USB info: %s", err)
        return None
