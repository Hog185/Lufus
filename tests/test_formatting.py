from __future__ import annotations
import sys
from pathlib import Path
import pytest
from subprocess import CalledProcessError

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from lufus.drives import formatting
from lufus.drives import states as st


def _setup_common_monkeypatch(monkeypatch) -> None:
    monkeypatch.setattr(formatting.fu, "find_usb", lambda: {"/media/testuser/USB": "USB"})
    monkeypatch.setattr(formatting.fu, "find_DN", lambda: "/dev/sdb1")
    monkeypatch.setattr(formatting.states, "DN", "/dev/sdb1")


# ---------------------------------------------------------------------------
# _get_raw_device
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("partition", "expected_raw"),
    [
        ("/dev/sdb1", "/dev/sdb"),
        ("/dev/sda10", "/dev/sda"),
        ("/dev/nvme0n1p1", "/dev/nvme0n1"),
        ("/dev/nvme1n2p3", "/dev/nvme1n2"),
        ("/dev/mmcblk0p1", "/dev/mmcblk0"),
        ("/dev/mmcblk1p12", "/dev/mmcblk1"),
        # Whole-disk (no partition suffix) → unchanged
        ("/dev/sdb", "/dev/sdb"),
        ("/dev/nvme0n1", "/dev/nvme0n1"),
    ],
)
def test_get_raw_device(partition: str, expected_raw: str) -> None:
    assert formatting._get_raw_device(partition) == expected_raw


# ---------------------------------------------------------------------------
# dskformat
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("fs_type", "expected_tool"),
    [
        (0, "mkfs.ntfs"),
        (1, "mkfs.vfat"),
        (2, "mkfs.exfat"),
        (3, "mkfs.ext4"),
    ],
)
def test_dskformat_runs_expected_mkfs_command(monkeypatch, fs_type: int, expected_tool: str) -> None:
    _setup_common_monkeypatch(monkeypatch)
    monkeypatch.setattr(formatting.states, "currentFS", fs_type)
    monkeypatch.setattr(formatting.states, "cluster_size", 0)
    monkeypatch.setattr(formatting.states, "partition_scheme", 0)

    calls = []

    def fake_run(cmd, check=True, **kwargs):
        calls.append(cmd)

    monkeypatch.setattr(formatting.subprocess, "run", fake_run)

    formatting.dskformat()

    # Find the mkfs call (partition scheme parted calls come first)
    mkfs_calls = [c for c in calls if c and c[0].startswith("mkfs")]
    assert len(mkfs_calls) == 1, f"Expected 1 mkfs call, got: {calls}"
    assert mkfs_calls[0][0] == expected_tool


def test_dskformat_calls_unexpected_for_unknown_fs(monkeypatch) -> None:
    _setup_common_monkeypatch(monkeypatch)
    monkeypatch.setattr(formatting.states, "currentFS", 99)
    monkeypatch.setattr(formatting.states, "cluster_size", 0)
    monkeypatch.setattr(formatting.states, "partition_scheme", 0)

    called = {"unexpected": False}

    def fake_unexpected():
        called["unexpected"] = True

    monkeypatch.setattr(formatting, "unexpected", fake_unexpected)
    monkeypatch.setattr(formatting.subprocess, "run", lambda *args, **kwargs: None)

    formatting.dskformat()

    assert called["unexpected"] is True


# ---------------------------------------------------------------------------
# cluster()
# ---------------------------------------------------------------------------

def test_cluster_returns_tuple_even_without_usb(monkeypatch) -> None:
    """cluster() must never crash — it must always return a valid 3-tuple."""
    monkeypatch.setattr(formatting.fu, "find_usb", lambda: {})
    monkeypatch.setattr(formatting.fu, "find_DN", lambda: None)
    monkeypatch.setattr(formatting.states, "DN", "")

    result = formatting.cluster()
    assert isinstance(result, tuple)
    assert len(result) == 3
    cluster1, cluster2, sector = result
    assert cluster1 > 0
    assert cluster2 > 0
    assert sector == cluster1 // cluster2


def test_cluster_respects_cluster_size_state(monkeypatch) -> None:
    monkeypatch.setattr(formatting.fu, "find_usb", lambda: {"/media/testuser/USB": "USB"})
    monkeypatch.setattr(formatting.fu, "find_DN", lambda: "/dev/sdb1")
    monkeypatch.setattr(formatting.states, "DN", "/dev/sdb1")

    monkeypatch.setattr(formatting.states, "cluster_size", 0)
    c1, _, _ = formatting.cluster()
    assert c1 == 4096

    monkeypatch.setattr(formatting.states, "cluster_size", 1)
    c1, _, _ = formatting.cluster()
    assert c1 == 8192


# ---------------------------------------------------------------------------
# _apply_partition_scheme
# ---------------------------------------------------------------------------

def test_apply_partition_scheme_gpt(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(formatting.subprocess, "run", lambda cmd, check=True, **kw: calls.append(cmd))
    monkeypatch.setattr(formatting.states, "partition_scheme", 0)

    formatting._apply_partition_scheme("/dev/sdb1")

    assert any("gpt" in c for c in calls)


def test_apply_partition_scheme_mbr(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(formatting.subprocess, "run", lambda cmd, check=True, **kw: calls.append(cmd))
    monkeypatch.setattr(formatting.states, "partition_scheme", 1)

    formatting._apply_partition_scheme("/dev/sdb1")

    assert any("msdos" in c for c in calls)


def test_apply_partition_scheme_uses_raw_device_for_nvme(monkeypatch) -> None:
    """_apply_partition_scheme must use /dev/nvme0n1, not /dev/nvme0n."""
    calls = []
    monkeypatch.setattr(formatting.subprocess, "run", lambda cmd, check=True, **kw: calls.append(cmd))
    monkeypatch.setattr(formatting.states, "partition_scheme", 0)

    formatting._apply_partition_scheme("/dev/nvme0n1p1")

    raw_devices_used = [c[2] for c in calls if len(c) > 2]
    assert all(d == "/dev/nvme0n1" for d in raw_devices_used), (
        f"Expected /dev/nvme0n1 but got: {raw_devices_used}"
    )


# ---------------------------------------------------------------------------
# checkdevicebadblock
# ---------------------------------------------------------------------------

def test_checkdevicebadblock_returns_false_when_no_drive(monkeypatch) -> None:
    monkeypatch.setattr(formatting.fu, "find_usb", lambda: {})
    monkeypatch.setattr(formatting.fu, "find_DN", lambda: None)
    monkeypatch.setattr(formatting.states, "DN", "")

    result = formatting.checkdevicebadblock()
    assert result is False


def test_checkdevicebadblock_returns_true_on_clean_run(monkeypatch) -> None:
    monkeypatch.setattr(formatting.states, "DN", "/dev/sdb1")
    monkeypatch.setattr(formatting.fu, "find_usb", lambda: {"/media/testuser/USB": "USB"})
    monkeypatch.setattr(formatting.fu, "find_DN", lambda: "/dev/sdb1")
    monkeypatch.setattr(formatting.states, "check_bad", 0)

    class FakeResult:
        returncode = 0
        stdout = ""
        stderr = ""

    def fake_run(cmd, *args, **kwargs):
        return FakeResult()

    monkeypatch.setattr(formatting.subprocess, "run", fake_run)
    assert formatting.checkdevicebadblock() is True


def test_checkdevicebadblock_returns_false_on_nonzero_exit(monkeypatch) -> None:
    monkeypatch.setattr(formatting.states, "DN", "/dev/sdb1")
    monkeypatch.setattr(formatting.fu, "find_usb", lambda: {"/media/testuser/USB": "USB"})
    monkeypatch.setattr(formatting.fu, "find_DN", lambda: "/dev/sdb1")
    monkeypatch.setattr(formatting.states, "check_bad", 0)

    class FakeResult:
        returncode = 1
        stdout = ""
        stderr = "some error"

    def fake_run(cmd, *args, **kwargs):
        return FakeResult()

    monkeypatch.setattr(formatting.subprocess, "run", fake_run)
    assert formatting.checkdevicebadblock() is False


def test_checkdevicebadblock_returns_false_when_badblocks_not_found(monkeypatch) -> None:
    monkeypatch.setattr(formatting.states, "DN", "/dev/sdb1")
    monkeypatch.setattr(formatting.fu, "find_usb", lambda: {"/media/testuser/USB": "USB"})
    monkeypatch.setattr(formatting.fu, "find_DN", lambda: "/dev/sdb1")
    monkeypatch.setattr(formatting.states, "check_bad", 0)

    call_count = [0]

    def fake_run(cmd, *args, **kwargs):
        call_count[0] += 1
        # First call is blockdev probe — let it succeed; second is badblocks — raise
        if call_count[0] == 1:
            class R:
                returncode = 0
                stdout = "512"
                stderr = ""
            return R()
        raise FileNotFoundError("badblocks not found")

    monkeypatch.setattr(formatting.subprocess, "run", fake_run)
    assert formatting.checkdevicebadblock() is False


# ---------------------------------------------------------------------------
# volumecustomlabel
# ---------------------------------------------------------------------------

def test_volumecustomlabel_no_drive_does_not_crash(monkeypatch) -> None:
    """volumecustomlabel() should gracefully handle missing drive node."""
    monkeypatch.setattr(formatting.fu, "find_usb", lambda: {})
    monkeypatch.setattr(formatting.fu, "find_DN", lambda: None)
    monkeypatch.setattr(formatting.states, "DN", "")
    monkeypatch.setattr(formatting.states, "currentFS", 0)
    monkeypatch.setattr(formatting.states, "new_label", "TESTLABEL")

    # Should not raise
    formatting.volumecustomlabel()


@pytest.mark.parametrize(
    ("current_fs", "expected_tool"),
    [
        (0, "ntfslabel"),
        (1, "fatlabel"),
        (2, "fatlabel"),
        (3, "e2label"),
    ],
)
def test_volumecustomlabel_invokes_correct_label_tool(monkeypatch, current_fs, expected_tool) -> None:
    device = "/dev/sdx1"
    label = "TESTLABEL"
    monkeypatch.setattr(formatting.fu, "find_usb", lambda: {device: {}})
    monkeypatch.setattr(formatting.fu, "find_DN", lambda: device)
    monkeypatch.setattr(formatting.states, "DN", device)
    monkeypatch.setattr(formatting.states, "currentFS", current_fs)
    monkeypatch.setattr(formatting.states, "new_label", label)

    recorded = {}

    def fake_run(cmd, *args, **kwargs):
        recorded["cmd"] = cmd

    monkeypatch.setattr(formatting.subprocess, "run", fake_run)
    formatting.volumecustomlabel()

    assert "cmd" in recorded
    cmd = recorded["cmd"]
    assert any(expected_tool in str(part) for part in cmd)
    assert any(device in str(part) for part in cmd)
    assert any(label in str(part) for part in cmd)


def test_volumecustomlabel_handles_pkexec_not_found(monkeypatch) -> None:
    device = "/dev/sdx1"
    monkeypatch.setattr(formatting.fu, "find_usb", lambda: {device: {}})
    monkeypatch.setattr(formatting.fu, "find_DN", lambda: device)
    monkeypatch.setattr(formatting.states, "DN", device)
    monkeypatch.setattr(formatting.states, "currentFS", 0)
    monkeypatch.setattr(formatting.states, "new_label", "TESTLABEL")
    monkeypatch.setattr(formatting.subprocess, "run", lambda *a, **kw: (_ for _ in ()).throw(FileNotFoundError()))

    called = {"pkexecNotFound": False}
    monkeypatch.setattr(formatting, "pkexecNotFound", lambda: called.update({"pkexecNotFound": True}))

    formatting.volumecustomlabel()
    assert called["pkexecNotFound"] is True


def test_volumecustomlabel_handles_called_process_error(monkeypatch) -> None:
    device = "/dev/sdx1"
    monkeypatch.setattr(formatting.fu, "find_usb", lambda: {device: {}})
    monkeypatch.setattr(formatting.fu, "find_DN", lambda: device)
    monkeypatch.setattr(formatting.states, "DN", device)
    monkeypatch.setattr(formatting.states, "currentFS", 0)
    monkeypatch.setattr(formatting.states, "new_label", "TESTLABEL")
    monkeypatch.setattr(formatting.subprocess, "run",
                        lambda cmd, *a, **kw: (_ for _ in ()).throw(CalledProcessError(1, cmd)))

    called = {"FormatFail": False}
    monkeypatch.setattr(formatting, "FormatFail", lambda: called.update({"FormatFail": True}))

    formatting.volumecustomlabel()
    assert called["FormatFail"] is True


# ---------------------------------------------------------------------------
# _get_mount_and_drive
# ---------------------------------------------------------------------------

def test_get_mount_and_drive_prefers_states_dn(monkeypatch) -> None:
    find_dn_called = {"called": False}

    def fake_find_DN():
        find_dn_called["called"] = True
        return "/dev/should-not-be-used"

    monkeypatch.setattr(formatting.fu, "find_usb", lambda: {"/media/testuser/USB": "USB"})
    monkeypatch.setattr(formatting.fu, "find_DN", fake_find_DN)
    monkeypatch.setattr(formatting.states, "DN", "/dev/sdz1")

    mount, drive, _ = formatting._get_mount_and_drive()
    assert drive == "/dev/sdz1"
    assert find_dn_called["called"] is False


def test_get_mount_and_drive_falls_back_to_find_dn(monkeypatch) -> None:
    monkeypatch.setattr(formatting.fu, "find_usb", lambda: {"/media/testuser/USB": "USB"})
    monkeypatch.setattr(formatting.fu, "find_DN", lambda: "/dev/fallback")
    monkeypatch.setattr(formatting.states, "DN", "")

    _, drive, _ = formatting._get_mount_and_drive()
    assert drive == "/dev/fallback"


# ---------------------------------------------------------------------------
# unmount / remount
# ---------------------------------------------------------------------------

def test_unmount_skips_subprocess_when_no_drive(monkeypatch, capsys) -> None:
    monkeypatch.setattr(formatting, "_get_mount_and_drive", lambda: (None, None, {}))

    def bad_run(*a, **kw):
        raise AssertionError("subprocess.run must not be called")

    monkeypatch.setattr(formatting.subprocess, "run", bad_run)
    formatting.unmount()
    out = capsys.readouterr()
    assert out.out or out.err


def test_remount_skips_subprocess_when_no_drive(monkeypatch, capsys) -> None:
    monkeypatch.setattr(formatting, "_get_mount_and_drive", lambda: (None, None, {}))

    def bad_run(*a, **kw):
        raise AssertionError("subprocess.run must not be called")

    monkeypatch.setattr(formatting.subprocess, "run", bad_run)
    formatting.remount()
    out = capsys.readouterr()
    assert out.out or out.err


def test_unmount_issues_umount_command(monkeypatch) -> None:
    mount = "/media/testuser/USB"
    drive = "/dev/sdb1"
    monkeypatch.setattr(formatting, "_get_mount_and_drive", lambda: (mount, drive, {}))
    calls = []
    monkeypatch.setattr(formatting.subprocess, "run", lambda cmd, *a, **kw: calls.append(cmd))
    formatting.unmount()
    assert calls and calls[0][0] == "umount" and drive in calls[0]


def test_remount_issues_mount_command(monkeypatch) -> None:
    mount = "/media/testuser/USB"
    drive = "/dev/sdb1"
    monkeypatch.setattr(formatting, "_get_mount_and_drive", lambda: (mount, drive, {}))
    calls = []
    monkeypatch.setattr(formatting.subprocess, "run", lambda cmd, *a, **kw: calls.append(cmd))
    formatting.remount()
    assert calls and calls[0][0] == "mount" and drive in calls[0] and mount in calls[0]



@pytest.mark.parametrize(
    ("fs_type", "expected_tool"),
    [
        (0, "mkfs.ntfs"),
        (1, "mkfs.vfat"),
        (2, "mkfs.exfat"),
        (3, "mkfs.ext4"),
    ],
)
def test_dskformat_runs_expected_mkfs_command(monkeypatch, fs_type: int, expected_tool: str) -> None:
    _setup_common_monkeypatch(monkeypatch)
    monkeypatch.setattr(formatting.states, "currentFS", fs_type)
    monkeypatch.setattr(formatting.states, "cluster_size", 0)
    monkeypatch.setattr(formatting.states, "partition_scheme", 0)

    calls = []

    def fake_run(cmd, check=True, **kwargs):
        calls.append(cmd)

    monkeypatch.setattr(formatting.subprocess, "run", fake_run)

    formatting.dskformat()

    # Find the mkfs call (partition scheme parted calls come first)
    mkfs_calls = [c for c in calls if c and Path(c[0]).name.startswith("mkfs")]
    assert len(mkfs_calls) == 1, f"Expected 1 mkfs call, got: {calls}"
    assert expected_tool in mkfs_calls[0][0]


def test_dskformat_calls_unexpected_for_unknown_fs(monkeypatch) -> None:
    _setup_common_monkeypatch(monkeypatch)
    monkeypatch.setattr(formatting.states, "currentFS", 99)
    monkeypatch.setattr(formatting.states, "cluster_size", 0)
    monkeypatch.setattr(formatting.states, "partition_scheme", 0)

    called = {"unexpected": False}

    def fake_unexpected():
        called["unexpected"] = True

    monkeypatch.setattr("lufus.drives.formatting.unexpected", fake_unexpected)
    monkeypatch.setattr(formatting.subprocess, "run", lambda *args, **kwargs: None)

    formatting.dskformat()

    assert called["unexpected"] is True


def test_cluster_returns_tuple_even_without_usb(monkeypatch) -> None:
    """cluster() must never crash — it must always return a valid 3-tuple."""
    monkeypatch.setattr(formatting.fu, "find_usb", lambda: {})
    monkeypatch.setattr(formatting.fu, "find_DN", lambda: None)
    monkeypatch.setattr(formatting.states, "DN", "")

    result = formatting.cluster()
    assert isinstance(result, tuple)
    assert len(result) == 3
    cluster1, cluster2, sector = result
    assert cluster1 > 0
    assert cluster2 > 0
    assert sector == cluster1 // cluster2


def test_cluster_respects_cluster_size_state(monkeypatch) -> None:
    monkeypatch.setattr(formatting.fu, "find_usb", lambda: {"/media/testuser/USB": "USB"})
    monkeypatch.setattr(formatting.fu, "find_DN", lambda: "/dev/sdb1")
    monkeypatch.setattr(formatting.states, "DN", "/dev/sdb1")

    monkeypatch.setattr(formatting.states, "cluster_size", 0)
    c1, _, _ = formatting.cluster()
    assert c1 == 4096

    monkeypatch.setattr(formatting.states, "cluster_size", 1)
    c1, _, _ = formatting.cluster()
    assert c1 == 8192


def test_apply_partition_scheme_gpt(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(formatting.subprocess, "run", lambda cmd, check=True, **kw: calls.append(cmd))
    monkeypatch.setattr(formatting.states, "partition_scheme", 0)

    formatting._apply_partition_scheme("/dev/sdb1")

    assert any("gpt" in c for c in calls)


def test_apply_partition_scheme_mbr(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(formatting.subprocess, "run", lambda cmd, check=True, **kw: calls.append(cmd))
    monkeypatch.setattr(formatting.states, "partition_scheme", 1)

    formatting._apply_partition_scheme("/dev/sdb1")

    assert any("msdos" in c for c in calls)


def test_checkdevicebadblock_returns_false_when_no_drive(monkeypatch) -> None:
    monkeypatch.setattr(formatting.fu, "find_usb", lambda: {})
    monkeypatch.setattr(formatting.fu, "find_DN", lambda: None)
    monkeypatch.setattr(formatting.states, "DN", "")

    result = formatting.checkdevicebadblock()
    assert result is False


def test_volumecustomlabel_no_drive_does_not_crash(monkeypatch) -> None:
    """volumecustomlabel() should gracefully handle missing drive node."""
    monkeypatch.setattr(formatting.fu, "find_usb", lambda: {})
    monkeypatch.setattr(formatting.fu, "find_DN", lambda: None)
    monkeypatch.setattr(formatting.states, "DN", "")
    monkeypatch.setattr(formatting.states, "currentFS", 0)
    monkeypatch.setattr(formatting.states, "new_label", "TESTLABEL")

    # Should not raise
    formatting.volumecustomlabel()
