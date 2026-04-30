import sys
import os
from lufus.lufus_logging import get_logger, setup_logging
from lufus.drives.find_usb import find_usb

setup_logging()
log = get_logger(__name__)


def launch_gui_with_usb_data() -> None:
    if os.geteuid() != 0:
        import shutil
        pkexec_path = shutil.which("pkexec") or "/usr/bin/pkexec"
        if os.path.isfile(pkexec_path) and "LUFUS_RELAUNCHED" not in os.environ:
            env_args = ["env"]
            gui_env = {
                "DISPLAY": os.environ.get("DISPLAY"),
                "XAUTHORITY": os.environ.get("XAUTHORITY") or os.path.expanduser("~/.Xauthority"),
                "WAYLAND_DISPLAY": os.environ.get("WAYLAND_DISPLAY"),
                "XDG_RUNTIME_DIR": os.environ.get("XDG_RUNTIME_DIR"),
                "PATH": os.environ.get("PATH", "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"),
                "PYTHONPATH": os.environ.get("PYTHONPATH", ""),
                "LUFUS_RELAUNCHED": "1",
            }
            for key, value in gui_env.items():
                if value:
                    env_args.append(f"{key}={value}")
            appimage = os.environ.get("APPIMAGE")
            executable = appimage if appimage else sys.executable
            cmd = [pkexec_path] + env_args + [executable] + sys.argv
            os.execvp(pkexec_path, cmd)

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
