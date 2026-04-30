from __future__ import annotations
import sys
from pathlib import Path
from unittest.mock import MagicMock, call, patch

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from lufus import state


def _make_monitor():
    """Return a UsbMonitor-like object without importing PyQt6/pyudev."""
    import types

    mon = types.SimpleNamespace(
        devices={},
        device_added=MagicMock(),
        device_removed=MagicMock(),
        device_list_updated=MagicMock(),
    )

    def _handle_event(device):
        if device.get("DEVTYPE") != "disk":
            return
        if device.get("ID_BUS") != "usb":
            return
        node = device.device_node
        if not node:
            print(f"UsbMonitor: ignoring event with no device_node (action={device.action})")
            return
        action = device.action
        label = device.get("ID_FS_LABEL") or device.get("ID_MODEL") or node
        changed = False
        if action == "add":
            mon.devices[node] = label
            mon.device_added.emit(node)
            changed = True
        elif action == "remove":
            if node in mon.devices:
                mon.devices.pop(node)
                mon.device_removed.emit(node)
                changed = True
        if changed:
            mon.device_list_updated.emit(mon.devices)

    mon._handle_event = _handle_event
    return mon


def _device(devtype="disk", bus="usb", node="/dev/sdb", action="add", label="MY_USB", model="MyDrive"):
    d = MagicMock()
    d.device_node = node
    d.action = action

    def _get(key):
        return {"DEVTYPE": devtype, "ID_BUS": bus, "ID_FS_LABEL": label, "ID_MODEL": model, "ID_VENDOR": "Acme"}.get(
            key
        )

    d.get = _get
    return d


class TestStatesTypeAnnotations:
    """All state variables must carry type annotations so static analysis
    catches misassignments (e.g. state.device_node = None instead of "").
    """

    def test_all_int_fields_annotated(self):
        import inspect

        src = inspect.getsource(type(state))
        for name in (
            "filesystem_index",
            "image_option",
            "partition_scheme",
            "target_system",
            "cluster_size",
            "quick_format",
            "create_extended",
            "check_bad",
            "flash_mode",
        ):
            assert f"{name}: int" in src, f"{name} missing int annotation"

    def test_all_str_fields_annotated(self):
        import inspect

        src = inspect.getsource(type(state))
        for name in ("new_label", "iso_path", "device_node", "language", "expected_hash"):
            assert f"{name}: str" in src, f"{name} missing str annotation"

    def test_bool_fields_annotated(self):
        import inspect

        src = inspect.getsource(type(state))
        assert "verify_hash: bool" in src

    def test_default_values_correct_types(self):
        assert isinstance(state.filesystem_index, int)
        assert isinstance(state.device_node, str)
        assert isinstance(state.verify_hash, bool)
        assert isinstance(state.new_label, str)


class TestStatesNewLabelLength:
    """Default new_label was 'Volume Label' (12 chars), exceeding the FAT32
    label limit of 11 characters.  The default must be <=11 chars.
    """

    def test_default_new_label_fits_fat32(self):
        assert len(state.new_label) <= 11, (
            f"new_label default {state.new_label!r} is {len(state.new_label)} chars; FAT32 limit is 11"
        )

    def test_default_new_label_is_not_old_value(self):
        assert state.new_label != "Volume Label", (
            "Default new_label is still 'Volume Label' (12 chars, exceeds FAT32 limit)"
        )


class TestHandleEventNoneNode:
    """device_node can be None for synthetic udev events.  Before the fix,
    None was silently used as a dict key, corrupting self.devices.
    """

    def test_none_node_on_add_does_not_corrupt_devices(self):
        mon = _make_monitor()
        d = _device(node=None, action="add")
        mon._handle_event(d)
        assert None not in mon.devices

    def test_none_node_on_remove_does_not_crash(self):
        mon = _make_monitor()
        d = _device(node=None, action="remove")
        mon._handle_event(d)
        assert mon.devices == {}

    def test_none_node_does_not_emit_signals(self):
        mon = _make_monitor()
        d = _device(node=None, action="add")
        mon._handle_event(d)
        mon.device_added.emit.assert_not_called()
        mon.device_list_updated.emit.assert_not_called()


class TestHandleEventChangedFlag:
    """device_list_updated must only fire when self.devices actually changed.
    Before the fix it fired on every event including unhandled actions like
    'change' or 'bind', causing spurious GUI redraws.
    """

    def test_add_emits_device_list_updated(self):
        mon = _make_monitor()
        mon._handle_event(_device(action="add"))
        mon.device_list_updated.emit.assert_called_once()

    def test_remove_known_emits_device_list_updated(self):
        mon = _make_monitor()
        mon.devices["/dev/sdb"] = "MY_USB"
        mon._handle_event(_device(action="remove"))
        mon.device_list_updated.emit.assert_called_once()

    def test_remove_unknown_does_not_emit_device_list_updated(self):
        mon = _make_monitor()
        mon._handle_event(_device(action="remove", node="/dev/sdb"))
        mon.device_list_updated.emit.assert_not_called()

    def test_unrecognised_action_does_not_emit_device_list_updated(self):
        mon = _make_monitor()
        mon._handle_event(_device(action="change"))
        mon.device_list_updated.emit.assert_not_called()

    def test_non_usb_device_does_not_emit(self):
        mon = _make_monitor()
        mon._handle_event(_device(bus="pci"))
        mon.device_list_updated.emit.assert_not_called()

    def test_non_disk_devtype_does_not_emit(self):
        mon = _make_monitor()
        mon._handle_event(_device(devtype="partition"))
        mon.device_list_updated.emit.assert_not_called()

    def test_add_updates_devices_dict(self):
        mon = _make_monitor()
        mon._handle_event(_device(action="add", node="/dev/sdc", label="DRIVE"))
        assert mon.devices.get("/dev/sdc") == "DRIVE"

    def test_remove_removes_from_devices_dict(self):
        mon = _make_monitor()
        mon.devices["/dev/sdc"] = "DRIVE"
        mon._handle_event(_device(action="remove", node="/dev/sdc"))
        assert "/dev/sdc" not in mon.devices
