import sys
import os
from lufus.lufus_logging import get_logger, setup_logging
from lufus.drives.find_usb import find_usb

setup_logging()
log = get_logger(__name__)


def launch_gui_with_usb_data() -> None:
    usb_devices = find_usb()
    log.info("Launching GUI with USB devices: %s", usb_devices)

    from PyQt6.QtWidgets import QApplication
    from PyQt6.QtCore import QTimer
    from lufus.gui.gui import lufus as LufusWindow

    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    autoflash_path = None
    if "--flash-now" in sys.argv:
        idx = sys.argv.index("--flash-now")
        if idx + 1 < len(sys.argv):
            autoflash_path = sys.argv[idx + 1]

    window = LufusWindow(usb_devices)
    if autoflash_path:
        window._autoflash_path = autoflash_path
        QTimer.singleShot(0, window._do_autoflash)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    launch_gui_with_usb_data()
