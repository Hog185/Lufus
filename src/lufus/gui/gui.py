import subprocess
import sys
import tempfile
import json
import os
import csv
import platform
import getpass
from typing import Dict, Any
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
    QScrollArea,
)
from PyQt6.QtCore import (
    Qt,
    QTimer,
    QThread,
    QObject,
    pyqtSignal,
    QPropertyAnimation,
)
from PyQt6.QtGui import QFont, QFontDatabase
from lufus.drives import states
from lufus.drives.autodetect_usb import UsbMonitor
from lufus.lufus_logging import get_logger

# themes live here :3
THEME_DIR = Path(__file__).parent / 'themes'


def _find_resource_dir(name: str) -> Path | None:
    # look for resource directories like languages or themes
    candidate = Path(__file__).parent / name
    return candidate if candidate.is_dir() else None

class Scale:
    # base dpi for scaling calculations :D
    BASE_DPI = 80.0
    DESIGN_W = 750
    DESIGN_H = 1050
    REF_W = 2560
    REF_H = 1440

    def __init__(self, app: QApplication, factor: float = None):
        # get screen info for scaling
        screen = app.primaryScreen()
        logical_dpi = screen.logicalDotsPerInch()
        device_ratio = screen.devicePixelRatio()

        if factor is not None:
            # use custom factor if provided :3
            self._factor = max(factor, 0.3)
        else:
            # calculate factor from dpi
            self._factor = max(logical_dpi / self.BASE_DPI, 0.75)

        print(
            f"[Scale] logicalDPI={logical_dpi:.1f}  DevicePixelRatio={device_ratio:.2f}"
            f"  → scale factor={self._factor:.3f}"
        )

    def f(self) -> float:
        # return raw factor
        return self._factor

    def px(self, base_pixels: int | float) -> int:
        # scale pixels based on factor
        return max(1, round(base_pixels * self._factor))

    def pt(self, base_points: int | float) -> int:
        # scale font points based on factor :D
        return max(6, round(base_points * self._factor))


def load_translations(language="English"):
    # load language csv files for localization
    lang_dir = _find_resource_dir("languages")
    t = {}
    if lang_dir is None:
        return t
    lang_file = lang_dir / f"{language}.csv"
    if lang_file.exists():
        # read translations from csv :3
        with open(lang_file, encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f):
                t[row["key"]] = row["value"]
    return t


class StdoutRedirector:
    def __init__(self, log_fn):
        # redirect stdout to log window
        self._log_fn = log_fn
        self._real_stdout = sys.stdout
        self._buf = ""

    def write(self, text):
        # write to real stdout and buffer for logging :D
        self._real_stdout.write(text)
        self._buf += text
        while "\n" in self._buf:
            # split by newlines and log each line
            line, self._buf = self._buf.split("\n", 1)
            line = line.rstrip()
            if line:
                self._log_fn(line)

    def flush(self):
        # flush the real stdout
        self._real_stdout.flush()

    def fileno(self):
        # return real stdout file descriptor
        return self._real_stdout.fileno()

    def isatty(self):
        # not a tty when redirected
        return False


class LogWindow(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        # grab translations and scale from parent :3
        self._T = parent._T if parent else {}
        self._S: Scale = parent._S if parent else None
        self.setWindowTitle(self._T.get("log_window_title", "Log Window"))

        if self._S:
            # apply scaled dimensions
            self.resize(self._S.px(650), self._S.px(450))
        else:
            self.resize(650, 450)

        layout = QVBoxLayout()
        # create readonly text widget for log display
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        font_size = self._S.pt(9) if self._S else 9
        self.log_text.setFont(QFont("Consolas", font_size))
        self.log_text.setStyleSheet("background-color: palette(base); color: palette(text); border: 1px solid palette(mid);")
        layout.addWidget(self.log_text)

        # add copy and save buttons
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
        # hide instead of closing
        event.ignore()
        self.hide()

    def _copy_log(self):
        # copy log text to clipboard
        QApplication.clipboard().setText(self.log_text.toPlainText())

    def _save_log(self):
        # show save dialog and write log to file
        path, _ = QFileDialog.getSaveFileName(
            self,
            self._T.get("dlg_save_log_title", "Save Log"),
            "lufus_log.txt",
            "Text Files (*.txt);;All Files (*)",
        )
        if path:
            try:
                # write log contents to chosen file :D
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
        # create floating notification widget :3
        self._S = scale
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        # color scheme for different notification types
        colors = {
            "info": "#6e6e6e",
            "success": "#5a5a5a",
        }

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # calculate scaled padding and radius :D
        pad_v  = self._S.px(15) if self._S else 15
        pad_h  = self._S.px(25) if self._S else 25
        radius = self._S.px(8)  if self._S else 8
        fsize  = self._S.pt(11) if self._S else 11

        # create label with styled background
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

        # fade in animation :3
        self.fade_in = QPropertyAnimation(self, b"windowOpacity")
        self.fade_in.setDuration(200)
        self.fade_in.setStartValue(0.0)
        self.fade_in.setEndValue(1.0)

        # position and show notification
        self.adjustSize()
        self.position_notification()
        self.show()
        self.fade_in.start()

        # auto hide after duration
        self.timer = QTimer()
        self.timer.timeout.connect(self.fade_out)
        self.timer.setSingleShot(True)
        self.timer.start(duration)

    def fade_out(self):
        # fade out animation then close :D
        self.fade_out_anim = QPropertyAnimation(self, b"windowOpacity")
        self.fade_out_anim.setDuration(200)
        self.fade_out_anim.setStartValue(1.0)
        self.fade_out_anim.setEndValue(0.0)
        self.fade_out_anim.finished.connect(self.close)
        self.fade_out_anim.start()

    def position_notification(self, index=0):
        # position notification at bottom right of screen or parent
        screen = QApplication.primaryScreen().availableGeometry()

        if self.parent() and isinstance(self.parent(), QWidget):
            # position relative to parent window if available :3
            parent_geo = self.parent().frameGeometry()
            if screen.contains(parent_geo.topLeft()):
                x = parent_geo.right() - self.width() - 20
                y = parent_geo.bottom() - (self.height() + 10) * (index + 1) - 20
                self.move(int(x), int(y))
                return

        # fallback to screen positioning
        x = screen.right() - self.width() - 20
        y = screen.bottom() - (self.height() + 10) * (index + 1) - 20
        self.move(int(x), int(y))


class NotificationManager:
    def __init__(self, parent=None, scale: Scale = None):
        # manage multiple notification widgets :D
        self.parent = parent
        self._S = scale
        self.notifications = []

    def show(self, message, notification_type="info", duration=3000):
        # create and show new notification
        notification = Notification(
            message, notification_type, duration, self.parent, scale=self._S
        )
        self.notifications.append(notification)
        # position based on existing notifications
        notification.position_notification(len(self.notifications) - 1)
        notification.show()
        # remove from list when destroyed
        notification.destroyed.connect(
            lambda: self.notifications.remove(notification)
            if notification in self.notifications else None
        )


class AboutWindow(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        # about dialog with app info :D
        self.parent_window = parent
        self._T = parent._T if parent else {}
        self._S: Scale = parent._S if parent else None
        self.setWindowTitle(self._T.get("about_window_title", "About"))

        if self._S:
            # apply scaled size
            self.resize(self._S.px(480), self._S.px(360))
        else:
            self.resize(480, 360)

        m = self._S.px(24) if self._S else 24
        layout = QVBoxLayout()
        layout.setContentsMargins(m, m, m, m)
        layout.setSpacing(self._S.px(10) if self._S else 10)

        # main title label :3
        lbl_title = QLabel("lufus")
        title_font_size = self._S.pt(20) if self._S else 20
        lbl_title.setFont(QFont("Sans Serif", title_font_size, QFont.Weight.Bold))
        lbl_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(lbl_title)

        # subtitle label
        lbl_sub = QLabel(self._T.get("about_subtitle", "USB Flash Tool"))
        sub_font_size = self._S.pt(10) if self._S else 10
        lbl_sub.setFont(QFont("Sans Serif", sub_font_size))
        lbl_sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl_sub.setObjectName("aboutSubtitle")
        layout.addWidget(lbl_sub)

        # horizontal separator line :D
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setFrameShadow(QFrame.Shadow.Sunken)
        layout.addWidget(sep)

        # content text area
        self.about_text = QTextEdit()
        self.about_text.setReadOnly(True)
        self.about_text.setFrameShape(QFrame.Shape.NoFrame)
        content_font_size = self._S.pt(9) if self._S else 9
        self.about_text.setFont(QFont("Sans Serif", content_font_size))
        layout.addWidget(self.about_text, 1)

        # close button at bottom :3
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_close = QPushButton(self._T.get("btn_close", "Close"))
        btn_close.setFixedWidth(self._S.px(90) if self._S else 90)
        btn_close.clicked.connect(self.hide)
        btn_row.addWidget(btn_close)
        layout.addLayout(btn_row)

        self.setLayout(layout)


class SettingsDialog(QDialog):
    # signals for when settings change :D
    language_changed = pyqtSignal(str)
    theme_changed = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        # settings dialog for language and theme selection
        self._T = parent._T if parent else {}
        self._S: Scale = parent._S if parent else None
        self.setWindowTitle(self._T.get("settings_window_title", "Settings"))
        if self._S:
            self.setFixedSize(self._S.px(750), self._S.px(450))
        else:
            self.setFixedSize(650, 450)
        m = self._S.px(20) if self._S else 20
        layout = QVBoxLayout()
        layout.setContentsMargins(m, m, m, m)
        layout.setSpacing(self._S.px(10) if self._S else 10)

        # language selector :3
        lbl_lang = QLabel(self._T.get("settings_label_language", "Language"))
        lbl_lang.setStyleSheet("font-weight: normal;")
        self.combo_language = QComboBox()
        languages = self._detect_languages()
        if languages:
            # populate with available languages
            self.combo_language.addItems(languages)
            current_lang = states.language if hasattr(states, "language") else "English"
            if current_lang in languages:
                self.combo_language.setCurrentText(current_lang)
        else:
            self.combo_language.addItem(self._T.get("settings_no_languages", "No languages found"))
            self.combo_language.setEnabled(False)
        layout.addWidget(lbl_lang)
        layout.addWidget(self.combo_language)

        # theme selector :D
        lbl_theme = QLabel(self._T.get("settings_label_theme", "Theme"))
        lbl_theme.setStyleSheet("font-weight: normal;")
        self.combo_theme = QComboBox()
        builtin, custom = self._detect_themes()
        # add builtin and custom themes
        self.combo_theme.addItems(builtin)
        self.combo_theme.addItems(custom)
        current_theme = getattr(states, "Theme", "Default")
        for i in range(self.combo_theme.count()):
            # select current theme
            if self.combo_theme.itemText(i) == current_theme:
                self.combo_theme.setCurrentIndex(i)
                break
        layout.addWidget(lbl_theme)
        layout.addWidget(self.combo_theme)

        layout.addStretch()
        # ok button to apply canges :3
        btn_ok = QPushButton("OK")
        btn_ok.clicked.connect(self._on_ok_clicked)
        layout.addWidget(btn_ok)
        self.setLayout(layout)

    def _on_ok_clicked(self):
        # emit signals when settings are changed :D
        language = self.combo_language.currentText()
        if language != "No languages found":
            self.language_changed.emit(language)
        theme = self.combo_theme.currentText()
        if not theme.startswith("──"):
            self.theme_changed.emit(theme)
        self.accept()

    @staticmethod
    def _detect_languages():
        # find all available language csv files
        lang_dir = _find_resource_dir("languages")
        if lang_dir is None:
            return []
        return sorted(p.stem for p in lang_dir.glob("*.csv"))

    @staticmethod
    def _detect_themes():
        # find builtin and user custom themes :3
        builtin = sorted(
            p.stem.replace('_theme', '')
            for p in THEME_DIR.glob('*_theme.json')
        )
        user_themes_dir = Path(user_config_dir("Lufus")) / "themes"
        user_themes_dir.mkdir(parents=True, exist_ok=True)
        custom = sorted(
            p.stem.replace('_theme', '')
            for p in user_themes_dir.glob('*_theme.json')
        )
        return builtin, custom


class VerifyWorker(QThread):
    # worker thread for sha256 verification :D
    progress = pyqtSignal(str)
    verify_done = pyqtSignal(bool)

    def __init__(self, iso_path: str, expected_hash: str):
        super().__init__()
        # store paths for verification
        self.iso_path = iso_path
        self.expected_hash = expected_hash

    def run(self):
        # run verification in background thread :3
        try:
            from lufus.writing.check_file_sig import check_sha256
            self.progress.emit(f"Verifying SHA256 checksum for {self.iso_path}...")
            result = check_sha256(self.iso_path, self.expected_hash)
            self.verify_done.emit(result)
        except Exception as e:
            self.progress.emit(f"Verification error: {str(e)}")
            self.flash_done.emit(False)


class FlashWorker(QThread):
    # worker thread for usb flashing operation meow
    progress = pyqtSignal(int)
    status = pyqtSignal(str)
    flash_done = pyqtSignal(bool)

    def __init__(self, options: dict):
        super().__init__()
        # store options for flashing
        self.options = options

    def run(self):
        # run flash operation in background thread
        _saved_stdout = sys.stdout
        sys.stdout = sys.__stdout__
        try:
            from lufus.drives import states, formatting as fo
            from lufus.writing.flash_usb import FlashUSB
            import glob

            options = self.options
            # apply options to states :3
            for key, value in options.items():
                setattr(states, key, value)

            device_node = options["device"]
            iso_path = options["iso_path"]
            flash_mode = options["currentflash"]
            image_option = options["image_option"]

            # unmount all partitions before flashing :D
            self.status.emit(f"Unmounting all partitions on {device_node}...")
            partitions = glob.glob(f"{device_node}*")
            for part in partitions:
                self.status.emit(f"Unmounting {part}...")
                fo.unmount(part)

            # perform flash based on mode
            if image_option == 0:
                if flash_mode == 0:
                    # iso mode for microslop windows
                    success = FlashUSB(iso_path, device_node,
                                       progress_cb=self.progress.emit,
                                       status_cb=self.status.emit)
                else:
                    success = False
            else:
                # other flash modes
                success = FlashUSB(iso_path, device_node,
                                   progress_cb=self.progress.emit,
                                   status_cb=self.status.emit)

            self.flash_done.emit(bool(success))
        except Exception as e:
            self.status.emit(f"Flash error: {e}")
            self.flash_done.emit(False)
        finally:
            # restore stdout :D
            sys.stdout = _saved_stdout


# log level mapping for colors and methods
_LOG_LEVELS = {
    "DEBUG":    ("debug",    "#888888"),
    "INFO":     ("info",     None),
    "WARN":     ("warning",  "#f0a500"),
    "WARNING":  ("warning",  "#f0a500"),
    "ERROR":    ("error",    "#e05555"),
    "CRITICAL": ("critical", "#e05555"),
}


class lufus(QMainWindow):
    def __init__(self, usb_devices=None, scale: Scale = None):
        super().__init__()
        # main window initialization :3
        self._logger = get_logger("gui")

        # setup usb monitoring
        self.usb_devices = usb_devices or {}
        self.monitor = UsbMonitor()
        self.monitor.device_added.connect(self.on_usb_added)
        self.monitor.device_list_updated.connect(self.update_usb_list)

        # load translations :D
        self.current_language = getattr(states, "language", "English")
        self._T = load_translations(self.current_language)

        self.setWindowTitle(self._T.get("window_title", "lufus"))

        # calculate window size based on screen dimensions
        screen = QApplication.primaryScreen().availableGeometry()
        scale = min(screen.width() / Scale.REF_W, screen.height() / Scale.REF_H)
        win_w = min(int(Scale.DESIGN_W * scale), int(screen.width() * 1.2))
        win_h = min(int(Scale.DESIGN_H * scale), int(screen.height() * 1.2))
        ui_factor = win_w / Scale.DESIGN_W
        self._S = Scale(QApplication.instance(), factor=ui_factor)
        self.setFixedSize(win_w, win_h)#oink

        # initialize worker threads and windows :3
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

        # redirect stdout to log :D
        sys.stdout = StdoutRedirector(self.log_message)

        # build ui and apply styles
        self.init_ui()
        self._apply_styles()
        QTimer.singleShot(0, self._apply_styles)
        self.update_usb_list(self.monitor.devices)
        self.setAcceptDrops(True)
        self.notifier = NotificationManager(self, scale=self._S)

        # start clipboard monitoring :3
        self._clipboard_timer = QTimer(self)
        self._clipboard_timer.timeout.connect(self._check_clipboard)
        self._clipboard_timer.start(500)

        # log startup info :D
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
        # load json values apply via qss all that yap is in the themes folder :3
        S = self._S
        APP_NAME = "Lufus"
        theme_dir = Path(__file__).parent / 'themes'
        default_theme_path = theme_dir / 'default_theme.json'
        template_path = theme_dir / 'style_template.qss'
        user_config_dir_path = Path(user_config_dir(APP_NAME, roaming=True))
        user_theme_path = user_config_dir_path / 'user_theme.json'

        try:
            # load default theme json :D
            with open(default_theme_path, 'r', encoding='utf-8') as fr:
                theme = json.load(fr)
        except FileNotFoundError:
            print("WARNING: no theme applied, json didn't load up in _apply_styles, gui.py.")
            return

        if os.path.exists(user_theme_path):
            try:
                # merge user theme overrides
                with open(user_theme_path, 'r', encoding='utf-8') as fr:
                    user_theme = json.load(fr)
                for category in ['colors', 'fonts', 'dimensions']:
                    if category in user_theme and isinstance(user_theme[category], dict):
                        theme[category].update(user_theme[category])
            except Exception as e:
                print(f"Error loading user theme: {e}")

        # check if gradients are enabled :3
        use_gradient = int(theme['dimensions'].get('use_gradient', 1))

        # keys that dont need scaling
        NO_SCALE_KEYS = {'use_gradient', 'btn_border_width', 'combo_border_width'}
        NO_SCALE_FONT_KEYS = {'family'}

        # create scaled theme dict :D
        scaled_theme = {
            'colors': theme['colors'].copy(),
            'fonts': {},
            'dimensions': {}
        }

        # scale font sizes
        for key, value in theme['fonts'].items():
            if key in NO_SCALE_FONT_KEYS:
                scaled_theme['fonts'][key] = value
            else:
                scaled_theme['fonts'][key] = S.pt(value)

        # scale dimensions :3
        for key, value in theme['dimensions'].items():
            scaled_theme['dimensions'][key] = value if key in NO_SCALE_KEYS else S.px(value)

        # flatten theme dict for template substitution
        flat_theme: Dict[str, Any] = {}
        for category, subdict in scaled_theme.items():
            for key, val in subdict.items():
                flat_theme[f"{category}_{key}"] = val

        try:
            # load qss template 
            with open(template_path, 'r', encoding='utf-8') as f:
                template = f.read()
        except FileNotFoundError: # (╯°□°)╯( ┻━┻
            print("Error: style_template.qss not found.")
            return

        if not use_gradient:
            # replace gradient rules with solid colors when disabled
            template = re.sub(
                r"background:\s*qlineargradient\(\s*x1:0,\s*y1:0,\s*x2:0,\s*y2:1,\s*"
                r"stop:0\s*\{colors_input_bg_top\},\s*stop:1\s*\{colors_input_bg\}\s*\)",
                "background-color: {colors_input_bg}",
                template, flags=re.MULTILINE,
            )
            template = re.sub(
                r"background:\s*qlineargradient\(\s*x1:0,\s*y1:0,\s*x2:0,\s*y2:1,\s*"
                r"stop:0\s*\{colors_button_bg_top\},\s*stop:1\s*\{colors_button_bg\}\s*\)",
                "background-color: {colors_button_bg}",
                template, flags=re.MULTILINE,
            )
            template = re.sub(
                r"background:\s*qlineargradient\(\s*x1:0,\s*y1:0,\s*x2:0,\s*y2:1,\s*"
                r"stop:0\s*\{colors_button_hover_bg_top\},\s*stop:1\s*\{colors_button_hover_bg\}\s*\)",
                "background-color: {colors_button_hover_bg}",
                template, flags=re.MULTILINE,
            )
            template = re.sub(
                r"background:\s*qlineargradient\(\s*x1:0,\s*y1:0,\s*x2:0,\s*y2:1,\s*"
                r"stop:0\s*\{colors_tool_button_bg_top\},\s*stop:1\s*\{colors_tool_button_bg\}\s*\)",
                "background-color: {colors_tool_button_bg}",
                template, flags=re.MULTILINE,
            )

        # apply template and set stylesheet
        self._flat_theme = flat_theme
        style_sheet = template.format(**flat_theme)
        self.setStyleSheet(style_sheet)

    def create_header(self, text):
        # create section header with horizontal line :3
        layout = QHBoxLayout()
        layout.setContentsMargins(0, self._S.px(4), 0, self._S.px(2))
        label = QLabel(text)
        label.setObjectName("sectionHeader")
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        line.setStyleSheet(
            "background-color: palette(mid); min-height: 1px; max-height: 1px;"
        )
        layout.addWidget(label)
        layout.addWidget(line, 1)
        return layout


    def update_usb_list(self, devices: dict):
        # update device dropdown with current usb devices
        self.combo_device.clear()
        self.usb_devices = devices

        if not devices:
            # show no devices message
            self.combo_device.addItem(self._T.get("no_usb_found", "No USB devices found"), None)
            return

        # add each device to combo
        for node, label in devices.items():
            display = f"{label} ({node})" if label != node else node
            self.combo_device.addItem(display, node)

    def on_usb_added(self, node):
        # handle new usb device detection :3
        self.log_message(f"USB device connected: {node}")
        self.notifier.show(f"✓ {node} connected", notification_type="success", duration=3000)

    def init_ui(self):
        # build main user interface :D
        S = self._S
        FIELD_SPACING = S.px(2)
        GROUP_SPACING = S.px(5)

        # create central widget with scroll area
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
        main_layout.setSpacing(S.px(3))
        m = S.px(15)
        main_layout.setContentsMargins(m, S.px(5), m, S.px(5))

        scroll.setWidget(scroll_content)
        outer_layout.addWidget(scroll)

        # drive properties section :3
        main_layout.addLayout(
            self.create_header(self._T.get("header_drive_properties", "Drive Properties"))
        )
        main_layout.addSpacing(S.px(4))

        # device selector with refresh button
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

        # boot selection with file browser :D
        self.lbl_boot = QLabel(self._T.get("lbl_boot_selection", "Boot Selection"))
        self.combo_boot = QComboBox()
        self.combo_boot.setEditable(True)
        self.combo_boot.lineEdit().setReadOnly(True)
        self.combo_boot.addItem(self._T.get("combo_boot_default", "installation_media.iso"))

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

        # image option selector :3
        self.lbl_image = QLabel(self._T.get("lbl_image_option", "Image Option"))
        self.combo_image_option = QComboBox()
        self.combo_image_option.addItem(self._T.get("combo_image_windows", "Windows"))
        self.combo_image_option.addItem(self._T.get("combo_image_linux", "Linux"))
        self.combo_image_option.addItem(self._T.get("combo_image_other", "Other"))
        self.combo_image_option.addItem(self._T.get("combo_image_format", "Format Only"))
        #self.combo_image_option.addItem(self._T.get("combo_image_ventoy", "Ventoy"))
        self.combo_image_option.currentTextChanged.connect(self.update_image_option)

        image_layout = QVBoxLayout()
        image_layout.setSpacing(FIELD_SPACING)
        image_layout.addWidget(self.lbl_image)
        image_layout.addWidget(self.combo_image_option)
        main_layout.addLayout(image_layout)
        main_layout.addSpacing(GROUP_SPACING)

        # partition and target system selectors commented out :D
        #self.lbl_part = QLabel(self._T.get("lbl_partition_scheme", "Partition Scheme"))
        #self.combo_partition = QComboBox()
        #self.combo_partition.addItem(self._T.get("combo_partition_gpt", "GPT"))
        #self.combo_partition.addItem(self._T.get("combo_partition_mbr", "MBR"))
        #self.combo_partition.currentTextChanged.connect(self.update_partition_scheme)

        #self.lbl_target = QLabel(self._T.get("lbl_target_system", "Target System"))
        #self.combo_target = QComboBox()
        #self.combo_target.addItem(self._T.get("combo_target_uefi", "UEFI"))
        #self.combo_target.addItem(self._T.get("combo_target_bios", "BIOS"))
        #self.combo_target.currentTextChanged.connect(self.update_target_system)

        grid_part = QGridLayout()
        grid_part.setHorizontalSpacing(S.px(10))
        grid_part.setVerticalSpacing(FIELD_SPACING)
        grid_part.setColumnStretch(0, 1)
        grid_part.setColumnStretch(1, 1)
        #grid_part.addWidget(self.lbl_part, 0, 0)
        #grid_part.addWidget(self.combo_partition, 1, 0)
        #grid_part.addWidget(self.lbl_target, 0, 1)
        #grid_part.addWidget(self.combo_target, 1, 1)
        main_layout.addLayout(grid_part)

        main_layout.addSpacing(S.px(6))

        # format options section :3
        main_layout.addLayout(
            self.create_header(self._T.get("header_format_options", "Format Options"))
        )
        main_layout.addSpacing(S.px(4))

        # volume label input field
        self.lbl_vol = QLabel(self._T.get("lbl_volume_label", "Volume Label"))
        self.input_label = QLineEdit()
        self.input_label.setPlaceholderText(self._T.get("lbl_volume_label", "Volume Label"))
        self.input_label.textChanged.connect(self.update_new_label)

        vol_layout = QVBoxLayout()
        vol_layout.setSpacing(FIELD_SPACING)
        vol_layout.addWidget(self.lbl_vol)
        vol_layout.addWidget(self.input_label)
        main_layout.addLayout(vol_layout)
        main_layout.addSpacing(GROUP_SPACING)

        # filesystem cluster and flash option selectors :D
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
            #self._T.get("combo_flash_ventoy", "Ventoy"),
            self._T.get("combo_flash_dd",     "DD"),
        ]
        self.combo_flash.addItems(self.all_flash_options)
        self.combo_flash.currentTextChanged.connect(self.updateflash)

        # grid layout for format options :3
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

        # checkboxes for format options :D
        self.chk_quick = QCheckBox(self._T.get("chk_quick_format", "Quick Format"))
        self.chk_quick.setChecked(True)
        self.chk_quick.stateChanged.connect(self.update_QF)

        self.chk_extended = QCheckBox(self._T.get("chk_extended_label", "Create Extended Label"))
        self.chk_extended.setChecked(True)
        self.chk_extended.stateChanged.connect(self.update_create_extended)

        # bad blocks check with pass selector :3
        self.chk_badblocks = QCheckBox(self._T.get("chk_bad_blocks", "Check for Bad Blocks"))
        self.combo_badblocks = QComboBox()
        self.combo_badblocks.addItem(self._T.get("combo_badblocks_1pass", "1 Pass"))
        self.combo_badblocks.addItem(self._T.get("combo_badblocks_2pass", "2 Pass"))
        self.combo_badblocks.addItem(self._T.get("combo_badblocks_3pass", "3 Pass"))
        self.combo_badblocks.setEnabled(False)
        self.chk_badblocks.stateChanged.connect(self.update_check_bad)
        
        # sha256 verification checkbox and input :D
        self.chk_verify = QCheckBox(self._T.get("chk_verify_hash", "Verify SHA256 Checksum"))
        self.chk_verify.stateChanged.connect(self.update_verify_hash)
        self.input_hash = QLineEdit()
        self.input_hash.setPlaceholderText(self._T.get("input_hash_placeholder", "Enter expected SHA256 hash here..."))
        self.input_hash.setEnabled(False)
        self.input_hash.textChanged.connect(self.update_expected_hash)

        # layout for all checkboxes :3
        chk_layout = QVBoxLayout()
        chk_layout.setSpacing(S.px(6))
        chk_layout.addWidget(self.chk_quick)
        chk_layout.addWidget(self.chk_extended)
        chk_layout.addWidget(self.chk_badblocks)
        chk_layout.addWidget(self.combo_badblocks)
        chk_layout.addWidget(self.chk_verify)
        chk_layout.addWidget(self.input_hash)

        main_layout.addLayout(chk_layout)

        main_layout.addSpacing(S.px(6))

        # status section with progress bar :D
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

        # toolbar buttons for download about settings log :3
        btn_icon1 = QToolButton()
        btn_icon1.setText("🌐")
        btn_icon1.setToolTip(self._T.get("tooltip_download", "Download"))
        btn_icon1.clicked.connect(self._open_url)
        

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

        # start and cancel buttons :D
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

        # bottom controls layout :3
        bottom_controls = QHBoxLayout()
        bottom_controls.setContentsMargins(m, S.px(10), m, S.px(10))
        bottom_controls.setSpacing(S.px(10))
        bottom_controls.addLayout(icons_layout, 1)
        bottom_controls.addLayout(btn_layout)

        outer_layout.addLayout(bottom_controls)

        # status bar at bottom :D
        self.statusBar = QStatusBar()
        self.setStatusBar(self.statusBar)
        self.statusBar.showMessage(self._T.get("status_ready", "Ready"), 0)

    def create_refresh_button(self):
        # create refresh button for usb device list :3
        S = self._S
        size = S.px(25)
        btn = QToolButton()
        btn.setText("🔄")
        btn.setToolTip(self._T.get("tooltip_refresh", "Refresh"))
        btn.setFixedSize(size, size)
        btn.clicked.connect(self.refresh_usb_devices)
        return btn

    def _populate_device_combo(self):
        # populate device combobox with usb devices :D
        self.combo_device.blockSignals(True)
        self.combo_device.clear()

        if self.usb_devices:
            # add each device with label
            for node, label in self.usb_devices.items():
                display = f"{label} ({node})" if label != node else node
                self.combo_device.addItem(display, node)
        else:
            # show no devices found message :3
            self.combo_device.addItem(self._T.get("no_usb_found", "No USB devices found"), None)

        self.combo_device.blockSignals(False)

    def refresh_usb_devices(self):
        # scan for usb devices and update list :D
        self.statusBar.showMessage(self._T.get("status_scanning", "Scanning..."), 2000)
        self.log_message("USB device scan initiated")
        try:
            new_devices = self.monitor.devices
            self.log_message(
                f"USB scan result: {len(new_devices)} device(s) found: {list(new_devices.keys())}"
            )

            if new_devices:
                # update device list with new devices :3
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
                # no devices detected :D
                self.usb_devices = {}
                self._populate_device_combo()
                self.log_message("No USB devices detected after scan", level="WARN")
                QMessageBox.information(
                    self,
                    self._T.get("msgbox_no_devices_title", "No Devices"),
                    self._T.get("msgbox_no_devices_body", "No USB devices detected"),
                )
        except Exception as e:
            # handle scan errors :3
            self.statusBar.showMessage(self._T.get("status_scan_failed", "Scan Failed"), 3000)
            self.log_message(f"USB scan raised exception: {type(e).__name__}: {str(e)}", level="ERROR")
            QMessageBox.critical(
                self,
                self._T.get("msgbox_scan_error_title", "Scan Error"),
                f'{self._T.get("msgbox_scan_error_body", "Scan failed")}\n{str(e)}',
            )


    def updateFS(self):
        # update filesystem selection in states :D
        states.currentFS = self.combo_fs.currentIndex()
        self.log_message(f"File system changed to: {self.combo_fs.currentText()} (index={states.currentFS})")

    def updateflash(self):
        # update flash mode selection in states :3
        states.currentflash = self.combo_flash.currentIndex()
        self.log_message(f"Flash option changed to: {self.combo_flash.currentText()} (index={states.currentflash})")

    def update_image_option(self):
        # update image option and refresh available filesystems and flash modes :D
        states.image_option = self.combo_image_option.currentIndex()
        self.log_message(f"Image option changed to: {self.combo_image_option.currentText()} (index={states.image_option})")
        self._update_filesystem_options()
        self._update_flashing_options()

    def _update_filesystem_options(self):
        # change available filesystems based on image type :3
        self.combo_fs.blockSignals(True)
        if states.image_option == 1:      # linux
            self.combo_fs.clear(); self.combo_fs.addItems(["ext4", "UDF"]); self.combo_fs.setCurrentText("ext4")
        elif states.image_option == 0:    # windows
            self.combo_fs.clear(); self.combo_fs.addItems(["NTFS", "FAT32", "exFAT"]); self.combo_fs.setCurrentText("NTFS")
        elif states.image_option == 4:    # ventoy
            self.combo_fs.clear(); self.combo_fs.addItems(["exFAT", "FAT32"]); self.combo_fs.setCurrentText("exFAT")
        elif states.image_option in (2, 3):
            # other or format only :D
            self.combo_fs.clear(); self.combo_fs.addItems(self.all_fs_options); self.combo_fs.setCurrentText("FAT32")
        self.combo_fs.blockSignals(False)
        self.updateFS()

    def _update_flashing_options(self):
        # change available flash modes based on image type :3
        self.combo_flash.blockSignals(True)
        self.combo_flash.clear()
        if states.image_option == 0:      # windows
            self.combo_flash.addItems([self._T.get("combo_flash_iso", "ISO")])
            self.combo_flash.setCurrentText(self._T.get("combo_flash_iso", "ISO"))
        elif states.image_option == 1:    # linux
            self.combo_flash.addItems([self._T.get("combo_flash_dd", "DD")])
            self.combo_flash.setCurrentText(self._T.get("combo_flash_dd", "DD"))
        elif states.image_option == 2:    # other
            self.combo_flash.addItems([self._T.get("combo_flash_dd", "DD")])
            self.combo_flash.setCurrentText(self._T.get("combo_flash_dd", "DD"))
        elif states.image_option == 3:    # format only :D
            self.combo_flash.addItems([self._T.get("combo_flash_none", "None")])
            self.combo_flash.setCurrentText(self._T.get("combo_flash_none", "None"))
        elif states.image_option == 4:    # ventoy
            self.combo_flash.addItems([self._T.get("combo_flash_ventoy", "Ventoy")])
            self.combo_flash.setCurrentText(self._T.get("combo_flash_ventoy", "Ventoy"))
        self.combo_flash.blockSignals(False)
        self.updateflash()

    # partition and target system updaters commented out :3
    #def update_partition_scheme(self):
    #    states.partition_scheme = self.combo_partition.currentIndex()
    #    self.log_message(f"Partition scheme changed to: {self.combo_partition.currentText()} (index={states.partition_scheme})")

    #def update_target_system(self):
    #    states.target_system = self.combo_target.currentIndex()
    #    self.log_message(f"Target system changed to: {self.combo_target.currentText()} (index={states.target_system})")

    def _open_url(self):
        # open github url in browser :D
        url = "http://www.github.com/hog185/lufus"
        pkexec_uid = os.environ.get("PKEXEC_UID")
        if pkexec_uid and os.geteuid() == 0:
            # when running as root via pkexec open as original user :3
            try:
                import pwd
                user_info = pwd.getpwuid(int(pkexec_uid))
                subprocess.Popen(
                    ["runuser", "-u", user_info.pw_name, "--", "xdg-open", url],
                    env={
                        "DISPLAY": os.environ.get("DISPLAY", ":0"),
                        "WAYLAND_DISPLAY": os.environ.get("WAYLAND_DISPLAY", ""),
                        "XDG_RUNTIME_DIR": f"/run/user/{pkexec_uid}",
                        "HOME": user_info.pw_dir,
                        "PATH": "/usr/bin:/bin",
                    }
                )
                return
            except Exception as e:
                self.log_message(f"Failed to open URL as user: {e}", level="WARN")
        # fallback to normal browser open :D
        webbrowser.open(url)

    def update_new_label(self, current_text):
        # update volume label in states :3
        states.new_label = current_text
        self.log_message(f"Volume label set to: {current_text!r}")

    def update_cluster_size(self):
        # update cluster size selection :D
        states.cluster_size = self.combo_cluster.currentIndex()
        self.log_message(f"Cluster size changed to: {self.combo_cluster.currentText()} (index={states.cluster_size})")

    def update_QF(self):
        # update quick format setting :3
        states.QF = 0 if self.chk_quick.isChecked() else 1
        self.log_message(f"Quick format: {'enabled' if self.chk_quick.isChecked() else 'disabled'}")

    def update_create_extended(self):
        # update extended label creation setting :D
        states.create_extended = 0 if self.chk_extended.isChecked() else 1
        self.log_message(f"Create extended label/icon files: {'enabled' if self.chk_extended.isChecked() else 'disabled'}")

    def update_check_bad(self):
        # update bad blocks check setting and enable pass selector :3
        states.check_bad = 0 if self.chk_badblocks.isChecked() else 1
        self.combo_badblocks.setEnabled(self.chk_badblocks.isChecked())
        self.log_message(f"Bad block check: {'enabled' if self.chk_badblocks.isChecked() else 'disabled'}")

    def update_verify_hash(self):
        # update sha256 verification setting :D
        states.verify_hash = self.chk_verify.isChecked()
        self.input_hash.setEnabled(states.verify_hash)
        self.log_message(f"SHA256 verification: {'enabled' if states.verify_hash else 'disabled'}")

    def update_expected_hash(self, text):
        # store expected hash for verification :3
        states.expected_hash = text.strip()


    def _check_clipboard(self):
        # monitor clipboard for iso file paths :D
        text = QApplication.clipboard().text().strip()
        if text == self._last_clipboard:
            return
        self._last_clipboard = text
        path = text.strip('"').strip("'")
        if path.lower().endswith(".iso") and Path(path).is_file():
            # auto load iso from clipboard :3
            file_size = os.path.getsize(path)
            states.iso_path = path
            clean_name = path.split("/")[-1].split("\\")[-1]
            self.combo_boot.setItemText(0, clean_name)
            self.input_label.setText(clean_name.split(".")[0].upper())
            self.log_message(f"Image loaded from clipboard: {path}")
            self.log_message(f"Image size: {file_size:,} bytes ({file_size / (1024**3):.2f} GiB)")
            self.notifier.show(f"✓ {clean_name} loaded from clipboard", notification_type="success", duration=3000)


    def dragEnterEvent(self, event):
        # accept drag of supported image files :D
        if event.mimeData().hasUrls():
            supported = [".iso", ".dmg", ".img", ".bin", ".raw"]
            if any(url.toLocalFile().lower().endswith(tuple(supported)) for url in event.mimeData().urls()):
                event.acceptProposedAction(); return
        event.ignore()

    def dragMoveEvent(self, event):
        # accept drag move of supported image files :3
        if event.mimeData().hasUrls():
            supported = [".iso", ".dmg", ".img", ".bin", ".raw"]
            if any(url.toLocalFile().lower().endswith(tuple(supported)) for url in event.mimeData().urls()):
                event.acceptProposedAction(); return
        event.ignore()

    def dropEvent(self, event):
        # handle dropped image files :D
        supported = [".iso", ".dmg", ".img", ".bin", ".raw"]
        img_files = [
            url.toLocalFile()
            for url in event.mimeData().urls()
            if url.toLocalFile().lower().endswith(tuple(supported))
        ]
        if img_files:
            # load first dropped image file :3
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
        # open file dialog to select image :D
        file_name, _ = QFileDialog.getOpenFileName(
            self,
            self._T.get("dlg_select_image_title", "Select Image"),
            "",
            self._T.get("dlg_select_image_filter", "Disk Images (*.iso *.dmg *.img *.bin *.raw);;All Files (*)"),
        )
        if file_name:
            # load selected image file :3
            file_size = os.path.getsize(file_name)
            states.iso_path = file_name
            clean_name = file_name.split("/")[-1].split("\\")[-1]
            self.combo_boot.setItemText(0, clean_name)
            self.input_label.setText(clean_name.split(".")[0].upper())
            self.log_message(f"Image selected: {file_name}")
            self.log_message(f"Image size: {file_size:,} bytes ({file_size / (1024**3):.2f} GiB)")


    def show_log(self):
        # show log window with all entries :D
        if self.log_window is None:
            self.log_window = LogWindow(self)
        self.log_window.log_text.clear()
        for entry in self.log_entries:
            # colorize log entries by level :3
            level = "INFO"
            for lvl in _LOG_LEVELS:
                if f"[{lvl}]" in entry:
                    level = lvl
                    break
            _, colour = _LOG_LEVELS.get(level, ("info", None))
            escaped = entry.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            html = f'<span style="color:{colour};">{escaped}</span>' if colour else f'<span>{escaped}</span>'
            self.log_window.log_text.append(html)
        self.log_window.show()
        self.log_window.raise_()
        self.log_window.activateWindow()
        # scroll to bottom :D
        scrollbar = self.log_window.log_text.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def log_message(self, msg, level="INFO"):
        # add message to log with timestamp and level :3
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        entry = f"[{timestamp}] [{level}] {msg}"
        self.log_entries.append(entry)
        log_method_name, colour = _LOG_LEVELS.get(level.upper(), ("info", None))
        getattr(self._logger, log_method_name)(msg)
        if self.log_window is not None:
            # update log window if open :D
            escaped = entry.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            html = f'<span style="color:{colour};">{escaped}</span>' if colour else f'<span>{escaped}</span>'
            self.log_window.log_text.append(html)
            scrollbar = self.log_window.log_text.verticalScrollBar()
            scrollbar.setValue(scrollbar.maximum())

    def show_about(self):
        # show about dialog :3
        if self.about_window is None:
            self.about_window = AboutWindow(self)
        content = self._T.get("about_content", "lufus - USB Flash Tool\n\nA simple, open-source USB flashing utility.")
        if not content.strip().startswith("<"):
            # convert plain text to html :D
            html_content = content.replace("\n", "<br>")
            self.about_window.about_text.setHtml(
                f"<div style='font-family:sans-serif; padding:4px;'>{html_content}</div>"
            )
        else:
            self.about_window.about_text.setHtml(content)
        self.about_window.show()
        self.about_window.raise_()
        self.about_window.activateWindow()

    def show_settings(self):
        # show settings dialog and connect signals :3
        dlg = SettingsDialog(self)
        dlg.language_changed.connect(self.apply_language)
        dlg.theme_changed.connect(self.apply_theme)
        dlg.exec()

    def apply_theme(self, theme_name):
        # copy theme json to user config and apply :D
        import shutil
        builtin_path = THEME_DIR / f'{theme_name}_theme.json'
        user_themes_dir = Path(user_config_dir("Lufus")) / "themes"
        user_path = user_themes_dir / f'{theme_name}_theme.json'
        dst = Path(user_config_dir("Lufus")) / 'user_theme.json'
        src = builtin_path if builtin_path.exists() else user_path
        if src.exists():
            # copy to user config :3
            shutil.copy(src, dst)
            sudo_dst = Path("/root/.config/Lufus/user_theme.json")
            try:
                shutil.copy(src, sudo_dst)
            except Exception:
                pass
            states.theme = theme_name
            self._apply_styles()
            self.log_message(f"Theme changed to: {theme_name}")

    def apply_language(self, language):
        # change language and update all ui text :D
        self.current_language = language
        states.language = language
        self._T = load_translations(language)
        self._update_ui_text()
        self.log_message(f"Language changed to: {language}")

    def _update_ui_text(self):
        # update all text labels with new translations :3
        self.setWindowTitle(self._T.get("window_title", "lufus"))
        self.lbl_device.setText(self._T.get("lbl_device", "Device"))
        self.lbl_boot.setText(self._T.get("lbl_boot_selection", "Boot Selection"))
        self.btn_select.setText(self._T.get("btn_select", "Select"))
        self.lbl_image.setText(self._T.get("lbl_image_option", "Image Option"))
        #self.lbl_part.setText(self._T.get("lbl_partition_scheme", "Partition Scheme"))
        #self.lbl_target.setText(self._T.get("lbl_target_system", "Target System"))
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

        # update image option combo :D
        current_img_idx = self.combo_image_option.currentIndex()
        self.combo_image_option.blockSignals(True)
        self.combo_image_option.clear()
        self.combo_image_option.addItem(self._T.get("combo_image_windows", "Windows"))
        self.combo_image_option.addItem(self._T.get("combo_image_linux", "Linux"))
        self.combo_image_option.addItem(self._T.get("combo_image_other", "Other"))
        self.combo_image_option.addItem(self._T.get("combo_image_format", "Format Only"))
        #self.combo_image_option.addItem(self._T.get("combo_image_ventoy", "Ventoy"))
        self.combo_image_option.setCurrentIndex(current_img_idx)
        self.combo_image_option.blockSignals(False)

        # update log and about windows if open
        if self.log_window:
            self.log_window.setWindowTitle(self._T.get("log_window_title", "Log Window"))
        if self.about_window:
            self.about_window.setWindowTitle(self._T.get("about_window_title", "About"))
            content = self._T.get("about_content", "lufus - USB Flash Tool")
            if not content.strip().startswith("<"):
                html_content = content.replace("\n", "<br>")
                self.about_window.about_text.setHtml(
                    f"<div style='font-family:sans-serif; padding:4px;'>{html_content}</div>"
                )
            else:
                self.about_window.about_text.setHtml(content)

        # update cluster size combo
        cur = self.combo_cluster.currentIndex()
        self.combo_cluster.blockSignals(True)
        self.combo_cluster.clear()
        self.combo_cluster.addItem(self._T.get("combo_cluster_4096", "4096"))
        self.combo_cluster.addItem(self._T.get("combo_cluster_8192", "8192"))
        self.combo_cluster.setCurrentIndex(cur)
        self.combo_cluster.blockSignals(False)

        # update badblocks combo :3
        cur = self.combo_badblocks.currentIndex()
        self.combo_badblocks.blockSignals(True)
        self.combo_badblocks.clear()
        self.combo_badblocks.addItem(self._T.get("combo_badblocks_1pass", "1 Pass"))
        self.combo_badblocks.addItem(self._T.get("combo_badblocks_2pass", "2 Pass"))
        self.combo_badblocks.addItem(self._T.get("combo_badblocks_3pass", "3 Pass"))
        self.combo_badblocks.setCurrentIndex(cur)
        self.combo_badblocks.blockSignals(False)

        # update verification controls :D
        self.chk_verify.setText(self._T.get("chk_verify_hash", "Verify SHA256 Checksum"))
        self.input_hash.setPlaceholderText(self._T.get("input_hash_placeholder", "Enter expected SHA256 hash here..."))
        self.input_label.setPlaceholderText(self._T.get("lbl_volume_label", "Volume Label"))

        # update boot combo default text :3
        if self.combo_boot.itemText(0) == "installation_media.iso" or self.combo_boot.itemText(0) == self._T.get("combo_boot_default", "installation_media.iso"):
            self.combo_boot.setItemText(0, self._T.get("combo_boot_default", "installation_media.iso"))

        if not self.usb_devices:
            # update no devices message :D
            self.combo_device.clear()
            self.combo_device.addItem(self._T.get("no_usb_found", "No USB devices found"), None)
        self._update_flashing_options()


    def get_selected_mount_path(self) -> str:
        # get device path from selected combo item :3
        data = self.combo_device.currentData()
        return data if isinstance(data, str) else ""


    def cancel_process(self):
        # cancel ongoing flash operation D:
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
                # check what processes are using device :3
                lsof = subprocess.run(["lsof", device_node], capture_output=True, text=True)
                if lsof.returncode == 0:
                    self.log_message(f"Processes using {device_node} before kill:\n{lsof.stdout}")
            except Exception as e:
                self.log_message(f"Could not run lsof: {e}")

            if self.flash_worker and self.flash_worker.isRunning():
                # terminate flash worker thread :D
                self.log_message("Terminating flash worker", level="WARN")
                self.flash_worker.terminate()
                if not self.flash_worker.wait(3000):
                    self.log_message("Flash worker did not stop, forcing quit", level="WARN")
                    self.flash_worker.quit()
                    self.flash_worker.wait(2000)

            try:
                # kill processes using device :3
                subprocess.run(["fuser", "-k", device_node], timeout=5, check=False)
                self.log_message("fuser -k executed")
            except Exception as e:
                self.log_message(f"fuser fallback failed: {e}")
            
            if hasattr(self, "verify_worker") and self.verify_worker and self.verify_worker.isRunning():
                # terminate verify worker :D
                self.log_message("Terminating verify worker", level="WARN")
                self.verify_worker.terminate()
                self.verify_worker.wait(2000)
                self.log_message("Verify worker terminated")
            
            if self.is_terminal:
                # reset terminal state :3
                try:
                    subprocess.run(["stty", "sane"], timeout=1, check=False)
                    self.log_message("Terminal reset to sane state")
                except Exception as e:
                    self.log_message(f"Failed to reset terminal: {e}")

            # reset ui state :D
            self.progress_bar.setValue(0)
            self.progress_bar.setFormat("")
            self.btn_start.setEnabled(True)
            self.btn_cancel.setEnabled(False)
            self.statusBar.showMessage(self._T.get("status_ready", "Ready"), 0)
            self.log_message("Flash process cancelled by user", level="WARN")    

    def start_process(self):
        # start flashing process with validation :3
        states.DN = self.combo_device.currentData() or ""
        self.log_message(
            f"Start process triggered: image_option={states.image_option}, flash_mode={states.currentflash}, device={states.DN}"
        )

        if states.image_option in [0, 1, 2]:
            # validate image path exists :D
            if not getattr(states, "iso_path", "") or not Path(states.iso_path).exists():
                self.log_message("Start aborted: no valid image path set", level="WARN")
                QMessageBox.warning(self, self._T.get("msgbox_no_image_title", "No Image"),
                                    self._T.get("msgbox_no_image_body", "Please select an image file"))
                return

            # validate device selected :3
            device_node = self.get_selected_mount_path()
            if not device_node:
                self.log_message("Start aborted: no USB device selected", level="WARN")
                QMessageBox.warning(self, self._T.get("msgbox_no_device_title", "No Device"),
                                    self._T.get("msgbox_no_device_body", "Please select a USB device"))
                return

        elif states.image_option == 4:  # ventoy no iso required but device is :D
            device_node = self.get_selected_mount_path()
            if not device_node:
                self.log_message("Start aborted: no USB device selected", level="WARN")
                QMessageBox.warning(self, self._T.get("msgbox_no_device_title", "No Device"),
                                    self._T.get("msgbox_no_device_body", "Please select a USB device"))
                return

        if states.image_option in [0, 1, 2] and states.verify_hash:
            # validate sha256 hash format
            h = states.expected_hash.strip().lower()
            if len(h) != 64 or not all(c in "0123456789abcdef" for c in h):
                self.log_message("Start aborted: invalid SHA256 hash format", level="WARN")
                QMessageBox.warning(self, self._T.get("msgbox_invalid_hash_title", "Invalid Hash"),
                                    self._T.get("msgbox_invalid_hash_body", "The provided SHA256 hash is invalid."))
                return

            # start verification worker :D
            self.btn_start.setEnabled(False)
            self.btn_cancel.setEnabled(True)
            self.progress_bar.setValue(0)
            self.progress_bar.setFormat(self._T.get("progress_verifying", "Verifying..."))

            self.verify_worker = VerifyWorker(states.iso_path, states.expected_hash)
            self.verify_worker.progress.connect(self.log_message)
            self.verify_worker.verify_done.connect(self.on_verify_finished)
            self.verify_worker.start()
        else:
            # skip verification and start flash :3
            self.perform_flash()

    def on_verify_finished(self, success: bool):
        # handle verification result :D
        if success:
            self.log_message("SHA256 verification successful, proceeding to flash")
            self.perform_flash()
        else:
            # verification failed  (╯°□°)╯( ┻━┻
            self.log_message("SHA256 verification FAILED", level="ERROR")
            QMessageBox.critical(self, self._T.get("msgbox_verify_fail_title", "Verification Failed"),
                                 self._T.get("msgbox_verify_fail_body", "SHA256 checksum mismatch!"))
            self.btn_start.setEnabled(True)
            self.btn_cancel.setEnabled(False)
            self.progress_bar.setValue(0)
            self.progress_bar.setFormat("")

    def perform_flash(self):
        # perform actual flash operation :D
        options = {
            "iso_path": states.iso_path,
            "device": self.get_selected_mount_path(),
            "image_option": states.image_option,
            "currentflash": states.currentflash,
            "currentFS": states.currentFS,
            #"partition_scheme": states.partition_scheme,
            #"target_system": states.target_system,
            "cluster_size": states.cluster_size,
            "QF": states.QF,
            "create_extended": states.create_extended,
            "check_bad": states.check_bad,
            "new_label": states.new_label,
            "verify_hash": states.verify_hash,
            "expected_hash": states.expected_hash,
        }

        if os.geteuid() != 0:
            # not root so relaunch with pkexec :3
            with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as tmp:
                json.dump(options, tmp)
                opts_path = tmp.name

            # preserve display session variables so the root gui can render :D
            gui_env = {
                "DISPLAY":          os.environ.get("DISPLAY"),
                "XAUTHORITY":       os.environ.get("XAUTHORITY") or os.path.expanduser("~/.Xauthority"),
                "WAYLAND_DISPLAY":  os.environ.get("WAYLAND_DISPLAY"),
                "XDG_RUNTIME_DIR":  os.environ.get("XDG_RUNTIME_DIR"),
                "PATH":             os.environ.get("PATH", "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"),
                "PYTHONPATH":       os.environ.get("PYTHONPATH", ""),
            }
            env_args = ["env"]
            for key, value in gui_env.items():
                if value:
                    env_args.append(f"{key}={value}")

            import shutil
            pkexec_path = shutil.which("pkexec") or "/usr/bin/pkexec"
            if not os.path.isfile(pkexec_path):
                # pkexec not found  (╯°□°)╯( ┻━┻
                self.log_message("Error: pkexec not found. Please install policykit-1 or run as root.", level="ERROR")
                return

            # build relaunch command :D
            appimage = os.environ.get("APPIMAGE")
            executable = appimage if appimage else sys.executable
            base_args = sys.argv[1:] if appimage else sys.argv[:]
            # strip any previous flash now args to avoid duplication on reexec :3
            clean_args = []
            skip_next = False
            for a in base_args:
                if skip_next:
                    skip_next = False
                    continue
                if a == "--flash-now":
                    skip_next = True
                    continue
                clean_args.append(a)

            cmd = [pkexec_path] + env_args + [executable] + clean_args + ["--flash-now", opts_path]
            self.log_message("Relaunching as root via pkexec for flash operation...")
            os.execvp(pkexec_path, cmd)
        else:
            # already root start flash worker :D
            self.log_message(f"Starting flash thread: image_option={options['image_option']}, flash_mode={options['currentflash']}, device={options['device']}")
            self.flash_worker = FlashWorker(options)
            self.flash_worker.progress.connect(self.progress_bar.setValue, Qt.ConnectionType.QueuedConnection)
            self.flash_worker.status.connect(self._on_flash_status, Qt.ConnectionType.QueuedConnection)
            self.flash_worker.flash_done.connect(self.on_flash_finished, Qt.ConnectionType.QueuedConnection)
            self.flash_worker.start()

    def _do_autoflash(self) -> None:
        # called after init when launched with flash now :3
        if not self._autoflash_path:
            return
        try:
            # load options from json file :D
            with open(self._autoflash_path) as f:
                options = json.load(f)
            try:
                os.unlink(self._autoflash_path)
            except Exception:
                pass
            self.log_message(f"Auto-flash triggered: device={options.get('device')}, image_option={options.get('image_option')}")
            self._start_flash_with_options(options)
        except Exception as e:
            self.log_message(f"Auto-flash failed to load options: {e}", level="ERROR")

    def _start_flash_with_options(self, options: dict) -> None:
        # start flashworker directly with prebuilt options dict :3
        self.log_message(f"Starting flash: image_option={options['image_option']}, flash_mode={options['currentflash']}, device={options['device']}")
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
        # update status bar and log with flash status :D
        self.log_message(msg)
        self.statusBar.showMessage(msg, 0)

    def on_flash_finished(self, success: bool):
        # handle flash completion :3
        if self.flash_worker is not None:
            self.flash_worker.wait()
        if success:
            # flash succeeded :D
            self.progress_bar.setValue(100)
            self.progress_bar.setFormat(self._T.get("progress_complete", "Complete"))
            self.log_message("Flash operation finished with result: SUCCESS")
            QMessageBox.information(
                self,
                self._T.get("msgbox_success_title", "Success"),
                self._T.get("msgbox_success_body", "Flash completed successfully"),
            )
        else:
            # flash failed :3
            self.progress_bar.setFormat(self._T.get("progress_failed", "Failed"))
            self.log_message("Flash operation finished with result: FAILED", level="ERROR")
            QMessageBox.critical(
                self,
                self._T.get("msgbox_error_title", "Error"),
                self._T.get("msgbox_error_body", "Flash failed"),
            )

        # reset ui state :D
        self.btn_start.setEnabled(True)
        self.btn_cancel.setEnabled(False)
        self.statusBar.showMessage(self._T.get("status_ready", "Ready"), 0)


    def keyPressEvent(self, event):
        # handle keyboard shortcuts :3
        if (event.key() == Qt.Key.Key_R
                and event.modifiers() == Qt.KeyboardModifier.ControlModifier):
            self.refresh_usb_devices()
        elif event.key() == Qt.Key.Key_F5:
            # f5 also refreshes device list :D
            self.refresh_usb_devices()
        super().keyPressEvent(event)



    def check_polkit_agent(self):
        # check if a polkit authentication agent is running :3
        # returns true if found false otherwise
        try:
            # common agent process names :D
            agents = [
                "polkit-gnome-authentication-agent-1",
                "polkit-kde-authentication-agent-1",
                "lxqt-policykit-agent",
                "mate-polkit",
                "polkit-1-agent"
            ]
            # use pgrep to search for any of these :3
            for agent in agents:
                result = subprocess.run(["pgrep", "-f", agent], capture_output=True)
                if result.returncode == 0:
                    return True
            return False
        except Exception:
            # if pgrep fails assume agent might be present better to try :D
            return True




if __name__ == "__main__":
    # setup high dpi scaling :3
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    app = QApplication(sys.argv)

    # parse usb devices from command line arg :D
    usb_devices = {}
    # only try to parse usb devices json when the arg is not a known flag :3
    if len(sys.argv) > 1 and sys.argv[1] not in ("--flash-now",):
        try:
            decoded_data = urllib.parse.unquote(sys.argv[1])
            usb_devices = json.loads(decoded_data)
            print("Successfully parsed USB devices:", usb_devices)
        except Exception as e:
            print(f"Error parsing USB devices: {e}")

    # create and show main window :D
    window = lufus(usb_devices)
    window.show()
    sys.exit(app.exec()) # oink meow meow meow :3
