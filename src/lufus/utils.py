import os
import re


def elevate_privileges() -> None:
    """Relaunch the application with root privileges using pkexec."""
    import sys
    import subprocess
    from lufus import state

    # LUFUS_THEME is used to pass the current theme to the root process
    # so user-added themes in ~/.config/Lufus/themes are still respected
    # if the app was able to find them before elevation.
    env = os.environ.copy()
    if state.theme:
        # Validate theme is a safe filename/path: no path separators, no shell metacharacters,
        # and must resolve inside the config directory to prevent path traversal.
        theme_val = str(state.theme)
        if re.match(r'^[A-Za-z0-9_\-. ]+$', os.path.basename(theme_val)) and ".." not in theme_val:
            env["LUFUS_THEME"] = theme_val
        else:
            import logging
            logging.getLogger("lufus").warning("elevate_privileges: rejected suspicious LUFUS_THEME value %r", theme_val)

    # Preserve DISPLAY and XAUTHORITY for GUI apps under pkexec/sudo
    env_vars = ["DISPLAY", "XAUTHORITY", "XDG_RUNTIME_DIR", "WAYLAND_DISPLAY", "PYTHONPATH", "LUFUS_THEME"]

    cmd = ["pkexec", "env"]
    for var in env_vars:
        val = os.environ.get(var) or env.get(var)
        if val:
            cmd.append(f"{var}={val}")

    cmd += [sys.executable] + sys.argv
    try:
        subprocess.run(cmd, check=True)
        sys.exit(0)
    except subprocess.CalledProcessError:
        # User likely cancelled or pkexec failed
        pass
    except Exception as e:
        print(f"Elevation failed: {e}")


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
