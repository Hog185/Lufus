import sys
import json
from glob import glob
import urllib.parse
import webbrowser
from pathlib import Path
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QGridLayout, QLabel, QComboBox, 
                             QPushButton, QProgressBar, QCheckBox, 
                             QMessageBox, QDialog, QTextEdit, QFileDialog,
                             QLineEdit, QFrame, QStatusBar, QToolButton, QSpacerItem)
from PyQt6.QtCore import Qt, QTimer, QThread, pyqtSignal, QPoint, QPropertyAnimation, QEasingCurve
from PyQt6.QtGui import QFont

from lufus.drives import states
from lufus.drives import formatting as fo
from lufus.writing.flash_usb import FlashUSB
from lufus.writing.flash_woeusb import flash_woeusb
from lufus.drives.find_usb import find_usb
from lufus.drives.autodetect_usb import UsbMonitor


class LogWindow(QDialog):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("lufus Log")
        self.resize(650, 450)
        layout = QVBoxLayout()
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setFont(QFont("Consolas", 9))
        self.log_text.setStyleSheet("background-color: white; border: 1px solid #ccc;")
        layout.addWidget(self.log_text)
        self.setLayout(layout)

class Notification(QFrame):
    def __init__(self, message, notification_type="info", duration=3000, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | 
                           Qt.WindowType.Tool | 
                           Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)   
        
        colors = {
            'info': '#3498db',
            'success': '#2ecc71',
        }
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        self.label = QLabel(message)
        self.label.setWordWrap(True)
        self.label.setStyleSheet(f"""
            QLabel {{
                background-color: {colors.get(notification_type.lower(), '#333333')};
                color: white;
                padding: 15px 25px;
                border-radius: 8px;
                font-size: 14px;
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
    def __init__(self, parent=None):
        self.parent = parent
        self.notifications = []
    
    def show(self, message, notification_type='info', duration=3000):
        notification = Notification(message, notification_type, duration, self.parent)
        self.notifications.append(notification)
        notification.position_notification(len(self.notifications) - 1)
        notification.show()
        notification.destroyed.connect(lambda: self.notifications.remove(notification))

class AboutWindow(QDialog):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("About")
        self.resize(650, 450)
        layout = QVBoxLayout()
        self.about_text = QTextEdit()
        self.about_text.setReadOnly(True)
        self.about_text.setFont(QFont("Consolas", 9))
        self.about_text.setStyleSheet("background-color: white; border: 1px solid #ccc;")
        layout.addWidget(self.about_text)
        self.setLayout(layout)


class FlashWorker(QThread):
    """Worker thread for flashing ISO to USB without freezing UI"""
    finished = pyqtSignal(bool)
    progress = pyqtSignal(str)
    progress_value = pyqtSignal(int)
    
    def __init__(self, iso_path: str, device_node: str):
        super().__init__()
        self.iso_path = iso_path
        self.device_node = device_node
    
    def run(self):
        try:
            self.progress.emit("Unmounting drive...")
            self.progress_value.emit(2)
            for partition in glob(f"{self.device_node}*"):
                fo.unmount(partition)
            
            self.progress.emit("Flashing ISO to device...")
            self.progress_value.emit(5)
            result = FlashUSB(self.iso_path, self.device_node, progress_cb=self.progress_value.emit, status_cb=self.progress.emit)
            
            if result:
                self.progress.emit("Flashing complete!")
            else:
                self.progress.emit("Flash failed.")
            
            self.finished.emit(result)
        except Exception as e:
            self.progress.emit(f"Error: {str(e)}")
            self.finished.emit(False)


class WoeUSBWorker(QThread):
    finished = pyqtSignal(bool)
    progress = pyqtSignal(str)
    progress_value = pyqtSignal(int)

    def __init__(self, iso_path: str, device_node: str):
        super().__init__()
        self.iso_path = iso_path
        self.device_node = device_node

    def run(self):
        try:
            self.progress.emit("Unmounting drive...")
            self.progress_value.emit(2)
            for partition in glob(f"{self.device_node}*"):
                fo.unmount(partition)

            self.progress.emit("Flashing with woeusb...")
            self.progress_value.emit(5)
            result = flash_woeusb(
                self.device_node,
                self.iso_path,
                progress_cb=self.progress_value.emit,
                status_cb=self.progress.emit,
            )

            if result:
                self.progress.emit("Flashing complete!")
            else:
                self.progress.emit("Flash failed.")

            self.finished.emit(result)
        except Exception as e:
            self.progress.emit(f"Error: {str(e)}")
            self.finished.emit(False)


class lufus(QMainWindow):
    def __init__(self, usb_devices=None):
        super().__init__()
        self.monitor = UsbMonitor()
        self.monitor.device_added.connect(self.on_usb_added)
        self.monitor.device_list_updated.connect(self.update_usb_list)
        
        self.usb_devices = usb_devices or {}
        self.setWindowTitle("lufus")
        self.setFixedSize(640, 690)
        self.flash_worker = None
        self.log_window = None
        self.about_window = None
        
        self._apply_styles()
        self.init_ui()

        self.notifier = NotificationManager(self)

    def _apply_styles(self):
        """Apply stylesheet to the main window"""
        self.setStyleSheet("""
            QMainWindow {
                background-color: #F0F0F0;
                font-family: 'Segoe UI', Tahoma, sans-serif;
                font-size: 9pt;
                color: #000000;
            }
            QLabel {
                color: #000000;
                padding: 2px;
            }
            QLabel#sectionHeader {
                font-size: 16pt;
                font-weight: normal;
                color: #000000;
                padding: 5px 0;
            }
            QComboBox, QLineEdit {
                border: 1px solid #D0D0D0;
                border-radius: 2px;
                padding: 4px 6px;
                background-color: white;
                min-height: 24px;
                max-height: 24px;
                font-size: 9pt;
                selection-background-color: #0078D7;
            }
            QComboBox:focus, QLineEdit:focus {
                border: 1px solid #0078D7;
            }
            QComboBox::drop-down {
                width: 20px;
                border-left: 1px solid #D0D0D0;
            }
            QPushButton {
                background-color: #E1E1E1;
                border: 1px solid #A0A0A0;
                border-radius: 2px;
                padding: 4px 15px;
                min-height: 20px;
                max-height: 20px;
                min-width: 100px;
                max-width: 100px;
                font-size: 9pt;
            }
            QPushButton:hover {
                background-color: #E5F1FB;
                border-color: #0078D7;
            }
            QPushButton:pressed {
                background-color: #D0D0D0;
            }
            QPushButton:disabled {
                color: #888888;
                background-color: #F0F0F0;
                border-color: #D0D0D0;
            }
            #btnStart {
                background-color: #E1E1E1;
                border: 1px solid #A0A0A0;
                border-radius: 2px;
                min-height: 20px;
                max-height: 20px;
                min-width: 100px;
                max-width: 100px;
                padding: 4px 15px;
                font-size: 9pt;
            }
            #btnStart:hover {
                background-color: #E5F1FB;
                border-color: #0078D7;
            }
            #btnStart:pressed {
                background-color: #00AA00;
            }
            #btnStart:disabled {
                color: #888888;
                background-color: #F0F0F0;
                border-color: #D0D0D0;
            }
            QCheckBox {
                spacing: 2px;
                font-size: 8pt;
                max-height:12px
                max-width:12px
            }
            QProgressBar {
                border: 1px solid #A0A0A0;
                border-radius: 2px;
                text-align: center;
                background-color: white;
                height: 22px;
                font-size: 9pt;
                color: white;
                font-weight: bold;
            }
            QProgressBar::chunk {
                background-color: #00CC00;
            }
            QToolButton {
                border: 1px solid #D0D0D0;
                background-color: white;
                border-radius: 2px;
                padding: 4px;
                min-width: 32px;
                max-width: 32px;
                min-height: 32px;
                max-height: 32px;
                font-size: 18px;
            }
            QToolButton:hover {
                background-color: #E5F1FB;
                border-color: #0078D7;
            }
            QToolButton:pressed {
                background-color: #D0D0D0;
            }
            QStatusBar {
                background-color: #F0F0F0;
                border-top: 1px solid #D0D0D0;
                font-size: 9pt;
                color: #000000;
            }
            QLabel#linkLabel {
                color: #000000;
                text-decoration: none;
                font-size: 9pt;
            }
            QLabel#linkLabel:hover {
                color: #0078D7;
                text-decoration: underline;
            }
        """)



    def create_header(self, text):
        """Create a section header with a horizontal line"""
        layout = QHBoxLayout()
        layout.setContentsMargins(0, 10, 0, 5)
        label = QLabel(text)
        label.setObjectName("sectionHeader")
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        line.setStyleSheet("background-color: #000000; min-height: 1px; max-height: 1px;")
        layout.addWidget(label)
        layout.addWidget(line, 1)
        return layout
    
    def update_usb_list(self,devices:dict):
        self.combo_device.clear()
        self.usb_devices=devices
        
        if not devices:
            self.combo_device.addItem("No USB devices found", None)
            return

        for node, label in devices.items():
            display = f"{label} ({node})" if label != node else node
            self.combo_device.addItem(display, node) 

    def on_usb_added(self, node):
        self.notifier.show(f"✓ {node} connected", notification_type='success', duration=3000)

    def create_refresh_button(self):
        btn = QToolButton()
        btn.setText("🔄")
        btn.setToolTip("Refresh USB devices (Ctrl+R)")
        btn.setStyleSheet("""
            QToolButton {
                border: 1px solid #D0D0D0;
                background-color: white;
                font-size: 15px;
                max-height: 25px;
                min-height: 25px;
                max-width: 25px;
                min-width: 25px;
            }
            QToolButton:hover {
                background-color: #E5F1FB;
                border-color: #0078D7;
            }
            QToolButton:pressed {
                background-color: #D0D0D0;
            }
        """)
        btn.clicked.connect(self.refresh_usb_devices)
        return btn

    def init_ui(self):
        """Initialize the user interface"""
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout()
        main_layout.setSpacing(0)
        main_layout.setContentsMargins(15, 10, 15, 10)

        main_layout.addLayout(self.create_header("Drive Properties"))

        lbl_device = QLabel("Device")
        lbl_device.setStyleSheet("font-weight: normal; font-size: 9pt; padding-bottom: 2px;")
        self.combo_device = QComboBox()
        
        self._populate_device_combo()
        
        btn_refresh = self.create_refresh_button()
        
        device_row = QHBoxLayout()
        device_row.setSpacing(5)
        device_row.addWidget(self.combo_device, 1)
        device_row.addWidget(btn_refresh)
        
        device_layout = QVBoxLayout()
        device_layout.setSpacing(2)
        device_layout.addWidget(lbl_device)
        device_layout.addLayout(device_row)
        main_layout.addLayout(device_layout)

        # Boot selection
        lbl_boot = QLabel("Boot selection")
        lbl_boot.setStyleSheet("font-weight: normal; font-size: 9pt; padding-bottom: 2px;")
        
        boot_row = QHBoxLayout()
        boot_row.setSpacing(5)
        
        self.combo_boot = QComboBox()
        self.combo_boot.setEditable(True)
        self.combo_boot.lineEdit().setReadOnly(True)
        self.combo_boot.addItem("installationmedia.iso")
        
        lbl_check = QLabel("✓") 
        lbl_check.setStyleSheet("font-size: 14pt; color: #666; padding: 0 5px;")
        
        btn_select = QPushButton("SELECT")
        btn_select.clicked.connect(self.browse_file)
        
        boot_row.addWidget(self.combo_boot, 1)
        boot_row.addWidget(lbl_check)
        boot_row.addWidget(btn_select)
        
        boot_layout = QVBoxLayout()
        boot_layout.setSpacing(2)
        boot_layout.addWidget(lbl_boot)
        boot_layout.addLayout(boot_row)
        main_layout.addLayout(boot_layout)

        # Image option
        lbl_image = QLabel("Image option")
        lbl_image.setStyleSheet("font-weight: normal; font-size: 9pt; padding-bottom: 2px;")
        self.combo_image_option = QComboBox()
        self.combo_image_option.addItem("Standard Windows installation")
        #self.combo_image_option.addItem("Windows To Go")
        self.combo_image_option.addItem("Standard Linux")
        self.combo_image_option.addItem("Only Formatting Mode")
        self.combo_image_option.currentTextChanged.connect(self.update_image_option)

        image_layout = QVBoxLayout()
        image_layout.setSpacing(2)
        image_layout.addWidget(lbl_image)
        image_layout.addWidget(self.combo_image_option)
        main_layout.addLayout(image_layout)

        # Partition scheme and target system
        grid_part = QGridLayout()
        grid_part.setSpacing(10)
        grid_part.setColumnStretch(1, 1)
        grid_part.setColumnStretch(3, 1)
        
        lbl_part = QLabel("Partition scheme")
        lbl_part.setStyleSheet("font-weight: normal; font-size: 9pt;")
        self.combo_partition = QComboBox()
        self.combo_partition.addItem("GPT")
        self.combo_partition.addItem("MBR")
        self.combo_partition.currentTextChanged.connect(self.update_partition_scheme)

        lbl_target = QLabel("Target system")
        lbl_target.setStyleSheet("font-weight: normal; font-size: 9pt;")
        self.combo_target = QComboBox()
        self.combo_target.addItem("UEFI (non CSM)")
        self.combo_target.addItem("BIOS (or UEFI-CSM)")
        self.combo_target.currentTextChanged.connect(self.update_target_system)

        grid_part.addWidget(lbl_part, 0, 0)
        grid_part.addWidget(self.combo_partition, 1, 0)
        grid_part.addWidget(lbl_target, 0, 2)
        grid_part.addWidget(self.combo_target, 1, 2)
        main_layout.addLayout(grid_part)
        
        main_layout.addSpacing(15)

        # === FORMAT OPTIONS ===
        main_layout.addLayout(self.create_header("Format Options"))

        # Volume label
        lbl_vol = QLabel("Volume label")
        lbl_vol.setStyleSheet("font-weight: normal; font-size: 9pt; padding-bottom: 2px;")
        self.input_label = QLineEdit("Volume label")
        self.input_label.textChanged.connect(self.update_new_label)
        
        vol_layout = QVBoxLayout()
        vol_layout.setSpacing(2)
        vol_layout.addWidget(lbl_vol)
        vol_layout.addWidget(self.input_label)
        main_layout.addLayout(vol_layout)

        # File system and cluster size
        grid_fmt = QGridLayout()
        grid_fmt.setSpacing(10)
        grid_fmt.setColumnStretch(1, 1)
        grid_fmt.setColumnStretch(3, 1)
        
        lbl_fs = QLabel("File system")
        lbl_fs.setStyleSheet("font-weight: normal; font-size: 9pt;")
        self.combo_fs = QComboBox()
        self.all_fs_options = ["NTFS", "FAT32", "exFAT", "ext4", "UDF"]
        self.combo_fs.addItems(self.all_fs_options)
        self.combo_fs.currentTextChanged.connect(self.updateFS)

        lbl_flash = QLabel("Flash option")
        lbl_flash.setStyleSheet("font-weight: normal; font-size: 9pt;")
        self.combo_flash = QComboBox()
        self.all_flash_options = ["Iso Mode","Woe USB","Ventoy","DD"]
        self.combo_flash.addItems(self.all_flash_options)
        self.combo_flash.currentTextChanged.connect(self.updateflash)
        
        lbl_cluster = QLabel("Cluster size")
        lbl_cluster.setStyleSheet("font-weight: normal; font-size: 9pt;")
        self.combo_cluster = QComboBox()
        self.combo_cluster.addItem("4096 bytes (Default)")
        self.combo_cluster.addItem("8192 bytes")
        self.combo_cluster.currentTextChanged.connect(self.update_cluster_size)
        
        grid_fmt.addWidget(lbl_fs, 0, 0)
        grid_fmt.addWidget(self.combo_fs, 1, 0)
        grid_fmt.addWidget(lbl_flash, 0, 5)
        grid_fmt.addWidget(self.combo_flash, 1, 5)
        grid_fmt.addWidget(lbl_cluster, 0, 2)
        grid_fmt.addWidget(self.combo_cluster, 1, 2)
        main_layout.addLayout(grid_fmt)

        # Checkboxes
        self.chk_quick = QCheckBox("Quick format")
        self.chk_quick.setChecked(True)
        self.chk_quick.stateChanged.connect(self.update_QF)

        self.chk_extended = QCheckBox("Create extended label and icon files")
        self.chk_extended.setChecked(True)
        self.chk_extended.stateChanged.connect(self.update_create_extended)
        
        bad_blocks_row = QHBoxLayout()
        self.chk_badblocks = QCheckBox("Check device for bad blocks")
        self.combo_badblocks = QComboBox()
        self.combo_badblocks.addItem("1 pass")
        self.combo_badblocks.setFixedWidth(100)
        self.combo_badblocks.setEnabled(False)
        self.chk_badblocks.stateChanged.connect(self.update_check_bad)
        
        bad_blocks_row.addWidget(self.chk_badblocks)
        bad_blocks_row.addWidget(self.combo_badblocks)
        bad_blocks_row.addStretch()

        chk_layout = QVBoxLayout()
        chk_layout.setSpacing(5)
        chk_layout.addWidget(self.chk_quick)
        chk_layout.addWidget(self.chk_extended)
        chk_layout.addLayout(bad_blocks_row)
        main_layout.addLayout(chk_layout)
        
        main_layout.addSpacing(15)

        # === STATUS ===
        main_layout.addLayout(self.create_header("Status"))

        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("")
        main_layout.addWidget(self.progress_bar)

        # Bottom controls
        bottom_controls = QHBoxLayout()
        bottom_controls.setSpacing(10)
        bottom_controls.setContentsMargins(0, 10, 0, 0)
        
        # Icon buttons
        icons_layout = QHBoxLayout()
        icons_layout.setSpacing(5)
        
        btn_icon1 = QToolButton()
        btn_icon1.setText("🌐")
        btn_icon1.setToolTip("Download updates")
        btn_icon1.clicked.connect(lambda: webbrowser.open('http://www.github.com/hog185/lufus'))
        
        btn_icon2 = QToolButton()
        btn_icon2.setText("ℹ")
        btn_icon2.setToolTip("About")
        btn_icon2.clicked.connect(self.show_about)
        
        btn_icon3 = QToolButton()
        btn_icon3.setText("⚙")
        btn_icon3.setToolTip("Settings")
        
        btn_icon4 = QToolButton()
        btn_icon4.setText("📄")
        btn_icon4.setToolTip("Log")
        btn_icon4.clicked.connect(self.show_log)
        
        icons_layout.addWidget(btn_icon1)
        icons_layout.addWidget(btn_icon2)
        icons_layout.addWidget(btn_icon3)
        icons_layout.addWidget(btn_icon4)
        icons_layout.addStretch()
        
        # Start/Cancel buttons
        self.btn_start = QPushButton("START")
        self.btn_start.setObjectName("btnStart")
        self.btn_start.setFixedSize(100, 50)
        self.btn_start.clicked.connect(self.start_process)

        self.btn_cancel = QPushButton("CANCEL")
        self.btn_cancel.setFixedSize(100, 50)
        self.btn_cancel.clicked.connect(self.cancel_process)
        
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)
        btn_layout.addWidget(self.btn_start)
        btn_layout.addWidget(self.btn_cancel)
        
        bottom_controls.addLayout(icons_layout, 1)
        bottom_controls.addLayout(btn_layout)
        main_layout.addLayout(bottom_controls)
        
        main_layout.addStretch()
        central_widget.setLayout(main_layout)
        
        # Status bar
        self.statusBar = QStatusBar()
        self.setStatusBar(self.statusBar)
        self.statusBar.showMessage("Ready", 0)

    def _populate_device_combo(self):
        """Populate the device combo box with USB devices"""
        self.combo_device.blockSignals(True)
        self.combo_device.clear()
        
        if self.usb_devices:
            for node, label in self.usb_devices.items():
                display = f"{label} ({node})" if label != node else node
                self.combo_device.addItem(display, node)
        else:
            self.combo_device.addItem("No USB devices found",None)
        
        self.combo_device.blockSignals(False)

    def refresh_usb_devices(self):
        self.statusBar.showMessage("Scanning for USB devices...", 2000)
        try:
            new_devices = self.monitor.devices
            
            if new_devices:
                self.usb_devices = new_devices
                self._populate_device_combo()
                self.log_message(f"USB scan complete: {len(new_devices)} device(s) found")
                QMessageBox.information(self, "New USB Device Found","USB Device Found")            
            else:
                self.usb_devices = {}
                self._populate_device_combo()
                self.log_message("No USB devices found during scan")
                QMessageBox.information(self, "No Devices", 
                    "No USB drives were found.\n\nPlease connect a drive and try again.")
        except Exception as e:
            self.statusBar.showMessage("Scan failed", 3000)
            self.log_message(f"USB scan error: {str(e)}")
            QMessageBox.critical(self, "Scan Error", f"Failed to scan for USB devices:\n{str(e)}")

    def updateFS(self):
        states.currentFS = self.combo_fs.currentIndex()

    def updateflash(self):
        self.combo_device.clear()
        states.currentflash = self.combo_flash.currentIndex()
        print(states.currentflash)
    
    def update_image_option(self):
        states.image_option = self.combo_image_option.currentIndex()
        self._update_filesystem_options()
        self._update_flashing_options()
    
    def _update_filesystem_options(self):
        self.combo_fs.blockSignals(True)
        if states.image_option == 1:
            self.combo_fs.clear()
            self.combo_fs.addItem("UDF")
        elif states.image_option == 0:
            self.combo_fs.clear()
            self.combo_fs.addItems(self.all_fs_options)
            self.combo_fs.setCurrentText("NTFS")
        self.combo_fs.blockSignals(False)
        self.updateFS()


    def _update_flashing_options(self):
        self.combo_flash.blockSignals(True)
        self.combo_flash.clear()
        
        if states.image_option == 1:
            # Linux mode: only DD and Ventoy
            self.combo_flash.addItems(["DD", "Ventoy"])
            self.combo_flash.setCurrentText("DD")
        elif states.image_option == 0:
            # Windows/Other mode: Iso Mode, Woe USB, Ventoy
            self.combo_flash.addItems(["Iso Mode", "Woe USB", "Ventoy"])
            self.combo_flash.setCurrentText("Iso Mode")
        elif states.image_option == 2:
            # Windows/Other mode: Iso Mode, Woe USB, Ventoy
            self.combo_flash.addItems(["None"])
            self.combo_flash.setCurrentText("None")
        self.combo_flash.blockSignals(False)
        self.updateflash()

    def update_partition_scheme(self):
        states.partition_scheme = self.combo_partition.currentIndex()

    def update_target_system(self):
        states.target_system = self.combo_target.currentIndex()
        # print(f"Global state updated to: {states.target_system}")
    
    def update_new_label(self, current_text):
        states.new_label = current_text
    
    def update_cluster_size(self):
        states.cluster_size = self.combo_cluster.currentIndex()
        # print(f"Global state updated to: {states.cluster_size}")

    def update_QF(self):
        states.QF = 0 if self.chk_quick.isChecked() else 1

    def update_create_extended(self):
        states.create_extended = 0 if self.chk_extended.isChecked() else 1

    def update_check_bad(self):
        states.check_bad = 0 if self.chk_badblocks.isChecked() else 1
        self.combo_badblocks.setEnabled(self.chk_badblocks.isChecked())

    def browse_file(self):
        file_name, _ = QFileDialog.getOpenFileName(self, "Select Disk Image", "", 
                                                    "ISO Images (*.iso);;All Files (*)")
        if file_name:
            states.iso_path = file_name
            clean_name = file_name.split("/")[-1].split("\\")[-1]
            self.combo_boot.setItemText(0, clean_name)
            self.input_label.setText(clean_name.split('.')[0].upper())
            self.log_message(f"Selected image: {file_name}")

    def show_log(self):
        if self.log_window is None:
            self.log_window = LogWindow()
        self.log_window.show()
        self.log_window.raise_()
        self.log_window.activateWindow()

    def show_about(self):
        if self.about_window is None:
            self.about_window = AboutWindow()
            about_content = "lufus is a disk image writer written in Python for Linux.\n\n"
            about_content += "Inspired by the original lufus tool for Windows.\n\n"
            about_content += "Version: 1.0.0\n"
            about_content += "GitHub: github.com/hog185/lufus"
            self.about_window.about_text.setPlainText(about_content)
        self.about_window.show()
        self.about_window.raise_()
        self.about_window.activateWindow()

    def log_message(self, msg):
        if self.log_window and self.log_window.isVisible():
            self.log_window.log_text.append(f"[INFO] {msg}")

    def get_selected_mount_path(self) -> str:
        text = self.combo_device.currentText()
        if '(' in text and ')' in text:
            return text.split('(')[1].split(')')[0].strip()
        return ""
    
    def cancel_process(self):
        reply = QMessageBox.question(self, "Cancel", 
            "Are you sure you want to cancel?", 
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            if self.flash_worker and self.flash_worker.isRunning():
                self.flash_worker.terminate()
            self.progress_bar.setValue(0)
            self.progress_bar.setFormat("")
            self.btn_start.setEnabled(True)
            self.btn_cancel.setEnabled(False)
            self.statusBar.showMessage("Ready", 0)
            self.log_message("Flash process cancelled by user")
    
    def on_flash_finished(self, success: bool):
        if success:
            self.progress_bar.setValue(100)
            self.progress_bar.setFormat("Complete! 100%")
            QMessageBox.information(self, "Success", "USB drive flashed successfully!")
            self.log_message("Flash completed successfully")
        else:
            self.progress_bar.setFormat("Failed")
            QMessageBox.critical(self, "Error", "Failed to flash USB drive.")
            self.log_message("Flash failed")
        
        self.btn_start.setEnabled(True)
        self.btn_cancel.setEnabled(False)
        self.statusBar.showMessage("Ready", 0)
    
    def start_process(self):

        # Bad blocks check
        if states.check_bad == 0:
            fo.checkdevicebadblock()

        states.DN = self.combo_device.currentData() or ""
        if states.image_option == 0: # WINDOWS
            if states.currentflash == 0: # iso mode
                if not getattr(states, 'iso_path', '') or not Path(states.iso_path).exists():
                    QMessageBox.warning(self, "No Image", "Please select a valid installation file first.")
                    return
                mount_path = self.get_selected_mount_path()
                if not mount_path:
                    QMessageBox.warning(self, "No Device", "Please select a USB device first.")
                    return

                self.btn_start.setEnabled(False)
                self.btn_cancel.setEnabled(True)
                self.progress_bar.setValue(0)
                self.progress_bar.setFormat("Preparing...")
                self.statusBar.showMessage("Flashing...", 0)

                self.flash_worker = FlashWorker(states.iso_path, mount_path)
                self.flash_worker.progress.connect(lambda msg: self.statusBar.showMessage(msg, 0))
                self.flash_worker.progress_value.connect(self.progress_bar.setValue)
                self.flash_worker.progress_value.connect(lambda v: self.progress_bar.setFormat(f"{v}%"))
                self.flash_worker.finished.connect(self.on_flash_finished)
                self.flash_worker.start()

                self.log_message(f"Starting Windows flash process: {states.iso_path} -> {mount_path}")

            elif states.currentflash == 1: # Woe USB
                if not getattr(states, 'iso_path', '') or not Path(states.iso_path).exists():
                    QMessageBox.warning(self, "No Image", "Please select a valid installation file first.")
                    return
                mount_path = self.get_selected_mount_path()
                if not mount_path:
                    QMessageBox.warning(self, "No Device", "Please select a USB device first.")
                    return

                self.btn_start.setEnabled(False)
                self.btn_cancel.setEnabled(True)
                self.progress_bar.setValue(0)
                self.progress_bar.setFormat("Preparing...")
                self.statusBar.showMessage("Flashing...", 0)

                self.flash_worker = WoeUSBWorker(states.iso_path, mount_path)
                self.flash_worker.progress.connect(lambda msg: self.statusBar.showMessage(msg, 0))
                self.flash_worker.progress_value.connect(self.progress_bar.setValue)
                self.flash_worker.progress_value.connect(lambda v: self.progress_bar.setFormat(f"{v}%"))
                self.flash_worker.finished.connect(self.on_flash_finished)
                self.flash_worker.start()

                self.log_message(f"Starting woeusb flash process: {states.iso_path} -> {mount_path}")

        elif states.image_option == 1: # LINUX
            if states.currentflash == 0: # DD METHOD
                ### FLASHING
                if not getattr(states, 'iso_path', '') or not Path(states.iso_path).exists():
                    QMessageBox.warning(self, "No Image", "Please select a valid installation file first.")
                    return
                device_node = self.get_selected_mount_path()
                if not device_node:
                    QMessageBox.warning(self, "No Device", "Please select a USB device first.")
                    return
                
                self.btn_start.setEnabled(False)
                self.btn_cancel.setEnabled(True)
                self.progress_bar.setValue(0)
                self.progress_bar.setFormat("Preparing...")
                self.statusBar.showMessage("Flashing...", 0)
                
                self.flash_worker = FlashWorker(states.iso_path, device_node)
                self.flash_worker.progress.connect(lambda msg: self.statusBar.showMessage(msg, 0))
                self.flash_worker.progress_value.connect(self.progress_bar.setValue)
                self.flash_worker.progress_value.connect(lambda v: self.progress_bar.setFormat(f"{v}%"))
                self.flash_worker.finished.connect(self.on_flash_finished)
                self.flash_worker.start()
                
                self.log_message(f"Starting flash process: {states.iso_path} -> {device_node}")
            else: # OTHER METHODS NOT YET DONE
                pass 
        elif states.image_option == 2: # ONLY FORMATTING
        ### FORMATTING
            self.btn_start.setEnabled(False)
            self.btn_cancel.setEnabled(True)
            self.progress_bar.setValue(10)
            self.progress_bar.setFormat("Starting.. 10%")
            # unmount
            fo.unmount()
            self.progress_bar.setValue(30)
            self.progress_bar.setFormat("Unmounted Drive.. 20%")
            # we must either flash iso or format the drive
            # logic will be implemented later
            # dd flashing goes here

            # format the drive
            fo.dskformat()
            self.progress_bar.setValue(60)
            self.progress_bar.setFormat("Format Drive.. 60%")
            # change label
            fo.volumecustomlabel()
            self.progress_bar.setValue(80)
            self.progress_bar.setFormat("Changed Label.. 80%")
            # re-mount
            fo.remount()
            self.progress_bar.setValue(100)
            self.progress_bar.setFormat("Mount Done.. Completed! 100%")

    def keyPressEvent(self, event):
        """Handle keyboard shortcuts"""
        if event.key() == Qt.Key.Key_R and event.modifiers() == Qt.KeyboardModifier.ControlModifier:
            self.refresh_usb_devices()
        elif event.key() == Qt.Key.Key_F5:
            self.refresh_usb_devices()
        super().keyPressEvent(event)

    def position_notification(self):
        if self.parent():
            parent_rect = self.parent().geometry()
            x = parent_rect.right() - self.width() - 20
            y = parent_rect.bottom() - self.height() - 20
            self.move(x, y)
        else:
            # Fallback to screen corner
            screen = QApplication.primaryScreen().geometry()
            x = screen.right() - self.width() - 20
            y = screen.bottom() - self.height() - 20
            self.move(x, y)


if __name__ == "__main__":
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
            usb_devices = {}
    else:
        print("No USB devices data received")
    
    window = lufus(usb_devices)
    window.show()
    sys.exit(app.exec())