from __future__ import annotations
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from lufus.drives import get_usb_info as get_usb_info_module


def test_get_usb_info_returns_empty_when_mount_not_found(monkeypatch) -> None:
    monkeypatch.setattr(
        get_usb_info_module.psutil,
        "disk_partitions",
        lambda *args, **kwargs: [SimpleNamespace(mountpoint="/mnt/other", device="/dev/sdb1")],
    )

    assert get_usb_info_module.get_usb_info("/media/testuser/USB") is None


def test_get_usb_info_returns_expected_dictionary(monkeypatch) -> None:
    mount_path = "/media/testuser/USB"
    device_node = "/dev/sdb1"

    monkeypatch.setattr(
        get_usb_info_module.psutil,
        "disk_partitions",
        lambda *args, **kwargs: [SimpleNamespace(mountpoint=mount_path, device=device_node)],
    )

    def fake_check_output(cmd, text=True, timeout=5):
        if cmd[-2:] == ["SIZE", device_node]:
            return str(16 * 1024**3)
        if cmd[-2:] == ["LABEL", device_node]:
            return "MYUSB\n"
        raise AssertionError(f"Unexpected command: {cmd}")

    monkeypatch.setattr(get_usb_info_module.subprocess, "check_output", fake_check_output)

    result = get_usb_info_module.get_usb_info(mount_path)
    assert result == {
        "device_node": device_node,
        "label": "MYUSB",
        "mount_path": mount_path,
    }


def test_get_usb_info_uses_mount_basename_when_label_is_empty(monkeypatch) -> None:
    mount_path = "/media/testuser/NO_LABEL"
    device_node = "/dev/sdc1"

    monkeypatch.setattr(
        get_usb_info_module.psutil,
        "disk_partitions",
        lambda *args, **kwargs: [SimpleNamespace(mountpoint=mount_path, device=device_node)],
    )

    def fake_check_output(cmd, text=True, timeout=5):
        if cmd[-2:] == ["SIZE", device_node]:
            return str(8 * 1024**3)
        if cmd[-2:] == ["LABEL", device_node]:
            return "\n"
        raise AssertionError(f"Unexpected command: {cmd}")

    monkeypatch.setattr(get_usb_info_module.subprocess, "check_output", fake_check_output)

    result = get_usb_info_module.get_usb_info(mount_path)
    assert result["label"] == "NO_LABEL"


def test_get_usb_info_returns_empty_when_lsblk_fails(monkeypatch) -> None:
    mount_path = "/media/testuser/USB"
    device_node = "/dev/sdb1"

    monkeypatch.setattr(
        get_usb_info_module.psutil,
        "disk_partitions",
        lambda *args, **kwargs: [SimpleNamespace(mountpoint=mount_path, device=device_node)],
    )

    def raise_lsblk_error(*args, **kwargs):
        raise subprocess.CalledProcessError(returncode=1, cmd="lsblk")

    monkeypatch.setattr(get_usb_info_module.subprocess, "check_output", raise_lsblk_error)

    assert get_usb_info_module.get_usb_info(mount_path) is None
