import subprocess
import sys
import tempfile
import json
import os
import signal
import csv
import platform
import getpass
from platformdirs import user_config_dir
from datetime import datetime
from glob import glob
import urllib.parse
import webbrowser
from pathlib import Path
from PyQt6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QLabel,
    QComboBox,
    QPushButton,
    QProgressBar,
    QCheckBox,
    QMessageBox,
    QDialog,
    QTextEdit,
    QFileDialog,
    QLineEdit,
    QFrame,
    QStatusBar,
    QToolButton,
    QSpacerItem,
    QScrollArea,
)
from PyQt6.QtCore import (
    Qt,
    QTimer,
    QThread,
    QProcess,
    pyqtSignal,
    QPoint,
    QPropertyAnimation,
    QEasingCurve,
)
from PyQt6.QtGui import QFont, QFontDatabase
from lufus.drives import states
from lufus.drives import formatting as fo
from lufus.writing.flash_usb import FlashUSB
from lufus.writing.flash_woeusb import flash_woeusb
from lufus.drives.find_usb import find_usb
from lufus.drives.autodetect_usb import UsbMonitor

THEME_DIR = Path(__file__).parent / 'themes'

class Scale:
    BASE_DPI = 80.0
    DESIGN_W = 640
    DESIGN_H = 980

    def __init__(self, app: QApplication, factor: float = None):
        screen = app.primaryScreen()
        logical_dpi = screen.logicalDotsPerInch()
        device_ratio = screen.devicePixelRatio()

        if factor is not None:
            self._factor = max(factor, 0.3)
        else:
            self._factor = max(logical_dpi / self.BASE_DPI, 0.75)

        print(
            f"[Scale] logicalDPI={logical_dpi:.1f}  DevicePixelRatio={device_ratio:.2f}"
            f"  → scale factor={self._factor:.3f}"
        )

    def f(self) -> float:
        return self._factor

    def px(self, base_pixels: int | float) -> int:
        return max(1, round(base_pixels * self._factor))

    def pt(self, base_points: int | float) -> int:
        return max(6, round(base_points * self._factor))


def load_translations(language="English"):
    lang_file = Path(__file__).parent / "languages" / f"{language}.csv"
    t = {}
    if lang_file.exists():
        with open(lang_file, encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f):
                t[row["key"]] = row["value"]
    return t


class StdoutRedirector:
    def __init__(self, log_fn):
        self._log_fn = log_fn
        self._real_stdout = sys.stdout
        self._buf = ""

    def write(self, text):
        self._real_stdout.write(text)
        self._buf += text
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            line = line.rstrip()
            if line:
                self._log_fn(line)

    def flush(self):
        self._real_stdout.flush()

    def fileno(self):
        return self._real_stdout.fileno()

    def isatty(self):
        return False


class LogWindow(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._T = parent._T if parent else {}
        self._S: Scale = parent._S if parent else None
        self.setWindowTitle(self._T.get("log_window_title", "Log Window"))

        if self._S:
            self.resize(self._S.px(650), self._S.px(450))
        else:
            self.resize(650, 450)

        layout = QVBoxLayout()
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        font_size = self._S.pt(9) if self._S else 9
        self.log_text.setFont(QFont("Consolas", font_size))
        self.log_text.setStyleSheet("background-color: white; border: 1px solid #ccc;")
        layout.addWidget(self.log_text)

        btn_row = QHBoxLayout()
        btn_copy = QPushButton(self._T.get("btn_copy_log", "Copy Log"))
        btn_copy.setFixedWidth(self._S.px(140) if self._S else 140)
        btn_copy.clicked.connect(self._copy_log)
        btn_save = QPushButton(self._T.get("btn_save_log", "Save Log"))
        btn_save.setFixedWidth(self._S.px(100) if self._S else 100)
        btn_save.clicked.connect(self._save_log)
        btn_row.addWidget(btn_copy)
        btn_row.addWidget(btn_save)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        self.setLayout(layout)

    def closeEvent(self, event):
        event.ignore()
        self.hide()

    def _copy_log(self):
        QApplication.clipboard().setText(self.log_text.toPlainText())

    def _save_log(self):
        path, _ = QFileDialog.getSaveFileName(
            self,
            self._T.get("dlg_save_log_title", "Save Log"),
            "lufus_log.txt",
            "Text Files (*.txt);;All Files (*)",
        )
        if path:
            try:
                with open(path, "w", encoding="utf-8") as f:
                    f.write(self.log_text.toPlainText())
            except OSError as e:
                QMessageBox.critical(
                    self,
                    self._T.get("save_failed_title", "Save Failed"),
                    f'{self._T.get("save_failed_body", "Failed to save log")}\n{e}',
                )


class Notification(QFrame):
    def __init__(self, message, notification_type="info", duration=3000, parent=None, scale: Scale = None):
        super().__init__(parent)
        self._S = scale
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        colors = {
            "info": "#6e6e6e",
            "success": "#5a5a5a",
        }

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        pad_v  = self._S.px(15) if self._S else 15
        pad_h  = self._S.px(25) if self._S else 25
        radius = self._S.px(8)  if self._S else 8
        fsize  = self._S.pt(11) if self._S else 11

        self.label = QLabel(message)
        self.label.setWordWrap(True)
        self.label.setStyleSheet(f"""
            QLabel {{
                background-color: {colors.get(notification_type.lower(), '#333333')};
                color: white;
                padding: {pad_v}px {pad_h}px;
                border-radius: {radius}px;
                font-size: {fsize}pt;
                font-weight: bold;
            }}
        """)
        layout.addWidget(self.label)

        self.fade_in = QPropertyAnimation(self, b"windowOpacity")
        self.fade_in.setDuration(200)
        self.fade_in.setStartValue(0.0)
        self.fade_in.setEndValue(1.0)

        self.adjustSize()
        self.position_notification()
        self.show()
        self.fade_in.start()

        self.timer = QTimer()
        self.timer.timeout.connect(self.fade_out)
        self.timer.setSingleShot(True)
        self.timer.start(duration)

    def fade_out(self):
        self.fade_out_anim = QPropertyAnimation(self, b"windowOpacity")
        self.fade_out_anim.setDuration(200)
        self.fade_out_anim.setStartValue(1.0)
        self.fade_out_anim.setEndValue(0.0)
        self.fade_out_anim.finished.connect(self.close)
        self.fade_out_anim.start()

    def position_notification(self, index=0):
        screen = QApplication.primaryScreen().availableGeometry()

        if self.parent() and isinstance(self.parent(), QWidget):
            parent_geo = self.parent().frameGeometry()
            if screen.contains(parent_geo.topLeft()):
                x = parent_geo.right() - self.width() - 20
                y = parent_geo.bottom() - (self.height() + 10) * (index + 1) - 20
                self.move(int(x), int(y))
                return

        x = screen.right() - self.width() - 20
        y = screen.bottom() - (self.height() + 10) * (index + 1) - 20
        self.move(int(x), int(y))


class NotificationManager:
    def __init__(self, parent=None, scale: Scale = None):
        self.parent = parent
        self._S = scale
        self.notifications = []

    def show(self, message, notification_type="info", duration=3000):
        notification = Notification(
            message, notification_type, duration, self.parent, scale=self._S
        )
        self.notifications.append(notification)
        notification.position_notification(len(self.notifications) - 1)
        notification.show()
        notification.destroyed.connect(
            lambda: self.notifications.remove(notification)
            if notification in self.notifications else None
        )


class AboutWindow(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent_window = parent
        self._T = parent._T if parent else {}
        self._S: Scale = parent._S if parent else None
        self.setWindowTitle(self._T.get("about_window_title", "About"))

        if self._S:
            self.resize(self._S.px(650), self._S.px(450))
        else:
            self.resize(650, 450)

        layout = QVBoxLayout()
        self.about_text = QTextEdit()
        self.about_text.setReadOnly(True)
        font_size = self._S.pt(9) if self._S else 9
        self.about_text.setFont(QFont("Consolas", font_size))
        self.about_text.setStyleSheet(
            "background-color: white; border: 1px solid #ccc;"
        )
        layout.addWidget(self.about_text)
        self.setLayout(layout)


class SettingsDialog(QDialog):
    language_changed = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._T = parent._T if parent else {}
        self._S: Scale = parent._S if parent else None
        self.setWindowTitle(self._T.get("settings_window_title", "Settings"))

        if self._S:
            self.setFixedSize(self._S.px(650), self._S.px(450))
        else:
            self.setFixedSize(650, 450)

        m = self._S.px(20) if self._S else 20
        layout = QVBoxLayout()
        layout.setContentsMargins(m, m, m, m)
        layout.setSpacing(self._S.px(10) if self._S else 10)

        lbl_lang = QLabel(self._T.get("settings_label_language", "Language"))
        lbl_lang.setStyleSheet("font-weight: normal;")

        self.combo_language = QComboBox()
        languages = self._detect_languages()
        if languages:
            self.combo_language.addItems(languages)
            current_lang = states.language if hasattr(states, "language") else "English"
            if current_lang in languages:
                self.combo_language.setCurrentText(current_lang)
        else:
            self.combo_language.addItem(self._T.get("settings_no_languages", "No languages found"))
            self.combo_language.setEnabled(False)

        layout.addWidget(lbl_lang)
        layout.addWidget(self.combo_language)
        layout.addStretch()

        btn_ok = QPushButton("OK")
        btn_ok.clicked.connect(self._on_ok_clicked)
        layout.addWidget(btn_ok)

        self.setLayout(layout)

    def _on_ok_clicked(self):
        language = self.combo_language.currentText()
        if language != "No languages found":
            self.language_changed.emit(language)
        self.accept()

    @staticmethod
    def _detect_languages():
        languages_dir = Path(__file__).parent / "languages"
        if not languages_dir.is_dir():
            return []
        return sorted(p.stem for p in languages_dir.glob("*.csv"))


class VerifyWorker(QThread):
    """Worker thread for SHA256 verification"""

    def __init__(self, iso_path: str, expected_hash: str):
        super().__init__()
        self.iso_path = iso_path
        self.expected_hash = expected_hash

    def run(self):
        try:
            from lufus.writing.check_file_sig import check_sha256
            self.progress.emit(f"Verifying SHA256 checksum for {self.iso_path}...")
            result = check_sha256(self.iso_path, self.expected_hash)
            self.finished.emit(result)
        except Exception as e:
            self.progress.emit(f"Verification error: {str(e)}")
            self.flash_done.emit(False)


class FlashWorker(QThread):
    progress = pyqtSignal(int)
    status = pyqtSignal(str)
    flash_done = pyqtSignal(bool)

    def __init__(self, options: dict):
        super().__init__()
        self.options = options

    def run(self):
        _saved_stdout = sys.stdout
        sys.stdout = sys.__stdout__
        try:
            from lufus.drives import states, formatting as fo
            from lufus.writing.flash_usb import FlashUSB
            from lufus.writing.flash_woeusb import flash_woeusb
            import glob

            options = self.options
            for key, value in options.items():
                setattr(states, key, value)

            device_node = options["device"]
            iso_path = options["iso_path"]
            flash_mode = options["currentflash"]
            image_option = options["image_option"]

            self.status.emit(f"Unmounting all partitions on {device_node}...")
            partitions = glob.glob(f"{device_node}*")
            for part in partitions:
                self.status.emit(f"Unmounting {part}...")
                fo.unmount(part)

            if image_option == 0:
                if flash_mode == 0:
                    success = FlashUSB(iso_path, device_node,
                                       progress_cb=self.progress.emit,
                                       status_cb=self.status.emit)
                elif flash_mode == 1:
                    success = flash_woeusb(device_node, iso_path,
                                           progress_cb=self.progress.emit,
                                           status_cb=self.status.emit)
                else:
                    success = False
            else:
                success = FlashUSB(iso_path, device_node,
                                   progress_cb=self.progress.emit,
                                   status_cb=self.status.emit)

            self.flash_done.emit(bool(success))
        except Exception as e:
            self.status.emit(f"Flash error: {e}")
            self.flash_done.emit(False)
        finally:
            sys.stdout = _saved_stdout


class lufus(QMainWindow):
    def __init__(self, usb_devices=None, scale: Scale = None):
        super().__init__()

        self.usb_devices = usb_devices or {}
        self.monitor = UsbMonitor()
        self.monitor.device_added.connect(self.on_usb_added)
        self.monitor.device_list_updated.connect(self.update_usb_list)

        self.current_language = getattr(states, "language", "English")
        self._T = load_translations(self.current_language)

        self.setWindowTitle(self._T.get("window_title", "lufus"))

        screen = QApplication.primaryScreen().availableGeometry()
        aspect = Scale.DESIGN_W / Scale.DESIGN_H
        win_w = int(screen.width() * 0.450)
        win_h = int(win_w / aspect)
        if win_h > screen.height() * 1:
            win_h = int(screen.height() * 1)
            win_w = int(win_h * aspect)
        ui_factor = win_w / Scale.DESIGN_W
        self._S = Scale(QApplication.instance(), factor=ui_factor)
        self.setFixedSize(win_w, win_h)

        self.flash_worker = None
        self.verify_worker = None
        self.log_window = None
        self.about_window = None
        self.log_entries = []
        self._last_clipboard = ""
        self.is_terminal = False
        try:
            self.is_terminal = sys.stdout.isatty()
        except (AttributeError, OSError):
            pass

        sys.stdout = StdoutRedirector(self.log_message)

        self._apply_styles()
        self.init_ui()
        self.update_usb_list(self.monitor.devices)
        self.setAcceptDrops(True)
        self.notifier = NotificationManager(self, scale=self._S)

        self._clipboard_timer = QTimer(self)
        self._clipboard_timer.timeout.connect(self._check_clipboard)
        self._clipboard_timer.start(500)

        self.log_message("lufus started")
        self.log_message(
            f"Python {sys.version.split()[0]} | {platform.system()} {platform.release()} {platform.machine()}"
        )
        self.log_message(f"Running as user: {getpass.getuser()} (uid={os.getuid()})")
        self.log_message(
            f"Startup USB devices passed in: {list((usb_devices or {}).keys()) or 'none'}"
        )
        self.flash_worker = None
        self.log_message(f"UI scale factor: {self._S.f():.3f}  (base 96 DPI)")

    def _apply_styles(self) -> None:
        """load json values, apply via .qss, all that yap is in the themes folder :3"""
        S = self._S
        APP_NAME = "Lufus"

        theme_dir = Path(__file__).parent / 'themes'
        default_theme_path = theme_dir / 'default_theme.json'
        template_path = theme_dir / 'style_template.qss'

        user_config_dir_path = Path(user_config_dir(APP_NAME, roaming=True))
        user_theme_path = user_config_path = user_config_dir_path / 'user_theme.json'
        

        try:
            with open(default_theme_path, 'r', encoding='utf-8') as fr:
                theme = json.load(fr)
        except FileNotFoundError as e:
            # Fallback if this doesn't bother to work... -_-
            print("WARNING: no theme applied, json didn't load up in _apply_styles, gui.py.")

        if os.path.exists(user_theme_path):
            try:
                with open(user_theme_path, 'r', encoding='utf-8') as fr:
                    user_theme = json.load(fr)
                for category in ['colors', 'fonts', 'dimensions']:
                    if category in user_theme and isinstance(user_theme[category], dict):
                        theme[category].update(user_theme[category])
            except Exception as e:
                print(f"Error loading user theme: {e}")

        scaled_theme = {
                'colors': theme['colors'].copy(),
                'fonts': {},
                'dimensions': {}
            }

        for key, value in theme['fonts'].items():
            scaled_theme['fonts'][key] = S.pt(value)

        for key, value in theme['dimensions'].items():
            scaled_theme['dimensions'][key] = S.px(value)

        flat_theme: Dict[str, Any] = {}
        for category, subdict in scaled_theme.items():
            for key, val in subdict.items():
                flat_theme[f"{category}_{key}"] = val

        try:
            with open(template_path, 'r', encoding='utf-8') as f:
                template = f.read()
        except FileNotFoundError:
            print("Error: style_template.qss not found.")
            return

        style_sheet = template.format(**flat_theme)
        self.setStyleSheet(style_sheet)

    def create_header(self, text):
        layout = QHBoxLayout()
        layout.setContentsMargins(0, self._S.px(10), 0, self._S.px(5))
        label = QLabel(text)
        label.setObjectName("sectionHeader")
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        line.setStyleSheet(
            "background-color: #000000; min-height: 1px; max-height: 1px;"
        )
        layout.addWidget(label)
        layout.addWidget(line, 1)
        return layout


    def update_usb_list(self, devices: dict):
        self.combo_device.clear()
        self.usb_devices = devices

        if not devices:
            self.combo_device.addItem(self._T.get("no_usb_found", "No USB devices found"), None)
            return

        for node, label in devices.items():
            display = f"{label} ({node})" if label != node else node
            self.combo_device.addItem(display, node)

    def on_usb_added(self, node):
        self.log_message(f"USB device connected: {node}")
        self.notifier.show(f"✓ {node} connected", notification_type="success", duration=3000)


    def create_refresh_button(self):
        S = self._S
        size = S.px(25)
        btn = QToolButton()
        btn.setText("🔄")
        btn.setToolTip(self._T.get("tooltip_refresh", "Refresh"))
        btn.setStyleSheet(f"""
            QToolButton {{
                border: 1px solid #D0D0D0;
                background-color: white;
                font-size: {S.pt(13)}pt;
                max-height: {size}px;
                min-height: {size}px;
                max-width:  {size}px;
                min-width:  {size}px;
            }}
            QToolButton:hover  {{ background-color: #E5F1FB; border-color: #0078D7; }}
            QToolButton:pressed {{ background-color: #D0D0D0; }}
        """)
        btn.clicked.connect(self.refresh_usb_devices)
        return btn


    def init_ui(self):
        S = self._S
        FIELD_SPACING = S.px(2)
        GROUP_SPACING = S.px(10)

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        outer_layout = QVBoxLayout(central_widget)
        outer_layout.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        scroll_content = QWidget()
        main_layout = QVBoxLayout(scroll_content)
        main_layout.setSpacing(GROUP_SPACING)
        m = S.px(15)
        main_layout.setContentsMargins(m, S.px(10), m, S.px(10))

        scroll.setWidget(scroll_content)
        outer_layout.addWidget(scroll)

        main_layout.addLayout(
            self.create_header(self._T.get("header_drive_properties", "Drive Properties"))
        )
        main_layout.addSpacing(S.px(4))

        self.lbl_device = QLabel(self._T.get("lbl_device", "Device"))
        self.combo_device = QComboBox()
        self._populate_device_combo()
        btn_refresh = self.create_refresh_button()

        device_row = QHBoxLayout()
        device_row.setSpacing(S.px(5))
        device_row.addWidget(self.combo_device, 1)
        device_row.addWidget(btn_refresh)

        device_layout = QVBoxLayout()
        device_layout.setSpacing(FIELD_SPACING)
        device_layout.addWidget(self.lbl_device)
        device_layout.addLayout(device_row)
        main_layout.addLayout(device_layout)
        main_layout.addSpacing(GROUP_SPACING)

        self.lbl_boot = QLabel(self._T.get("lbl_boot_selection", "Boot Selection"))
        self.combo_boot = QComboBox()
        self.combo_boot.setEditable(True)
        self.combo_boot.lineEdit().setReadOnly(True)
        self.combo_boot.addItem("installationmedia.iso")

        self.btn_select = QPushButton(self._T.get("btn_select", "Select"))
        self.btn_select.clicked.connect(self.browse_file)

        boot_row = QHBoxLayout()
        boot_row.setSpacing(S.px(5))
        boot_row.addWidget(self.combo_boot, 1)
        boot_row.addWidget(self.btn_select)

        boot_layout = QVBoxLayout()
        boot_layout.setSpacing(FIELD_SPACING)
        boot_layout.addWidget(self.lbl_boot)
        boot_layout.addLayout(boot_row)
        main_layout.addLayout(boot_layout)
        main_layout.addSpacing(GROUP_SPACING)

        self.lbl_image = QLabel(self._T.get("lbl_image_option", "Image Option"))
        self.combo_image_option = QComboBox()
        self.combo_image_option.addItem(self._T.get("combo_image_windows", "Windows"))
        self.combo_image_option.addItem(self._T.get("combo_image_linux", "Linux"))
        self.combo_image_option.addItem(self._T.get("combo_image_other", "Other"))
        self.combo_image_option.addItem(self._T.get("combo_image_format", "Format Only"))
        self.combo_image_option.currentTextChanged.connect(self.update_image_option)

        image_layout = QVBoxLayout()
        image_layout.setSpacing(FIELD_SPACING)
        image_layout.addWidget(self.lbl_image)
        image_layout.addWidget(self.combo_image_option)
        main_layout.addLayout(image_layout)
        main_layout.addSpacing(GROUP_SPACING)

        self.lbl_part = QLabel(self._T.get("lbl_partition_scheme", "Partition Scheme"))
        self.combo_partition = QComboBox()
        self.combo_partition.addItem(self._T.get("combo_partition_gpt", "GPT"))
        self.combo_partition.addItem(self._T.get("combo_partition_mbr", "MBR"))
        self.combo_partition.currentTextChanged.connect(self.update_partition_scheme)

        self.lbl_target = QLabel(self._T.get("lbl_target_system", "Target System"))
        self.combo_target = QComboBox()
        self.combo_target.addItem(self._T.get("combo_target_uefi", "UEFI"))
        self.combo_target.addItem(self._T.get("combo_target_bios", "BIOS"))
        self.combo_target.currentTextChanged.connect(self.update_target_system)

        grid_part = QGridLayout()
        grid_part.setHorizontalSpacing(S.px(10))
        grid_part.setVerticalSpacing(FIELD_SPACING)
        grid_part.setColumnStretch(0, 1)
        grid_part.setColumnStretch(1, 1)
        grid_part.addWidget(self.lbl_part, 0, 0)
        grid_part.addWidget(self.combo_partition, 1, 0)
        grid_part.addWidget(self.lbl_target, 0, 1)
        grid_part.addWidget(self.combo_target, 1, 1)
        main_layout.addLayout(grid_part)

        main_layout.addSpacing(S.px(16))

        main_layout.addLayout(
            self.create_header(self._T.get("header_format_options", "Format Options"))
        )
        main_layout.addSpacing(S.px(4))

        self.lbl_vol = QLabel(self._T.get("lbl_volume_label", "Volume Label"))
        self.input_label = QLineEdit(self._T.get("lbl_volume_label", "Volume Label"))
        self.input_label.textChanged.connect(self.update_new_label)

        vol_layout = QVBoxLayout()
        vol_layout.setSpacing(FIELD_SPACING)
        vol_layout.addWidget(self.lbl_vol)
        vol_layout.addWidget(self.input_label)
        main_layout.addLayout(vol_layout)
        main_layout.addSpacing(GROUP_SPACING)

        self.lbl_fs = QLabel(self._T.get("lbl_file_system", "File System"))
        self.combo_fs = QComboBox()
        self.all_fs_options = ["NTFS", "FAT32", "exFAT", "ext4", "UDF"]
        self.combo_fs.addItems(["NTFS", "FAT32", "exFAT"])
        self.combo_fs.currentTextChanged.connect(self.updateFS)

        self.lbl_cluster = QLabel(self._T.get("lbl_cluster_size", "Cluster Size"))
        self.combo_cluster = QComboBox()
        self.combo_cluster.addItem(self._T.get("combo_cluster_4096", "4096"))
        self.combo_cluster.addItem(self._T.get("combo_cluster_8192", "8192"))
        self.combo_cluster.currentTextChanged.connect(self.update_cluster_size)

        self.lbl_flash = QLabel(self._T.get("lbl_flash_option", "Flash Option"))
        self.combo_flash = QComboBox()
        self.all_flash_options = [
            self._T.get("combo_flash_iso",    "ISO"),
            self._T.get("combo_flash_woe",    "WoeUSB"),
            self._T.get("combo_flash_ventoy", "Ventoy"),
            self._T.get("combo_flash_dd",     "DD"),
        ]
        self.combo_flash.addItems(self.all_flash_options)
        self.combo_flash.currentTextChanged.connect(self.updateflash)

        grid_fmt = QGridLayout()
        grid_fmt.setHorizontalSpacing(S.px(10))
        grid_fmt.setVerticalSpacing(FIELD_SPACING)
        grid_fmt.setColumnStretch(0, 1)
        grid_fmt.setColumnStretch(1, 1)
        grid_fmt.setColumnStretch(2, 1)
        grid_fmt.addWidget(self.lbl_fs,      0, 0)
        grid_fmt.addWidget(self.combo_fs,    1, 0)
        grid_fmt.addWidget(self.lbl_cluster, 0, 1)
        grid_fmt.addWidget(self.combo_cluster, 1, 1)
        grid_fmt.addWidget(self.lbl_flash,   0, 2)
        grid_fmt.addWidget(self.combo_flash, 1, 2)
        main_layout.addLayout(grid_fmt)
        main_layout.addSpacing(GROUP_SPACING)

        self.chk_quick = QCheckBox(self._T.get("chk_quick_format", "Quick Format"))
        self.chk_quick.setChecked(True)
        self.chk_quick.stateChanged.connect(self.update_QF)

        self.chk_extended = QCheckBox(self._T.get("chk_extended_label", "Create Extended Label"))
        self.chk_extended.setChecked(True)
        self.chk_extended.stateChanged.connect(self.update_create_extended)

        self.chk_badblocks = QCheckBox(self._T.get("chk_bad_blocks", "Check for Bad Blocks"))
        self.combo_badblocks = QComboBox()
        self.combo_badblocks.addItem(self._T.get("combo_badblocks_1pass", "1 Pass"))
        self.combo_badblocks.setFixedWidth(S.px(100))
        self.combo_badblocks.setEnabled(False)
        self.chk_badblocks.stateChanged.connect(self.update_check_bad)

        bad_blocks_row = QHBoxLayout()
        bad_blocks_row.setSpacing(S.px(6))
        bad_blocks_row.addWidget(self.chk_badblocks)
        bad_blocks_row.addWidget(self.combo_badblocks)
        bad_blocks_row.addStretch()

        self.chk_verify = QCheckBox(self._T.get("chk_verify_hash", "Verify SHA256 Checksum"))
        self.chk_verify.stateChanged.connect(self.update_verify_hash)
        self.input_hash = QLineEdit()
        self.input_hash.setPlaceholderText("Enter expected SHA256 hash here...")
        self.input_hash.setEnabled(False)
        self.input_hash.textChanged.connect(self.update_expected_hash)

        chk_layout = QVBoxLayout()
        chk_layout.setSpacing(S.px(6))
        chk_layout.addWidget(self.chk_quick)
        chk_layout.addWidget(self.chk_extended)
        chk_layout.addLayout(bad_blocks_row)
        chk_layout.addWidget(self.chk_verify)
        chk_layout.addWidget(self.input_hash)
        main_layout.addLayout(chk_layout)

        main_layout.addStretch()
        main_layout.addSpacing(S.px(16))

        main_layout.addLayout(
            self.create_header(self._T.get("header_status", "Status"))
        )
        main_layout.addSpacing(S.px(4))

        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("")
        self.progress_bar.setMinimumHeight(S.px(22))
        main_layout.addWidget(self.progress_bar)
        main_layout.addSpacing(S.px(10))

        btn_icon1 = QToolButton()
        btn_icon1.setText("🌐")
        btn_icon1.setToolTip(self._T.get("tooltip_download", "Download"))
        btn_icon1.clicked.connect(
            lambda: webbrowser.open("http://www.github.com/hog185/lufus")
        )

        btn_icon2 = QToolButton()
        btn_icon2.setText("ℹ")
        btn_icon2.setToolTip(self._T.get("tooltip_about", "About"))
        btn_icon2.clicked.connect(self.show_about)

        btn_icon3 = QToolButton()
        btn_icon3.setText("⚙")
        btn_icon3.setToolTip(self._T.get("tooltip_settings", "Settings"))
        btn_icon3.clicked.connect(self.show_settings)

        btn_icon4 = QToolButton()
        btn_icon4.setText("📄")
        btn_icon4.setToolTip(self._T.get("tooltip_log", "Log"))
        btn_icon4.clicked.connect(self.show_log)

        icons_layout = QHBoxLayout()
        icons_layout.setSpacing(S.px(5))
        icons_layout.addWidget(btn_icon1)
        icons_layout.addWidget(btn_icon2)
        icons_layout.addWidget(btn_icon3)
        icons_layout.addWidget(btn_icon4)
        icons_layout.addStretch()

        self.btn_start = QPushButton(self._T.get("btn_start", "Start"))
        self.btn_start.setObjectName("btnStart")
        self.btn_start.setMinimumHeight(S.px(40))
        self.btn_start.clicked.connect(self.start_process)

        self.btn_cancel = QPushButton(self._T.get("btn_cancel", "Cancel"))
        self.btn_cancel.setMinimumHeight(S.px(40))
        self.btn_cancel.clicked.connect(self.cancel_process)

        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(S.px(10))
        btn_layout.addWidget(self.btn_start)
        btn_layout.addWidget(self.btn_cancel)

        bottom_controls = QHBoxLayout()
        bottom_controls.setContentsMargins(m, S.px(10), m, S.px(10))
        bottom_controls.setSpacing(S.px(10))
        bottom_controls.addLayout(icons_layout, 1)
        bottom_controls.addLayout(btn_layout)

        outer_layout.addLayout(bottom_controls)

        self.statusBar = QStatusBar()
        self.setStatusBar(self.statusBar)
        self.statusBar.showMessage(self._T.get("status_ready", "Ready"), 0)


    def _populate_device_combo(self):
        self.combo_device.blockSignals(True)
        self.combo_device.clear()

        if self.usb_devices:
            for node, label in self.usb_devices.items():
                display = f"{label} ({node})" if label != node else node
                self.combo_device.addItem(display, node)
        else:
            self.combo_device.addItem(self._T.get("no_usb_found", "No USB devices found"), None)

        self.combo_device.blockSignals(False)

    def refresh_usb_devices(self):
        self.statusBar.showMessage(self._T.get("status_scanning", "Scanning..."), 2000)
        self.log_message("USB device scan initiated")
        try:
            new_devices = self.monitor.devices
            self.log_message(
                f"USB scan result: {len(new_devices)} device(s) found: {list(new_devices.keys())}"
            )

            if new_devices:
                self.usb_devices = new_devices
                self._populate_device_combo()
                self.log_message(
                    f"Device list updated: {[f'{k} ({v})' for k, v in new_devices.items()]}"
                )
                QMessageBox.information(
                    self,
                    self._T.get("msgbox_usb_found_title", "USB Found"),
                    self._T.get("msgbox_usb_found_body", "USB device(s) found"),
                )
            else:
                self.usb_devices = {}
                self._populate_device_combo()
                self.log_message("No USB devices detected after scan", level="WARN")
                QMessageBox.information(
                    self,
                    self._T.get("msgbox_no_devices_title", "No Devices"),
                    self._T.get("msgbox_no_devices_body", "No USB devices detected"),
                )
        except Exception as e:
            self.statusBar.showMessage(self._T.get("status_scan_failed", "Scan Failed"), 3000)
            self.log_message(f"USB scan raised exception: {type(e).__name__}: {str(e)}", level="ERROR")
            QMessageBox.critical(
                self,
                self._T.get("msgbox_scan_error_title", "Scan Error"),
                f'{self._T.get("msgbox_scan_error_body", "Scan failed")}\n{str(e)}',
            )


    def updateFS(self):
        states.currentFS = self.combo_fs.currentIndex()
        self.log_message(f"File system changed to: {self.combo_fs.currentText()} (index={states.currentFS})")

    def updateflash(self):
        states.currentflash = self.combo_flash.currentIndex()
        self.log_message(f"Flash option changed to: {self.combo_flash.currentText()} (index={states.currentflash})")

    def update_image_option(self):
        states.image_option = self.combo_image_option.currentIndex()
        self.log_message(f"Image option changed to: {self.combo_image_option.currentText()} (index={states.image_option})")
        self._update_filesystem_options()
        self._update_flashing_options()

    def _update_filesystem_options(self):
        self.combo_fs.blockSignals(True)
        if states.image_option == 1:      # Linux
            self.combo_fs.clear(); self.combo_fs.addItems(["ext4", "UDF"]); self.combo_fs.setCurrentText("ext4")
        elif states.image_option == 0:    # Windows
            self.combo_fs.clear(); self.combo_fs.addItems(["NTFS", "FAT32", "exFAT"]); self.combo_fs.setCurrentText("NTFS")
        elif states.image_option in (2, 3):
            self.combo_fs.clear(); self.combo_fs.addItems(self.all_fs_options); self.combo_fs.setCurrentText("FAT32")
        self.combo_fs.blockSignals(False)
        self.updateFS()

    def _update_flashing_options(self):
        self.combo_flash.blockSignals(True)
        self.combo_flash.clear()
        if states.image_option == 1:      # Linux
            self.combo_flash.addItems([self._T.get("combo_flash_dd", "DD"), self._T.get("combo_flash_ventoy", "Ventoy")])
            self.combo_flash.setCurrentText(self._T.get("combo_flash_dd", "DD"))
        elif states.image_option == 0:    # Windows
            self.combo_flash.addItems([self._T.get("combo_flash_iso", "ISO"), self._T.get("combo_flash_woe", "WoeUSB"), self._T.get("combo_flash_ventoy", "Ventoy")])
            self.combo_flash.setCurrentText(self._T.get("combo_flash_iso", "ISO"))
        elif states.image_option == 2:
            self.combo_flash.addItems([self._T.get("combo_flash_dd", "DD")])
            self.combo_flash.setCurrentText(self._T.get("combo_flash_dd", "DD"))
        elif states.image_option == 3:
            self.combo_flash.addItems([self._T.get("combo_flash_none", "None")])
            self.combo_flash.setCurrentText(self._T.get("combo_flash_none", "None"))
        self.combo_flash.blockSignals(False)
        self.updateflash()

    def update_partition_scheme(self):
        states.partition_scheme = self.combo_partition.currentIndex()
        self.log_message(f"Partition scheme changed to: {self.combo_partition.currentText()} (index={states.partition_scheme})")

    def update_target_system(self):
        states.target_system = self.combo_target.currentIndex()
        self.log_message(f"Target system changed to: {self.combo_target.currentText()} (index={states.target_system})")

    def update_new_label(self, current_text):
        states.new_label = current_text
        self.log_message(f"Volume label set to: {current_text!r}")

    def update_cluster_size(self):
        states.cluster_size = self.combo_cluster.currentIndex()
        self.log_message(f"Cluster size changed to: {self.combo_cluster.currentText()} (index={states.cluster_size})")

    def update_QF(self):
        states.QF = 0 if self.chk_quick.isChecked() else 1
        self.log_message(f"Quick format: {'enabled' if self.chk_quick.isChecked() else 'disabled'}")

    def update_create_extended(self):
        states.create_extended = 0 if self.chk_extended.isChecked() else 1
        self.log_message(f"Create extended label/icon files: {'enabled' if self.chk_extended.isChecked() else 'disabled'}")

    def update_check_bad(self):
        states.check_bad = 0 if self.chk_badblocks.isChecked() else 1
        self.combo_badblocks.setEnabled(self.chk_badblocks.isChecked())
        self.log_message(f"Bad block check: {'enabled' if self.chk_badblocks.isChecked() else 'disabled'}")

    def update_verify_hash(self):
        states.verify_hash = self.chk_verify.isChecked()
        self.input_hash.setEnabled(states.verify_hash)
        self.log_message(f"SHA256 verification: {'enabled' if states.verify_hash else 'disabled'}")

    def update_expected_hash(self, text):
        states.expected_hash = text.strip()


    def _check_clipboard(self):
        text = QApplication.clipboard().text().strip()
        if text == self._last_clipboard:
            return
        self._last_clipboard = text
        path = text.strip('"').strip("'")
        if path.lower().endswith(".iso") and Path(path).is_file():
            file_size = os.path.getsize(path)
            states.iso_path = path
            clean_name = path.split("/")[-1].split("\\")[-1]
            self.combo_boot.setItemText(0, clean_name)
            self.input_label.setText(clean_name.split(".")[0].upper())
            self.log_message(f"Image loaded from clipboard: {path}")
            self.log_message(f"Image size: {file_size:,} bytes ({file_size / (1024**3):.2f} GiB)")
            self.notifier.show(f"✓ {clean_name} loaded from clipboard", notification_type="success", duration=3000)


    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            supported = [".iso", ".dmg", ".img", ".bin", ".raw"]
            if any(url.toLocalFile().lower().endswith(tuple(supported)) for url in event.mimeData().urls()):
                event.acceptProposedAction(); return
        event.ignore()

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            supported = [".iso", ".dmg", ".img", ".bin", ".raw"]
            if any(url.toLocalFile().lower().endswith(tuple(supported)) for url in event.mimeData().urls()):
                event.acceptProposedAction(); return
        event.ignore()

    def dropEvent(self, event):
        supported = [".iso", ".dmg", ".img", ".bin", ".raw"]
        img_files = [
            url.toLocalFile()
            for url in event.mimeData().urls()
            if url.toLocalFile().lower().endswith(tuple(supported))
        ]
        if img_files:
            file_name = img_files[0]
            file_size = os.path.getsize(file_name)
            states.iso_path = file_name
            clean_name = file_name.split("/")[-1].split("\\")[-1]
            self.combo_boot.setItemText(0, clean_name)
            self.input_label.setText(clean_name.split(".")[0].upper())
            self.log_message(f"Image selected via drag-and-drop: {file_name}")
            self.log_message(f"Image size: {file_size:,} bytes ({file_size / (1024**3):.2f} GiB)")
            self.notifier.show(f"✓ {clean_name} loaded", notification_type="success", duration=3000)
            event.acceptProposedAction()
        else:
            event.ignore()


    def browse_file(self):
        file_name, _ = QFileDialog.getOpenFileName(
            self,
            self._T.get("dlg_select_image_title", "Select Image"),
            "",
            self._T.get("dlg_select_image_filter", "Disk Images (*.iso *.dmg *.img *.bin *.raw);;All Files (*)"),
        )
        if file_name:
            file_size = os.path.getsize(file_name)
            states.iso_path = file_name
            clean_name = file_name.split("/")[-1].split("\\")[-1]
            self.combo_boot.setItemText(0, clean_name)
            self.input_label.setText(clean_name.split(".")[0].upper())
            self.log_message(f"Image selected: {file_name}")
            self.log_message(f"Image size: {file_size:,} bytes ({file_size / (1024**3):.2f} GiB)")


    def show_log(self):
        if self.log_window is None:
            self.log_window = LogWindow(self)
        self.log_window.log_text.setPlainText("\n".join(self.log_entries))
        self.log_window.show()
        self.log_window.raise_()
        self.log_window.activateWindow()
        scrollbar = self.log_window.log_text.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def log_message(self, msg, level="INFO"):
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        entry = f"[{timestamp}] [{level}] {msg}"
        self.log_entries.append(entry)
        if self.log_window is not None:
            self.log_window.log_text.append(entry)
            scrollbar = self.log_window.log_text.verticalScrollBar()
            scrollbar.setValue(scrollbar.maximum())

    def show_about(self):
        if self.about_window is None:
            self.about_window = AboutWindow(self)
            self.about_window.about_text.setPlainText(
                self._T.get("about_content", "lufus - USB Flash Tool")
            )
        self.about_window.show()
        self.about_window.raise_()
        self.about_window.activateWindow()

    def show_settings(self):
        dlg = SettingsDialog(self)
        dlg.language_changed.connect(self.apply_language)
        dlg.exec()

    def apply_language(self, language):
        self.current_language = language
        states.language = language
        self._T = load_translations(language)
        self._update_ui_text()
        self.log_message(f"Language changed to: {language}")

    def _update_ui_text(self):
        self.setWindowTitle(self._T.get("window_title", "lufus"))
        self.lbl_device.setText(self._T.get("lbl_device", "Device"))
        self.lbl_boot.setText(self._T.get("lbl_boot_selection", "Boot Selection"))
        self.btn_select.setText(self._T.get("btn_select", "Select"))
        self.lbl_image.setText(self._T.get("lbl_image_option", "Image Option"))
        self.lbl_part.setText(self._T.get("lbl_partition_scheme", "Partition Scheme"))
        self.lbl_target.setText(self._T.get("lbl_target_system", "Target System"))
        self.lbl_vol.setText(self._T.get("lbl_volume_label", "Volume Label"))
        self.lbl_fs.setText(self._T.get("lbl_file_system", "File System"))
        self.lbl_flash.setText(self._T.get("lbl_flash_option", "Flash Option"))
        self.lbl_cluster.setText(self._T.get("lbl_cluster_size", "Cluster Size"))
        self.chk_quick.setText(self._T.get("chk_quick_format", "Quick Format"))
        self.chk_extended.setText(self._T.get("chk_extended_label", "Create Extended Label"))
        self.chk_badblocks.setText(self._T.get("chk_bad_blocks", "Check for Bad Blocks"))
        self.btn_start.setText(self._T.get("btn_start", "Start"))
        self.btn_cancel.setText(self._T.get("btn_cancel", "Cancel"))
        self.statusBar.showMessage(self._T.get("status_ready", "Ready"), 0)
        if self.log_window:
            self.log_window.setWindowTitle(self._T.get("log_window_title", "Log Window"))
        if self.about_window:
            self.about_window.setWindowTitle(self._T.get("about_window_title", "About"))
            self.about_window.about_text.setPlainText(self._T.get("about_content", "lufus - USB Flash Tool"))
        self._update_flashing_options()


    def get_selected_mount_path(self) -> str:
        text = self.combo_device.currentText()
        if "(" in text and ")" in text:
            return text.split("(")[1].split(")")[0].strip()
        return ""


    def cancel_process(self):
        reply = QMessageBox.question(
            self,
            self._T.get("msgbox_cancel_title", "Cancel"),
            self._T.get("msgbox_cancel_body", "Are you sure you want to cancel?"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            device_node = self.get_selected_mount_path()
            self.log_message(f"Cancellation requested for device {device_node}", level="WARN")

            try:
                lsof = subprocess.run(["lsof", device_node], capture_output=True, text=True)
                if lsof.returncode == 0:
                    self.log_message(f"Processes using {device_node} before kill:\n{lsof.stdout}")
            except Exception as e:
                self.log_message(f"Could not run lsof: {e}")

            if self.flash_worker and self.flash_worker.isRunning():
                self.log_message("Terminating flash worker", level="WARN")
                self.flash_worker.terminate()
                if not self.flash_worker.wait(3000):
                    self.log_message("Flash worker did not stop, forcing quit", level="WARN")
                    self.flash_worker.quit()
                    self.flash_worker.wait(2000)

            try:
                subprocess.run(["fuser", "-k", device_node], timeout=5, check=False)
                self.log_message("fuser -k executed")
            except Exception as e:
                self.log_message(f"fuser fallback failed: {e}")
            
            if hasattr(self, "verify_worker") and self.verify_worker and self.verify_worker.isRunning():
                self.log_message("Terminating verify worker", level="WARN")
                self.verify_worker.terminate()
                self.verify_worker.wait(2000)
                self.log_message("Verify worker terminated")
            
            if self.is_terminal:
                try:
                    subprocess.run(["stty", "sane"], timeout=1, check=False)
                    self.log_message("Terminal reset to sane state")
                except Exception as e:
                    self.log_message(f"Failed to reset terminal: {e}")

            self.progress_bar.setValue(0)
            self.progress_bar.setFormat("")
            self.btn_start.setEnabled(True)
            self.btn_cancel.setEnabled(False)
            self.statusBar.showMessage(self._T.get("status_ready", "Ready"), 0)
            self.log_message("Flash process cancelled by user", level="WARN")    

    def start_process(self):
        states.DN = self.combo_device.currentData() or ""
        self.log_message(
            f"Start process triggered: image_option={states.image_option}, flash_mode={states.currentflash}, device={states.DN}"
        )

        if states.image_option in [0, 1, 2]:
            if not getattr(states, "iso_path", "") or not Path(states.iso_path).exists():
                self.log_message("Start aborted: no valid image path set", level="WARN")
                QMessageBox.warning(self, self._T.get("msgbox_no_image_title", "No Image"),
                                    self._T.get("msgbox_no_image_body", "Please select an image file"))
                return

            device_node = self.get_selected_mount_path()
            if not device_node:
                self.log_message("Start aborted: no USB device selected", level="WARN")
                QMessageBox.warning(self, self._T.get("msgbox_no_device_title", "No Device"),
                                    self._T.get("msgbox_no_device_body", "Please select a USB device"))
                return

        if states.image_option in [0, 1, 2] and states.verify_hash:
            h = states.expected_hash.strip().lower()
            if len(h) != 64 or not all(c in "0123456789abcdef" for c in h):
                self.log_message("Start aborted: invalid SHA256 hash format", level="WARN")
                QMessageBox.warning(self, self._T.get("msgbox_invalid_hash_title", "Invalid Hash"),
                                    self._T.get("msgbox_invalid_hash_body", "The provided SHA256 hash is invalid."))
                return

            self.btn_start.setEnabled(False)
            self.btn_cancel.setEnabled(True)
            self.progress_bar.setValue(0)
            self.progress_bar.setFormat(self._T.get("progress_verifying", "Verifying..."))

            self.verify_worker = VerifyWorker(states.iso_path, states.expected_hash)
            self.verify_worker.progress.connect(self.log_message)
            self.verify_worker.finished.connect(self.on_verify_finished)
            self.verify_worker.start()
        else:
            self.perform_flash()

    def on_verify_finished(self, success: bool):
        if success:
            self.log_message("SHA256 verification successful, proceeding to flash")
            self.perform_flash()
        else:
            self.log_message("SHA256 verification FAILED", level="ERROR")
            QMessageBox.critical(self, self._T.get("msgbox_verify_fail_title", "Verification Failed"),
                                 self._T.get("msgbox_verify_fail_body", "SHA256 checksum mismatch!"))
            self.btn_start.setEnabled(True)
            self.btn_cancel.setEnabled(False)
            self.progress_bar.setValue(0)
            self.progress_bar.setFormat("")

    def perform_flash(self):
        options = {
            "iso_path": states.iso_path,
            "device": self.get_selected_mount_path(),
            "image_option": states.image_option,
            "currentflash": states.currentflash,
            "currentFS": states.currentFS,
            "partition_scheme": states.partition_scheme,
            "target_system": states.target_system,
            "cluster_size": states.cluster_size,
            "QF": states.QF,
            "create_extended": states.create_extended,
            "check_bad": states.check_bad,
            "new_label": states.new_label,
            "verify_hash": states.verify_hash,
            "expected_hash": states.expected_hash,
        }

        self.log_message(f"Starting flash thread: image_option={options['image_option']}, flash_mode={options['currentflash']}, device={options['device']}")

        self.flash_worker = FlashWorker(options)
        self.flash_worker.progress.connect(self.progress_bar.setValue, Qt.ConnectionType.QueuedConnection)
        self.flash_worker.status.connect(self._on_flash_status, Qt.ConnectionType.QueuedConnection)
        self.flash_worker.flash_done.connect(self.on_flash_finished, Qt.ConnectionType.QueuedConnection)
        self.flash_worker.start()

        self.btn_start.setEnabled(False)
        self.btn_cancel.setEnabled(True)
        self.progress_bar.setValue(0)
        self.statusBar.showMessage(self._T.get("status_flashing", "Flashing..."), 0)
    
    def _on_flash_status(self, msg):
        self.log_message(msg)
        self.statusBar.showMessage(msg, 0)

    def on_flash_finished(self, success: bool):
        if self.flash_worker is not None:
            self.flash_worker.wait()
        if success:
            self.progress_bar.setValue(100)
            self.progress_bar.setFormat(self._T.get("progress_complete", "Complete"))
            self.log_message("Flash operation finished with result: SUCCESS")
            QMessageBox.information(
                self,
                self._T.get("msgbox_success_title", "Success"),
                self._T.get("msgbox_success_body", "Flash completed successfully"),
            )
        else:
            self.progress_bar.setFormat(self._T.get("progress_failed", "Failed"))
            self.log_message("Flash operation finished with result: FAILED", level="ERROR")
            QMessageBox.critical(
                self,
                self._T.get("msgbox_error_title", "Error"),
                self._T.get("msgbox_error_body", "Flash failed"),
            )

        self.btn_start.setEnabled(True)
        self.btn_cancel.setEnabled(False)
        self.statusBar.showMessage(self._T.get("status_ready", "Ready"), 0)


    def keyPressEvent(self, event):
        if (event.key() == Qt.Key.Key_R
                and event.modifiers() == Qt.KeyboardModifier.ControlModifier):
            self.refresh_usb_devices()
        elif event.key() == Qt.Key.Key_F5:
            self.refresh_usb_devices()
        super().keyPressEvent(event)

    def position_notification(self):
        if self.parent():
            parent_rect = self.parent().geometry()
            x = parent_rect.right()  - self.width()  - 20
            y = parent_rect.bottom() - self.height() - 20
            self.move(x, y)
        else:
            screen = QApplication.primaryScreen().geometry()
            x = screen.right()  - self.width()  - 20
            y = screen.bottom() - self.height() - 20
            self.move(x, y)

    def check_polkit_agent(self):
        """Check if a Polkit authentication agent is running.
        Returns True if found, False otherwise."""        
        try:
            # Common agent process names
            agents = [
                "polkit-gnome-authentication-agent-1",
                "polkit-kde-authentication-agent-1",
                "lxqt-policykit-agent",
                "mate-polkit",
                "polkit-1-agent"
            ]
            # Use pgrep to search for any of these
            for agent in agents:
                result = subprocess.run(["pgrep", "-f", agent], capture_output=True)
                if result.returncode == 0:
                    return True
            return False
        except Exception:
            # If pgrep fails, assume agent might be present (better to try)
            return True




if __name__ == "__main__":
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    usb_devices = {}
    if len(sys.argv) > 1:
        try:
            decoded_data = urllib.parse.unquote(sys.argv[1])
            usb_devices = json.loads(decoded_data)
            print("Successfully parsed USB devices:", usb_devices)
        except Exception as e:
            print(f"Error parsing USB devices: {e}")

    window = lufus(usb_devices)
    window.show()
    sys.exit(app.exec())
