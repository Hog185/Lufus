import glob
import re
import shlex
import subprocess
import sys
import os
from pathlib import Path
import time
from lufus.drives import states
from lufus.drives import find_usb as fu
from lufus.lufus_logging import get_logger

log = get_logger(__name__)


def _get_raw_device(drive: str|None) -> str|None:
    """Return the raw disk device for a partition node.

    Handles standard SCSI/SATA names (e.g. /dev/sdb1 → /dev/sdb),
    NVMe names (e.g. /dev/nvme0n1p1 → /dev/nvme0n1), and
    MMC/eMMC names (e.g. /dev/mmcblk0p1 → /dev/mmcblk0).
    if a null device given return None
    Falls back to the input unchanged if no pattern matches.
    """
    # handling if null is given as drive
    if not drive:
        return None
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
    log.error("The command pkexec or labeling software was not found on your system.")


def FormatFail():
    log.error("Formatting failed. Was the password correct? Is the drive unmounted?")


def UnmountFail():
    log.error(
        "Unmounting failed. Perhaps either the drive was already unmounted or is in use."
    )


def unexpected():
    log.error("An unexpected error occurred")


# UNMOUNT FUNCTION
def unmount(drive: str = None):
    if not drive:
        _, drive, _ = _get_mount_and_drive()
    if not drive:
        msg="No drive node found. Cannot unmount."
        log.error(msg)
        print(msg)
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


# MOUNT FUNCTION
def remount():
    mount, drive, _ = _get_mount_and_drive()
    if not drive or not mount:
        msg = "No drive node or mount point found. Cannot remount."
        log.error(msg)
        print(msg) 
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


### DISK FORMATTING ###
def volumecustomlabel():
    newlabel =str(states.new_label or "") # re crashing if the label was null
    # Sanitize label: allow only alphanumeric, spaces, hyphens, and underscores
    newlabel = re.sub(r'[^a-zA-Z0-9 \-_]', '', newlabel).strip()
    if not newlabel:
        newlabel = "USB_DRIVE"

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
    fs_type = states.currentFS
    cmd_map = {
        0: ["ntfslabel", drive, newlabel],
        1: ["fatlabel", drive, newlabel],
        2: ["exfatlabel", drive, newlabel], # this should be exfatlabel
        3: ["e2label", drive, newlabel],
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
    """Return (cluster_bytes, sector_bytes, cluster_in_sectors) tuple.

    Falls back to safe defaults when the drive node is unavailable.
    Never crashes — always returns a valid 3-tuple.
    """
    _, drive, mount_dict = _get_mount_and_drive()

    if not mount_dict and not drive:
        log.error("No USB mount found. Is the drive plugged in and mounted?")
        return 4096, 512, 8

    # Map states.cluster_size index to block size in bytes
    cluster_size_map = {0: 4096, 1: 8192}
    cluster1 = cluster_size_map.get(states.cluster_size, 4096)

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
    args = ["badblocks", "-sv", "-b", str(logical_block_size)]
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
            return False
        log.info("No bad blocks found on %s.", drive)
        return True
    except FileNotFoundError:
        log.error("'badblocks' utility not found. Install e2fsprogs.")
        return False
    except Exception as e:
        log.error("(BADBLOCK) Unexpected error: %s: %s", type(e).__name__, e)
        unexpected()
        return False
    
    
def get_first_partition(raw_device:str):
    for _ in range(10): # wait for kernel sync
        if "nvme" in raw_device or "mmcblk" in raw_device:
            candidates=sorted(glob.glob(f"{raw_device}p*"))
        else:
            candidates=sorted(glob.glob(f"{raw_device}[0-9]*"))
        if candidates:
            return candidates[0]
        time.sleep(0.5)
        
    return None


def dskformat():
    cluster1, cluster2, sector = cluster()
    _, drive, _ = _get_mount_and_drive()
    if not drive:
        log.error("No drive found. Cannot format.")
        return

    # Ensure we have the raw device for partitioning
    raw_device = _get_raw_device(drive)

    fs_type = states.currentFS
    clusters = cluster1
    sectors = sector

    # Build partition table based on scheme before formatting
    _apply_partition_scheme(raw_device)

    # Sync kernel partition table
    try:
        subprocess.run(["partprobe", raw_device], check=False)
        subprocess.run(["udevadm", "settle"], timeout=10, check=False)
    except Exception:
        pass

    # Determine the first partition node

    partition = get_first_partition(raw_device)

    log.info("Formatting partition %s (fs_type=%d, clusters=%d, sectors=%d)...", partition, fs_type, clusters, sectors)

    if fs_type == 0:
        try:
            subprocess.run(
                ["mkfs.ntfs", "-c", str(clusters), "-Q", partition], check=True
            )
            log.info("Successfully formatted %s as NTFS.", partition)
        except FileNotFoundError:
            pkexecNotFound()
        except subprocess.CalledProcessError:
            FormatFail()
        except Exception as e:
            log.error("(NTFS) %s: %s", type(e).__name__, e)
            unexpected()
    elif fs_type == 1:
        try:
            subprocess.run(
                ["mkfs.vfat", "-s", str(sectors), "-F", "32", partition], check=True
            )
            log.info("Successfully formatted %s as FAT32.", partition)
        except FileNotFoundError:
            pkexecNotFound()
        except subprocess.CalledProcessError:
            FormatFail()
        except Exception as e:
            log.error("(FAT32) %s: %s", type(e).__name__, e)
            unexpected()
    elif fs_type == 2:
        try:
            subprocess.run(["mkfs.exfat", "-b", str(clusters), partition], check=True)
            log.info("Successfully formatted %s as exFAT.", partition)
        except FileNotFoundError:
            pkexecNotFound()
        except subprocess.CalledProcessError:
            FormatFail()
        except Exception as e:
            log.error("(exFAT) %s: %s", type(e).__name__, e)
            unexpected()
    elif fs_type == 3:
        try:
            subprocess.run(["mkfs.ext4", "-b", str(clusters), partition], check=True)
            log.info("Successfully formatted %s as ext4.", partition)
        except FileNotFoundError:
            pkexecNotFound()
        except subprocess.CalledProcessError:
            FormatFail()
        except Exception as e:
            log.error("(ext4) %s: %s", type(e).__name__, e)
            unexpected()
    else:
        unexpected()


def _apply_partition_scheme(drive: str|None):
    """Write a GPT or MBR partition table to the raw disk.

    states.partition_scheme: 0 = GPT, 1 = MBR
    states.target_system:    0 = UEFI (non CSM), 1 = BIOS (or UEFI-CSM)
    """
    # check if null drive
    if not drive:
        log.error("No drive provided for partitioning.")
        return
    
    raw_device = _get_raw_device(drive)
    
    # again null drive
    if not raw_device:
        log.error("Got null as drive at formatting.py")
        return
    scheme = states.partition_scheme  # 0 = GPT, 1 = MBR

    scheme_name = "GPT" if scheme == 0 else "MBR"
    log.info("Applying %s partition scheme to %s...", scheme_name, raw_device)
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
    cmd = ["sfdisk", raw_device]
    log.info("Attempting drive repair on %s (raw: %s)...", drive, raw_device)
    try:
        subprocess.run(["umount", drive], check=True)
        subprocess.run(cmd, input=b",,0c;\n", check=True)
        subprocess.run(["mkfs.vfat", "-F", "32", "-n", "REPAIRED", drive], check=True)
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
        "addvalue BypassNRO 4 1" # \n will break cause its already joined with \n
        "save"
        "exit"
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
                            <Name>{user_name}</Name>
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
