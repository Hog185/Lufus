"""Global application state for Lufus."""

from dataclasses import dataclass


@dataclass
class AppState:
    """Mutable runtime state shared across the application."""

    # App info
    version: str = "v1.0.0"

    # Format options
    filesystem_index: int = 0  # 0=NTFS, 1=FAT32, 2=exFAT, 3=ext4, 4=UDF
    image_option: int = 0  # 0=Windows, 1=Linux, 2=Other, 3=Format Only, 4=Ventoy
    partition_scheme: int = 0  # 0=GPT, 1=MBR
    target_system: int = 0  # 0=UEFI, 1=BIOS
    cluster_size: int = 0  # 0=4096, 1=8192
    quick_format: int = 0  # 0=quick, 1=full
    create_extended: int = 0
    check_bad: int = 0  # 0=1 pass, 1=2 passes
    new_label: str = "USB_DRIVE"
    flash_mode: int = 0  # 0=ISO, 1=DD
    theme: str = "default"
    # Runtime state
    iso_path: str = ""
    device_node: str = ""

    # Verification
    verify_hash: bool = False
    expected_hash: str = ""

    # Localization
    language: str = "English"

    # Windows tweaks
    win_hardware_bypass: int = 0
    win_microsoft_acc: int = 0
    win_local_acc_chk: int = 0
    win_local_acc: str = "default"
    win_privacy: int = 0

    # Settings persistence
    theme_index: int = 0
    language_index: int = 0


state = AppState()
