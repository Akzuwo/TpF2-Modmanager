from pathlib import Path
import struct

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QImage, QImageReader, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
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


def _load_tga_qimage(path: Path) -> QImage | None:
    try:
        data = path.read_bytes()
    except Exception:
        return None

    if len(data) < 18:
        return None

    try:
        (
            image_id_length,
            color_map_type,
            image_type,
            color_map_first_entry,
            color_map_length,
            color_map_entry_size,
            x_origin,
            y_origin,
            width,
            height,
            pixel_depth,
            image_descriptor,
        ) = struct.unpack("<BBBHHBHHHHBB", data[:18])
    except struct.error:
        return None

    del color_map_first_entry, color_map_length, color_map_entry_size, x_origin, y_origin

    if color_map_type != 0 or image_type not in {2, 10} or pixel_depth not in {24, 32} or width <= 0 or height <= 0:
        return None

    bytes_per_pixel = pixel_depth // 8
    offset = 18 + image_id_length
    pixel_count = width * height
    pixels = bytearray()

    def append_pixel(chunk: bytes) -> None:
        if len(chunk) < bytes_per_pixel:
            raise ValueError("Incomplete TGA pixel data")
        blue = chunk[0]
        green = chunk[1]
        red = chunk[2]
        alpha = chunk[3] if bytes_per_pixel == 4 else 255
        pixels.extend((red, green, blue, alpha))

    try:
        if image_type == 2:
            needed = pixel_count * bytes_per_pixel
            raw = data[offset : offset + needed]
            if len(raw) != needed:
                return None
            for index in range(0, len(raw), bytes_per_pixel):
                append_pixel(raw[index : index + bytes_per_pixel])
        else:
            while len(pixels) < pixel_count * 4 and offset < len(data):
                packet_header = data[offset]
                offset += 1
                run_length = (packet_header & 0x7F) + 1
                if packet_header & 0x80:
                    chunk = data[offset : offset + bytes_per_pixel]
                    offset += bytes_per_pixel
                    for _ in range(run_length):
                        append_pixel(chunk)
                else:
                    chunk_size = run_length * bytes_per_pixel
                    chunk = data[offset : offset + chunk_size]
                    offset += chunk_size
                    if len(chunk) != chunk_size:
                        return None
                    for index in range(0, len(chunk), bytes_per_pixel):
                        append_pixel(chunk[index : index + bytes_per_pixel])
    except ValueError:
        return None

    if len(pixels) != pixel_count * 4:
        return None

    # Bit 5 marks a top-left origin. Without it, rows are stored bottom-up.
    if not (image_descriptor & 0x20):
        stride = width * 4
        flipped = bytearray(len(pixels))
        for row in range(height):
            source_start = row * stride
            target_start = (height - 1 - row) * stride
            flipped[target_start : target_start + stride] = pixels[source_start : source_start + stride]
        pixels = flipped

    image = QImage(bytes(pixels), width, height, width * 4, QImage.Format_RGBA8888)
    if image.isNull():
        return None
    return image.copy()


class SettingsDialog(QDialog):
    def __init__(self, i18n, app_langs, mod_langs, config: dict, parent=None) -> None:
        super().__init__(parent)
        self.i18n = i18n
        self.setWindowTitle(self.i18n.t("settings_title"))
        self.setModal(True)
        self.resize(860, 520)

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

        self.debug_logging_checkbox = QCheckBox(self.i18n.t("debug_logging_hint"))
        self.debug_logging_checkbox.setChecked(bool(config.get("debug_logging_enabled", False)))

        self.key_edit = QLineEdit(config.get("deepl_api_key", ""))
        self.key_edit.setEchoMode(QLineEdit.Password)

        self.appworkshop_edit = QLineEdit(config.get("appworkshop_path", ""))
        self.workshop_mods_edit = QLineEdit(config.get("workshop_mods_path", ""))

        self.duplicate_behavior_combo = QComboBox()
        self.duplicate_behavior_combo.addItem(self.i18n.t("duplicate_behavior_manual"), "manual")
        self.duplicate_behavior_combo.addItem(self.i18n.t("duplicate_behavior_auto"), "auto_above_85")

        self.parallel_install_checkbox = QCheckBox(self.i18n.t("parallel_install_hint"))
        self.parallel_install_checkbox.setChecked(bool(config.get("parallel_install_enabled", False)))

        self.delete_download_archives_checkbox = QCheckBox(self.i18n.t("delete_download_archives_hint"))
        self.delete_download_archives_checkbox.setChecked(
            bool(config.get("delete_download_archives_after_install", False))
        )

        self.max_workers_spin = QSpinBox()
        self.max_workers_spin.setRange(1, 16)
        self.max_workers_spin.setValue(int(config.get("max_parallel_workers", 2)))
        self.max_workers_spin.setEnabled(self.parallel_install_checkbox.isChecked())
        self.parallel_install_checkbox.toggled.connect(self.max_workers_spin.setEnabled)

        help_button = QPushButton(self.i18n.t("deepl_help"))
        help_button.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(DEEPL_GUIDE_URL)))

        appworkshop_button = QPushButton(self.i18n.t("browse"))
        appworkshop_button.clicked.connect(self._pick_appworkshop_file)

        workshop_mods_button = QPushButton(self.i18n.t("browse"))
        workshop_mods_button.clicked.connect(self._pick_workshop_folder)

        form.addWidget(QLabel(self.i18n.t("app_lang")), 0, 0)
        form.addWidget(self.app_lang_combo, 0, 1)
        form.addWidget(QLabel(self.i18n.t("mod_lang")), 1, 0)
        form.addWidget(self.mod_lang_combo, 1, 1)
        form.addWidget(QLabel(self.i18n.t("fallback")), 1, 2)
        form.addWidget(self.fallback_combo, 1, 3)
        form.addWidget(QLabel(self.i18n.t("debug_logging")), 2, 0)
        form.addWidget(self.debug_logging_checkbox, 2, 1, 1, 3)
        form.addWidget(QLabel(self.i18n.t("deepl_key")), 3, 0)
        form.addWidget(self.key_edit, 3, 1, 1, 2)
        form.addWidget(help_button, 3, 3)
        form.addWidget(QLabel(self.i18n.t("appworkshop_path")), 4, 0)
        form.addWidget(self.appworkshop_edit, 4, 1, 1, 2)
        form.addWidget(appworkshop_button, 4, 3)
        form.addWidget(QLabel(self.i18n.t("workshop_mods_path")), 5, 0)
        form.addWidget(self.workshop_mods_edit, 5, 1, 1, 2)
        form.addWidget(workshop_mods_button, 5, 3)
        form.addWidget(QLabel(self.i18n.t("duplicate_behavior")), 6, 0)
        form.addWidget(self.duplicate_behavior_combo, 6, 1, 1, 3)
        form.addWidget(QLabel(self.i18n.t("parallel_install")), 7, 0)
        form.addWidget(self.parallel_install_checkbox, 7, 1, 1, 2)
        form.addWidget(QLabel(self.i18n.t("delete_download_archives")), 8, 0)
        form.addWidget(self.delete_download_archives_checkbox, 8, 1, 1, 3)
        form.addWidget(QLabel(self.i18n.t("max_workers")), 9, 0)
        form.addWidget(self.max_workers_spin, 9, 1)

        info = QLabel(self.i18n.t("guide_info"))
        info.setObjectName("MutedLabel")
        info.setWordWrap(True)
        root.addWidget(info)

        self._set_combo_value(self.app_lang_combo, config.get("app_language", "de"))
        self._set_combo_value(self.mod_lang_combo, config.get("language", "de"))
        self._set_combo_value(self.fallback_combo, config.get("fallback_language", "en"))
        self._set_combo_value(self.duplicate_behavior_combo, config.get("duplicate_behavior", "manual"))

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _set_combo_value(self, combo: QComboBox, value: str) -> None:
        index = combo.findData(value)
        if index >= 0:
            combo.setCurrentIndex(index)

    def _pick_appworkshop_file(self) -> None:
        selected, _ = QFileDialog.getOpenFileName(
            self,
            self.i18n.t("appworkshop_path"),
            self.appworkshop_edit.text().strip(),
            "Steam appworkshop (*.acf);;All files (*.*)",
        )
        if selected:
            self.appworkshop_edit.setText(selected)

    def _pick_workshop_folder(self) -> None:
        selected = QFileDialog.getExistingDirectory(
            self,
            self.i18n.t("workshop_mods_path"),
            self.workshop_mods_edit.text().strip(),
        )
        if selected:
            self.workshop_mods_edit.setText(selected)

    def values(self) -> dict:
        return {
            "app_language": self.app_lang_combo.currentData(),
            "language": self.mod_lang_combo.currentData(),
            "fallback_language": self.fallback_combo.currentData(),
            "debug_logging_enabled": self.debug_logging_checkbox.isChecked(),
            "deepl_api_key": self.key_edit.text().strip(),
            "appworkshop_path": self.appworkshop_edit.text().strip(),
            "workshop_mods_path": self.workshop_mods_edit.text().strip(),
            "duplicate_behavior": self.duplicate_behavior_combo.currentData(),
            "parallel_install_enabled": self.parallel_install_checkbox.isChecked(),
            "delete_download_archives_after_install": self.delete_download_archives_checkbox.isChecked(),
            "max_parallel_workers": self.max_workers_spin.value(),
        }


class DuplicateResolutionDialog(QDialog):
    def __init__(self, i18n, match: dict, parent=None) -> None:
        super().__init__(parent)
        self.i18n = i18n
        self.match = match
        self.selected_action = "skip"
        self.setWindowTitle(self.i18n.t("duplicate_dialog_title"))
        self.resize(820, 320)

        local_mod = match.get("local_mod", {})
        workshop_mod = match.get("workshop_mod", {})

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(12)

        title = QLabel(self.i18n.t("duplicate_dialog_title"))
        title.setObjectName("SectionTitle")
        root.addWidget(title)

        summary = QLabel(
            self.i18n.t(
                "duplicate_summary",
                local_name=local_mod.get("name", local_mod.get("id", "-")),
                workshop_name=workshop_mod.get("name", workshop_mod.get("id", "-")),
                workshop_id=match.get("workshop_id", "-"),
                score=match.get("score", 0),
            )
        )
        summary.setWordWrap(True)
        root.addWidget(summary)

        reason = QLabel(self.i18n.t("duplicate_reason", value=match.get("reason", "")))
        reason.setWordWrap(True)
        root.addWidget(reason)

        table = QTableWidget(2, 4)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.verticalHeader().setVisible(False)
        table.horizontalHeader().setStretchLastSection(True)
        table.setHorizontalHeaderLabels(
            [
                self.i18n.t("duplicate_source"),
                self.i18n.t("col_name"),
                self.i18n.t("col_author"),
                self.i18n.t("col_path"),
            ]
        )

        rows = [
            (self.i18n.t("duplicate_local_mod"), local_mod),
            (self.i18n.t("duplicate_workshop_mod"), workshop_mod),
        ]
        for row, (source, mod) in enumerate(rows):
            table.setItem(row, 0, QTableWidgetItem(source))
            table.setItem(row, 1, QTableWidgetItem(mod.get("name", "")))
            table.setItem(row, 2, QTableWidgetItem(mod.get("author", "")))
            path_text = mod.get("path", "")
            if row == 1 and match.get("workshop_id"):
                path_text = f"{path_text} (ID {match['workshop_id']})"
            table.setItem(row, 3, QTableWidgetItem(path_text))
        root.addWidget(table)

        actions = QHBoxLayout()
        actions.addStretch(1)

        delete_local_button = QPushButton(self.i18n.t("duplicate_delete_local"))
        delete_local_button.setProperty("accent", True)
        delete_local_button.clicked.connect(lambda: self._finish("delete_local"))
        actions.addWidget(delete_local_button)

        delete_workshop_button = QPushButton(self.i18n.t("duplicate_delete_workshop"))
        delete_workshop_button.clicked.connect(lambda: self._finish("delete_workshop"))
        actions.addWidget(delete_workshop_button)

        skip_button = QPushButton(self.i18n.t("duplicate_skip"))
        skip_button.clicked.connect(lambda: self._finish("skip"))
        actions.addWidget(skip_button)
        root.addLayout(actions)

    def _finish(self, action: str) -> None:
        self.selected_action = action
        self.accept()


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

    reader = QImageReader(str(path))
    image = reader.read()
    if not image.isNull():
        pixmap = QPixmap.fromImage(image)
        if not pixmap.isNull():
            return pixmap

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
            pass

    if path.suffix.lower() == ".tga":
        image = _load_tga_qimage(path)
        if image is not None:
            return QPixmap.fromImage(image)
    return None
