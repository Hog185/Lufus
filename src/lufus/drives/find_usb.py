import psutil
import os
import subprocess
import getpass
from lufus.drives import states


def _media_directories() -> list:
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
                print(f"Permission denied accessing {path}")
            except Exception as err:
                print(f"Error accessing {path}: {err}")
    return directories


### USB RECOGNITION ###
def find_usb() -> dict:
    """Return a mapping of mount-path -> volume-label for detected USB drives."""
    usbdict = {}  # DICTIONARY WHERE USB MOUNT PATH IS KEY AND LABEL IS VALUE

    all_directories = _media_directories()
    dir_set = set(all_directories)

    # Check each partition to see if it matches our potential mount points
    for part in psutil.disk_partitions(all=True):
        if part.mountpoint not in dir_set:
            continue
        mount_path = part.mountpoint
        device_node = part.device
        if device_node:
            try:
                label = subprocess.check_output(
                    ["lsblk", "-d", "-n", "-o", "LABEL", device_node],
                    text=True,
                    timeout=5,
                ).strip()
                if not label:
                    label = os.path.basename(mount_path)
                usbdict[mount_path] = label
                print(f"Found USB: {mount_path} -> {label}")
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
                label = os.path.basename(mount_path)
                usbdict[mount_path] = label
                print(f"Found USB: {mount_path} -> {label}")

    return usbdict


### FOR DEVICE NODE ###
def find_DN() -> str | None:
    """Return the device node for the first detected USB drive, or None."""
    all_directories = _media_directories()
    dir_set = set(all_directories)

    for part in psutil.disk_partitions(all=True):
        if part.mountpoint not in dir_set:
            continue
        device_node = part.device
        if device_node:
            states.DN = device_node
            return device_node

    return None
