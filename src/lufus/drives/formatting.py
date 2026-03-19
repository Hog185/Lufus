import re
import shlex
import shutil
import subprocess
import sys
import os
from pathlib import Path
from lufus.drives import states
from lufus.drives import find_usb as fu
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
# gets the mount location and drive info
    drive = states.DN
    mount_dict = fu.find_usb()
    mount = next(iter(mount_dict)) if mount_dict else None
    if not drive:
        drive = fu.find_DN()
    return mount, drive, mount_dict


def pkexecNotFound():
    log.error("The command pkexec or labeling software was not found on your system.")


def FormatFail():
    log.error("Formatting failed. Was the password correct? Is the drive unmounted?")


def UnmountFail():
    log.error(
        "Unmounting failed. Perhaps either the drive was already unmounted or is in use."
    )


def unexpected():
    log.error("An unexpected error occurred")


#unmountain
def unmount(drive: str = None):
    if not drive:
        _, drive, _ = _get_mount_and_drive()
    if not drive:
        log.error("No drive node found. Cannot unmount.")
        return
    log.info("Unmounting %s...", drive)
    try:
        subprocess.run(["umount", drive], check=True)
        log.info("Unmounted %s successfully.", drive)
    except subprocess.CalledProcessError:
        UnmountFail()
    except Exception as e:
        log.error("(UMNTFUNC) Unexpected error type: %s — %s", type(e).__name__, e)
        unexpected()


#mountain
def remount():
    mount, drive, _ = _get_mount_and_drive()
    if not drive or not mount:
        log.error("No drive node or mount point found. Cannot remount.")
        return
    log.info("Remounting %s -> %s...", drive, mount)
    try:
        subprocess.run(["mount", drive, mount], check=True)
        log.info("Remounted %s -> %s successfully.", drive, mount)
    except subprocess.CalledProcessError:
        FormatFail()
    except Exception as e:
        log.error("(MNTFUNC) Unexpected error type: %s — %s", type(e).__name__, e)
        unexpected()


#disk formatting
def volumecustomlabel(target_partition: str = None):
    newlabel = states.new_label
    # Sanitize label: allow only alphanumeric, spaces, hyphens, and underscores
    import re
    newlabel = re.sub(r'[^a-zA-Z0-9 \-_]', '', newlabel).strip()
    if not newlabel:
        newlabel = "USB_DRIVE"

    if target_partition:
        drive = target_partition
    else:
        _, drive, _ = _get_mount_and_drive()

    if not drive:
        log.error("No drive node found. Cannot relabel.")
        return

    # Sanitize label: strip characters that could be misinterpreted.
    # Since commands are passed as lists (shell=False), shell injection is not
    # possible, but we still quote each argument defensively.
    safe_drive = shlex.quote(drive)
    safe_label = shlex.quote(newlabel)

    # 0 -> NTFS, 1 -> FAT32, 2 -> exFAT, 3 -> ext4
    fs_type = getattr(states, 'currentFS', 0)
    cmd_map = {
        0: [_find_tool("ntfslabel"), drive, newlabel],
        1: [_find_tool("fatlabel"), drive, newlabel],
        2: [_find_tool("fatlabel"), drive, newlabel],
        3: [_find_tool("e2label"), drive, newlabel],
    }
    cmd = cmd_map.get(fs_type)
    if cmd is None:
        unexpected()
        return
    log.info("Applying volume label %r to %s (fs_type=%d)...", newlabel, drive, fs_type)
    try:
        subprocess.run(cmd, check=True)
        log.info("Volume label %r applied successfully to %s.", newlabel, drive)
    except FileNotFoundError:
        pkexecNotFound()
    except subprocess.CalledProcessError:
        FormatFail()
    except Exception as e:
        log.error("(LABEL) Unexpected error type: %s — %s", type(e).__name__, e)
        unexpected()


def cluster():
#cluster bs, go
    _, drive, mount_dict = _get_mount_and_drive()

    if not mount_dict and not drive:
        log.error("No USB mount found. Is the drive plugged in and mounted?")
        return 4096, 512, 8

    # Map states.cluster_size index to block size in bytes
    cluster_size_map = {0: 4096, 1: 8192}
    cluster1 = cluster_size_map.get(getattr(states, 'cluster_size', 0), 4096)

    # Logical sector size — 512 bytes is the universal safe default
    cluster2 = 512

    sector = cluster1 // cluster2
    log.debug("cluster(): cluster=%d, sector_size=%d, sectors_per_cluster=%d", cluster1, cluster2, sector)
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
        log.error("No drive node found. Cannot check for bad blocks.")
        return False

    passes = 2 if states.check_bad else 1

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
                    drive, probed,
                )
        else:
            log.warning(
                "blockdev failed for %s (exit %d). Using default block size.",
                drive, probe.returncode,
            )
    except Exception as exc:
        log.warning(
            "Could not probe sector size for %s: %s. Using default block size.", drive, exc
        )

    # -s = show progress, -v = verbose output
    # -n = non-destructive read-write test (safe default)
    args = [_find_tool("badblocks"), "-sv", "-b", str(logical_block_size)]
    if passes > 1:
        args.append("-n")  # non-destructive read-write
    args.append(drive)

    log.info(
        "Checking %s for bad blocks (%d pass(es), block size %d)...",
        drive, passes, logical_block_size,
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
            return True
        log.info("No bad blocks found on %s.", drive)
        return True
    except FileNotFoundError:
        log.error("'badblocks' utility not found. Install e2fsprogs.")
        return False
    except Exception as e:
        log.error("(BADBLOCK) Unexpected error: %s: %s", type(e).__name__, e)
        unexpected()
        return False


def dskformat(status_cb=None) -> bool:
    """Format the drive. Returns True on success, False on failure.
    Accepts an optional status_cb(str) to emit progress messages to the GUI.
    """
    def _status(msg: str) -> None:
        log.info(msg)
        if status_cb:
            status_cb(msg)

    cluster1, cluster2, sector = cluster()
    _, drive, _ = _get_mount_and_drive()
    if not drive:
        _status("ERROR: No drive found. Cannot format.")
        return False

    # Get the raw device (whole disk, not partition)
    raw_device = _get_raw_device(drive)
    
    try:
        _status(f"Unmounting {drive} before formatting...")
        subprocess.run(["umount", drive], check=True)
    except subprocess.CalledProcessError:
        _status(f"WARNING: Failed to unmount {drive}. It may already be unmounted or in use.")
    except Exception as e:
        _status(f"WARNING: Unexpected unmount error: {type(e).__name__}: {e}")  

    fs_type = getattr(states, 'currentFS', 0)
    clusters = cluster1
    sectors = sector

    # Check if quick format is enabled (states.QF: 0 = quick, 1 = full)
    is_quick_format = (getattr(states, 'QF', 0) == 0)

    _status(f"Starting format: device={raw_device}, fs_type={fs_type}, clusters={clusters}, sectors={sectors}, quick={is_quick_format}")

    if fs_type == 0:  # NTFS
        try:
            tool = _find_tool("mkfs.ntfs")
            cmd = [tool, "-c", str(clusters), "-F"]
            if is_quick_format:
                cmd.append("-Q")
            cmd.append(raw_device)
            _status(f"Running: {' '.join(cmd)}")
            subprocess.run(cmd, check=True)
            _status(f"Successfully formatted {raw_device} as NTFS.")
        except FileNotFoundError:
            _status(f"ERROR: mkfs.ntfs not found. Install ntfs-3g.")
            return False
        except subprocess.CalledProcessError as e:
            _status(f"ERROR: mkfs.ntfs failed (exit {e.returncode}). Is the drive unmounted?")
            return False
        except Exception as e:
            _status(f"ERROR (NTFS): {type(e).__name__}: {e}")
            return False

    elif fs_type == 1:  # FAT32
        try:
            tool = _find_tool("mkfs.vfat")
            cmd = [tool, "-s", str(sectors), "-F", "32", raw_device]
            _status(f"Running: {' '.join(cmd)}")
            subprocess.run(cmd, check=True)
            _status(f"Successfully formatted {raw_device} as FAT32.")
        except FileNotFoundError:
            _status(f"ERROR: mkfs.vfat not found. Install dosfstools.")
            return False
        except subprocess.CalledProcessError as e:
            _status(f"ERROR: mkfs.vfat failed (exit {e.returncode}). Is the drive unmounted?")
            return False
        except Exception as e:
            _status(f"ERROR (FAT32): {type(e).__name__}: {e}")
            return False

    elif fs_type == 2:  # exFAT
        try:
            tool = _find_tool("mkfs.exfat")
            cmd = [tool, "-b", str(clusters), raw_device]
            _status(f"Running: {' '.join(cmd)}")
            subprocess.run(cmd, check=True)
            _status(f"Successfully formatted {raw_device} as exFAT.")
        except FileNotFoundError:
            _status(f"ERROR: mkfs.exfat not found. Install exfatprogs or exfat-utils.")
            return False
        except subprocess.CalledProcessError as e:
            _status(f"ERROR: mkfs.exfat failed (exit {e.returncode}). Is the drive unmounted?")
            return False
        except Exception as e:
            _status(f"ERROR (exFAT): {type(e).__name__}: {e}")
            return False

    elif fs_type == 3:  # ext4
        try:
            tool = _find_tool("mkfs.ext4")
            cmd = [tool, "-b", str(clusters), raw_device]
            _status(f"Running: {' '.join(cmd)}")
            subprocess.run(cmd, check=True)
            _status(f"Successfully formatted {raw_device} as ext4.")
        except FileNotFoundError:
            _status(f"ERROR: mkfs.ext4 not found. Install e2fsprogs.")
            return False
        except subprocess.CalledProcessError as e:
            _status(f"ERROR: mkfs.ext4 failed (exit {e.returncode}). Is the drive unmounted?")
            return False
        except Exception as e:
            _status(f"ERROR (ext4): {type(e).__name__}: {e}")
            return False

    else:
        _status(f"ERROR: Unknown fs_type={fs_type}")
        return False

    # Apply volume label after successful format
    _status("Applying volume label to formatted device...")
    volumecustomlabel(target_partition=raw_device)
    return True


def _apply_partition_scheme(drive: str):
    """Write a GPT or MBR partition table to the raw disk.

    states.partition_scheme: 0 = GPT, 1 = MBR
    states.target_system:    0 = UEFI (non CSM), 1 = BIOS (or UEFI-CSM)

    NOTE: This function is currently bypassed in dskformat() - formatting happens directly on raw device
    """
    raw_device = _get_raw_device(drive)
    scheme = getattr(states, 'partition_scheme', 0)  # 0 = GPT, 1 = MBR

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
        unexpected()


def drive_repair():
    _, drive, _ = _get_mount_and_drive()
    if not drive:
        log.error("No drive node found. Cannot repair.")
        return
    raw_device = _get_raw_device(drive)
    cmd = [_find_tool("sfdisk"), raw_device]
    log.info("Attempting drive repair on %s (raw: %s)...", drive, raw_device)
    try:
        subprocess.run(["umount", drive], check=True)
        subprocess.run(cmd, input=b",,0c;\n", check=True)
        subprocess.run([_find_tool("mkfs.vfat"), "-F", "32", "-n", "REPAIRED", drive], check=True)
        log.info("Successfully repaired drive %s (FAT32).", drive)
    except Exception as e:
        log.error("Could not repair drive %s: %s: %s", drive, type(e).__name__, e)


'''This file is for defining windows tweaks functions, this includes:
1. Hardware Requirements Bypass
2. Making Local Accounts
3. Disabling privacy questions'''
# bypass hardware requirements
def winhardwarebypass():
    mount, _, _ = _get_mount_and_drive()
    commands = [
        "cd Setup",
        "newkey LabConfig",
        "cd LabConfig",
        "addvalue BypassTPMCheck 4 1",
        "addvalue BypassSecureBootCheck 4 1",
        "addvalue BypassRAMCheck 4 1",
        "save",
        "exit"
    ]
    cmd_string = "\n".join(commands) + "\n"
    log.info("winhardwarebypass: injecting registry keys into boot.wim at %s...", mount)
    try:
        #creates temporary mount point for the windows iso
        subprocess.run(['mkdir', '/media/tempwinmnt'], check=True)
        #mounts the boot.wim file using wimlib
        subprocess.run(['wimmountrw', f'{mount}/sources/boot.wim', '2', '/media/tempwinmnt'], check=True)
        #using chntpw to edit the registry file SYSTEM and then also run the commands using stdin
        subprocess.run(['chntpw', 'e', '/media/tempwinmnt/Windows/System32/config/SYSTEM'], input=cmd_string, text=True, capture_output=True, check=True)
        subprocess.run(['wimunmount', '/media/tempwinmnt', '--commit'], check=True)
        subprocess.run(['rm', '-rf', '/media/tempwinmnt'], check=True)
        log.info("winhardwarebypass: registry keys injected successfully.")
    except subprocess.CalledProcessError as e:
        log.error("winhardwarebypass: CalledProcessError: %s", e.stderr)

# ability to make local accounts
def winlocalacc():
    mount, _, _ = _get_mount_and_drive()
    commands = [
        "cd Microsoft\\Windows\\CurrentVersion\\OOBE\n"
        "addvalue BypassNRO 4 1\n"
        "save\n"
        "exit\n"
    ]
    cmd_string = "\n".join(commands) + "\n"
    log.info("winlocalacc: bypassing online account requirement at %s...", mount)
    try:
        #creates temporary mount point for the windows iso
        subprocess.run(['mkdir', '/media/tempwinmnt'], check=True)
        #mounts the boot.wim file using wimlib
        subprocess.run(['wimmountrw', f'{mount}/sources/boot.wim', '2', '/media/tempwinmnt'], check=True)
        #using chntpw to edit the registry file SOFTWARE and then also run the commands using stdin
        subprocess.run(['chntpw', 'e', '/media/tempwinmnt/Windows/System32/config/SOFTWARE'], input=cmd_string, text=True, capture_output=True, check=True)
        subprocess.run(['wimunmount', '/media/tempwinmnt', '--commit'], check=True)
        subprocess.run(['rm', '-rf', '/media/tempwinmnt'], check=True)
        log.info("winlocalacc: online account bypass applied successfully.")
    except subprocess.CalledProcessError as e:
        log.error("winlocalacc: CalledProcessError: %s", e.stderr)

#skip privacy questions in windows
def winskipprivacyques():
    mount, _, _ = _get_mount_and_drive()
    xml_content = """<?xml version="1.0" encoding="utf-8"?>
<unattend xmlns="urn:schemas-microsoft-com:unattend">
    <settings pass="oobeSystem">
        <component name="Microsoft-Windows-Shell-Setup" processorArchitecture="amd64" publicKeyToken="31bf3856ad364e35" language="neutral" versionScope="nonSxS">
            <OOBE>
                <HideEULAPage>true</HideEULAPage>
                <HidePrivacyExperience>true</HidePrivacyExperience>
                <HideOnlineAccountScreens>true</HideOnlineAccountScreens>
                <ProtectYourPC>3</ProtectYourPC>
            </OOBE>
        </component>
    </settings>
</unattend>"""
    xml_path = os.path.join(mount, "autounattend.xml")
    log.info("winskipprivacyques: writing autounattend.xml to %s...", xml_path)
    with open(xml_path, "w") as f:
        f.write(xml_content)
    log.info("winskipprivacyques: autounattend.xml created to skip privacy screens.")

#creating custom name local account (!) this also includes skip microsoft account (!)
def winlocalaccname():
    mount, _, _ = _get_mount_and_drive()
    user_name = states.winlocalacc
    ## username CANNOT HAVE \/[]:;|=,+*?<> or be empty!!! need to check for that!
    xml_template = f"""<?xml version="1.0" encoding="utf-8"?>
    <unattend xmlns="urn:schemas-microsoft-com:unattend">
        <settings pass="oobeSystem">
            <component name="Microsoft-Windows-Shell-Setup" processorArchitecture="amd64" publicKeyToken="31bf3856ad364e35" language="neutral" versionScope="nonSxS">
                <OOBE>
                    <HideEULAPage>true</HideEULAPage>
                    <HidePrivacyExperience>true</HidePrivacyExperience>
                    <HideOnlineAccountScreens>true</HideOnlineAccountScreens>
                    <ProtectYourPC>3</ProtectYourPC>
                </OOBE>
                <UserAccounts>
                    <LocalAccounts>
                        <LocalAccount wcm:action="add" xmlns:wcm="http://schemas.microsoft.com/WMIConfig/2002/State">
                            <Password><Value></Value><PlainText>true</PlainText></Password>
                            <Description>Primary Local Account</Description>
                            <DisplayName>{user_name}</DisplayName>
                            <Group>Administrators</Group>
                            <n>{user_name}</n>
                        </LocalAccount>
                    </LocalAccounts>
                </UserAccounts>
            </component>
        </settings>
    </unattend>"""
    xml_path = os.path.join(mount, "autounattend.xml")
    log.info("winlocalaccname: writing autounattend.xml for local account %r to %s...", user_name, xml_path)
    with open(xml_path, "w") as f:
        f.write(xml_template)
    log.info(
        "winlocalaccname: autounattend.xml created — privacy screens skipped, local account %r created.",
        user_name,
    )
    #fuck you, formatting.py
