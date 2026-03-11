from pathlib import Path

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QFontDatabase, QImage, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QPlainTextEdit,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
)

from helpers.deepl_helper import DeepLClient
from helpers.mods_helper import find_mod_link, find_preview_image

try:
    from PIL import Image

    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False
    Image = None


LANG_LABELS = {
    "de": "Deutsch (de)",
    "en": "English (en)",
    "es": "Espanol (es)",
    "it": "Italiano (it)",
}

APP_LANG_LABELS = {
    "de": "Deutsch",
    "en": "English",
}

DEEPL_GUIDE_URL = "https://www.deepl.com/en/pro/change-plan#developer"


class SettingsDialog(QDialog):
    def __init__(self, i18n, app_langs, mod_langs, config: dict, parent=None) -> None:
        super().__init__(parent)
        self.i18n = i18n
        self.setWindowTitle(self.i18n.t("settings_title"))
        self.setModal(True)
        self.resize(680, 280)

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(16)

        header = QLabel(self.i18n.t("settings_title"))
        header.setObjectName("SectionTitle")
        root.addWidget(header)

        form = QGridLayout()
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(12)
        root.addLayout(form)

        self.app_lang_combo = QComboBox()
        for code in app_langs:
            self.app_lang_combo.addItem(APP_LANG_LABELS[code], code)

        self.mod_lang_combo = QComboBox()
        for code in mod_langs:
            self.mod_lang_combo.addItem(LANG_LABELS[code], code)

        self.fallback_combo = QComboBox()
        for code in mod_langs:
            self.fallback_combo.addItem(LANG_LABELS[code], code)

        self.key_edit = QLineEdit(config.get("deepl_api_key", ""))
        self.key_edit.setEchoMode(QLineEdit.Password)

        help_button = QPushButton(self.i18n.t("deepl_help"))
        help_button.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(DEEPL_GUIDE_URL)))

        form.addWidget(QLabel(self.i18n.t("app_lang")), 0, 0)
        form.addWidget(self.app_lang_combo, 0, 1)
        form.addWidget(QLabel(self.i18n.t("mod_lang")), 1, 0)
        form.addWidget(self.mod_lang_combo, 1, 1)
        form.addWidget(QLabel(self.i18n.t("fallback")), 1, 2)
        form.addWidget(self.fallback_combo, 1, 3)
        form.addWidget(QLabel(self.i18n.t("deepl_key")), 2, 0)
        form.addWidget(self.key_edit, 2, 1, 1, 2)
        form.addWidget(help_button, 2, 3)

        info = QLabel(self.i18n.t("guide_info"))
        info.setObjectName("MutedLabel")
        info.setWordWrap(True)
        root.addWidget(info)

        self._set_combo_value(self.app_lang_combo, config.get("app_language", "de"))
        self._set_combo_value(self.mod_lang_combo, config.get("language", "de"))
        self._set_combo_value(self.fallback_combo, config.get("fallback_language", "en"))

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _set_combo_value(self, combo: QComboBox, value: str) -> None:
        index = combo.findData(value)
        if index >= 0:
            combo.setCurrentIndex(index)

    def values(self) -> dict:
        return {
            "app_language": self.app_lang_combo.currentData(),
            "language": self.mod_lang_combo.currentData(),
            "fallback_language": self.fallback_combo.currentData(),
            "deepl_api_key": self.key_edit.text().strip(),
        }


class DependencyPickerDialog(QDialog):
    dependency_selected = Signal(dict)

    def __init__(self, i18n, links: list[dict], parent=None) -> None:
        super().__init__(parent)
        self.i18n = i18n
        self.setWindowTitle(self.i18n.t("dependencies_label"))
        self.resize(480, 320)

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(12)

        title = QLabel(self.i18n.t("dependencies_label"))
        title.setObjectName("SectionTitle")
        root.addWidget(title)

        self.list_widget = QListWidget()
        for dep in links:
            target = dep["target"]
            item = QListWidgetItem(f"{dep['id']} -> {target.get('name', dep['id'])}")
            item.setData(Qt.UserRole, target)
            self.list_widget.addItem(item)
        self.list_widget.itemDoubleClicked.connect(self._emit_selected)
        root.addWidget(self.list_widget)

        footer = QHBoxLayout()
        footer.addStretch(1)

        open_button = QPushButton(self.i18n.t("details_tab"))
        open_button.setProperty("accent", True)
        open_button.clicked.connect(self.open_selected)
        footer.addWidget(open_button)

        close_button = QPushButton(self.i18n.t("cancel"))
        close_button.clicked.connect(self.reject)
        footer.addWidget(close_button)
        root.addLayout(footer)

    def open_selected(self) -> None:
        item = self.list_widget.currentItem()
        if item is not None:
            self._emit_selected(item)

    def _emit_selected(self, item: QListWidgetItem) -> None:
        target = item.data(Qt.UserRole)
        if target:
            self.dependency_selected.emit(target)
            self.accept()


class ModDetailsDialog(QDialog):
    open_dependency = Signal(dict)

    def __init__(self, i18n, mod: dict, mod_lang: str, deepl_key: str, parent=None) -> None:
        super().__init__(parent)
        self.i18n = i18n
        self.mod = mod
        self.mod_lang = mod_lang
        self.deepl_key = deepl_key.strip()

        mod_path = Path(self.mod.get("path", ""))
        mod_lua = mod_path / "mod.lua"
        self.setWindowTitle(self.i18n.t("details_title", name=self.mod.get("name", mod_path.name)))
        self.resize(1120, 760)

        self.raw_content = mod_lua.read_text(encoding="utf-8", errors="ignore")
        self._apply_lazy_translation()
        self._build_ui(mod_path)

    def _apply_lazy_translation(self) -> None:
        if self.deepl_key and self.mod.get("description") and not self.mod.get("_deepl_done", False):
            deepl = DeepLClient(self.deepl_key)
            translated, deepl_error = deepl.translate(self.mod.get("description", ""), self.mod_lang)
            self.mod["description_translated"] = translated
            self.mod["deepl_error"] = deepl_error
            self.mod["_deepl_done"] = True

    def _build_ui(self, mod_path: Path) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(14)

        tabs = QTabWidget()
        root.addWidget(tabs)

        details_tab = QFrame()
        details_layout = QVBoxLayout(details_tab)
        details_layout.setContentsMargins(6, 6, 6, 6)
        details_layout.setSpacing(14)

        overview = QFrame()
        overview.setObjectName("DetailCard")
        overview_layout = QVBoxLayout(overview)
        overview_layout.setContentsMargins(16, 16, 16, 16)
        overview_layout.setSpacing(8)

        title = QLabel(self.mod.get("name", "-"))
        title.setObjectName("WindowTitle")
        title.setWordWrap(True)
        overview_layout.addWidget(title)

        overview_layout.addWidget(self._info_label(self.i18n.t("author", value=self.mod.get("author", "-"))))
        overview_layout.addWidget(self._info_label(self.i18n.t("version", value=self.mod.get("version", "-"))))
        overview_layout.addWidget(self._info_label(self.i18n.t("path", value=str(mod_path))))

        desc = self.mod.get("description_translated") or self.mod.get("description") or ""
        if desc:
            desc_label = self._info_label(self.i18n.t("description", value=desc))
            desc_label.setWordWrap(True)
            overview_layout.addWidget(desc_label)

        if self.mod.get("translation_notice"):
            label = self._info_label(self.i18n.t("translation_notice", value=self.mod.get("translation_notice")))
            label.setObjectName("MutedLabel")
            label.setWordWrap(True)
            overview_layout.addWidget(label)
        if self.mod.get("translation_available_languages"):
            text = ", ".join(self.mod.get("translation_available_languages", []))
            label = self._info_label(self.i18n.t("available_languages", value=text))
            label.setWordWrap(True)
            overview_layout.addWidget(label)
        if self.mod.get("translation_effective_language"):
            label = self._info_label(
                self.i18n.t("effective_language", value=self.mod.get("translation_effective_language"))
            )
            overview_layout.addWidget(label)
        if self.mod.get("deepl_error"):
            label = self._info_label(self.i18n.t("deepl_note", value=self.mod.get("deepl_error")))
            label.setObjectName("MutedLabel")
            label.setWordWrap(True)
            overview_layout.addWidget(label)

        link = find_mod_link(self.mod.get("resolved_fields", self.mod.get("raw_fields", {})))
        if link:
            link_button = QPushButton(link)
            link_button.setProperty("subtle", True)
            link_button.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(link)))
            overview_layout.addWidget(link_button)

        details_layout.addWidget(overview)

        content_row = QHBoxLayout()
        content_row.setSpacing(14)
        details_layout.addLayout(content_row, 1)

        fields_card = QFrame()
        fields_card.setObjectName("DetailCard")
        fields_layout = QVBoxLayout(fields_card)
        fields_layout.setContentsMargins(12, 12, 12, 12)
        fields_layout.setSpacing(10)

        fields_title = QLabel(self.i18n.t("details_tab"))
        fields_title.setObjectName("SectionTitle")
        fields_layout.addWidget(fields_title)

        fields_table = QTableWidget(0, 3)
        fields_table.setHorizontalHeaderLabels(
            [self.i18n.t("field"), self.i18n.t("value_resolved"), self.i18n.t("value_raw")]
        )
        fields_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        fields_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        fields_table.verticalHeader().setVisible(False)
        fields_table.horizontalHeader().setStretchLastSection(True)

        raw_fields = self.mod.get("raw_fields", {})
        fields = self.mod.get("resolved_fields", raw_fields)
        for row, key in enumerate(sorted(fields.keys())):
            fields_table.insertRow(row)
            fields_table.setItem(row, 0, QTableWidgetItem(key))
            fields_table.setItem(row, 1, QTableWidgetItem(str(fields.get(key, ""))))
            fields_table.setItem(row, 2, QTableWidgetItem(str(raw_fields.get(key, ""))))
        fields_layout.addWidget(fields_table)
        content_row.addWidget(fields_card, 3)

        side_col = QVBoxLayout()
        side_col.setSpacing(14)
        content_row.addLayout(side_col, 2)

        dep_card = QFrame()
        dep_card.setObjectName("DetailCard")
        dep_layout = QVBoxLayout(dep_card)
        dep_layout.setContentsMargins(12, 12, 12, 12)
        dep_layout.setSpacing(10)

        dep_title = QLabel(self.i18n.t("dependencies_label"))
        dep_title.setObjectName("SectionTitle")
        dep_layout.addWidget(dep_title)

        dep_list = QListWidget()
        for dep in self.mod.get("dependency_links", []):
            target = dep.get("target")
            text = f"{dep['id']} -> {target.get('name', dep['id'])}" if target else f"{dep['id']} (missing)"
            item = QListWidgetItem(text)
            item.setData(Qt.UserRole, target)
            dep_list.addItem(item)
        dep_list.itemDoubleClicked.connect(self._dependency_clicked)
        dep_layout.addWidget(dep_list)
        side_col.addWidget(dep_card)

        preview_card = QFrame()
        preview_card.setObjectName("DetailCard")
        preview_layout = QVBoxLayout(preview_card)
        preview_layout.setContentsMargins(12, 12, 12, 12)
        preview_layout.setSpacing(10)

        preview_title = QLabel(self.i18n.t("preview_label"))
        preview_title.setObjectName("SectionTitle")
        preview_layout.addWidget(preview_title)

        preview_label = QLabel(self.i18n.t("no_preview"))
        preview_label.setAlignment(Qt.AlignCenter)
        preview_label.setMinimumHeight(320)
        preview_label.setWordWrap(True)
        preview_layout.addWidget(preview_label, 1)

        preview_path = find_preview_image(mod_path)
        pixmap = load_preview_pixmap(preview_path)
        if pixmap is not None:
            preview_label.setPixmap(
                pixmap.scaled(360, 360, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            )
            preview_label.setText("")
        side_col.addWidget(preview_card, 1)

        raw_tab = QFrame()
        raw_layout = QVBoxLayout(raw_tab)
        raw_layout.setContentsMargins(6, 6, 6, 6)

        raw_text = QPlainTextEdit()
        raw_text.setReadOnly(True)
        raw_text.setPlainText(self.raw_content)
        raw_text.setFont(QFontDatabase.systemFont(QFontDatabase.FixedFont))
        raw_layout.addWidget(raw_text)

        tabs.addTab(details_tab, self.i18n.t("details_tab"))
        tabs.addTab(raw_tab, self.i18n.t("lua_tab"))

    def _info_label(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("ValueLabel")
        label.setWordWrap(True)
        label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        return label

    def _dependency_clicked(self, item: QListWidgetItem) -> None:
        target = item.data(Qt.UserRole)
        if target:
            self.open_dependency.emit(target)


def load_preview_pixmap(path: Path | None) -> QPixmap | None:
    if path is None or not path.exists():
        return None

    suffix = path.suffix.lower()
    if suffix in {".png", ".jpg", ".jpeg", ".bmp", ".webp"}:
        pixmap = QPixmap(str(path))
        if not pixmap.isNull():
            return pixmap

    if PIL_AVAILABLE:
        try:
            with Image.open(path) as img:
                rgba = img.convert("RGBA")
                image = QImage(
                    rgba.tobytes("raw", "RGBA"),
                    rgba.width,
                    rgba.height,
                    rgba.width * 4,
                    QImage.Format_RGBA8888,
                )
                return QPixmap.fromImage(image.copy())
        except Exception:
            return None
    return None
