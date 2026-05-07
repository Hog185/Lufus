import psutil
import os
import pyudev
import getpass
from lufus import state
from lufus.lufus_logging import get_logger

log = get_logger(__name__)


def _media_directories() -> list[str]:
    """Return a deduplicated list of candidate USB mount directories.

    Scans /media, /run/media, and per-user subdirectories thereof.
    Skips paths that are inaccessible due to permissions or other errors.
    """
    username = getpass.getuser()
    paths = ["/media", "/run/media", f"/media/{username}", f"/run/media/{username}"]

    seen = set()
    directories = []
    for path in paths:
        if os.path.exists(path) and os.path.isdir(path):
            try:
                for entry in os.listdir(path):
                    full = os.path.join(path, entry)
                    if os.path.isdir(full) and full not in seen:
                        seen.add(full)
                        directories.append(full)
            except PermissionError:
                log.warning("Permission denied accessing %s", path)
            except Exception as err:
                log.error("Error accessing %s: %s", path, err)
    return directories


### USB RECOGNITION ###
def find_usb() -> dict[str, str]:
    """Return a mapping of mount-path -> volume-label for detected USB drives."""
    usbdict = {}  # DICTIONARY WHERE USB MOUNT PATH IS KEY AND LABEL IS VALUE

    all_directories = _media_directories()
    dir_set = set(all_directories)

    # Check each partition to see if it matches our potential mount points
    context = pyudev.Context()
    for part in psutil.disk_partitions(all=True):
        if part.mountpoint not in dir_set:
            continue
        mount_path = part.mountpoint
        device_node = part.device
        if not device_node:
            continue

        label = None
        try:
            # Using os.stat to get device number as per requirements
            st = os.stat(device_node)
            device = pyudev.Devices.from_device_number(context, "block", st.st_rdev)
            label = device.get("ID_FS_LABEL")
        except Exception:
            pass

        if not label:
            label = os.path.basename(mount_path)

        usbdict[mount_path] = label
        log.info("Found USB: %s -> %s", mount_path, label)

    return usbdict


### FOR DEVICE NODE ###
def find_device_node() -> str | None:
    """Return the device node for the first detected USB drive, or None."""
    all_directories = _media_directories()
    dir_set = set(all_directories)

    for part in psutil.disk_partitions(all=True):
        if part.mountpoint not in dir_set:
            continue
        device_node = part.device
        if device_node:
            log.info("find_device_node: resolved device node %s", device_node)
            return device_node

    log.warning("find_device_node: no USB device node found")
    return None
