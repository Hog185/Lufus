from PyQt6.QtCore import QObject, pyqtSignal, QSocketNotifier
import pyudev


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

        print("UsbMonitor: initializing, scanning existing block devices...")
        self._load_existing()
        print("UsbMonitor: QSocketNotifier active, watching for hotplug events")

    def _load_existing(self):
        found = 0
        for device in self.context.list_devices(subsystem="block", DEVTYPE="disk"):
            if device.get("ID_BUS") == "usb":
                node = device.device_node
                label = device.get("ID_FS_LABEL") or device.get("ID_MODEL") or node
                vendor = device.get("ID_VENDOR") or "unknown vendor"
                model = device.get("ID_MODEL") or "unknown model"
                serial = device.get("ID_SERIAL_SHORT") or "no serial"
                self.devices[node] = label
                print(
                    f"UsbMonitor: found existing USB device: {node} label={label!r} "
                    f"vendor={vendor!r} model={model!r} serial={serial!r}"
                )
                found += 1
        print(f"UsbMonitor: initial scan complete, {found} USB block device(s) found")

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
        action = device.action
        label = device.get("ID_FS_LABEL") or device.get("ID_MODEL") or node
        vendor = device.get("ID_VENDOR") or "unknown vendor"
        model = device.get("ID_MODEL") or "unknown model"

        print(
            f"UsbMonitor: udev event -> action={action}, node={node}, label={label!r}, "
            f"vendor={vendor!r}, model={model!r}"
        )

        if action == "add":
            self.devices[node] = label
            print(f"UsbMonitor: device added: {node} ({label})")
            self.device_added.emit(node)
        elif action == "remove":
            if node in self.devices:
                removed_label = self.devices.pop(node)
                print(
                    f"UsbMonitor: device removed: {node} (was labeled {removed_label!r})"
                )
                self.device_removed.emit(node)
            else:
                print(f"UsbMonitor: remove event for unknown node {node}, ignoring")

        self.device_list_updated.emit(self.devices)
