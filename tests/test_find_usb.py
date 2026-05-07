from __future__ import annotations
import sys
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from lufus.drives import find_usb as find_usb_module


def test_find_usb_returns_mount_to_label_mapping(monkeypatch) -> None:
    user = "testuser"
    mount_path = f"/media/{user}/MY_USB"
    device_node = "/dev/sdb1"

    monkeypatch.setattr(find_usb_module.getpass, "getuser", lambda: user)
    monkeypatch.setattr(
        find_usb_module.os.path,
        "exists",
        lambda p: p in {"/media", f"/media/{user}", mount_path},
    )
    monkeypatch.setattr(
        find_usb_module.os.path,
        "isdir",
        lambda p: p in {"/media", f"/media/{user}", mount_path},
    )
    monkeypatch.setattr(
        find_usb_module.os,
        "listdir",
        lambda p: ["MY_USB"] if p == f"/media/{user}" else [],
    )
    monkeypatch.setattr(
        find_usb_module.psutil,
        "disk_partitions",
        lambda *args, **kwargs: [SimpleNamespace(mountpoint=mount_path, device=device_node)],
    )

    # Mock os.stat safely
    os_stat_orig = os.stat
    def mock_os_stat(p):
        if str(p).startswith("/dev/"):
            mock_stat = MagicMock()
            mock_stat.st_rdev = 1234
            return mock_stat
        return os_stat_orig(p)
    monkeypatch.setattr(find_usb_module.os, "stat", mock_os_stat)

    # Mock pyudev
    mock_context = MagicMock()
    mock_device = MagicMock()
    mock_device.get.return_value = "lufus_USB"
    monkeypatch.setattr(find_usb_module.pyudev, "Context", lambda: mock_context)
    monkeypatch.setattr(find_usb_module.pyudev.Devices, "from_device_number", lambda ctx, type, num: mock_device)

    result = find_usb_module.find_usb()
    assert result == {mount_path: "lufus_USB"}


def test_find_usb_falls_back_to_dir_name_when_pyudev_fails(monkeypatch) -> None:
    user = "testuser"
    mount_path = f"/media/{user}/NO_LABEL"
    device_node = "/dev/sdc1"

    monkeypatch.setattr(find_usb_module.getpass, "getuser", lambda: user)
    monkeypatch.setattr(
        find_usb_module.os.path,
        "exists",
        lambda p: p in {"/media", f"/media/{user}", mount_path},
    )
    monkeypatch.setattr(
        find_usb_module.os.path,
        "isdir",
        lambda p: p in {"/media", f"/media/{user}", mount_path},
    )
    monkeypatch.setattr(
        find_usb_module.os,
        "listdir",
        lambda p: ["NO_LABEL"] if p == f"/media/{user}" else [],
    )
    monkeypatch.setattr(
        find_usb_module.psutil,
        "disk_partitions",
        lambda *args, **kwargs: [SimpleNamespace(mountpoint=mount_path, device=device_node)],
    )

    # Mock os.stat safely
    os_stat_orig = os.stat
    def mock_os_stat(p):
        if str(p).startswith("/dev/"):
            mock_stat = MagicMock()
            mock_stat.st_rdev = 5678
            return mock_stat
        return os_stat_orig(p)
    monkeypatch.setattr(find_usb_module.os, "stat", mock_os_stat)

    # Mock pyudev to fail
    mock_context = MagicMock()
    monkeypatch.setattr(find_usb_module.pyudev, "Context", lambda: mock_context)
    monkeypatch.setattr(find_usb_module.pyudev.Devices, "from_device_number", MagicMock(side_effect=Exception("udev fail")))

    result = find_usb_module.find_usb()
    assert result == {mount_path: "NO_LABEL"}


def test_find_dn_returns_matching_device_node(monkeypatch) -> None:
    user = "testuser"
    mount_path = f"/media/{user}/FLASH"

    monkeypatch.setattr(find_usb_module.getpass, "getuser", lambda: user)
    monkeypatch.setattr(
        find_usb_module.os.path,
        "exists",
        lambda p: p in {"/media", f"/media/{user}", mount_path},
    )
    monkeypatch.setattr(
        find_usb_module.os.path,
        "isdir",
        lambda p: p in {"/media", f"/media/{user}", mount_path},
    )
    monkeypatch.setattr(
        find_usb_module.os,
        "listdir",
        lambda p: ["FLASH"] if p == f"/media/{user}" else [],
    )
    monkeypatch.setattr(
        find_usb_module.psutil,
        "disk_partitions",
        lambda *args, **kwargs: [SimpleNamespace(mountpoint=mount_path, device="/dev/sdd1")],
    )

    assert find_usb_module.find_device_node() == "/dev/sdd1"
