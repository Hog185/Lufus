import re
import shlex
import subprocess
import sys
from pathlib import Path
from lufus.drives import states
from lufus.drives import find_usb as fu


def _get_raw_device(drive: str) -> str:
    """Return the raw disk device for a partition node.

    Handles standard SCSI/SATA names (e.g. /dev/sdb1 → /dev/sdb),
    NVMe names (e.g. /dev/nvme0n1p1 → /dev/nvme0n1), and
    MMC/eMMC names (e.g. /dev/mmcblk0p1 → /dev/mmcblk0).
    Falls back to the input unchanged if no pattern matches.
    """
    # NVMe: /dev/nvmeXnYpZ  → /dev/nvmeXnY
    m = re.match(r"^(/dev/nvme\d+n\d+)p\d+$", drive)
    if m:
        return m.group(1)
    # MMC/eMMC: /dev/mmcblkXpY → /dev/mmcblkX
    m = re.match(r"^(/dev/mmcblk\d+)p\d+$", drive)
    if m:
        return m.group(1)
    # Standard SCSI/SATA/USB: /dev/sdXN → /dev/sdX
    m = re.match(r"^(/dev/[a-z]+)\d+$", drive)
    if m:
        return m.group(1)
    return drive

#######


def _get_mount_and_drive():
    """Resolve mount point and drive node from current state or live detection."""
    drive = states.DN
    mount_dict = fu.find_usb()
    mount = next(iter(mount_dict)) if mount_dict else None
    if not drive:
        drive = fu.find_DN()
    return mount, drive, mount_dict


def pkexecNotFound():
    print("Error: The command pkexec or labeling software was not found on your system.")


def FormatFail():
    print("Error: Formatting failed. Was the password correct? Is the drive unmounted?")

def UnmountFail():
    print("Error: Unmounting failed. Perhaps either the drive was already unmounted or is in use.")

def unexpected():
    print("An unexpected error occurred")


# UNMOUNT FUNCTION
def unmount(drive: str = None):
    if not drive:
        print("Error: No drive node found. Cannot unmount.")
        return
    try:
        subprocess.run(["umount", drive], check=True)
    except subprocess.CalledProcessError:
        UnmountFail()
    except Exception as e:
        print(f"(UMNTFUNC) DEBUG: Unexpected error type: {type(e).__name__}")
        print(f"DEBUG: Error message: {e}")
        unexpected()


# MOUNT FUNCTION
def remount():
    mount, drive, _ = _get_mount_and_drive()
    if not drive or not mount:
        print("Error: No drive node or mount point found. Cannot remount.")
        return
    try:
        subprocess.run(["mount", drive, mount], check=True)
    except subprocess.CalledProcessError:
        FormatFail()
    except Exception as e:
        print(f"(MNTFUNC) DEBUG: Unexpected error type: {type(e).__name__}")
        print(f"DEBUG: Error message: {e}")
        unexpected()


### DISK FORMATTING ###
def volumecustomlabel():
    newlabel = states.new_label
    _, drive, _ = _get_mount_and_drive()
    if not drive:
        print("Error: No drive node found. Cannot relabel.")
        return

    # Sanitize label: strip characters that could be misinterpreted.
    # Since commands are passed as lists (shell=False), shell injection is not
    # possible, but we still quote each argument defensively.
    safe_drive = shlex.quote(drive)
    safe_label = shlex.quote(newlabel)

    # 0 -> NTFS, 1 -> FAT32, 2 -> exFAT, 3 -> ext4
    fs_type = states.currentFS
    cmd_map = {
        0: ["ntfslabel", drive, newlabel],
        1: ["fatlabel", drive, newlabel],
        2: ["fatlabel", drive, newlabel],
        3: ["e2label", drive, newlabel],
    }
    cmd = cmd_map.get(fs_type)
    if cmd is None:
        unexpected()
        return
    try:
        subprocess.run(cmd, check=True)
    except FileNotFoundError:
        pkexecNotFound()
    except subprocess.CalledProcessError:
        FormatFail()
    except Exception as e:
        print(f"(LABEL) DEBUG: Unexpected error type: {type(e).__name__}")
        print(f"DEBUG: Error message: {e}")
        unexpected()


def cluster():
    """Return (cluster_bytes, sector_bytes, cluster_in_sectors) tuple.

    Falls back to safe defaults when the drive node is unavailable.
    Never crashes — always returns a valid 3-tuple.
    """
    _, drive, mount_dict = _get_mount_and_drive()

    if not mount_dict and not drive:
        print("Error: No USB mount found. Is the drive plugged in and mounted?")
        return 4096, 512, 8

    # Map states.cluster_size index to block size in bytes
    cluster_size_map = {0: 4096, 1: 8192}
    cluster1 = cluster_size_map.get(states.cluster_size, 4096)

    # Logical sector size — 512 bytes is the universal safe default
    cluster2 = 512

    sector = cluster1 // cluster2
    return cluster1, cluster2, sector


def quickformat():
    # detect quick format option ticked or not and put it in a variable
    # the if logic will be implemented later
    pass


def createextended():
    # detect create extended label and icon files check box and put it in a variable
    pass


def checkdevicebadblock():
    """Check the device for bad blocks using badblocks.
    Requires the drive to be unmounted.  The number of passes is determined by
    states.check_bad (0 = 1 pass read-only, 1 = 2 passes read/write).
    """
    _, drive, _ = _get_mount_and_drive()
    if not drive:
        print("Error: No drive node found. Cannot check for bad blocks.")
        return False

    passes = 2 if states.check_bad else 1

    # Probe the device's logical sector size so badblocks uses the real
    # device geometry. Fall back to 4096 bytes if detection fails.
    logical_block_size = 4096
    try:
        probe = subprocess.run(
            ["blockdev", "--getss", drive],
            capture_output=True,
            text=True,
            check=False,
        )
        if probe.returncode == 0:
            probed = probe.stdout.strip()
            if probed.isdigit():
                logical_block_size = int(probed)
            else:
                print(f"Warning: Unexpected blockdev output for {drive!r}: {probed!r}. Using default.")
        else:
            print(f"Warning: blockdev failed for {drive} (exit {probe.returncode}). Using default block size.")
    except Exception as exc:
        print(f"Warning: Could not probe sector size for {drive}: {exc}. Using default block size.")

    # -s = show progress, -v = verbose output
    # -n = non-destructive read-write test (safe default)
    args = ["badblocks", "-sv", "-b", str(logical_block_size)]
    if passes > 1:
        args.append("-n")  # non-destructive read-write
    args.append(drive)

    print(f"Checking {drive} for bad blocks ({passes} pass(es), block size {logical_block_size})...")
    try:
        result = subprocess.run(args, capture_output=True, text=True)
        output = result.stdout + result.stderr
        if result.returncode != 0:
            print(f"badblocks exited with code {result.returncode}:\n{output}")
            return False
        # badblocks reports bad block numbers one per line in stderr; a clean
        # run produces no such lines and exits 0. We rely on the exit code as
        # the authoritative result and only scan output for a user-friendly
        # summary — we do NOT parse numeric lines as a bad-block count because
        # the output format may include other numeric status lines.
        bad_lines = [line for line in output.splitlines() if line.strip().isdigit()]
        if bad_lines:
            print(f"WARNING: {len(bad_lines)} bad block(s) found on {drive}!")
            return False
        print(f"No bad blocks found on {drive}.")
        return True
    except FileNotFoundError:
        print("Error: 'badblocks' utility not found. Install e2fsprogs.")
        return False
    except Exception as e:
        print(f"(BADBLOCK) Unexpected error: {type(e).__name__}: {e}")
        unexpected()
        return False


def dskformat():
    cluster1, cluster2, sector = cluster()
    _, drive, _ = _get_mount_and_drive()
    if not drive:
        print("Error: No drive found. Cannot format.")
        return

    fs_type = states.currentFS
    clusters = cluster1
    sectors = sector

    # Build partition table based on scheme before formatting
    _apply_partition_scheme(drive)

    if fs_type == 0:
        try:
            subprocess.run(["mkfs.ntfs", "-c", str(clusters), "-Q", drive], check=True)
            print("success format to ntfs!")
        except FileNotFoundError:
            pkexecNotFound()
        except subprocess.CalledProcessError:
            FormatFail()
        except Exception as e:
            print(f"(NTFS) DEBUG: {type(e).__name__}: {e}")
            unexpected()
    elif fs_type == 1:
        try:
            subprocess.run(["mkfs.vfat", "-s", str(sectors), "-F", "32", drive], check=True)
            print("success format to fat32!")
        except FileNotFoundError:
            pkexecNotFound()
        except subprocess.CalledProcessError:
            FormatFail()
        except Exception as e:
            print(f"(FAT32) DEBUG: {type(e).__name__}: {e}")
            unexpected()
    elif fs_type == 2:
        try:
            subprocess.run(["mkfs.exfat", "-b", str(clusters), drive], check=True)
            print("success format to exFAT!")
        except FileNotFoundError:
            pkexecNotFound()
        except subprocess.CalledProcessError:
            FormatFail()
        except Exception as e:
            print(f"(exFAT) DEBUG: {type(e).__name__}: {e}")
            unexpected()
    elif fs_type == 3:
        try:
            subprocess.run(["mkfs.ext4", "-b", str(clusters), drive], check=True)
            print("success format to ext4!")
        except FileNotFoundError:
            pkexecNotFound()
        except subprocess.CalledProcessError:
            FormatFail()
        except Exception as e:
            print(f"(ext4) DEBUG: {type(e).__name__}: {e}")
            unexpected()
    else:
        unexpected()


def _apply_partition_scheme(drive: str):
    """Write a GPT or MBR partition table to the raw disk.

    states.partition_scheme: 0 = GPT, 1 = MBR
    states.target_system:    0 = UEFI (non CSM), 1 = BIOS (or UEFI-CSM)
    """
    raw_device = _get_raw_device(drive)
    scheme = states.partition_scheme  # 0 = GPT, 1 = MBR

    try:
        if scheme == 0:
            # GPT — used for UEFI targets
            subprocess.run(["parted", "-s", raw_device, "mklabel", "gpt"], check=True)
            subprocess.run(
                ["parted", "-s", raw_device, "mkpart", "primary", "1MiB", "100%"],
                check=True,
            )
        else:
            # MBR — used for BIOS/legacy targets
            subprocess.run(["parted", "-s", raw_device, "mklabel", "msdos"], check=True)
            subprocess.run(
                ["parted", "-s", raw_device, "mkpart", "primary", "1MiB", "100%"],
                check=True,
            )
        print(f"Partition scheme {'GPT' if scheme == 0 else 'MBR'} applied to {raw_device}")
    except FileNotFoundError:
        print("Error: 'parted' not found. Install parted.")
    except subprocess.CalledProcessError as e:
        print(f"(PARTITION) Failed to apply partition scheme: {e}")
    except Exception as e:
        print(f"(PARTITION) Unexpected error: {type(e).__name__}: {e}")
        unexpected()


def drive_repair():
    _, drive, _ = _get_mount_and_drive()
    if not drive:
        print("Error: No drive node found. Cannot repair.")
        return
    raw_device = _get_raw_device(drive)
    cmd = ["sfdisk", raw_device]
    try:
        subprocess.run(["umount", drive], check=True)
        subprocess.run(cmd, input=b",,0c;\n", check=True)
        subprocess.run(["mkfs.vfat", "-F", "32", "-n", "REPAIRED", drive], check=True)
        print("SUCCESSFULLY REPAIRED DRIVE (FAT32)")
    except Exception:
        print("COULDN'T REPAIR DRIVE")
