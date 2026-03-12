from pathlib import Path

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QImage, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
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
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
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
        self.resize(720, 360)

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

        self.parallel_install_checkbox = QCheckBox(self.i18n.t("parallel_install_hint"))
        self.parallel_install_checkbox.setChecked(bool(config.get("parallel_install_enabled", False)))

        self.max_workers_spin = QSpinBox()
        self.max_workers_spin.setRange(1, 16)
        self.max_workers_spin.setValue(int(config.get("max_parallel_workers", 2)))
        self.max_workers_spin.setEnabled(self.parallel_install_checkbox.isChecked())
        self.parallel_install_checkbox.toggled.connect(self.max_workers_spin.setEnabled)

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
        form.addWidget(QLabel(self.i18n.t("parallel_install")), 3, 0)
        form.addWidget(self.parallel_install_checkbox, 3, 1, 1, 2)
        form.addWidget(QLabel(self.i18n.t("max_workers")), 4, 0)
        form.addWidget(self.max_workers_spin, 4, 1)

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
            "parallel_install_enabled": self.parallel_install_checkbox.isChecked(),
            "max_parallel_workers": self.max_workers_spin.value(),
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


class ModDetailsPage(QWidget):
    back_requested = Signal()
    open_dependency = Signal(dict)

    def __init__(self, i18n, parent=None) -> None:
        super().__init__(parent)
        self.i18n = i18n
        self.mod: dict | None = None
        self.mod_lang = "de"
        self.deepl_key = ""
        self.current_link_url = ""
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(16)

        header = QHBoxLayout()
        self.back_button = QPushButton("← " + self.i18n.t("back"))
        self.back_button.setProperty("accent", True)
        self.back_button.clicked.connect(self.back_requested.emit)
        header.addWidget(self.back_button)

        self.header_title = QLabel("")
        self.header_title.setObjectName("WindowTitle")
        self.header_title.setWordWrap(True)
        header.addWidget(self.header_title, 1)
        root.addLayout(header)

        self.overview = QFrame()
        self.overview.setObjectName("DetailCard")
        self.overview_layout = QVBoxLayout(self.overview)
        self.overview_layout.setContentsMargins(16, 16, 16, 16)
        self.overview_layout.setSpacing(8)

        self.author_label = self._info_label("")
        self.version_label = self._info_label("")
        self.path_label = self._info_label("")
        self.description_label = self._info_label("")
        self.translation_notice_label = self._info_label("")
        self.available_languages_label = self._info_label("")
        self.effective_language_label = self._info_label("")
        self.deepl_error_label = self._info_label("")
        self.link_button = QPushButton()
        self.link_button.setProperty("subtle", True)
        self.link_button.clicked.connect(self._open_current_link)

        for widget in [
            self.author_label,
            self.version_label,
            self.path_label,
            self.description_label,
            self.translation_notice_label,
            self.available_languages_label,
            self.effective_language_label,
            self.deepl_error_label,
            self.link_button,
        ]:
            self.overview_layout.addWidget(widget)

        root.addWidget(self.overview)

        content_row = QHBoxLayout()
        content_row.setSpacing(14)
        root.addLayout(content_row, 1)

        fields_card = QFrame()
        fields_card.setObjectName("DetailCard")
        fields_layout = QVBoxLayout(fields_card)
        fields_layout.setContentsMargins(12, 12, 12, 12)
        fields_layout.setSpacing(10)
        fields_title = QLabel(self.i18n.t("details_tab"))
        fields_title.setObjectName("SectionTitle")
        fields_layout.addWidget(fields_title)

        self.fields_table = QTableWidget(0, 3)
        self.fields_table.setHorizontalHeaderLabels(
            [self.i18n.t("field"), self.i18n.t("value_resolved"), self.i18n.t("value_raw")]
        )
        self.fields_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.fields_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.fields_table.verticalHeader().setVisible(False)
        self.fields_table.horizontalHeader().setStretchLastSection(True)
        fields_layout.addWidget(self.fields_table)
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

        self.dep_list = QListWidget()
        self.dep_list.itemDoubleClicked.connect(self._dependency_clicked)
        dep_layout.addWidget(self.dep_list)

        side_col.addWidget(dep_card)

        preview_card = QFrame()
        preview_card.setObjectName("DetailCard")
        preview_layout = QVBoxLayout(preview_card)
        preview_layout.setContentsMargins(12, 12, 12, 12)
        preview_layout.setSpacing(10)
        preview_title = QLabel(self.i18n.t("preview_label"))
        preview_title.setObjectName("SectionTitle")
        preview_layout.addWidget(preview_title)

        self.preview_label = QLabel(self.i18n.t("no_preview"))
        self.preview_label.setAlignment(Qt.AlignCenter)
        self.preview_label.setMinimumHeight(320)
        self.preview_label.setWordWrap(True)
        preview_layout.addWidget(self.preview_label, 1)
        side_col.addWidget(preview_card, 1)

    def set_mod(
        self,
        mod: dict,
        mod_lang: str,
        deepl_key: str,
    ) -> None:
        self.mod = mod
        self.mod_lang = mod_lang
        self.deepl_key = deepl_key.strip()
        self._apply_lazy_translation()

        mod_path = Path(self.mod.get("path", ""))
        self.header_title.setText(self.mod.get("name", "-"))
        self.author_label.setText(self.i18n.t("author", value=self.mod.get("author", "-")))
        self.version_label.setText(self.i18n.t("version", value=self.mod.get("version", "-")))
        self.path_label.setText(self.i18n.t("path", value=str(mod_path)))

        desc = self.mod.get("description_translated") or self.mod.get("description") or ""
        self.description_label.setText(self.i18n.t("description", value=desc) if desc else "")
        self.description_label.setVisible(bool(desc))

        translation_notice = self._build_translation_notice()
        self.translation_notice_label.setText(
            self.i18n.t("translation_notice", value=translation_notice) if translation_notice else ""
        )
        self.translation_notice_label.setVisible(bool(translation_notice))

        available = self.mod.get("translation_available_languages", [])
        self.available_languages_label.setText(
            self.i18n.t("available_languages", value=", ".join(available)) if available else ""
        )
        self.available_languages_label.setVisible(bool(available))

        effective = self.mod.get("translation_effective_language")
        self.effective_language_label.setText(
            self.i18n.t("effective_language", value=effective) if effective else ""
        )
        self.effective_language_label.setVisible(bool(effective))

        deepl_error = self.mod.get("deepl_error")
        self.deepl_error_label.setText(self.i18n.t("deepl_note", value=deepl_error) if deepl_error else "")
        self.deepl_error_label.setVisible(bool(deepl_error))

        link = find_mod_link(self.mod.get("resolved_fields", self.mod.get("raw_fields", {})))
        self.link_button.setVisible(bool(link))
        self.current_link_url = link or ""
        if link:
            self.link_button.setText(link)
        else:
            self.link_button.setText("")

        self.fields_table.setRowCount(0)
        raw_fields = self.mod.get("raw_fields", {})
        fields = self.mod.get("resolved_fields", raw_fields)
        for row, key in enumerate(sorted(fields.keys())):
            self.fields_table.insertRow(row)
            self.fields_table.setItem(row, 0, QTableWidgetItem(key))
            self.fields_table.setItem(row, 1, QTableWidgetItem(str(fields.get(key, ""))))
            self.fields_table.setItem(row, 2, QTableWidgetItem(str(raw_fields.get(key, ""))))

        self.dep_list.clear()
        for dep in self.mod.get("dependency_links", []):
            target = dep.get("target")
            text = f"{dep['id']} -> {target.get('name', dep['id'])}" if target else f"{dep['id']} (missing)"
            item = QListWidgetItem(text)
            item.setData(Qt.UserRole, target)
            self.dep_list.addItem(item)

        preview_path = find_preview_image(mod_path)
        pixmap = load_preview_pixmap(preview_path)
        self.preview_label.setPixmap(QPixmap())
        self.preview_label.setText(self.i18n.t("no_preview"))
        if pixmap is not None:
            self.preview_label.setPixmap(
                pixmap.scaled(360, 360, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            )
            self.preview_label.setText("")

    def update_texts(self) -> None:
        self.back_button.setText("← " + self.i18n.t("back"))

    def _apply_lazy_translation(self) -> None:
        if self.deepl_key and self.mod and self.mod.get("description") and not self.mod.get("_deepl_done", False):
            deepl = DeepLClient(self.deepl_key)
            translated, deepl_error = deepl.translate(self.mod.get("description", ""), self.mod_lang)
            self.mod["description_translated"] = translated
            self.mod["deepl_error"] = deepl_error
            self.mod["_deepl_done"] = True

    def _build_translation_notice(self) -> str:
        if not self.mod:
            return ""

        parts: list[str] = []
        notice_key = str(self.mod.get("translation_notice_key", "") or "").strip()
        notice_params = self.mod.get("translation_notice_params", {}) or {}
        if notice_key:
            parts.append(self.i18n.t(notice_key, **notice_params))

        source_lang = str(self.mod.get("translation_effective_language", "") or "").strip()
        description = str(self.mod.get("description", "") or "")
        translated = str(self.mod.get("description_translated", "") or "")
        deepl_error = str(self.mod.get("deepl_error", "") or "").strip()
        if (
            description
            and translated
            and translated != description
            and not deepl_error
            and source_lang
            and source_lang != self.mod_lang
        ):
            parts.append(self.i18n.t("notice_deepl_applied", source=source_lang, target=self.mod_lang))

        return " ".join(part for part in parts if part)

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

    def _open_current_link(self) -> None:
        if self.current_link_url:
            QDesktopServices.openUrl(QUrl(self.current_link_url))


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
