from __future__ import annotations
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from lufus.drives import find_usb as find_usb_module


def test_find_usb_returns_mount_to_label_mapping(monkeypatch) -> None:
    user = "testuser"
    mount_path = f"/media/{user}/MY_USB"

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
        lambda *args, **kwargs: [SimpleNamespace(mountpoint=mount_path, device="/dev/sdb1")],
    )
    monkeypatch.setattr(
        find_usb_module.subprocess,
        "check_output",
        lambda *args, **kwargs: "lufus_USB\n",
    )

    result = find_usb_module.find_usb()
    assert result == {mount_path: "lufus_USB"}


def test_find_usb_falls_back_to_dir_name_when_lsblk_fails(monkeypatch) -> None:
    user = "testuser"
    mount_path = f"/media/{user}/NO_LABEL"

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
        lambda *args, **kwargs: [SimpleNamespace(mountpoint=mount_path, device="/dev/sdc1")],
    )

    def raise_lsblk_error(*args, **kwargs):
        raise subprocess.CalledProcessError(returncode=1, cmd="lsblk")

    monkeypatch.setattr(find_usb_module.subprocess, "check_output", raise_lsblk_error)

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
