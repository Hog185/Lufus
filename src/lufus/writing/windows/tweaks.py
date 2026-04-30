"""Windows installation customization functions.

These modify Windows installation media (boot.wim, autounattend.xml)
to bypass hardware requirements, skip privacy questions, and create
local accounts.
"""

import subprocess
import os
import re
import tempfile
import xml.etree.ElementTree as ET
from lufus.utils import get_mount_and_drive
from lufus import state
from lufus.lufus_logging import get_logger

log = get_logger(__name__)


def _get_mount_and_drive():
    return get_mount_and_drive()


def _is_valid_windows_username(username: str) -> bool:
    """Validate Windows username: 1-20 chars, no \ / [ ] : ; | = , + * ? < > @."""
    if not username or len(username) > 20:
        return False
    # Prohibited characters in Windows usernames
    invalid_chars = r'[\\/\[\]:;|=,+*?<>@]'
    if re.search(invalid_chars, username):
        return False
    # Check for reserved names (simplified)
    reserved = {"CON", "PRN", "AUX", "NUL", "COM1", "COM2", "LPT1", "ADMINISTRATOR", "GUEST"}
    if username.upper() in reserved:
        return False
    return True


def _apply_wim_registry_tweaks(mount_path: str, wim_path: str, config_name: str, commands: list[str]):
    """Helper to mount boot.wim and apply registry changes via chntpw."""
    with tempfile.TemporaryDirectory() as temp_mnt:
        try:
            log.info("Mounting %s to %s...", wim_path, temp_mnt)
            subprocess.run(["sudo", "wimmountrw", wim_path, "2", temp_mnt], check=True)
            
            reg_file = os.path.join(temp_mnt, "Windows/System32/config", config_name)
            if not os.path.exists(reg_file):
                raise FileNotFoundError(f"Registry file not found: {reg_file}")

            cmd_string = "\n".join(commands) + "\n"
            log.info("Injecting registry keys into %s...", config_name)
            
            subprocess.run(
                ["sudo", "chntpw", "-e", reg_file],
                input=cmd_string,
                text=True,
                capture_output=True,
                check=True,
            )
            
            log.info("Committing WIM changes...")
            subprocess.run(["sudo", "wimunmount", temp_mnt, "--commit"], check=True)
        except Exception as e:
            log.error("Failed to apply WIM tweaks: %s", e)
            # Ensure we attempt to unmount if something went wrong
            subprocess.run(["sudo", "wimunmount", temp_mnt], capture_output=True)
            raise


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
    wim_path = os.path.join(mount, "sources/boot.wim")
    try:
        _apply_wim_registry_tweaks(mount, wim_path, "SYSTEM", commands)
        log.info("win_hardware_bypass: registry keys injected successfully.")
    except Exception as e:
        log.error("win_hardware_bypass failed: %s", e)


def win_local_acc():
    mount, _, _ = _get_mount_and_drive()
    if not mount:
        log.error("win_local_acc: no USB mount found")
        return
        
    commands = [
        "cd Microsoft\\Windows\\CurrentVersion\\OOBE",
        "addvalue BypassNRO 4 1",
        "save",
        "exit",
    ]
    wim_path = os.path.join(mount, "sources/boot.wim")
    try:
        _apply_wim_registry_tweaks(mount, wim_path, "SOFTWARE", commands)
        log.info("win_local_acc: online account bypass applied successfully.")
    except Exception as e:
        log.error("win_local_acc failed: %s", e)


def _write_autounattend(mount_path: str, user_name: str = None):
    """Generate autounattend.xml securely using ElementTree."""
    ns = {"": "urn:schemas-microsoft-com:unattend", "wcm": "http://schemas.microsoft.com/WMIConfig/2002/State"}
    # Register namespaces to avoid ns0 prefixes
    for prefix, uri in ns.items():
        ET.register_namespace(prefix, uri)

    root = ET.Element("unattend", xmlns=ns[""])
    settings = ET.SubElement(root, "settings", pass="oobeSystem")
    comp = ET.SubElement(settings, "component", {
        "name": "Microsoft-Windows-Shell-Setup",
        "processorArchitecture": "amd64",
        "publicKeyToken": "31bf3856ad364e35",
        "language": "neutral",
        "versionScope": "nonSxS"
    })
    
    oobe = ET.SubElement(comp, "OOBE")
    ET.SubElement(oobe, "HideEULAPage").text = "true"
    ET.SubElement(oobe, "HidePrivacyExperience").text = "true"
    ET.SubElement(oobe, "HideOnlineAccountScreens").text = "true"
    ET.SubElement(oobe, "ProtectYourPC").text = "3"

    if user_name:
        accounts = ET.SubElement(comp, "UserAccounts")
        local_accs = ET.SubElement(accounts, "LocalAccounts")
        acc = ET.SubElement(local_accs, "LocalAccount", {
            "{http://schemas.microsoft.com/WMIConfig/2002/State}action": "add"
        })
        pw = ET.SubElement(acc, "Password")
        ET.SubElement(pw, "Value")
        ET.SubElement(pw, "PlainText").text = "true"
        ET.SubElement(acc, "Description").text = "Primary Local Account"
        ET.SubElement(acc, "DisplayName").text = user_name
        ET.SubElement(acc, "Group").text = "Administrators"
        ET.SubElement(acc, "Name").text = user_name

    xml_path = os.path.join(mount_path, "autounattend.xml")
    tree = ET.ElementTree(root)
    
    # Prepend XML declaration manually as ET.write(xml_declaration=True) handles it differently
    with open(xml_path, "wb") as f:
        f.write(b'<?xml version="1.0" encoding="utf-8"?>\n')
        tree.write(f, encoding="utf-8", xml_declaration=False)


def win_skip_privacy_questions():
    mount, _, _ = _get_mount_and_drive()
    if not mount:
        return
    try:
        _write_autounattend(mount)
        log.info("win_skip_privacy_questions: autounattend.xml created.")
    except Exception as e:
        log.error("win_skip_privacy_questions failed: %s", e)


def win_local_acc_name():
    mount, _, _ = _get_mount_and_drive()
    if not mount:
        return
    user_name = state.win_local_acc
    
    if not _is_valid_windows_username(user_name):
        log.error("win_local_acc_name: invalid username %r, skipping account creation", user_name)
        return

    try:
        _write_autounattend(mount, user_name)
        log.info("win_local_acc_name: autounattend.xml created for user %r", user_name)
    except Exception as e:
        log.error("win_local_acc_name failed: %s", e)
