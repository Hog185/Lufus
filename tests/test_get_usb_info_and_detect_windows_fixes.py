from __future__ import annotations
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import lufus.drives.get_usb_info as gui_module
from lufus.drives.get_usb_info import get_usb_info
import lufus.writing.windows.detect as dw_module
from lufus.writing.windows.detect import _label_is_windows, _read_iso_label, is_windows_iso


def _fake_partitions(mount, device):
    return lambda all=False: [SimpleNamespace(mountpoint=mount, device=device)]


def _fake_check_output(size="1000000000", label="MY_USB"):
    def impl(cmd, **kwargs):
        if "SIZE" in cmd:
            return size + "\n"
        return label + "\n"

    return impl


class Testget_usb_infoNormalisedMountPath:
    """mount_path in the returned dict must be the normalised path, not the
    raw input.  Before the fix, passing '/media/u/USB/' returned that exact
    string; comparisons with os.path.normpath() elsewhere silently failed.
    """

    def test_trailing_slash_is_stripped(self, monkeypatch):
        monkeypatch.setattr(gui_module.psutil, "disk_partitions", _fake_partitions("/media/u/USB/", "/dev/sdb1"))
        monkeypatch.setattr(gui_module.subprocess, "check_output", _fake_check_output())
        result = get_usb_info("/media/u/USB/")
        assert result["mount_path"] == "/media/u/USB"

    def test_normalised_path_matches_normpath(self, monkeypatch, tmp_path):
        mount = str(tmp_path)
        monkeypatch.setattr(gui_module.psutil, "disk_partitions", _fake_partitions(mount, "/dev/sdc1"))
        monkeypatch.setattr(gui_module.subprocess, "check_output", _fake_check_output())
        result = get_usb_info(mount)
        import os

        assert result["mount_path"] == os.path.normpath(mount)


class Testget_usb_infoAllTrue:
    """disk_partitions must be called with all=True so bind-mounted volumes
    are not missed, consistent with find_usb and check_file_sig.
    """

    def test_disk_partitions_called_with_all_true(self, monkeypatch):
        calls = {}

        def fake_dp(all=False):
            calls["all"] = all
            return []

        monkeypatch.setattr(gui_module.psutil, "disk_partitions", fake_dp)
        get_usb_info("/any/path")
        assert calls.get("all") is True


class Testget_usb_infoTimeoutExpired:
    """TimeoutExpired was previously swallowed by the broad Exception handler
    with a generic message.  It must now be caught explicitly.
    """

    def test_returns_empty_dict_on_timeout(self, monkeypatch):
        monkeypatch.setattr(gui_module.psutil, "disk_partitions", _fake_partitions("/media/u/USB", "/dev/sdb1"))

        def raise_timeout(*args, **kwargs):
            raise subprocess.TimeoutExpired(cmd="lsblk", timeout=5)

        monkeypatch.setattr(gui_module.subprocess, "check_output", raise_timeout)
        result = get_usb_info("/media/u/USB")
        assert result is None

    def test_timeout_handler_is_explicit(self):
        import inspect

        src = inspect.getsource(get_usb_info)
        assert "TimeoutExpired" in src


class Testget_usb_infoForElse:
    """When no partition matches the mount path, get_usb_info must return {}."""

    def test_returns_empty_when_no_match(self, monkeypatch):
        monkeypatch.setattr(gui_module.psutil, "disk_partitions", lambda *args, **kwargs: [])
        result = get_usb_info("/no/match")
        assert result is None


class TestLabelIsWindowsDeadBranch:
    """'or label.startswith("WINDOWS")' was dead code — every "WINDOWS…"
    string already starts with "WIN".  The redundant check must be gone.
    """

    def test_windows_prefix_still_detected(self):
        assert _label_is_windows("WINDOWS10") is True
        assert _label_is_windows("WIN10") is True
        assert _label_is_windows("windows_server") is True

    def test_dead_branch_removed_from_source(self):
        import inspect

        code = "\n".join(line.split("# [ANNOTATION]")[0] for line in inspect.getsource(_label_is_windows).splitlines())
        assert 'startswith("WINDOWS")' not in code
        assert "startswith('WINDOWS')" not in code

    def test_non_windows_returns_false(self):
        assert _label_is_windows("UBUNTU") is False
        assert _label_is_windows("") is False

    def test_esd_iso_detected(self):
        assert _label_is_windows("ESD-ISO") is True


class TestReadIsoLabelOsError:
    """_read_iso_label previously used bare 'except Exception' which could
    mask programming errors.  It must now catch only OSError.
    """

    def test_returns_empty_string_on_missing_file(self, tmp_path):
        result = _read_iso_label(str(tmp_path / "missing.iso"))
        assert result == ""

    def test_uses_oserror_not_bare_exception(self):
        import inspect

        code = "\n".join(line.split("# [ANNOTATION]")[0] for line in inspect.getsource(_read_iso_label).splitlines())
        assert "except Exception" not in code
        assert "except OSError" in code

    def test_reads_correct_label_from_valid_iso(self, tmp_path):
        iso = tmp_path / "test.iso"
        payload = bytearray(32808 + 32)
        label_bytes = b"MYISO                           "[:32]
        payload[32808:32840] = label_bytes
        iso.write_bytes(bytes(payload))
        result = _read_iso_label(str(iso))
        assert result == "MYISO"
