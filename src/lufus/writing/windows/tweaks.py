"""Windows installation customization functions.

These modify Windows installation media (boot.wim, autounattend.xml)
to bypass hardware requirements, skip privacy questions, and create
local accounts.
"""

import subprocess
import os
from lufus.utils import get_mount_and_drive
from lufus import state
from lufus.lufus_logging import get_logger

log = get_logger(__name__)


def _get_mount_and_drive():
    return get_mount_and_drive()


def win_hardware_bypass():
    mount, _, _ = _get_mount_and_drive()
    if not mount:
        log.error("win_hardware_bypass: no USB mount found")
        return
    commands = [
        "cd Setup",
        "newkey LabConfig",
        "cd LabConfig",
        "addvalue BypassTPMCheck 4 1",
        "addvalue BypassSecureBootCheck 4 1",
        "addvalue BypassRAMCheck 4 1",
        "save",
        "exit",
    ]
    cmd_string = "\n".join(commands) + "\n"
    log.info("win_hardware_bypass: injecting registry keys into boot.wim at %s...", mount)
    try:
        subprocess.run(["mkdir", "/media/tempwinmnt"], check=True)
        subprocess.run(["wimmountrw", f"{mount}/sources/boot.wim", "2", "/media/tempwinmnt"], check=True)
        subprocess.run(
            ["chntpw", "e", "/media/tempwinmnt/Windows/System32/config/SYSTEM"],
            input=cmd_string,
            text=True,
            capture_output=True,
            check=True,
        )
        subprocess.run(["wimunmount", "/media/tempwinmnt", "--commit"], check=True)
        subprocess.run(["rm", "-rf", "/media/tempwinmnt"], check=True)
        log.info("win_hardware_bypass: registry keys injected successfully.")
    except subprocess.CalledProcessError as e:
        log.error("win_hardware_bypass: CalledProcessError: %s", e.stderr)


def win_local_acc():
    mount, _, _ = _get_mount_and_drive()
    if not mount:
        log.error("win_local_acc: no USB mount found")
        return
    commands = ["cd Microsoft\\Windows\\CurrentVersion\\OOBE\naddvalue BypassNRO 4 1\nsave\nexit\n"]
    cmd_string = "\n".join(commands) + "\n"
    log.info("win_local_acc: bypassing online account requirement at %s...", mount)
    try:
        subprocess.run(["mkdir", "/media/tempwinmnt"], check=True)
        subprocess.run(["wimmountrw", f"{mount}/sources/boot.wim", "2", "/media/tempwinmnt"], check=True)
        subprocess.run(
            ["chntpw", "e", "/media/tempwinmnt/Windows/System32/config/SOFTWARE"],
            input=cmd_string,
            text=True,
            capture_output=True,
            check=True,
        )
        subprocess.run(["wimunmount", "/media/tempwinmnt", "--commit"], check=True)
        subprocess.run(["rm", "-rf", "/media/tempwinmnt"], check=True)
        log.info("win_local_acc: online account bypass applied successfully.")
    except subprocess.CalledProcessError as e:
        log.error("win_local_acc: CalledProcessError: %s", e.stderr)


def win_skip_privacy_questions():
    mount, _, _ = _get_mount_and_drive()
    if not mount:
        log.error("win_skip_privacy_questions: no USB mount found")
        return
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
    log.info("win_skip_privacy_questions: writing autounattend.xml to %s...", xml_path)
    with open(xml_path, "w") as f:
        f.write(xml_content)
    log.info("win_skip_privacy_questions: autounattend.xml created to skip privacy screens.")


def win_local_acc_name():
    mount, _, _ = _get_mount_and_drive()
    if not mount:
        log.error("win_local_acc_name: no USB mount found")
        return
    user_name = state.win_local_acc
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
    log.info("win_local_acc_name: writing autounattend.xml for local account %r to %s...", user_name, xml_path)
    with open(xml_path, "w") as f:
        f.write(xml_template)
    log.info(
        "win_local_acc_name: autounattend.xml created — privacy screens skipped, local account %r created.",
        user_name,
    )
