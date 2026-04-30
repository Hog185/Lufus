from PyQt6.QtCore import QObject, pyqtSignal, QSocketNotifier
import pyudev
from lufus.lufus_logging import get_logger

log = get_logger(__name__)


class UsbMonitor(QObject):
    device_added = pyqtSignal(str)
    device_removed = pyqtSignal(str)
    device_list_updated = pyqtSignal(dict)

    def __init__(self):
        super().__init__()
        self.context = pyudev.Context()
        self.monitor = pyudev.Monitor.from_netlink(self.context)
        self.monitor.filter_by(subsystem="block")
        self.monitor.start()
        self.devices = {}

        self._notifier = QSocketNotifier(
            self.monitor.fileno(),
            QSocketNotifier.Type.Read,
            self,
        )
        self._notifier.activated.connect(self._on_socket_ready)

        log.info("UsbMonitor: initializing, scanning existing block devices...")
        self._load_existing()
        log.info("UsbMonitor: QSocketNotifier active, watching for hotplug events")

    def _load_existing(self):
        found = 0
        for device in self.context.list_devices(subsystem="block", DEVTYPE="disk"):
            if device.get("ID_BUS") == "usb":
                node = device.device_node
                if not node:
                    continue
                label = device.get("ID_FS_LABEL") or device.get("ID_MODEL") or node
                vendor = device.get("ID_VENDOR") or "unknown vendor"
                model = device.get("ID_MODEL") or "unknown model"
                serial = device.get("ID_SERIAL_SHORT") or "no serial"
                self.devices[node] = label
                log.info(
                    "UsbMonitor: found existing USB device: %s label=%r vendor=%r model=%r serial=%r",
                    node,
                    label,
                    vendor,
                    model,
                    serial,
                )
                found += 1
        log.info("UsbMonitor: initial scan complete, %d USB block device(s) found", found)

    def _on_socket_ready(self):
        while True:
            device = self.monitor.poll(timeout=0)
            if device is None:
                break
            self._handle_event(device)

    def _handle_event(self, device):
        if device.get("DEVTYPE") != "disk":
            return
        if device.get("ID_BUS") != "usb":
            return

        node = device.device_node
        if not node:
            log.warning("UsbMonitor: ignoring event with no device_node (action=%s)", device.action)
            return

        action = device.action
        label = device.get("ID_FS_LABEL") or device.get("ID_MODEL") or node
        vendor = device.get("ID_VENDOR") or "unknown vendor"
        model = device.get("ID_MODEL") or "unknown model"

        log.info(
            "UsbMonitor: udev event -> action=%s, node=%s, label=%r, vendor=%r, model=%r",
            action,
            node,
            label,
            vendor,
            model,
        )

        changed = False
        if action == "add":
            self.devices[node] = label
            log.info("UsbMonitor: device added: %s (%s)", node, label)
            self.device_added.emit(node)
            changed = True
        elif action == "remove":
            if node in self.devices:
                removed_label = self.devices.pop(node)
                log.info("UsbMonitor: device removed: %s (was labeled %r)", node, removed_label)
                self.device_removed.emit(node)
                changed = True
            else:
                log.warning("UsbMonitor: remove event for unknown node %s, ignoring", node)

        if changed:
            self.device_list_updated.emit(self.devices)
