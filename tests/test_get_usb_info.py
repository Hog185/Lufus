from __future__ import annotations
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

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

    # Mock os.stat safely
    os_stat_orig = get_usb_info_module.os.stat
    def mock_os_stat(p):
        if str(p).startswith("/dev/"):
            mock_stat = MagicMock()
            mock_stat.st_rdev = 1234
            return mock_stat
        return os_stat_orig(p)
    monkeypatch.setattr(get_usb_info_module.os, "stat", mock_os_stat)

    # Mock pyudev
    mock_context = MagicMock()
    mock_device = MagicMock()
    mock_device.attributes = {"size": str((16 * 1024**3) // 512)}
    mock_device.get.return_value = "MYUSB"
    monkeypatch.setattr(get_usb_info_module.pyudev, "Context", lambda: mock_context)
    monkeypatch.setattr(get_usb_info_module.pyudev.Devices, "from_device_number", lambda ctx, type, num: mock_device)

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

    # Mock os.stat safely
    os_stat_orig = get_usb_info_module.os.stat
    def mock_os_stat(p):
        if str(p).startswith("/dev/"):
            mock_stat = MagicMock()
            mock_stat.st_rdev = 5678
            return mock_stat
        return os_stat_orig(p)
    monkeypatch.setattr(get_usb_info_module.os, "stat", mock_os_stat)

    # Mock pyudev
    mock_context = MagicMock()
    mock_device = MagicMock()
    mock_device.attributes = {"size": str((8 * 1024**3) // 512)}
    mock_device.get.return_value = None
    monkeypatch.setattr(get_usb_info_module.pyudev, "Context", lambda: mock_context)
    monkeypatch.setattr(get_usb_info_module.pyudev.Devices, "from_device_number", lambda ctx, type, num: mock_device)

    result = get_usb_info_module.get_usb_info(mount_path)
    assert result["label"] == "NO_LABEL"


def test_get_usb_info_returns_empty_when_pyudev_fails(monkeypatch) -> None:
    mount_path = "/media/testuser/USB"
    device_node = "/dev/sdb1"

    monkeypatch.setattr(
        get_usb_info_module.psutil,
        "disk_partitions",
        lambda *args, **kwargs: [SimpleNamespace(mountpoint=mount_path, device=device_node)],
    )

    # Mock os.stat safely
    os_stat_orig = get_usb_info_module.os.stat
    def mock_os_stat(p):
        if str(p).startswith("/dev/"):
            raise Exception("stat fail")
        return os_stat_orig(p)
    monkeypatch.setattr(get_usb_info_module.os, "stat", mock_os_stat)

    # This should return None because of the catch-all Exception in get_usb_info
    assert get_usb_info_module.get_usb_info(mount_path) is None
