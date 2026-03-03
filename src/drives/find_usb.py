import psutil
import os
import subprocess
import getpass

###USB RECOGNITION###
def find_usb():
    usbdict = {}    # DICTIONARY WHERE USB MOUNT PATH IS KEY AND LABEL IS VALUE
    
    # Get current username
    username = getpass.getuser()
    
    # Properly formatted paths with actual username
    paths = ["/media", "/run/media", f"/media/{username}", f"/run/media/{username}"]
    
    # First, collect all possible user directories from media paths
    all_directories = []
    for path in paths:
        if os.path.exists(path) and os.path.isdir(path):
            try:
                directories = [d for d in os.listdir(path) if os.path.isdir(os.path.join(path, d))]
                all_directories.extend([os.path.join(path, d) for d in directories])
            except PermissionError:
                print(f"Permission denied accessing {path}")
                continue
            except Exception as err:
                # catching other exceptions makes debugging easier
                print(f"Error accessing {path}: {err}")
                continue
    
    # Check each partition to see if it matches our potential mount points
    for part in psutil.disk_partitions():
        for mount_path in all_directories:
            if part.mountpoint == mount_path:
                device_node = part.device
                if device_node:
                    try:
                        # Get the label of the USB device
                        label = subprocess.check_output(["lsblk", "-d", "-n", "-o", "LABEL", device_node], text=True, timeout=5).strip()
                        if not label:  # If no label, use directory name
                            label = os.path.basename(mount_path)
                        usbdict[mount_path] = label
                        print(f"Found USB: {mount_path} -> {label}")
                    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
                        # If lsblk fails, use directory name as fallback
                        label = os.path.basename(mount_path)
                        usbdict[mount_path] = label
                        print(f"Found USB: {mount_path} -> {label}")
    
    return usbdict