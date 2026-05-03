import re
import shutil
import subprocess
import sys
import os
import glob
import time
from pathlib import Path
from lufus import state
from lufus.drives import find_usb as fu
from lufus.utils import strip_partition_suffix, require_root, get_mount_and_drive
from lufus.lufus_logging import get_logger

log = get_logger(__name__)

# pkexec strips /sbin and /usr/sbin from PATH so we must search them explicitly
_TOOL_PATH = "/usr/sbin:/usr/bin:/sbin:/bin"


def _find_tool(name: str) -> str:
    # resolve full path of a system tool, searching sbin dirs pkexec drops
    found = shutil.which(name, path=_TOOL_PATH)
    if found:
        return found
    log.warning("_find_tool: %s not found in %s, falling back to bare name", name, _TOOL_PATH)
    return name


#######


def _get_mount_and_drive() -> tuple[str | None, str | None, dict]:
    return get_mount_and_drive()


def pkexec_not_found() -> None:
    log.error("The command pkexec or labeling software was not found on your system.")


def format_fail() -> None:
    log.error("Formatting failed. Was the password correct? Is the drive unmounted?")


def unmount_fail() -> None:
    log.error("Unmounting failed. Perhaps either the drive was already unmounted or is in use.")


def log_unexpected_error() -> None:
    log.error("An unexpected error occurred")


# unmountain
def unmount(drive: str = None) -> bool:
    if not drive:
        _, drive, _ = _get_mount_and_drive()
    if not drive:
        log.error("No drive node found. Cannot unmount.")
        return False
    targets = glob.glob(f"{drive}*")
    log.info("Unmounting %s...", drive)
    for target in targets:
        try:
            subprocess.run(["umount", "-l", target], check=True)
            time.sleep(0.5)
            log.info("Unmounted %s successfully.", target)
        except subprocess.CalledProcessError as e:
            # exit 32 = "not mounted" on Linux — acceptable when clearing a drive
            if e.returncode == 32:
                log.info("Unmounted %s (was already unmounted).", target)
                continue
            log.error("umount -l %s exited with code %d", target, e.returncode)
            unmount_fail()
            return False
        except Exception as e:
            log.error("(UMNTFUNC) Unexpected error type: %s — %s", type(e).__name__, e)
            log_unexpected_error()
            return False
    subprocess.run(["udevadm", "settle"])
    time.sleep(0.5)
    return True


# mountain
def remount(drive: str = None) -> bool:
    mount = None
    if not drive:
        mount, drive, _ = _get_mount_and_drive()
    else:
        # drive was supplied by caller; resolve mount point from current state
        _, _, mount_dict = _get_mount_and_drive()
        # find the mount point whose device node matches the given drive
        mount = next((mp for mp, _label in mount_dict.items()), None)
    if not drive:
        log.error("No drive node found. Cannot unmount.")
        return False
    if not mount:
        log.error("No drive node or mount point found. Cannot remount.")
        return False
    log.info("Remounting %s -> %s...", drive, mount)
    try:
        subprocess.run(["mount", drive, mount], check=True)
        log.info("Remounted %s -> %s successfully.", drive, mount)
        return True
    except subprocess.CalledProcessError:
        format_fail()
        return False
    except Exception as e:
        log.error("(MNTFUNC) Unexpected error type: %s — %s", type(e).__name__, e)
        log_unexpected_error()
        return False


# disk formatting
def volume_custom_label(target_partition: str = None) -> bool:
    newlabel = state.new_label
    # Sanitize label: allow only alphanumeric, spaces, hyphens, and underscores
    newlabel = re.sub(r"[^a-zA-Z0-9 \-_]", "", newlabel).strip()
    if not newlabel:
        newlabel = "USB_DRIVE"

    if target_partition:
        drive = target_partition
    else:
        _, drive, _ = _get_mount_and_drive()

    if not drive:
        log.error("No drive node found. Cannot relabel.")
        return False

    # Commands are passed as lists (shell=False) so shell injection is not possible.
    # Label sanitization above ensures the string is safe for all labelling tools.

    # 0 -> NTFS, 1 -> FAT32, 2 -> exFAT, 3 -> ext4, 4 -> UDF
    fs_type = state.filesystem_index
    cmd_map = {
        0: [_find_tool("ntfslabel"), drive, newlabel],
        1: [_find_tool("fatlabel"), drive, newlabel],
        2: [_find_tool("fatlabel"), drive, newlabel],
        3: [_find_tool("e2label"), drive, newlabel],
        4: [_find_tool("udflabel"), drive, newlabel],
    }
    cmd = cmd_map.get(fs_type)
    if cmd is None:
        log_unexpected_error()
        return False
    log.info("Applying volume label %r to %s (fs_type=%d)...", newlabel, drive, fs_type)
    try:
        subprocess.run(cmd, check=True)
        log.info("Volume label %r applied successfully to %s.", newlabel, drive)
        return True
    except FileNotFoundError:
        pkexec_not_found()
        return False
    except subprocess.CalledProcessError:
        format_fail()
        return False
    except Exception as e:
        log.error("(LABEL) Unexpected error type: %s — %s", type(e).__name__, e)
        log_unexpected_error()
        return False


def get_format_geometry() -> tuple[int, int, int]:
    """Return (block_size, sector_size, sectors_per_cluster) for formatting."""
    _, drive, mount_dict = _get_mount_and_drive()

    if not mount_dict and not drive:
        log.error("No USB mount found. Is the drive plugged in and mounted?")
        return 4096, 512, 8

    # Map state.cluster_size index to block size in bytes
    cluster_size_map = {0: 4096, 1: 8192}
    block_size = cluster_size_map.get(state.cluster_size, 4096)

    # Logical sector size — 512 bytes is the universal safe default
    sector_size = 512

    sectors_per_cluster = block_size // sector_size
    log.debug(
        "get_format_geometry(): block_size=%d, sector_size=%d, sectors_per_cluster=%d",
        block_size,
        sector_size,
        sectors_per_cluster,
    )
    return block_size, sector_size, sectors_per_cluster


# TODO: Decide if these are needed — currently just pass stubs
# def quickformat():
#     # detect quick format option ticked or not and put it in a variable
#     # the if logic will be implemented later
#     pass
#
# def createextended():
#     # detect create extended label and icon files check box and put it in a variable
#     pass


def check_device_bad_blocks() -> bool:
    """Check the device for bad blocks using badblocks.
    Requires the drive to be unmounted.  The number of passes is determined by
    state.check_bad (0 = 1 pass read-only, 1 = 2 passes read/write).
    """
    _, drive, _ = _get_mount_and_drive()
    if not drive:
        log.error("No drive node found. Cannot check for bad blocks.")
        return False

    passes = 2 if state.check_bad else 1

    # Probe the device's logical sector size so badblocks uses the real
    # device geometry. Fall back to 4096 bytes if detection fails.
    logical_block_size = 4096
    try:
        probe = subprocess.run(
            [_find_tool("blockdev"), "--getss", drive],
            capture_output=True,
            text=True,
            check=False,
        )
        if probe.returncode == 0:
            probed = probe.stdout.strip()
            if probed.isdigit():
                logical_block_size = int(probed)
            else:
                log.warning(
                    "Unexpected blockdev output for %r: %r. Using default block size.",
                    drive,
                    probed,
                )
        else:
            log.warning(
                "blockdev failed for %s (exit %d). Using default block size.",
                drive,
                probe.returncode,
            )
    except Exception as exc:
        log.warning("Could not probe sector size for %s: %s. Using default block size.", drive, exc)

    # -s = show progress, -v = verbose output
    # -n = non-destructive read-write test (safe default)
    args = [_find_tool("badblocks"), "-sv", "-b", str(logical_block_size)]
    if passes > 1:
        args.append("-n")  # non-destructive read-write
    args.append(drive)

    log.info(
        "Checking %s for bad blocks (%d pass(es), block size %d)...",
        drive,
        passes,
        logical_block_size,
    )
    try:
        result = subprocess.run(args, capture_output=True, text=True)
        output = result.stdout + result.stderr
        if result.returncode != 0:
            log.error("badblocks exited with code %d:\n%s", result.returncode, output)
            return False
        # badblocks reports bad block numbers one per line in stderr; a clean
        # run produces no such lines and exits 0. We rely on the exit code as
        # the authoritative result and only scan output for a user-friendly
        # summary — we do NOT parse numeric lines as a bad-block count because
        # the output format may include other numeric status lines.
        bad_lines = [line for line in output.splitlines() if line.strip().isdigit()]
        if bad_lines:
            log.warning("%d bad block(s) found on %s!", len(bad_lines), drive)
            return False
        log.info("No bad blocks found on %s.", drive)
        return True
    except FileNotFoundError:
        log.error("'badblocks' utility not found. Install e2fsprogs.")
        return False
    except Exception as e:
        log.error("(BADBLOCK) Unexpected error: %s: %s", type(e).__name__, e)
        log_unexpected_error()
        return False


def disk_format(status_cb=None) -> bool:
    """Format the drive. Returns True on success, False on failure.
    Accepts an optional status_cb(str) to emit progress messages to the GUI.
    """

    def _status(msg: str) -> None:
        log.info(msg)
        if status_cb:
            status_cb(msg)

    if not require_root():
        _status("ERROR: Root privileges required for formatting.")
        return False

    block_size, sector_size, sectors_per_cluster = get_format_geometry()
    _, drive, _ = _get_mount_and_drive()
    if not drive:
        _status("ERROR: No drive found. Cannot format.")
        return False

    # Get the raw device (whole disk, not partition)
    raw_device = strip_partition_suffix(drive)

    fs_type = state.filesystem_index

    # Check if quick format is enabled (state.quick_format: 0 = quick, 1 = full)
    is_quick_format = state.quick_format == 0

    _status(
        f"Starting format: device={raw_device}, fs_type={fs_type}, clusters={block_size}, sectors={sectors_per_cluster}, quick={is_quick_format}"
    )

    # Filesystem tool configurations: (tool_name, args_builder, fs_label, install_hint)
    fs_configs = {
        0: (
            "mkfs.ntfs",
            lambda: ["-c", str(block_size), "-F"] + (["-Q"] if is_quick_format else []) + [raw_device],
            "NTFS",
            "ntfs-3g",
        ),
        1: ("mkfs.vfat", lambda: ["-I", "-s", str(sectors_per_cluster), "-F", "32", raw_device], "FAT32", "dosfstools"),
        2: ("mkfs.exfat", lambda: ["-b", str(block_size), raw_device], "exFAT", "exfatprogs or exfat-utils"),
        3: ("mkfs.ext4", lambda: ["-b", str(block_size), raw_device], "ext4", "e2fsprogs"),
        4: ("mkudffs", lambda: ["--blocksize=" + str(sector_size), raw_device], "UDF", "udftools"),
    }

    if fs_type not in fs_configs:
        _status(f"ERROR: Unknown fs_type={fs_type}")
        return False

    tool_name, args_fn, fs_label, install_hint = fs_configs[fs_type]
    try:
        tool = _find_tool(tool_name)
        cmd = [tool] + args_fn()
        _status(f"Running: {' '.join(cmd)}")
        subprocess.run(cmd, check=True)
        _status(f"Successfully formatted {raw_device} as {fs_label}.")
    except FileNotFoundError:
        _status(f"ERROR: {tool_name} not found. Install {install_hint}.")
        return False
    except subprocess.CalledProcessError as e:
        _status(f"ERROR: {tool_name} failed (exit {e.returncode}). Is the drive unmounted?")
        return False
    except Exception as e:
        _status(f"ERROR ({fs_label}): {type(e).__name__}: {e}")
        return False

    # Apply volume label after successful format
    _status("Applying volume label to formatted device...")
    volume_custom_label(target_partition=raw_device)
    return True


def _apply_partition_scheme(drive: str) -> None:
    """Write a GPT or MBR partition table to the raw disk.

    state.partition_scheme: 0 = GPT, 1 = MBR
    state.target_system:    0 = UEFI (non CSM), 1 = BIOS (or UEFI-CSM)

    NOTE: This function is currently bypassed in disk_format() - formatting happens directly on raw device
    """
    raw_device = strip_partition_suffix(drive)
    scheme = state.partition_scheme  # 0 = GPT, 1 = MBR

    scheme_name = "GPT" if scheme == 0 else "MBR"
    log.info("Applying %s partition scheme to %s...", scheme_name, raw_device)
    try:
        if scheme == 0:
            # GPT — used for UEFI targets
            subprocess.run([_find_tool("parted"), "-s", raw_device, "mklabel", "gpt"], check=True)
            subprocess.run(
                [_find_tool("parted"), "-s", raw_device, "mkpart", "primary", "1MiB", "100%"],
                check=True,
            )
        else:
            # MBR — used for BIOS/legacy targets
            subprocess.run([_find_tool("parted"), "-s", raw_device, "mklabel", "msdos"], check=True)
            subprocess.run(
                [_find_tool("parted"), "-s", raw_device, "mkpart", "primary", "1MiB", "100%"],
                check=True,
            )
        log.info("Partition scheme %s applied to %s.", scheme_name, raw_device)
    except FileNotFoundError:
        log.error("'parted' not found. Install parted.")
    except subprocess.CalledProcessError as e:
        log.error("(PARTITION) Failed to apply partition scheme: %s", e)
    except Exception as e:
        log.error("(PARTITION) Unexpected error: %s: %s", type(e).__name__, e)
        log_unexpected_error()


def drive_repair() -> None:
    _, drive, _ = _get_mount_and_drive()
    if not drive:
        log.error("No drive node found. Cannot repair.")
        return
    raw_device = strip_partition_suffix(drive)
    cmd = [_find_tool("sfdisk"), raw_device]
    log.info("Attempting drive repair on %s (raw: %s)...", drive, raw_device)
    try:
        subprocess.run(["umount", drive], check=True)
        subprocess.run(cmd, input=b",,0c;\n", check=True)
        subprocess.run([_find_tool("mkfs.vfat"), "-F", "32", "-n", "REPAIRED", drive], check=True)
        log.info("Successfully repaired drive %s (FAT32).", drive)
    except Exception as e:
        log.error("Could not repair drive %s: %s: %s", drive, type(e).__name__, e)
