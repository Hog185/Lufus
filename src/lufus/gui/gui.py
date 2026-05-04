import subprocess
import sys
import tempfile
import json
import os
import platform
import getpass
import time
import ssl
import urllib.parse
import urllib.request
import webbrowser
from typing import Dict, Any
from packaging import version
from platformdirs import user_config_dir
from datetime import datetime
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
    QPropertyAnimation,
)
from PyQt6.QtGui import QIcon

from lufus import state
from lufus.drives.autodetect_usb import UsbMonitor
from lufus.lufus_logging import get_logger
from lufus.gui.themes.icon_utils import svg_icon
from lufus.gui.constants import THEME_DIR, ASSETS_DIR, ICONS
from lufus.gui.scale import Scale
from lufus.gui.i18n import load_translations
from lufus.gui.redirector import StdoutRedirector
from lufus.gui.dialogs import LogWindow, AboutWindow, SettingsDialog, WinTweaks
from lufus.gui.workers import FlashWorker, VerifyWorker
from lufus.writing.windows.tweaks import *

# log level mapping for colors and methods
_LOG_LEVELS = {
    "DEBUG": ("debug", "#888888"),
    "INFO": ("info", None),
    "WARN": ("warning", "#f0a500"),
    "WARNING": ("warning", "#f0a500"),
    "ERROR": ("error", "#e05555"),
    "CRITICAL": ("critical", "#e05555"),
}


class BackgroundWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._bg_pixmap = None

    def set_background(self, image_path):
        # load and cache bg pixmap :3
        if image_path and Path(image_path).is_file():
            from PyQt6.QtGui import QPixmap

            self._bg_pixmap = QPixmap(str(image_path))
        else:
            self._bg_pixmap = None
        self.update()

    def paintEvent(self, event):
        if self._bg_pixmap and not self._bg_pixmap.isNull():
            from PyQt6.QtGui import QPainter

            painter = QPainter(self)
            # scale to fill widget keeping aspect ratio, centre-cropped :D
            scaled = self._bg_pixmap.scaled(
                self.size(),
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation,
            )
            x = (self.width() - scaled.width()) // 2
            y = (self.height() - scaled.height()) // 2
            painter.drawPixmap(x, y, scaled)
            painter.end()
        else:
            super().paintEvent(event)


class LufusWindow(QMainWindow):
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
        self.current_language = state.language
        self._T = load_translations(self.current_language)

        # restore theme from env when relaunched as root via pkexec :3
        env_theme = os.environ.get("LUFUS_THEME", "")
        if env_theme:
            state.theme = env_theme

        # load persisted theme from config when not set via env :3
        if not getattr(state, "theme", ""):
            try:
                _theme_cfg = Path(user_config_dir("Lufus")) / "active_theme"
                state.theme = _theme_cfg.read_text(encoding="utf-8").strip()
            except Exception:
                pass

        self.setWindowTitle(self._T.get("window_title", "lufus"))

        # calculate window size based on screen dimensions
        screen = QApplication.primaryScreen().availableGeometry()
        scale = min(screen.width() / Scale.REF_W, screen.height() / Scale.REF_H)
        win_w = min(int(Scale.DESIGN_W * scale), int(screen.width() * 1.2))
        win_h = min(int(Scale.DESIGN_H * scale), int(screen.height() * 1.2))
        ui_factor = win_w / Scale.DESIGN_W
        self._S = Scale(QApplication.instance(), factor=ui_factor)
        self.resize(win_w, win_h)  # oink
        self.setMinimumSize(int(win_w * 0.6), int(win_h * 0.6))

        # initialize worker threads and windows :3
        self.flash_worker = None
        self.verify_worker = None
        self._autoflash_path = None
        self.log_window = None
        self.about_window = None
        self.log_entries = []
        self._last_clipboard = ""
        self.is_terminal = False
        self.worker = FlashWorker()
        self.worker.request_tweaks.connect(self.show_tweak_dialog)
        try:
            self.is_terminal = sys.stdout.isatty()
        except (AttributeError, OSError):
            pass

        self._flash_start_time = None
        self._flash_total_bytes = 0
        self._last_progress_pct = 0
        self._speed_samples = []

        # redirect stdout to log :D
        sys.stdout = StdoutRedirector(self.log_message)

        # build ui and apply styles
        self.init_ui()
        self._apply_styles()
        QTimer.singleShot(0, self._apply_styles)
        self.update_usb_list(self.monitor.devices)
        self.setAcceptDrops(True)
        # icon stuff
        SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
        icon_path = os.path.join(SCRIPT_DIR, "assets", "icons", "lufuslogo.ico")
        self.setWindowIcon(QIcon(icon_path))
        QApplication.setWindowIcon(QIcon(icon_path))
        # start clipboard monitoring :3
        self._clipboard_timer = QTimer(self)
        self._clipboard_timer.timeout.connect(self._check_clipboard)
        self._clipboard_timer.start(500)

        # periodic speed/eta refresh independent of progress signal frequency
        self._speed_timer = QTimer(self)
        self._speed_timer.timeout.connect(self._tick_speed_eta)
        self._speed_timer.setInterval(400)

        # log startup info :D
        self.log_message(f"lufus started (version: {state.version})")
        self.log_message(
            f"Python {sys.version.split()[0]} | {platform.system()} {platform.release()} {platform.machine()}"
        )
        self.log_message(f"Running as user: {getpass.getuser()} (uid={os.getuid()})")
        self.log_message(f"Startup USB devices passed in: {list((usb_devices or {}).keys()) or 'none'}")
        self.flash_worker = None
        self.log_message(f"UI scale factor: {self._S.f():.3f}  (base 96 DPI)")
        self._check_latest_download()

        # check for new updates function call
        QTimer.singleShot(100, self.get_latest_release)

    def _check_latest_download(self):
        if state.iso_path:
            return
        try:
            result = subprocess.run(["xdg-user-dir", "DOWNLOAD"], capture_output=True, text=True, timeout=2)
            downloads = (
                Path(result.stdout.strip())
                if result.returncode == 0 and result.stdout.strip()
                else Path.home() / "Downloads"
            )
        except Exception:
            downloads = Path.home() / "Downloads"
        if not downloads.is_dir():
            return
        try:
            isos = sorted(downloads.glob("*.iso"), key=lambda p: p.stat().st_mtime, reverse=True)
        except Exception:
            return
        if not isos:
            return
        latest = isos[0]
        try:
            file_size = latest.stat().st_size
        except Exception:
            return
        state.iso_path = str(latest)
        clean_name = latest.name
        self.combo_boot.setItemText(0, clean_name)
        self.input_label.setText(clean_name.rsplit(".", 1)[0].upper())
        self.log_message(f"Latest download auto-loaded: {latest}")
        self.log_message(f"Image size: {file_size:,} bytes ({file_size / (1024**3):.2f} GiB)")
        self._detect_iso_and_update_ui(str(latest))

    def _apply_styles(self) -> None:
        # load json values apply via qss all that yap is in the themes folder :3
        S = self._S
        APP_NAME = "Lufus"
        theme_dir = Path(__file__).parent / "themes"
        template_path = theme_dir / "style_template.qss"
        user_config_dir_path = Path(user_config_dir(APP_NAME, roaming=True))

        # resolve which theme folder to use :3
        theme_name = getattr(state, "theme", "") or "default"
        user_themes_dir = user_config_dir_path / "themes"
        builtin_json = theme_dir / theme_name / f"{theme_name}_theme.json"
        user_json = user_themes_dir / theme_name / f"{theme_name}_theme.json"
        fallback_json = theme_dir / "default" / "default_theme.json"

        if builtin_json.exists():
            theme_json_path = builtin_json
        elif user_json.exists():
            theme_json_path = user_json
        else:
            theme_json_path = fallback_json

        try:
            # load active theme json :D
            with open(theme_json_path, "r", encoding="utf-8") as fr:
                theme = json.load(fr)
        except FileNotFoundError:
            print("WARNING: no theme applied, json didn't load up in _apply_styles, gui.py.")
            return

        # check if gradients are enabled :3
        use_gradient = int(theme["dimensions"].get("use_gradient", 1))

        # keys that dont need scaling
        NO_SCALE_KEYS = {"use_gradient", "btn_border_width", "combo_border_width"}
        NO_SCALE_FONT_KEYS = {"family"}

        # sensible defaults for every key the QSS template may reference :3
        _DIM_DEFAULTS = {
            "combo_pad_vertical": 4,
            "combo_pad_horizontal": 10,
            "combo_height": 28,
            "combo_dropdown_width": 20,
            "combo_radius": 6,
            "btn_radius": 6,
            "btn_pad_vertical": 6,
            "btn_pad_horizontal": 14,
            "btn_min_height": 28,
            "btn_min_width": 80,
            "btn_border_width": 1,
            "combo_border_width": 1,
            "check_indicator_size": 16,
            "progress_radius": 4,
            "progress_height": 20,
            "tool_border_radius": 4,
            "tool_padding": 4,
            "tool_size": 28,
            "use_gradient": 1,
        }
        _FONT_DEFAULTS = {
            "family": "sans-serif",
            "base": 10,
            "small": 9,
            "header": 13,
            "tool": 10,
            "label": 10,
        }

        theme.setdefault("dimensions", {})
        theme.setdefault("fonts", {})
        theme.setdefault("colors", {})

        # merge defaults under any missing keys :D
        for k, v in _DIM_DEFAULTS.items():
            theme["dimensions"].setdefault(k, v)
        for k, v in _FONT_DEFAULTS.items():
            theme["fonts"].setdefault(k, v)

        # create scaled theme dict :D
        scaled_theme = {"colors": theme["colors"].copy(), "fonts": {}, "dimensions": {}}

        # scale font sizes
        for key, value in theme["fonts"].items():
            if key in NO_SCALE_FONT_KEYS:
                scaled_theme["fonts"][key] = value
            else:
                scaled_theme["fonts"][key] = S.pt(value)

        # scale dimensions :3
        for key, value in theme["dimensions"].items():
            scaled_theme["dimensions"][key] = value if key in NO_SCALE_KEYS else S.px(value)

        # flatten theme dict for template substitution
        flat_theme: Dict[str, Any] = {}
        for category, subdict in scaled_theme.items():
            for key, val in subdict.items():
                flat_theme[f"{category}_{key}"] = val

        fg_color = theme["colors"].get("fg", "#000000")
        arrow_size = S.px(10)

        def _tinted_arrow_path(name: str) -> str:
            src = ASSETS_DIR / "icons" / name
            if src.is_file():
                try:
                    svg_data = src.read_text(encoding="utf-8")
                    svg_data = svg_data.replace("currentColor", fg_color)
                    import hashlib

                    sig = hashlib.md5(f"{src}{fg_color}".encode()).hexdigest()[:8]
                    tmp_path = Path(tempfile.gettempdir()) / f"lufus_arrow_{sig}.svg"
                    tmp_path.write_text(svg_data, encoding="utf-8")
                    return tmp_path.as_posix()
                except Exception:
                    pass
            return ""

        flat_theme["meta_arrow_down"] = _tinted_arrow_path("down_arrow.svg")
        flat_theme["meta_arrow_up"] = _tinted_arrow_path("up_arrow.svg")
        flat_theme["dimensions_arrow_size"] = arrow_size

        try:
            # load qss template
            with open(template_path, "r", encoding="utf-8") as f:
                template = f.read()
        except FileNotFoundError:  # (╯°□°)╯( ┻━┻
            print("Error: style_template.qss not found.")
            return

        if not use_gradient:
            # replace gradient rules with solid colors when disabled
            import re

            template = re.sub(
                r"background:\s*qlineargradient\(\s*x1:0,\s*y1:0,\s*x2:0,\s*y2:1,\s*"
                r"stop:0\s*\{colors_input_bg_top\},\s*stop:1\s*\{colors_input_bg\}\s*\)",
                "background-color: {colors_input_bg}",
                template,
                flags=re.MULTILINE,
            )
            template = re.sub(
                r"background:\s*qlineargradient\(\s*x1:0,\s*y1:0,\s*x2:0,\s*y2:1,\s*"
                r"stop:0\s*\{colors_button_bg_top\},\s*stop:1\s*\{colors_button_bg\}\s*\)",
                "background-color: {colors_button_bg}",
                template,
                flags=re.MULTILINE,
            )
            template = re.sub(
                r"background:\s*qlineargradient\(\s*x1:0,\s*y1:0,\s*x2:0,\s*y2:1,\s*"
                r"stop:0\s*\{colors_button_hover_bg_top\},\s*stop:1\s*\{colors_button_hover_bg\}\s*\)",
                "background-color: {colors_button_hover_bg}",
                template,
                flags=re.MULTILINE,
            )
            template = re.sub(
                r"background:\s*qlineargradient\(\s*x1:0,\s*y1:0,\s*x2:0,\s*y2:1,\s*"
                r"stop:0\s*\{colors_tool_button_bg_top\},\s*stop:1\s*\{colors_tool_button_bg\}\s*\)",
                "background-color: {colors_tool_button_bg}",
                template,
                flags=re.MULTILINE,
            )

        # apply template and set stylesheet
        self._flat_theme = flat_theme
        style_sheet = template.format(**flat_theme)

        # look for background image in the theme's images/ folder :3
        theme_images_dir = theme_json_path.parent / "images"
        bg_image_path = None
        for ext in ("png", "jpg", "jpeg", "webp"):
            candidate = theme_images_dir / f"background_image.{ext}"
            if candidate.is_file():
                bg_image_path = candidate
                break

        # build final stylesheet, appending transparency rules if a bg image is active :3
        if hasattr(self, "_bg_widget") and bg_image_path:
            style_sheet += "QWidget#centralWidget, QScrollArea, QWidget#scrollContent { background: transparent; }"

        QApplication.instance().setStyleSheet(style_sheet)

        # push bg image to widget - paintEvent handles scaling :D
        if hasattr(self, "_bg_widget"):
            self._bg_widget.set_background(bg_image_path)

        # force every widget to re-evaluate the new stylesheet :D
        for widget in QApplication.instance().allWidgets():
            widget.style().unpolish(widget)
            widget.style().polish(widget)
            widget.update()

        if hasattr(self, "btn_icon1"):
            self.apply_icons()

    def apply_icons(self):
        # svg shit recolor for themes
        fg = self._flat_theme.get("colors_fg", "#000000")
        self.btn_icon1.setIcon(svg_icon(ICONS["website"], fg))
        self.btn_icon2.setIcon(svg_icon(ICONS["about"], fg))
        self.btn_icon3.setIcon(svg_icon(ICONS["settings"], fg))
        self.btn_icon4.setIcon(svg_icon(ICONS["log"], fg))
        self.btn_refresh.setIcon(svg_icon(ICONS["refresh"], fg))

    def create_header(self, text):
        # create section header with horizontal line :3
        layout = QHBoxLayout()
        layout.setContentsMargins(0, self._S.px(4), 0, self._S.px(2))
        label = QLabel(text)
        label.setObjectName("sectionHeader")
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        line.setStyleSheet("background-color: palette(mid); min-height: 1px; max-height: 1px;")
        layout.addWidget(label)
        layout.addWidget(line, 1)
        return layout, label

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

    def init_ui(self):
        # build main user interface :D
        S = self._S
        FIELD_SPACING = S.px(2)
        GROUP_SPACING = S.px(5)

        # create central widget with scroll area
        central_widget = BackgroundWidget()
        central_widget.setObjectName("centralWidget")
        self._bg_widget = central_widget
        self.setCentralWidget(central_widget)
        outer_layout = QVBoxLayout(central_widget)
        outer_layout.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        scroll_content = QWidget()
        scroll_content.setObjectName("scrollContent")
        main_layout = QVBoxLayout(scroll_content)
        main_layout.setSpacing(S.px(3))
        m = S.px(15)
        main_layout.setContentsMargins(m, S.px(5), m, S.px(5))

        scroll.setWidget(scroll_content)
        outer_layout.addWidget(scroll)

        # drive properties section :3
        _hdr_drive, self.lbl_header_drive = self.create_header(
            self._T.get("header_drive_properties", "Drive Properties")
        )
        main_layout.addLayout(_hdr_drive)
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
        # self.combo_image_option.addItem(self._T.get("combo_image_ventoy", "Ventoy"))
        self.combo_image_option.currentTextChanged.connect(self.update_image_option)

        image_layout = QVBoxLayout()
        image_layout.setSpacing(FIELD_SPACING)
        image_layout.addWidget(self.lbl_image)
        image_layout.addWidget(self.combo_image_option)
        main_layout.addLayout(image_layout)
        main_layout.addSpacing(GROUP_SPACING)

        # TODO: Decide if partition scheme / target system selectors are needed for a future release
        # self.lbl_part = QLabel(self._T.get("lbl_partition_scheme", "Partition Scheme"))
        # self.combo_partition = QComboBox()
        # self.combo_partition.addItem(self._T.get("combo_partition_gpt", "GPT"))
        # self.combo_partition.addItem(self._T.get("combo_partition_mbr", "MBR"))
        # self.combo_partition.currentTextChanged.connect(self.update_partition_scheme)

        # self.lbl_target = QLabel(self._T.get("lbl_target_system", "Target System"))
        # self.combo_target = QComboBox()
        # self.combo_target.addItem(self._T.get("combo_target_uefi", "UEFI"))
        # self.combo_target.addItem(self._T.get("combo_target_bios", "BIOS"))
        # self.combo_target.currentTextChanged.connect(self.update_target_system)

        grid_part = QGridLayout()
        grid_part.setHorizontalSpacing(S.px(10))
        grid_part.setVerticalSpacing(FIELD_SPACING)
        grid_part.setColumnStretch(0, 1)
        grid_part.setColumnStretch(1, 1)
        # grid_part.addWidget(self.lbl_part, 0, 0)
        # grid_part.addWidget(self.combo_partition, 1, 0)
        # grid_part.addWidget(self.lbl_target, 0, 1)
        # grid_part.addWidget(self.combo_target, 1, 1)
        main_layout.addLayout(grid_part)

        main_layout.addSpacing(S.px(6))

        # format options section :3
        _hdr_fmt, self.lbl_header_format = self.create_header(self._T.get("header_format_options", "Format Options"))
        main_layout.addLayout(_hdr_fmt)
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
        self.all_fs_options = ["NTFS", "FAT32", "exFAT", "ext4", "UDF", "HFS+", "ext2", "ext3", "Btrfs", "XFS", "ZFS"]
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
            self._T.get("combo_flash_iso", "ISO"),
            # self._T.get("combo_flash_ventoy", "Ventoy"),
            self._T.get("combo_flash_dd", "DD"),
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
        grid_fmt.addWidget(self.lbl_fs, 0, 0)
        grid_fmt.addWidget(self.combo_fs, 1, 0)
        grid_fmt.addWidget(self.lbl_cluster, 0, 1)
        grid_fmt.addWidget(self.combo_cluster, 1, 1)
        grid_fmt.addWidget(self.lbl_flash, 0, 2)
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
        self.combo_badblocks.setMaximumHeight(0)
        self.chk_badblocks.stateChanged.connect(self.update_check_bad)
        self.update_check_bad()

        # sha256 verification checkbox and input :D
        self.chk_verify = QCheckBox(self._T.get("chk_verify_hash", "Verify SHA256 Checksum"))
        self.chk_verify.stateChanged.connect(self.update_verify_hash)
        self.lbl_expected_hash = QLabel(self._T.get("lbl_expected_hash", "Expected SHA256:"))
        self.lbl_expected_hash.setVisible(False)
        self.input_hash = QLineEdit()
        self.input_hash.setPlaceholderText(self._T.get("input_hash_placeholder", "Enter expected SHA256 hash here..."))
        self.input_hash.setEnabled(False)
        self.input_hash.setMaximumHeight(0)
        self.input_hash.textChanged.connect(self.update_expected_hash)
        self.update_verify_hash()

        # layout for all checkboxes :3
        chk_layout = QVBoxLayout()
        chk_layout.setSpacing(S.px(6))
        chk_layout.addWidget(self.chk_quick)
        chk_layout.addWidget(self.chk_extended)
        chk_layout.addWidget(self.chk_badblocks)
        chk_layout.addWidget(self.combo_badblocks)
        chk_layout.addWidget(self.chk_verify)
        chk_layout.addWidget(self.lbl_expected_hash)
        chk_layout.addWidget(self.input_hash)

        main_layout.addLayout(chk_layout)

        main_layout.addSpacing(S.px(6))

        # status section with progress bar :D
        _hdr_status, self.lbl_header_status = self.create_header(self._T.get("header_status", "Status"))
        main_layout.addLayout(_hdr_status)
        main_layout.addSpacing(S.px(4))

        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("")
        self.progress_bar.setMinimumHeight(S.px(22))
        main_layout.addWidget(self.progress_bar)
        main_layout.addSpacing(S.px(10))

        # toolbar buttons
        self.btn_icon1 = QToolButton()
        self.btn_icon1.setText("")
        self.btn_icon1.setToolTip(self._T.get("tooltip_website", "website"))
        self.btn_icon1.clicked.connect(self._open_url)

        self.btn_icon2 = QToolButton()
        self.btn_icon2.setText("")
        self.btn_icon2.setToolTip(self._T.get("tooltip_about", "about"))
        self.btn_icon2.clicked.connect(self.show_about)

        self.btn_icon3 = QToolButton()
        self.btn_icon3.setText("")
        self.btn_icon3.setToolTip(self._T.get("tooltip_settings", "settings"))
        self.btn_icon3.clicked.connect(self.show_settings)

        self.btn_icon4 = QToolButton()
        self.btn_icon4.setText("")
        self.btn_icon4.setToolTip(self._T.get("tooltip_log", "log"))
        self.btn_icon4.clicked.connect(self.show_log)

        icons_layout = QHBoxLayout()
        icons_layout.setSpacing(S.px(5))
        icons_layout.addWidget(self.btn_icon1)
        icons_layout.addWidget(self.btn_icon2)
        icons_layout.addWidget(self.btn_icon3)
        icons_layout.addWidget(self.btn_icon4)
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

        self._lbl_speed_eta = QLabel("")
        self._lbl_speed_eta.setObjectName("speedEtaLabel")
        self._lbl_speed_eta.setMinimumWidth(S.px(220))
        self._lbl_speed_eta.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.statusBar.addPermanentWidget(self._lbl_speed_eta)

        self.update_image_option()
        self._apply_accessible_names()

    def create_refresh_button(self):
        # create refresh button for usb device list :3
        S = self._S
        size = S.px(25)
        self.btn_refresh = QToolButton()
        self.btn_refresh.setText("")
        self.btn_refresh.setToolTip(self._T.get("tooltip_refresh", "refresh"))
        self.btn_refresh.setFixedSize(size, size)
        self.btn_refresh.clicked.connect(self.refresh_usb_devices)
        return self.btn_refresh

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
            self.log_message(f"USB scan result: {len(new_devices)} device(s) found: {list(new_devices.keys())}")

            if new_devices:
                # update device list with new devices :3
                self.usb_devices = new_devices
                self._populate_device_combo()
                self.log_message(f"Device list updated: {[f'{k} ({v})' for k, v in new_devices.items()]}")
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
                f"{self._T.get('msgbox_scan_error_body', 'Scan failed')}\n{str(e)}",
            )

    def updateFS(self):
        # update filesystem selection in states :D
        state.filesystem_index = self.combo_fs.currentIndex()
        self.log_message(f"File system changed to: {self.combo_fs.currentText()} (index={state.filesystem_index})")

    def updateflash(self):
        # update flash mode selection in states :3
        state.flash_mode = self.combo_flash.currentIndex()
        self.log_message(f"Flash option changed to: {self.combo_flash.currentText()} (index={state.flash_mode})")

    def update_image_option(self):
        # update image option and refresh available filesystems and flash modes :D
        state.image_option = self.combo_image_option.currentIndex()
        self.log_message(
            f"Image option changed to: {self.combo_image_option.currentText()} (index={state.image_option})"
        )
        self._update_filesystem_options()
        self._update_flashing_options()

    def _update_filesystem_options(self):
        # change available filesystems based on image type :3
        self.combo_fs.blockSignals(True)
        if state.image_option == 1:  # linux
            self.combo_fs.clear()
            self.combo_fs.addItems(["ext4", "FAT32", "exFAT", "UDF"])
            self.combo_fs.setCurrentText("ext4")
        elif state.image_option == 0:  # windows
            self.combo_fs.clear()
            # self.combo_fs.addItems(["NTFS", "FAT32", "exFAT"]); self.combo_fs.setCurrentText("NTFS")
            self.combo_fs.addItems(["FAT32"])
            self.combo_fs.setCurrentText("FAT32")
        elif state.image_option == 4:  # ventoy
            self.combo_fs.clear()
            self.combo_fs.addItems(["exFAT", "FAT32"])
            self.combo_fs.setCurrentText("exFAT")
        elif state.image_option in (2, 3):
            # other or format only :D
            self.combo_fs.clear()
            self.combo_fs.addItems(self.all_fs_options)
            self.combo_fs.setCurrentText("FAT32")
        self.combo_fs.blockSignals(False)
        self.updateFS()

    def _update_flashing_options(self):
        # change available flash modes based on image type :3
        self.combo_flash.blockSignals(True)
        self.combo_flash.clear()
        if state.image_option == 0:  # windows
            self.combo_flash.addItems([self._T.get("combo_flash_iso", "ISO")])
            self.combo_flash.setCurrentText(self._T.get("combo_flash_iso", "ISO"))
        elif state.image_option == 1:  # linux
            self.combo_flash.addItems([self._T.get("combo_flash_dd", "DD")])
            self.combo_flash.setCurrentText(self._T.get("combo_flash_dd", "DD"))
        elif state.image_option == 2:  # other
            self.combo_flash.addItems([self._T.get("combo_flash_dd", "DD")])
            self.combo_flash.setCurrentText(self._T.get("combo_flash_dd", "DD"))
        elif state.image_option == 3:  # format only :D
            self.combo_flash.addItems([self._T.get("combo_flash_none", "None")])
            self.combo_flash.setCurrentText(self._T.get("combo_flash_none", "None"))
        elif state.image_option == 4:  # ventoy
            self.combo_flash.addItems([self._T.get("combo_flash_ventoy", "Ventoy")])
            self.combo_flash.setCurrentText(self._T.get("combo_flash_ventoy", "Ventoy"))
        self.combo_flash.blockSignals(False)
        self.updateflash()

    # partition and target system updaters commented out :3
    # def update_partition_scheme(self):
    #    state.partition_scheme = self.combo_partition.currentIndex()
    #    self.log_message(f"Partition scheme changed to: {self.combo_partition.currentText()} (index={state.partition_scheme})")

    # def update_target_system(self):
    #    state.target_system = self.combo_target.currentIndex()
    #    self.log_message(f"Target system changed to: {self.combo_target.currentText()} (index={state.target_system})")

    def _open_url(self):
        # open github url in browser :D
        url = "https://github.com/Hog185/Lufus"
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
                    },
                )
                return
            except Exception as e:
                self.log_message(f"Failed to open URL as user: {e}", level="WARN")
        # fallback to normal browser open :D
        webbrowser.open(url)

    def update_new_label(self, current_text):
        # update volume label in states :3
        state.new_label = current_text
        self.log_message(f"Volume label set to: {current_text!r}")

    def update_cluster_size(self):
        # update cluster size selection :D
        state.cluster_size = self.combo_cluster.currentIndex()
        self.log_message(f"Cluster size changed to: {self.combo_cluster.currentText()} (index={state.cluster_size})")

    def update_QF(self):
        # update quick format setting :3
        state.quick_format = 0 if self.chk_quick.isChecked() else 1
        self.log_message(f"Quick format: {'enabled' if self.chk_quick.isChecked() else 'disabled'}")

    def update_create_extended(self):
        # update extended label creation setting :D
        state.create_extended = 0 if self.chk_extended.isChecked() else 1
        self.log_message(
            f"Create extended label/icon files: {'enabled' if self.chk_extended.isChecked() else 'disabled'}"
        )

    def _animate_widget(self, widget, show: bool, anim_attr: str):
        anim = QPropertyAnimation(widget, b"maximumHeight")
        anim.setDuration(80)

        if show:
            widget.show()  # IMPORTANT
            anim.setStartValue(0)
            anim.setEndValue(self._S.px(36))
            anim.finished.connect(lambda: widget.setMaximumHeight(16777215))
        else:
            anim.setStartValue(widget.maximumHeight())
            anim.setEndValue(0)
            anim.finished.connect(widget.hide)

        anim.start()
        setattr(self, anim_attr, anim)

    def update_check_bad(self):
        # update bad blocks check setting and enable pass selector :3
        state.check_bad = 0 if self.chk_badblocks.isChecked() else 1
        show = self.chk_badblocks.isChecked()
        self.combo_badblocks.setEnabled(show)
        self._animate_widget(self.combo_badblocks, show, "_anim_badblocks")
        self.log_message(f"Bad block check: {'enabled' if self.chk_badblocks.isChecked() else 'disabled'}")

    def update_verify_hash(self):
        # update sha256 verification setting :D
        state.verify_hash = self.chk_verify.isChecked()
        self.input_hash.setEnabled(state.verify_hash)
        if hasattr(self, "lbl_expected_hash"):
            self.lbl_expected_hash.setVisible(state.verify_hash)
        self._animate_widget(self.input_hash, state.verify_hash, "_anim_hash")
        self.log_message(f"SHA256 verification: {'enabled' if state.verify_hash else 'disabled'}")

    def update_expected_hash(self, text):
        # store expected hash for verification :3
        state.expected_hash = text.strip()

    def _load_latest_download_iso(self):
        # check downloads folder for the most recently modified iso :3
        downloads_dir = Path.home() / "Downloads"
        if not downloads_dir.is_dir():
            return
        isos = sorted(downloads_dir.glob("*.iso"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not isos:
            return
        latest = isos[0]
        file_size = latest.stat().st_size
        state.iso_path = str(latest)
        clean_name = latest.name
        self.combo_boot.setItemText(0, clean_name)
        self.input_label.setText(latest.stem.upper())
        self.log_message(f"Latest download ISO loaded: {latest}")
        self.log_message(f"Image size: {file_size:,} bytes ({file_size / (1024**3):.2f} GiB)")

    def _check_clipboard(self):
        # monitor clipboard for iso file paths :D
        clipboard = QApplication.clipboard()
        mime = clipboard.mimeData()
        if mime.hasUrls():
            for url in mime.urls():
                local_file = url.toLocalFile()
                if local_file and local_file.lower().endswith(".iso") and Path(local_file).is_file():
                    if local_file == self._last_clipboard:
                        return
                    self._last_clipboard = local_file
                    file_size = os.path.getsize(local_file)
                    state.iso_path = local_file
                    clean_name = local_file.split("/")[-1].split("\\")[-1]
                    self.combo_boot.setItemText(0, clean_name)
                    self.input_label.setText(clean_name.split(".")[0].upper())
                    self.log_message(f"Image loaded from clipboard: {local_file}")
                    self.log_message(f"Image size: {file_size:,} bytes ({file_size / (1024**3):.2f} GiB)")
                    return
        text = clipboard.text().strip()
        if text == self._last_clipboard:
            return
        self._last_clipboard = text
        path = text.strip('"').strip("'")
        if path.lower().endswith(".iso") and Path(path).is_file():
            # auto load iso from clipboard :3
            file_size = os.path.getsize(path)
            state.iso_path = path
            clean_name = path.split("/")[-1].split("\\")[-1]
            self.combo_boot.setItemText(0, clean_name)
            self.input_label.setText(clean_name.split(".")[0].upper())
            self.log_message(f"Image loaded from clipboard: {path}")
            self.log_message(f"Image size: {file_size:,} bytes ({file_size / (1024**3):.2f} GiB)")

    def dragEnterEvent(self, event):
        # accept drag of supported image files :D
        if event.mimeData().hasUrls():
            supported = [".iso", ".dmg", ".img", ".bin", ".raw"]
            if any(url.toLocalFile().lower().endswith(tuple(supported)) for url in event.mimeData().urls()):
                event.acceptProposedAction()
                return
        event.ignore()

    def dragMoveEvent(self, event):
        # accept drag move of supported image files :3
        if event.mimeData().hasUrls():
            supported = [".iso", ".dmg", ".img", ".bin", ".raw"]
            if any(url.toLocalFile().lower().endswith(tuple(supported)) for url in event.mimeData().urls()):
                event.acceptProposedAction()
                return
        event.ignore()

    def dropEvent(self, event):
        # handle dropped image files :D
        supported = [".iso", ".dmg", ".img", ".bin", ".raw"]
        img_files = [
            url.toLocalFile() for url in event.mimeData().urls() if url.toLocalFile().lower().endswith(tuple(supported))
        ]
        if img_files:
            # load first dropped image file :3
            file_name = img_files[0]
            file_size = os.path.getsize(file_name)
            state.iso_path = file_name
            clean_name = file_name.split("/")[-1].split("\\")[-1]
            self.combo_boot.setItemText(0, clean_name)
            self.input_label.setText(clean_name.split(".")[0].upper())
            self.log_message(f"Image selected via drag-and-drop: {file_name}")
            self.log_message(f"Image size: {file_size:,} bytes ({file_size / (1024**3):.2f} GiB)")
            self._detect_iso_and_update_ui(file_name)
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
            state.iso_path = file_name
            clean_name = file_name.split("/")[-1].split("\\")[-1]
            self.combo_boot.setItemText(0, clean_name)
            self.input_label.setText(clean_name.split(".")[0].upper())
            self.log_message(f"Image selected: {file_name}")
            self.log_message(f"Image size: {file_size:,} bytes ({file_size / (1024**3):.2f} GiB)")
            self._detect_iso_and_update_ui(file_name)

    def _detect_iso_and_update_ui(self, iso_path: str):
        """Automatically detect ISO type and update UI selectors."""
        from lufus.writing.windows.detect import detect_iso_type, IsoType

        # Non-ISO raw images (.img, .bin, .raw, .dmg) are always "Other / DD mode"
        if not iso_path.lower().endswith(".iso"):
            self.log_message(f"Non-ISO image ({Path(iso_path).suffix or 'no ext'}), defaulting to Other/DD mode")
            self.combo_image_option.setCurrentIndex(2)  # Other
            return

        self.log_message(f"Detecting ISO type for: {iso_path}...")
        iso_type = detect_iso_type(iso_path)

        if iso_type == IsoType.WINDOWS:
            self.log_message("Detected Windows ISO")
            self.combo_image_option.setCurrentIndex(0)  # Windows
        elif iso_type == IsoType.LINUX:
            self.log_message("Detected Linux ISO")
            self.combo_image_option.setCurrentIndex(1)  # Linux
        else:
            self.log_message("Unknown ISO type, defaulting to Other")
            self.combo_image_option.setCurrentIndex(2)  # Other

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
            html = f'<span style="color:{colour};">{escaped}</span>' if colour else f"<span>{escaped}</span>"
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
            html = f'<span style="color:{colour};">{escaped}</span>' if colour else f"<span>{escaped}</span>"
            self.log_window.log_text.append(html)
            scrollbar = self.log_window.log_text.verticalScrollBar()
            scrollbar.setValue(scrollbar.maximum())

    def show_about(self):
        # show about dialog :3
        if self.about_window:
            self.about_window.close()
        self.about_window = AboutWindow(self)
        content = self._T.get("about_content", "Lufus - USB Flash Tool\n\nA simple, open-source USB flashing utility.")
        flat = getattr(self, "_flat_theme", {})
        font_family = flat.get("fonts_family", "")
        fg_color = flat.get("colors_fg", "")

        if not content.strip().startswith("<"):
            html_content = content.replace("\n", "<br>")
            self.about_window.about_text.setHtml(
                f"<div style='font-family:{font_family}; color:{fg_color}; padding:4px;'>{html_content}</div>"
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
        # set active theme by name and re-apply styles :D
        user_config_dir_path = Path(user_config_dir("Lufus"))
        builtin_json = THEME_DIR / theme_name / f"{theme_name}_theme.json"
        user_json = user_config_dir_path / "themes" / theme_name / f"{theme_name}_theme.json"
        if builtin_json.exists() or user_json.exists():
            state.theme = theme_name
            # persist so it survives restarts without needing the env var :3
            try:
                _theme_cfg = user_config_dir_path / "active_theme"
                _theme_cfg.parent.mkdir(parents=True, exist_ok=True)
                _theme_cfg.write_text(theme_name, encoding="utf-8")
            except Exception:
                pass
            self._apply_styles()
            self.log_message(f"Theme changed to: {theme_name}")
            if self.about_window and self.about_window.isVisible():
                self.show_about()

    def apply_language(self, language):
        # change language and update all ui text :D
        self.current_language = language
        state.language = language
        self._T = load_translations(language)
        self._update_ui_text()
        self.log_message(f"Language changed to: {language}")

    def _update_ui_text(self):
        # update all text labels with new translations :3
        self.setWindowTitle(self._T.get("window_title", "lufus"))
        self.lbl_header_drive.setText(self._T.get("header_drive_properties", "Drive Properties"))
        self.lbl_header_format.setText(self._T.get("header_format_options", "Format Options"))
        self.lbl_header_status.setText(self._T.get("header_status", "Status"))
        self.lbl_device.setText(self._T.get("lbl_device", "Device"))
        self.lbl_boot.setText(self._T.get("lbl_boot_selection", "Boot Selection"))
        self.btn_select.setText(self._T.get("btn_select", "Select"))
        self.lbl_image.setText(self._T.get("lbl_image_option", "Image Option"))
        # self.lbl_part.setText(self._T.get("lbl_partition_scheme", "Partition Scheme"))
        # self.lbl_target.setText(self._T.get("lbl_target_system", "Target System"))
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

        # update toolbar button tooltips :3
        self.btn_refresh.setToolTip(self._T.get("tooltip_refresh", "Refresh USB devices (Ctrl+R)"))
        self.btn_icon1.setToolTip(self._T.get("tooltip_website", "Website"))
        self.btn_icon2.setToolTip(self._T.get("tooltip_about", "About"))
        self.btn_icon3.setToolTip(self._T.get("tooltip_settings", "Settings"))
        self.btn_icon4.setToolTip(self._T.get("tooltip_log", "Log"))

        # update image option combo :D
        current_img_idx = self.combo_image_option.currentIndex()
        self.combo_image_option.blockSignals(True)
        self.combo_image_option.clear()
        self.combo_image_option.addItem(self._T.get("combo_image_windows", "Windows"))
        self.combo_image_option.addItem(self._T.get("combo_image_linux", "Linux"))
        self.combo_image_option.addItem(self._T.get("combo_image_other", "Other"))
        self.combo_image_option.addItem(self._T.get("combo_image_format", "Format Only"))
        # self.combo_image_option.addItem(self._T.get("combo_image_ventoy", "Ventoy"))
        self.combo_image_option.setCurrentIndex(current_img_idx)
        self.combo_image_option.blockSignals(False)

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
        self.lbl_expected_hash.setText(self._T.get("lbl_expected_hash", "Expected SHA256:"))
        self.input_hash.setPlaceholderText(self._T.get("input_hash_placeholder", "Enter expected SHA256 hash here..."))
        self.input_label.setPlaceholderText(self._T.get("lbl_volume_label", "Volume Label"))

        # update boot combo default text :3
        if self.combo_boot.itemText(0) == "installation_media.iso" or self.combo_boot.itemText(0) == self._T.get(
            "combo_boot_default", "installation_media.iso"
        ):
            self.combo_boot.setItemText(0, self._T.get("combo_boot_default", "installation_media.iso"))

        if not self.usb_devices:
            # update no devices message :D
            self.combo_device.clear()
            self.combo_device.addItem(self._T.get("no_usb_found", "No USB devices found"), None)
        self._update_flashing_options()
        self._apply_accessible_names()

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
            self.progress_bar.setRange(0, 100)  # exit indeterminate mode
            self.progress_bar.setValue(0)
            self.progress_bar.setFormat("")
            self.btn_start.setEnabled(True)
            self.btn_cancel.setEnabled(False)
            self.statusBar.showMessage(self._T.get("status_ready", "Ready"), 0)
            self._clear_speed_eta()
            self.log_message("Flash process cancelled by user", level="WARN")

    def start_process(self):
        # start flashing process with validation :3
        state.device_node = self.combo_device.currentData() or ""
        self.log_message(
            f"Start process triggered: image_option={state.image_option}, flash_mode={state.flash_mode}, device={state.device_node}"
        )

        if state.image_option in [0, 1, 2]:
            # validate image path exists :D
            if not state.iso_path or not Path(state.iso_path).exists():
                self.log_message("Start aborted: no valid image path set", level="WARN")
                QMessageBox.warning(
                    self,
                    self._T.get("msgbox_no_image_title", "No Image"),
                    self._T.get("msgbox_no_image_body", "Please select an image file"),
                )
                return

        # validate device selected
        device_node = self.get_selected_mount_path()
        if not device_node:
            self.log_message("Start aborted: no USB device selected", level="WARN")
            QMessageBox.warning(
                self,
                self._T.get("msgbox_no_device_title", "No Device"),
                self._T.get("msgbox_no_device_body", "Please select a USB device"),
            )
            return

        if state.image_option in [0, 1, 2] and state.verify_hash:
            # validate sha256 hash format
            h = state.expected_hash.strip().lower()
            if len(h) != 64 or not all(c in "0123456789abcdef" for c in h):
                self.log_message("Start aborted: invalid SHA256 hash format", level="WARN")
                QMessageBox.warning(
                    self,
                    self._T.get("msgbox_invalid_hash_title", "Invalid Hash"),
                    self._T.get("msgbox_invalid_hash_body", "The provided SHA256 hash is invalid."),
                )
                return

            # start verification worker :D
            self.btn_start.setEnabled(False)
            self.btn_cancel.setEnabled(True)
            self.progress_bar.setRange(0, 0)
            self.progress_bar.setValue(0)
            self.progress_bar.setFormat(self._T.get("progress_verifying", "Verifying..."))
            self._flash_start_time = time.monotonic()
            self._flash_total_bytes = os.path.getsize(state.iso_path) if Path(state.iso_path).exists() else 0
            # if you are reading this, fuck you
            self.verify_worker = VerifyWorker(state.iso_path, state.expected_hash)
            self.verify_worker.progress.connect(self.log_message)
            self.verify_worker.int_progress.connect(self._on_progress, Qt.ConnectionType.QueuedConnection)
            self.verify_worker.flash_done.connect(self.on_verify_finished)
            self._speed_timer.start()
            self.verify_worker.start()
        else:
            # skip verification and start flash :3
            if states.image_option == 0 and states.currentflash == 0:
                dlg = WinTweaks(self)
                if dlg.exec() == QDialog.DialogCode.Rejected:
                    return
            self.perform_flash()

    def on_verify_finished(self, success: bool):
        # handle verification result :D
        if success:
            self.log_message("SHA256 verification successful, proceeding to flash")
            self._clear_speed_eta()
            if states.image_option == 0 and states.currentflash == 0:
                dlg = WinTweaks(self)
                if dlg.exec() == QDialog.DialogCode.Rejected:
                    self.btn_start.setEnabled(True)
                    self.btn_cancel.setEnabled(False)
                    self.progress_bar.setValue(0)
                    self.progress_bar.setFormat("")
                    return
            self.perform_flash()
        else:
            # verification failed  (╯°□°)╯( ┻━┻
            self.log_message("SHA256 verification FAILED", level="ERROR")
            QMessageBox.critical(
                self,
                self._T.get("msgbox_verify_fail_title", "Verification Failed"),
                self._T.get("msgbox_verify_fail_body", "SHA256 checksum mismatch!"),
            )
            self.btn_start.setEnabled(True)
            self.btn_cancel.setEnabled(False)
            self.progress_bar.setValue(0)
            self.progress_bar.setFormat("")
            self._clear_speed_eta()

    def perform_flash(self):
        # perform actual flash operation :D
        options = {
            "iso_path": state.iso_path,
            "device": self.get_selected_mount_path(),
            "image_option": state.image_option,
            "flash_mode": state.flash_mode,
            "currentflash": state.flash_mode,  # for backward compatibility in workers if needed
            "filesystem_index": state.filesystem_index,
            "fs_text": self.combo_fs.currentText(),
            "cluster_size": state.cluster_size,
            "quick_format": state.quick_format,
            "create_extended": state.create_extended,
            "check_bad": state.check_bad,
            "new_label": state.new_label,
            "verify_hash": state.verify_hash,
            "expected_hash": state.expected_hash,
        }

        # Root elevation is now handled at startup in start_gui.py.
        # We assume we have root here, or the user chose to run without it.

        # already root start flash worker :D
        iso_path = options.get("iso_path", "")
        self._flash_start_time = time.monotonic()
        self._flash_total_bytes = os.path.getsize(iso_path) if iso_path and Path(iso_path).exists() else 0
        self.log_message(
            f"Starting flash thread: image_option={options['image_option']}, flash_mode={options['flash_mode']}, device={options['device']}"
        )
        self.flash_worker = FlashWorker(options, self._T)
        self.flash_worker.progress.connect(self._on_progress, Qt.ConnectionType.QueuedConnection)
        self.flash_worker.status.connect(self._on_flash_status, Qt.ConnectionType.QueuedConnection)
        self.flash_worker.flash_done.connect(self.on_flash_finished, Qt.ConnectionType.QueuedConnection)
        self.flash_worker.request_tweaks.connect(self.show_tweak_dialog, Qt.ConnectionType.QueuedConnection)
        self.flash_worker.start()
        self.btn_start.setEnabled(False)
        self.btn_cancel.setEnabled(True)
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setValue(0)
        self._speed_timer.start()
        self.statusBar.showMessage(self._T.get("status_flashing", "Flashing..."), 0)

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
            self.log_message(
                f"Auto-flash triggered: device={options.get('device')}, image_option={options.get('image_option')}"
            )
            self._start_flash_with_options(options)
        except Exception as e:
            self.log_message(f"Auto-flash failed to load options: {e}", level="ERROR")

    def _start_flash_with_options(self, options: dict) -> None:
        # start flashworker directly with prebuilt options dict :3
        iso_path = options.get("iso_path", "")
        self._flash_start_time = time.monotonic()
        self._flash_total_bytes = os.path.getsize(iso_path) if iso_path and Path(iso_path).exists() else 0
        self.log_message(
            f"Starting flash: image_option={options['image_option']}, flash_mode={options['flash_mode']}, device={options['device']}"
        )
        self.flash_worker = FlashWorker(options, self._T)
        self.flash_worker.progress.connect(self._on_progress, Qt.ConnectionType.QueuedConnection)
        self.flash_worker.status.connect(self._on_flash_status, Qt.ConnectionType.QueuedConnection)
        self.flash_worker.flash_done.connect(self.on_flash_finished, Qt.ConnectionType.QueuedConnection)
        self.flash_worker.request_tweaks.connect(self.show_tweak_dialog, Qt.ConnectionType.QueuedConnection)
        self.flash_worker.start()
        self.btn_start.setEnabled(False)
        self.btn_cancel.setEnabled(True)
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setValue(0)
        self._speed_timer.start()
        self.statusBar.showMessage(self._T.get("status_flashing", "Flashing..."), 0)

    def _on_flash_status(self, msg):
        # update status bar and log with flash status :D
        self.log_message(msg)
        self.statusBar.showMessage(msg, 0)

    def on_flash_finished(self, success: bool):
        # handle flash completion :3
        if self.flash_worker is not None:
            self.flash_worker.wait()
        # restore determinate mode in case we were in indeterminate :D
        self.progress_bar.setRange(0, 100)
        if success:
            # flash succeeded :D
            self.progress_bar.setValue(100)
            self.progress_bar.setFormat(self._T.get("progress_complete", "Complete"))
            # change from fo to tweaks
            self.log_message("Flash operation finished with result: SUCCESS")
            if states.image_option == 0 and states.currentflash == 0:
                if getattr(states, "win_hardware_bypass", 0) == 1:
                    win_hardware_bypass()
                if getattr(states, "win_microsoft_acc", 0) == 1:
                    if getattr(states, "win_local_acc_chk", 0) == 1:
                        win_local_acc_name()
                    else:
                        win_local_acc()
                if getattr(states, "win_privacy", 0) == 1:
                    win_skip_privacy_questions()
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
        self._clear_speed_eta()

    def _on_progress(self, pct: int) -> None:
        # route progress signal: switch out of indeterminate mode on first real value
        if pct > 0 and self.progress_bar.maximum() == 0:
            self.progress_bar.setRange(0, 100)
        self._last_progress_pct = pct
        self.progress_bar.setValue(pct)
        self._update_speed_eta(pct)

    def _tick_speed_eta(self) -> None:
        # periodic timer tick to keep speed/eta display fresh between progress signals
        self._update_speed_eta(self._last_progress_pct)

    def _update_speed_eta(self, pct: int) -> None:
        if self._flash_start_time is None or pct <= 0:
            return
        now = time.monotonic()
        elapsed = now - self._flash_start_time
        if elapsed < 0.5:
            return
        if self._flash_total_bytes > 0:
            bytes_done = int(pct / 100 * self._flash_total_bytes)
            # rolling 8-second window for stable speed estimation
            self._speed_samples.append((now, bytes_done))
            cutoff = now - 8.0
            self._speed_samples = [(t, b) for t, b in self._speed_samples if t >= cutoff]
            if len(self._speed_samples) >= 2:
                dt = self._speed_samples[-1][0] - self._speed_samples[0][0]
                db = self._speed_samples[-1][1] - self._speed_samples[0][1]
                if dt > 0 and db > 0:
                    speed = db / dt
                    remaining = self._flash_total_bytes - bytes_done
                    eta_sec = remaining / speed
                    if speed >= 1024 * 1024:
                        speed_str = f"{speed / (1024 * 1024):.1f} MB/s"
                    elif speed >= 1024:
                        speed_str = f"{speed / 1024:.1f} KB/s"
                    else:
                        speed_str = f"{speed:.0f} B/s"
                    if eta_sec >= 3600:
                        eta_str = f"{int(eta_sec // 3600)}h {int((eta_sec % 3600) // 60)}m"
                    elif eta_sec >= 60:
                        eta_str = f"{int(eta_sec // 60)}m {int(eta_sec % 60)}s"
                    else:
                        eta_str = f"{int(eta_sec)}s"
                    self._lbl_speed_eta.setText(f"{speed_str}  ETA {eta_str}")

    def _clear_speed_eta(self) -> None:
        self._flash_start_time = None
        self._flash_total_bytes = 0
        self._last_progress_pct = 0
        self._speed_samples = []
        self._speed_timer.stop()
        self._lbl_speed_eta.setText("")

    def _apply_accessible_names(self) -> None:
        self.combo_device.setAccessibleName(self._T.get("acc_device", "Device selector"))
        self.combo_device.setAccessibleDescription(self._T.get("acc_device_desc", "Select the USB device to flash"))
        self.btn_refresh.setAccessibleName(self._T.get("acc_refresh", "Refresh devices"))
        self.btn_refresh.setAccessibleDescription(self._T.get("acc_refresh_desc", "Scan for connected USB devices"))
        self.combo_boot.setAccessibleName(self._T.get("acc_boot", "Boot image selector"))
        self.combo_boot.setAccessibleDescription(
            self._T.get("acc_boot_desc", "Shows the currently selected boot image file")
        )
        self.btn_select.setAccessibleName(self._T.get("acc_select", "Browse for image file"))
        self.combo_image_option.setAccessibleName(self._T.get("acc_image_option", "Image option selector"))
        self.combo_image_option.setAccessibleDescription(
            self._T.get(
                "acc_image_option_desc", "Choose the type of image to write: Windows, Linux, Other, or Format Only"
            )
        )
        self.input_label.setAccessibleName(self._T.get("acc_volume_label", "Volume label input"))
        self.input_label.setAccessibleDescription(
            self._T.get("acc_volume_label_desc", "Enter a name for the USB volume")
        )
        self.combo_fs.setAccessibleName(self._T.get("acc_filesystem", "File system selector"))
        self.combo_cluster.setAccessibleName(self._T.get("acc_cluster", "Cluster size selector"))
        self.combo_flash.setAccessibleName(self._T.get("acc_flash_option", "Flash method selector"))
        self.chk_quick.setAccessibleName(self._T.get("acc_quick_format", "Quick format checkbox"))
        self.chk_extended.setAccessibleName(self._T.get("acc_extended_label", "Create extended label checkbox"))
        self.chk_badblocks.setAccessibleName(self._T.get("acc_bad_blocks", "Check for bad blocks checkbox"))
        self.combo_badblocks.setAccessibleName(self._T.get("acc_bad_blocks_passes", "Bad block check passes selector"))
        self.chk_verify.setAccessibleName(self._T.get("acc_verify_hash", "Verify SHA256 checksum checkbox"))
        self.input_hash.setAccessibleName(self._T.get("acc_hash_input", "Expected SHA256 hash input"))
        self.input_hash.setAccessibleDescription(
            self._T.get("acc_hash_input_desc", "Paste the expected 64-character SHA256 hash here")
        )
        self.progress_bar.setAccessibleName(self._T.get("acc_progress", "Operation progress bar"))
        self.btn_start.setAccessibleName(self._T.get("acc_start", "Start operation"))
        self.btn_cancel.setAccessibleName(self._T.get("acc_cancel", "Cancel operation"))
        self.btn_icon1.setAccessibleName(self._T.get("acc_website", "Open Lufus website"))
        self.btn_icon2.setAccessibleName(self._T.get("acc_about", "About Lufus"))
        self.btn_icon3.setAccessibleName(self._T.get("acc_settings", "Open settings"))
        self.btn_icon4.setAccessibleName(self._T.get("acc_log", "Open log window"))

    def keyPressEvent(self, event):
        # handle keyboard shortcuts :3
        if event.key() == Qt.Key.Key_R and event.modifiers() == Qt.KeyboardModifier.ControlModifier:
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
                "polkit-1-agent",
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

    def get_latest_release(self):
        owner = "Hog185"
        repo = "Lufus"
        url = f"https://api.github.com/repos/{owner}/{repo}/releases/latest"
        current_version = state.version
        try:
            ssl_ctx = ssl.create_default_context()
            req = urllib.request.urlopen(url, timeout=5, context=ssl_ctx)
            if req.status == 200:
                data = json.loads(req.read().decode())
                tag_name = data.get("tag_name", "")
                if not tag_name:
                    self.log_message("Update check: missing tag_name in API response", level="WARNING")
                    return
                try:
                    is_newer = version.parse(tag_name) > version.parse(current_version)
                except Exception:
                    self.log_message(f"Update check: could not parse version tag {tag_name!r}", level="WARNING")
                    return
                if is_newer:
                    self.log_message(f"New version found: {tag_name} > {current_version}", level="DEBUG")
                else:
                    self.log_message(f"Running latest release build: {tag_name} <= {current_version}", level="INFO")
                    return
            else:
                self.log_message(f"Couldn't get latest release, response: {req.status}", level="WARNING")
                return
        except Exception as e:
            self.log_message(f"Update check failed: {e}", level="ERROR")
            return
        newupdate = QMessageBox(self)
        newupdate.setWindowTitle("New Update Available!")
        newupdate.setText(f"A new version ({data.get('tag_name', '?')}) is available!")
        newupdate.setInformativeText(f"Would you like to download {data.get('name', 'it')} now?")
        download_btn = newupdate.addButton(QMessageBox.StandardButton.Apply)
        download_btn.setText("Download Now")
        later_btn = newupdate.addButton(QMessageBox.StandardButton.Discard)
        later_btn.setText("Later")
        newupdate.setIcon(QMessageBox.Icon.Information)
        newupdate.exec()
        if newupdate.clickedButton() == download_btn:
            self.log_message(f"New update download button clicked", level="DEBUG")
            webbrowser.open("https://github.com/Hog185/Lufus/releases")
        else:
            self.log_message(f"download later button clicked", level="DEBUG")

    # for win twaks
    def show_tweak_dialog(self):
        dialog = WinTweaks(self)
        dialog.exec()


if __name__ == "__main__":
    # setup high dpi scaling :3
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)

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
    window = LufusWindow(usb_devices)
    window.show()
    sys.exit(app.exec())  # oink meow meow meow :3
