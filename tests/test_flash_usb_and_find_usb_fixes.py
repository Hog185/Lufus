"""Regression tests for bugs fixed in flash_usb.py and find_usb.py.

Each test is named after the bug it reproduces and verifies the fix.
Tests use monkeypatching so no real hardware, dd, or network is needed.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import lufus.writing.flash_usb as flash_usb_module
from lufus.utils import strip_partition_suffix
from lufus.writing.flash_usb import flash_usb
import lufus.drives.find_usb as find_usb_module
from lufus.drives.find_usb import _media_directories


# ---------------------------------------------------------------------------
# strip_partition_suffix — BUG: re.sub(r"[0-9]+$") mangled NVMe names
# ---------------------------------------------------------------------------


class TestStripPartitionSuffix:
    """Before the fix, `re.sub(r'[0-9]+$', '', '/dev/nvme0n1p1')` produced
    '/dev/nvme0n' — stripping the trailing '1' of the namespace component.
    The new helper must handle NVMe, MMC, and standard SCSI correctly.
    """

    def test_nvme_partition_stripped_correctly(self):
        # BUG: old code gave '/dev/nvme0n' (stripped '1' from 'n1')
        assert strip_partition_suffix("/dev/nvme0n1p1") == "/dev/nvme0n1"

    def test_nvme_multi_digit_namespace_and_partition(self):
        assert strip_partition_suffix("/dev/nvme1n2p3") == "/dev/nvme1n2"

    def test_mmc_partition_stripped_correctly(self):
        assert strip_partition_suffix("/dev/mmcblk0p1") == "/dev/mmcblk0"

    def test_mmc_multi_digit_partition(self):
        assert strip_partition_suffix("/dev/mmcblk1p12") == "/dev/mmcblk1"

    def test_scsi_single_digit_partition(self):
        assert strip_partition_suffix("/dev/sdb1") == "/dev/sdb"

    def test_scsi_multi_digit_partition(self):
        assert strip_partition_suffix("/dev/sda10") == "/dev/sda"

    def test_whole_disk_unchanged(self):
        assert strip_partition_suffix("/dev/sdb") == "/dev/sdb"

    def test_nvme_whole_disk_unchanged(self):
        assert strip_partition_suffix("/dev/nvme0n1") == "/dev/nvme0n1"

    def test_unknown_path_unchanged(self):
        assert strip_partition_suffix("/dev/loop0") == "/dev/loop0"


# ---------------------------------------------------------------------------
# flash_usb — BUG: OSError from os.path.getsize propagated instead of False
# ---------------------------------------------------------------------------


class Testflash_usbOsError:
    """Before the fix, calling flash_usb with a non-existent iso_path raised
    OSError (from os.path.getsize). Callers expect a bool return value.
    """

    def test_returns_false_when_iso_path_does_not_exist(self, tmp_path):
        missing = str(tmp_path / "nonexistent.iso")
        result = flash_usb("/dev/sdb", missing)
        assert result is False

    def test_returns_false_when_iso_path_is_directory(self, tmp_path):
        result = flash_usb("/dev/sdb", str(tmp_path))
        assert result is False


# ---------------------------------------------------------------------------
# flash_usb — BUG: FileNotFoundError from Popen propagated instead of False
# ---------------------------------------------------------------------------


class Testflash_usbDdNotFound:
    """Before the fix, if dd was absent, Popen raised FileNotFoundError
    which was not caught — the caller received an exception instead of False.
    """

    def test_returns_false_when_dd_not_found(self, tmp_path, monkeypatch):
        iso = tmp_path / "valid.iso"
        # Write a minimal valid ISO9660 PVD so signature check passes
        payload = bytearray(32775)
        payload[32768] = 0x01
        payload[32769:32774] = b"CD001"
        payload[32774] = 0x01
        iso.write_bytes(bytes(payload))

        # Patch is_windows_iso to avoid 7z subprocess
        monkeypatch.setattr(flash_usb_module, "is_windows_iso", lambda p: False)
        # Patch check_iso_signature to pass
        monkeypatch.setattr(flash_usb_module, "check_iso_signature", lambda p: True)

        # Make Popen raise FileNotFoundError (dd absent)
        def raise_fnf(*args, **kwargs):
            raise FileNotFoundError("dd not found")

        monkeypatch.setattr(flash_usb_module.subprocess, "Popen", raise_fnf)

        result = flash_usb("/dev/sdb", str(iso))
        assert result is False


# ---------------------------------------------------------------------------
# flash_usb — device stripping uses correct helper (NVMe regression guard)
# ---------------------------------------------------------------------------


class Testflash_usbNvmeDeviceStrip:
    """Ensure flash_usb forwards the correctly stripped NVMe device to dd."""

    def test_nvme_device_stripped_before_dd(self, tmp_path, monkeypatch):
        iso = tmp_path / "test.img"
        iso.write_bytes(b"\x00" * 100)

        monkeypatch.setattr(flash_usb_module, "check_iso_signature", lambda p: True)
        monkeypatch.setattr(flash_usb_module, "is_windows_iso", lambda p: False)

        popen_calls = {}

        class FakeProcess:
            pid = 12345
            returncode = 0

            def __init__(self, args, **kwargs):
                popen_calls["args"] = args
                self.stderr = FakePipe()

            def wait(self):
                pass

        class FakePipe:
            def readline(self):
                return b""

        monkeypatch.setattr(flash_usb_module.subprocess, "Popen", FakeProcess)

        flash_usb("/dev/nvme0n1p1", str(iso))

        dd_of = next((a for a in popen_calls["args"] if a.startswith("of=")), None)
        assert dd_of == "of=/dev/nvme0n1", f"Expected of=/dev/nvme0n1, got {dd_of}"


# ---------------------------------------------------------------------------
# find_usb / find_device_node — BUG: duplicated path-scan logic (DRY violation)
# ---------------------------------------------------------------------------


class TestMediaDirectories:
    """_media_directories() must deduplicate entries — before the fix
    the two scan passes could yield duplicate entries for the same path.
    """

    def test_no_duplicates_in_result(self, monkeypatch):
        user = "testuser"
        monkeypatch.setattr(find_usb_module.getpass, "getuser", lambda: user)

        # /media contains 'testuser' (a dir), /media/testuser also exists
        # — the old code would add /media/testuser/USB twice.
        def fake_exists(p):
            return p in {"/media", f"/media/{user}", f"/media/{user}/USB"}

        def fake_isdir(p):
            return fake_exists(p)

        def fake_listdir(p):
            if p == "/media":
                return [user]  # yields /media/testuser
            if p == f"/media/{user}":
                return ["USB"]  # yields /media/testuser/USB
            return []

        monkeypatch.setattr(find_usb_module.os.path, "exists", fake_exists)
        monkeypatch.setattr(find_usb_module.os.path, "isdir", fake_isdir)
        monkeypatch.setattr(find_usb_module.os, "listdir", fake_listdir)

        result = _media_directories()
        # No duplicates
        assert len(result) == len(set(result)), f"Duplicates found: {result}"


# ---------------------------------------------------------------------------
# find_usb — BUG: psutil.disk_partitions() called without all=True
# ---------------------------------------------------------------------------


class TestFindUsbUsesAllPartitions:
    """find_usb must call disk_partitions(all=True) so bind-mounted USB
    volumes are not silently skipped on systems that use them.
    """

    def test_find_usb_passes_all_true_to_disk_partitions(self, monkeypatch):
        calls = {}

        def fake_disk_partitions(all=False):
            calls["all"] = all
            return []

        monkeypatch.setattr(find_usb_module.psutil, "disk_partitions", fake_disk_partitions)
        monkeypatch.setattr(find_usb_module.getpass, "getuser", lambda: "u")
        monkeypatch.setattr(find_usb_module.os.path, "exists", lambda p: False)
        monkeypatch.setattr(find_usb_module.os.path, "isdir", lambda p: False)

        find_usb_module.find_usb()
        assert calls.get("all") is True

    def test_find_dn_passes_all_true_to_disk_partitions(self, monkeypatch):
        calls = {}

        def fake_disk_partitions(all=False):
            calls["all"] = all
            return []

        monkeypatch.setattr(find_usb_module.psutil, "disk_partitions", fake_disk_partitions)
        monkeypatch.setattr(find_usb_module.getpass, "getuser", lambda: "u")
        monkeypatch.setattr(find_usb_module.os.path, "exists", lambda p: False)
        monkeypatch.setattr(find_usb_module.os.path, "isdir", lambda p: False)

        find_usb_module.find_device_node()
        assert calls.get("all") is True


# ---------------------------------------------------------------------------
# find_device_node — BUG: empty device_node would overwrite states.DN with ""
# ---------------------------------------------------------------------------


class TestFindDNGuardsEmptyDevice:
    """find_device_node must not write an empty string to states.DN."""

    def test_empty_device_node_does_not_overwrite_states_dn(self, monkeypatch):
        from lufus import state as state_mod

        user = "testuser"
        mount_path = f"/media/{user}/USB"
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
            lambda p: ["USB"] if p == f"/media/{user}" else [],
        )
        # Partition with empty device string
        monkeypatch.setattr(
            find_usb_module.psutil,
            "disk_partitions",
            lambda *args, **kwargs: [SimpleNamespace(mountpoint=mount_path, device="")],
        )

        state_mod.device_node = "/dev/sdb1"  # set a valid value first
        result = find_usb_module.find_device_node()

        assert result is None, "find_device_node should return None when device is empty"
        assert state_mod.device_node == "/dev/sdb1", "states.DN must not be overwritten with empty string"


# ---------------------------------------------------------------------------
# Existing-behaviour smoke tests (ensure refactor didn't break happy paths)
# ---------------------------------------------------------------------------


class TestFindUsbHappyPath:
    def test_find_usb_returns_label_from_lsblk(self, monkeypatch):
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
            lambda *a, **kw: "MY_LABEL\n",
        )

        result = find_usb_module.find_usb()
        assert result == {mount_path: "MY_LABEL"}

    def test_find_dn_returns_device_node(self, monkeypatch):
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
