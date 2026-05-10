import sys
import os
from lufus.lufus_logging import get_logger, setup_logging
from lufus.drives.find_usb import find_usb
from lufus.utils import elevate_privileges
from lufus import state
from pathlib import Path
from platformdirs import user_config_dir

setup_logging()
log = get_logger(__name__)


def _load_initial_theme():
    # Load theme before elevation so it can be passed via env
    if getattr(state, "theme", ""):
        return
    try:
        _theme_cfg = Path(user_config_dir("Lufus")) / "active_theme"
        if _theme_cfg.exists():
            state.theme = _theme_cfg.read_text(encoding="utf-8").strip()
    except Exception:
        pass


def _show_root_warning() -> None:
    from PySide6.QtWidgets import QApplication, QMessageBox
    from PySide6.QtCore import QTimer
    import sys

    app = QApplication(sys.argv)
    msg = QMessageBox()
    msg.setIcon(QMessageBox.Icon.Warning)
    msg.setWindowTitle("Root Privileges Required")
    msg.setText("This application must run as root.")
    msg.setInformativeText(
        "To run Lufus as root, you need:\n"
        "• pkexec (from polkit package)\n"
        "• polkit (policy kit) installed on your system\n\n"
        "Please install these packages via your distribution's package manager.\n"
        "Example: sudo apt install polkit (Debian/Ubuntu)\n"
        "         sudo dnf install polkit (Fedora)\n"
        "         sudo pacman -S polkit (Arch)"
    )
    msg.setStandardButtons(QMessageBox.StandardButton.Ok)
    msg.exec()

    app.quit()


def launch_gui_with_usb_data() -> None:
    elevation_attempted = False
    if os.geteuid() != 0:
        # Capture user context (XDG_DOWNLOAD_DIR path) before pkexec elevation
        from lufus.user_paths import get_best_starting_dir, ENV_DOWNLOAD_DIR

        try:
            detected_path = get_best_starting_dir()
            os.environ[ENV_DOWNLOAD_DIR] = detected_path
            log.info("Captured user starting directory: %s", detected_path)
        except Exception as e:
            log.warning("Could not capture user starting directory: %s", e)

        _load_initial_theme()
        elevation_attempted = True
        elevate_privileges()

    if elevation_attempted and os.geteuid() != 0:
        _show_root_warning()
        sys.exit(1)

    usb_devices = find_usb()
    log.info("Launching GUI with USB devices: %s", usb_devices)

    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import QTimer
    from lufus.gui.gui import LufusWindow

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
