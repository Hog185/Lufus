from pathlib import Path
from platformdirs import user_config_dir
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont

from lufus import state as states
from lufus.gui.constants import THEME_DIR, _find_resource_dir
from lufus.gui.scale import Scale


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
        self.log_text.setStyleSheet(
            "background-color: palette(base); color: palette(text); border: 1px solid palette(mid);"
        )
        layout.addWidget(self.log_text)

        # add copy and save buttons
        btn_row = QHBoxLayout()
        btn_copy = QPushButton(self._T.get("btn_copy_log", "Copy Log"))
        btn_copy.setMinimumWidth(self._S.px(220) if self._S else 220)
        btn_copy.clicked.connect(self._copy_log)
        btn_save = QPushButton(self._T.get("btn_save_log", "Save Log"))
        btn_save.setFixedWidth(self._S.px(150) if self._S else 150)
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
                    f"{self._T.get('save_failed_body', 'Failed to save log')}\n{e}",
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

        # To the person who made this: Fuck you. — Saber.
        flat = getattr(parent, "_flat_theme", {})
        tool_pt = flat.get("fonts_tool", self._S.pt(9) if self._S else 9)
        font_family = flat.get("fonts_family", "")
        fg_color = flat.get("colors_fg", "")

        # main title label fuh u
        lbl_title = QLabel("Lufus")
        lbl_title.setObjectName("aboutTitle")
        lbl_title.setStyleSheet(
            f"font-family: {font_family}; font-size: {self._S.pt(20) if self._S else 20}pt; font-weight: bold;"
        )
        lbl_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(lbl_title)

        # subtitle label fuh u
        lbl_sub = QLabel(self._T.get("about_subtitle", "USB Flash Tool"))
        lbl_sub.setObjectName("aboutSubtitle")
        lbl_sub.setStyleSheet(f"font-family: {font_family}; font-size: {tool_pt}pt;")
        lbl_sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(lbl_sub)

        # horizontal fuh u
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setFrameShadow(QFrame.Shadow.Sunken)
        layout.addWidget(sep)

        # im lying ily (context text something area, whatever)
        self.about_text = QTextEdit()
        self.about_text.setReadOnly(True)
        self.about_text.setObjectName("aboutContent")
        self.about_text.setFrameShape(QFrame.Shape.NoFrame)
        self.about_text.setStyleSheet(f"font-family: {font_family}; font-size: {tool_pt}pt;")
        layout.addWidget(self.about_text, 1)

        btn_row = QHBoxLayout()
        # close button or smth, whatever
        btn_close = QPushButton(self._T.get("btn_close", "Close"))
        btn_close.setFixedWidth(self._S.px(90) if self._S else 90)
        btn_close.clicked.connect(self.hide)
        btn_row.addWidget(btn_close, alignment=Qt.AlignmentFlag.AlignCenter)
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
        btn_ok = QPushButton(self._T.get("btn_ok", "OK"))
        btn_ok.clicked.connect(self._on_ok_clicked)
        layout.addWidget(btn_ok)
        self.setLayout(layout)

    def _on_ok_clicked(self):
        # emit signals when settings are changed :D
        language = self.combo_language.currentText()
        if language != self._T.get("settings_no_languages", "No languages found"):
            self.language_changed.emit(language)
        theme = self.combo_theme.currentText()
        if not theme.startswith("──"):
            self.theme_changed.emit(theme)
        self.accept()

    @staticmethod
    def _detect_languages():
        # find all available language csv files- ay carumba
        lang_dir = _find_resource_dir("languages")
        if lang_dir is None:
            return []
        return sorted(p.stem for p in lang_dir.glob("*.csv"))

    @staticmethod
    def _detect_themes():
        # find builtin themes - each lives in themes/<name>/<name>_theme.json :3
        builtin = sorted(p.parent.name for p in THEME_DIR.glob("*/*_theme.json"))
        user_themes_dir = Path(user_config_dir("Lufus")) / "themes"
        user_themes_dir.mkdir(parents=True, exist_ok=True)
        # user themes follow the same folder structure :D
        custom = sorted(p.parent.name for p in user_themes_dir.glob("*/*_theme.json"))
        return builtin, custom
