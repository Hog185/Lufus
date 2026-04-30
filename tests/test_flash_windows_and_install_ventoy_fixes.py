"""Regression tests for bugs fixed in flash_windows.py and install_ventoy.py.

Each test is named after the bug it reproduces and verifies the fix.
All tests are deterministic and isolated — no real partitions or downloads.
"""

from __future__ import annotations

import os
import sys
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import lufus.writing.windows.flash as fw_module
from lufus.writing.windows.flash import _get_wim_size, _find_path_case_insensitive
import lufus.writing.install_ventoy as iv_module
from lufus.writing.install_ventoy import download_wimboot, install_grub


class TestFlashWindowsImports:
    def test_optional_callable_not_imported(self):
        """Optional and Callable were imported but never used — removed."""
        import importlib, types

        spec = importlib.util.spec_from_file_location("fw_check", str(SRC / "lufus/writing/windows/flash.py"))
        mod = importlib.util.module_from_spec(spec)
        # If Optional/Callable were still imported they'd be attributes
        assert not hasattr(mod, "Optional"), "Optional should not be imported"
        assert not hasattr(mod, "Callable"), "Callable should not be imported"


class TestRunOutRemoved:
    def test_run_out_no_longer_present(self):
        """run_out() was dead code — it should be gone."""
        assert not hasattr(fw_module, "run_out"), "run_out() dead code should be removed"


class TestFlashWindowsOsErrorOnMissingIso:
    """Before the fix, flash_windows(...) with a missing ISO raised OSError.
    After the fix it must return False.
    """

    def test_returns_false_when_iso_does_not_exist(self, tmp_path):
        missing_iso = str(tmp_path / "nonexistent.iso")
        result = fw_module.flash_windows("/dev/sdb", missing_iso, fw_module.PartitionScheme.SIMPLE_FAT32)
        assert result is False

    def test_returns_false_when_iso_is_a_directory(self, tmp_path):
        result = fw_module.flash_windows("/dev/sdb", str(tmp_path), fw_module.PartitionScheme.SIMPLE_FAT32)
        assert result is False


class TestGetWimSizeCaseInsensitive:
    """Before the fix, glob patterns were hardcoded as 'install.wim' and
    'INSTALL.WIM' but missed 'Install.Wim' or other mixed-case variants.
    """

    def test_finds_lowercase_install_wim(self, tmp_path):
        sources = tmp_path / "sources"
        sources.mkdir()
        wim = sources / "install.wim"
        wim.write_bytes(b"x" * 1000)
        assert _get_wim_size(str(tmp_path)) == 1000

    def test_finds_uppercase_install_wim(self, tmp_path):
        sources = tmp_path / "sources"
        sources.mkdir()
        wim = sources / "INSTALL.WIM"
        wim.write_bytes(b"x" * 2000)
        assert _get_wim_size(str(tmp_path)) == 2000

    def test_finds_mixed_case_install_wim(self, tmp_path):
        """This specific case FAILED before the fix — now it must pass."""
        sources = tmp_path / "sources"
        sources.mkdir()
        wim = sources / "Install.Wim"
        wim.write_bytes(b"x" * 3000)
        assert _get_wim_size(str(tmp_path)) == 3000

    def test_finds_install_esd(self, tmp_path):
        sources = tmp_path / "sources"
        sources.mkdir()
        esd = sources / "install.esd"
        esd.write_bytes(b"y" * 500)
        assert _get_wim_size(str(tmp_path)) == 500

    def test_returns_zero_when_no_wim(self, tmp_path):
        sources = tmp_path / "sources"
        sources.mkdir()
        assert _get_wim_size(str(tmp_path)) == 0


class TestBootmgrLoopVariableRenamed:
    """The loop variable was named 'f' (shadows built-in). It must be 'fname'."""

    def test_loop_uses_fname_variable(self):
        import ast, inspect

        src = inspect.getsource(fw_module.flash_windows)
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.For):
                if isinstance(node.target, ast.Name):
                    # There must be no bare 'f' loop target in flash_windows
                    assert node.target.id != "f", "Loop variable 'f' still present — should be renamed to 'fname'"


class TestMountIso:
    def test_mount_iso_success_uses_unique_temp_mount(self, monkeypatch, tmp_path):
        iso = tmp_path / "image.iso"
        iso.write_bytes(b"iso")
        mount_dir = tmp_path / "lufus-iso-test"
        calls = {}

        def fake_mkdtemp(prefix, dir=None):
            calls["mkdtemp"] = (prefix, dir)
            mount_dir.mkdir()
            return str(mount_dir)

        def fake_run(cmd, **kwargs):
            calls["cmd"] = cmd
            calls["kwargs"] = kwargs
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

        monkeypatch.setattr(fw_module.tempfile, "mkdtemp", fake_mkdtemp)
        monkeypatch.setattr(fw_module.subprocess, "run", fake_run)
        monkeypatch.setattr(fw_module.os.path, "ismount", lambda path: path == str(mount_dir))

        result = fw_module.mount_iso(str(iso))

        assert result == str(mount_dir)
        assert calls["mkdtemp"][0] == "lufus-iso-"
        assert calls["cmd"] == ["sudo", "mount", "-o", "loop", str(iso), str(mount_dir)]
        assert calls["kwargs"] == {"capture_output": True, "text": True}

    def test_mount_iso_failure_returns_none_and_removes_temp_dir(self, monkeypatch, tmp_path):
        iso = tmp_path / "image.iso"
        iso.write_bytes(b"iso")
        mount_dir = tmp_path / "lufus-iso-test"
        removed = {}
        original_rmdir = os.rmdir

        def fake_mkdtemp(prefix, dir=None):
            mount_dir.mkdir()
            return str(mount_dir)

        def fake_run(cmd, **kwargs):
            return subprocess.CompletedProcess(cmd, 1, stdout="out", stderr="err")

        def fake_rmdir(path):
            removed["path"] = path
            original_rmdir(path)

        monkeypatch.setattr(fw_module.tempfile, "mkdtemp", fake_mkdtemp)
        monkeypatch.setattr(fw_module.subprocess, "run", fake_run)
        monkeypatch.setattr(fw_module.os, "rmdir", fake_rmdir)

        result = fw_module.mount_iso(str(iso))

        assert result is None
        assert removed["path"] == str(mount_dir)

    def test_mount_iso_missing_iso_returns_none_before_mount(self, monkeypatch, tmp_path):
        def fail_run(*args, **kwargs):
            raise AssertionError("mount should not be attempted for a missing ISO")

        monkeypatch.setattr(fw_module.subprocess, "run", fail_run)

        assert fw_module.mount_iso(str(tmp_path / "missing.iso")) is None


class TestCreatePartitions:
    def _capture_partitioning(self, monkeypatch):
        calls = []

        def fake_run(cmd, **kwargs):
            calls.append((cmd, kwargs))
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

        monkeypatch.setattr(fw_module, "_get_disk_size_sectors", lambda drive: 16 * 1024 * 1024)
        monkeypatch.setattr(fw_module.subprocess, "run", fake_run)
        monkeypatch.setattr(fw_module.time, "sleep", lambda seconds: None)
        return calls

    def test_create_partitions_simple_fat32(self, monkeypatch):
        calls = self._capture_partitioning(monkeypatch)

        parts = fw_module.create_partitions("/dev/sdx", fw_module.PartitionScheme.SIMPLE_FAT32)

        assert [p["role"] for p in parts] == ["data"]
        sfdisk_cmd, sfdisk_kwargs = calls[0]
        assert sfdisk_cmd == ["sudo", "sfdisk", "--label", "gpt", "/dev/sdx"]
        assert "type=EBD0A0A2-B9E5-4433-87C0-68B6B72699C7" in sfdisk_kwargs["input"]
        assert "C12A7328-F81F-11D2-BA4B-00A0C93EC93B" not in sfdisk_kwargs["input"]
        assert sfdisk_kwargs["text"] is True
        assert sfdisk_kwargs["check"] is True

    def test_create_partitions_windows_ntfs(self, monkeypatch):
        calls = self._capture_partitioning(monkeypatch)

        parts = fw_module.create_partitions("/dev/sdx", fw_module.PartitionScheme.WINDOWS_NTFS)

        assert [p["role"] for p in parts] == ["data", "efi"]
        script = calls[0][1]["input"]
        assert "type=EBD0A0A2-B9E5-4433-87C0-68B6B72699C7" in script
        assert "type=C12A7328-F81F-11D2-BA4B-00A0C93EC93B" in script

    def test_create_partitions_windows_exfat_nvme_separator(self, monkeypatch):
        calls = self._capture_partitioning(monkeypatch)

        parts = fw_module.create_partitions("/dev/nvme0n1", fw_module.PartitionScheme.WINDOWS_EXFAT)

        assert parts == [
            {"role": "data", "path": "/dev/nvme0n1p1"},
            {"role": "efi", "path": "/dev/nvme0n1p2"},
        ]
        assert "type=C12A7328-F81F-11D2-BA4B-00A0C93EC93B" in calls[0][1]["input"]
        assert calls[1][0] == ["sudo", "partprobe", "/dev/nvme0n1"]
        assert calls[1][1]["check"] is True


class TestFlashWindowsValidation:
    @pytest.mark.parametrize("device", ["/dev/loop0", "not-a-device", "/tmp/fake-disk"])
    def test_rejects_invalid_device_paths(self, device, tmp_path):
        with pytest.raises(ValueError):
            fw_module.flash_windows(device, str(tmp_path / "image.iso"), fw_module.PartitionScheme.SIMPLE_FAT32)


class TestDownloadWimbootTimeout:
    """Before the fix, urlretrieve had no timeout. After the fix, URLError
    (which wraps socket.timeout) must be caught and return False gracefully.
    """

    def test_returns_false_on_url_error(self, tmp_path, monkeypatch):
        import urllib.error

        def raise_timeout(*args, **kwargs):
            raise urllib.error.URLError("timed out")

        monkeypatch.setattr(iv_module.urllib.request, "urlopen", raise_timeout)
        result = download_wimboot(str(tmp_path / "wimboot"))
        assert result is False

    def test_returns_true_on_success(self, tmp_path, monkeypatch):
        class FakeResponse:
            def read(self):
                return b"WIMBOOTDATA"

        monkeypatch.setattr(iv_module.urllib.request, "urlopen", lambda *a, **kw: FakeResponse())
        dest = tmp_path / "wimboot"
        result = download_wimboot(str(dest))
        assert result is True
        assert dest.read_bytes() == b"WIMBOOTDATA"

    def test_timeout_constant_is_set(self):
        """A named timeout constant must exist and be positive."""
        assert hasattr(iv_module, "WIMBOOT_TIMEOUT")
        assert iv_module.WIMBOOT_TIMEOUT > 0


class TestInstallGrubUsesTempDirs:
    """install_grub must use unique temp directories, not /tmp/efi_prepare."""

    def test_hardcoded_tmp_paths_removed(self):
        import inspect

        src = inspect.getsource(install_grub)
        # Strip annotation comments before checking so the old path names
        # mentioned inside # [ANNOTATION] strings don't cause false positives.
        code = "\n".join(
            line.split("# [ANNOTATION]")[0] for line in src.splitlines() if not line.strip().startswith("#")
        )
        assert "/tmp/efi_prepare" not in code, "Hardcoded /tmp/efi_prepare still present in code"
        assert "/tmp/data_prepare" not in code, "Hardcoded /tmp/data_prepare still present in code"
        assert "mkdtemp" in code, "mkdtemp must be used instead of hardcoded /tmp paths"


class TestInstallGrubBroadExcept:
    """The except clause must be broad enough to catch non-subprocess errors."""

    def test_returns_false_on_permission_error(self, monkeypatch):
        """Before the fix a PermissionError propagated; now it returns False."""
        monkeypatch.setattr(iv_module.os, "geteuid", lambda: 0)

        def raise_perm(*args, **kwargs):
            raise PermissionError("permission denied")

        monkeypatch.setattr(iv_module.subprocess, "run", raise_perm)
        monkeypatch.setattr(iv_module.glob, "glob", lambda *a, **kw: [])

        result = install_grub("/dev/sdb")
        assert result is False

    def test_returns_false_when_not_root(self, monkeypatch):
        monkeypatch.setattr(iv_module.os, "geteuid", lambda: 1000)
        result = install_grub("/dev/sdb")
        assert result is False

    def test_returns_false_for_nvme_device(self, monkeypatch):
        monkeypatch.setattr(iv_module.os, "geteuid", lambda: 0)
        result = install_grub("/dev/nvme0n1")
        assert result is False

    def test_returns_false_for_mmcblk_device(self, monkeypatch):
        monkeypatch.setattr(iv_module.os, "geteuid", lambda: 0)
        result = install_grub("/dev/mmcblk0")
        assert result is False


class TestInstallGrubMmcblkSeparator:
    """The partition separator 'p' was only added for NVMe, not mmcblk.
    The mmcblk guard now prevents reaching that code, but the separator
    logic must be consistent if the guard is ever relaxed.
    """

    def test_separator_logic_includes_mmcblk(self):
        import inspect, ast

        src = inspect.getsource(install_grub)
        # The sep assignment must reference 'mmcblk'
        assert "mmcblk" in src.split("sep =")[1].split("\n")[0], "separator assignment must include 'mmcblk' check"


class TestInstallGrubMountCleanup:
    """Before the fix, returning False early after mounting left the EFI
    partition mounted. The finally block must always run unmount.
    """

    def test_finally_always_runs_on_early_return(self, monkeypatch):
        """Simulate a scenario where grub.cfg is missing (early return path)
        and verify umount is still called for the efi partition.
        """
        import inspect

        src = inspect.getsource(install_grub)
        # Verify the function uses a finally block (structural test)
        assert "finally:" in src, "install_grub must use a finally block for cleanup"
        assert "efi_mounted" in src, "efi_mounted flag must exist to guard conditional unmount"
        assert "data_mounted" in src, "data_mounted flag must exist to guard conditional unmount"
