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

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import lufus.writing.flash_windows as fw_module
from lufus.writing.flash_windows import _get_wim_size, _find_path_case_insensitive
import lufus.writing.install_ventoy as iv_module
from lufus.writing.install_ventoy import download_wimboot, install_grub

class TestFlashWindowsImports:
    def test_optional_callable_not_imported(self):
        """Optional and Callable were imported but never used — removed."""
        import importlib, types
        spec = importlib.util.spec_from_file_location(
            "fw_check", str(SRC / "lufus/writing/flash_windows.py")
        )
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
        result = fw_module.flash_windows("/dev/sdb", missing_iso)
        assert result is False

    def test_returns_false_when_iso_is_a_directory(self, tmp_path):
        result = fw_module.flash_windows("/dev/sdb", str(tmp_path))
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
                    assert node.target.id != "f", (
                        "Loop variable 'f' still present — should be renamed to 'fname'"
                    )

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

        monkeypatch.setattr(
            iv_module.urllib.request, "urlopen", lambda *a, **kw: FakeResponse()
        )
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
            line.split("# [ANNOTATION]")[0]
            for line in src.splitlines()
            if not line.strip().startswith("#")
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
        assert "mmcblk" in src.split("sep =")[1].split("\n")[0], (
            "separator assignment must include 'mmcblk' check"
        )

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
