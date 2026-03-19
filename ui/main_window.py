import os
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QThread, Qt, Signal
from PySide6.QtGui import QAction, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from helpers.archive_helper import ARCHIVE_EXTENSIONS
from helpers.config_helper import load_config, save_config
from helpers.i18n import APP_LANGS, I18N
from helpers.mods_helper import (
    SUPPORTED_MOD_LANGS,
    delete_mod_folder,
    delete_or_unsubscribe_workshop_mod,
)
from ui.dialogs import DuplicateResolutionDialog, ModDetailsPage, SettingsDialog
from ui.workers import DuplicateScanWorker, InstallWorker, ScanWorker


class DropZone(QFrame):
    paths_dropped = Signal(list)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("DropZone")
        self.setAcceptDrops(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(6)

        self.title_label = QLabel()
        self.title_label.setObjectName("SectionTitle")
        self.title_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.title_label)

        self.subtitle_label = QLabel()
        self.subtitle_label.setObjectName("MutedLabel")
        self.subtitle_label.setAlignment(Qt.AlignCenter)
        self.subtitle_label.setWordWrap(True)
        layout.addWidget(self.subtitle_label)

    def setTexts(self, title: str, subtitle: str) -> None:
        self.title_label.setText(title)
        self.subtitle_label.setText(subtitle)

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasUrls():
            self.setProperty("dragActive", True)
            self.style().unpolish(self)
            self.style().polish(self)
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragLeaveEvent(self, event) -> None:
        self.setProperty("dragActive", False)
        self.style().unpolish(self)
        self.style().polish(self)
        super().dragLeaveEvent(event)

    def dropEvent(self, event) -> None:
        self.setProperty("dragActive", False)
        self.style().unpolish(self)
        self.style().polish(self)
        paths = []
        for url in event.mimeData().urls():
            if url.isLocalFile():
                paths.append(Path(url.toLocalFile()))
        if paths:
            self.paths_dropped.emit(paths)
            event.acceptProposedAction()
        else:
            event.ignore()


class ModManagerMainWindow(QMainWindow):
    def __init__(self, resource_dir: Path, data_dir: Path) -> None:
        super().__init__()
        self.resource_dir = resource_dir
        self.data_dir = data_dir
        self.config_path = self.data_dir / "config.json"
        self.app_strings_path = self.resource_dir / "resources" / "app_strings.json"
        self.logo_path = self.resource_dir / "media" / "logo.png"

        self.config = load_config(self.config_path)
        self.i18n = I18N(self.app_strings_path, self.config.get("app_language", "de"))

        self.mods_data: list[dict] = []
        self.filtered_mods: list[dict] = []
        self.current_mod: dict | None = None

        self.scan_thread: QThread | None = None
        self.scan_worker: ScanWorker | None = None
        self.scan_in_progress = False
        self.duplicate_thread: QThread | None = None
        self.duplicate_worker: DuplicateScanWorker | None = None
        self.duplicate_scan_in_progress = False
        self.install_thread: QThread | None = None
        self.install_worker: InstallWorker | None = None
        self.install_in_progress = False

        self.setWindowTitle(self.i18n.t("app_title"))
        self.resize(1380, 860)
        self.setMinimumSize(1040, 700)

        self._build_ui()
        self._apply_language()
        self.refresh_table()

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)

        root = QHBoxLayout(central)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(18)

        sidebar = QFrame()
        sidebar.setObjectName("SidebarCard")
        sidebar.setFixedWidth(260)
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(18, 18, 18, 18)
        sidebar_layout.setSpacing(18)

        self.window_title_label = QLabel()
        self.window_title_label.setObjectName("WindowTitle")
        self.window_title_label.setWordWrap(True)
        self.window_title_label.setAlignment(Qt.AlignCenter)
        sidebar_layout.addWidget(self.window_title_label)

        self.logo_label = QLabel()
        self.logo_label.setAlignment(Qt.AlignCenter)
        self.logo_label.setMinimumHeight(120)
        self.logo_label.setMaximumHeight(180)
        sidebar_layout.addWidget(self.logo_label)

        subtitle = QLabel("Transport Fever 2")
        subtitle.setObjectName("MutedLabel")
        subtitle.setAlignment(Qt.AlignCenter)
        sidebar_layout.addWidget(subtitle)

        self.settings_button = QPushButton()
        self.settings_button.clicked.connect(self.open_settings_dialog)
        sidebar_layout.addWidget(self.settings_button)

        sidebar_layout.addStretch(1)

        self.stats_label = QLabel()
        self.stats_label.setObjectName("SectionTitle")
        sidebar_layout.addWidget(self.stats_label)

        self.status_hint_label = QLabel()
        self.status_hint_label.setObjectName("MutedLabel")
        self.status_hint_label.setWordWrap(True)
        sidebar_layout.addWidget(self.status_hint_label)

        root.addWidget(sidebar)

        self.content_stack = QStackedWidget()
        root.addWidget(self.content_stack, 1)

        self.overview_page = QWidget()
        content = QVBoxLayout(self.overview_page)
        content.setContentsMargins(0, 0, 0, 0)
        content.setSpacing(16)

        top_card = QFrame()
        top_card.setObjectName("PanelCard")
        top_layout = QGridLayout(top_card)
        top_layout.setContentsMargins(18, 18, 18, 18)
        top_layout.setHorizontalSpacing(12)
        top_layout.setVerticalSpacing(12)

        self.mods_dir_label = QLabel()
        self.mods_dir_label.setObjectName("SectionTitle")
        top_layout.addWidget(self.mods_dir_label, 0, 0)

        self.path_edit = QLineEdit(self.config.get("mods_path", ""))
        self.path_edit.editingFinished.connect(self._persist_all)
        top_layout.addWidget(self.path_edit, 0, 1, 1, 2)

        self.browse_button = QPushButton()
        self.browse_button.clicked.connect(self.pick_folder)
        top_layout.addWidget(self.browse_button, 0, 3)

        self.scan_button = QPushButton()
        self.scan_button.setProperty("accent", True)
        self.scan_button.clicked.connect(self.scan)
        top_layout.addWidget(self.scan_button, 0, 4)

        self.find_duplicates_button = QPushButton()
        self.find_duplicates_button.clicked.connect(self.find_duplicates)
        top_layout.addWidget(self.find_duplicates_button, 0, 5)

        self.search_edit = QLineEdit()
        self.search_edit.textChanged.connect(self.refresh_table)
        top_layout.addWidget(self.search_edit, 1, 0, 1, 5)

        self.clear_button = QPushButton()
        self.clear_button.clicked.connect(self.clear_search)
        top_layout.addWidget(self.clear_button, 1, 5)

        self.install_button = QPushButton()
        self.install_button.setProperty("accent", True)
        self.install_button.clicked.connect(self.install_archives_from_dialog)
        top_layout.addWidget(self.install_button, 2, 5)

        content.addWidget(top_card)

        action_row = QHBoxLayout()
        action_row.setSpacing(16)
        content.addLayout(action_row)

        self.drop_zone = DropZone()
        self.drop_zone.paths_dropped.connect(self.install_inputs)
        action_row.addWidget(self.drop_zone, 1)

        progress_card = QFrame()
        progress_card.setObjectName("PanelCard")
        progress_layout = QVBoxLayout(progress_card)
        progress_layout.setContentsMargins(18, 18, 18, 18)
        progress_layout.setSpacing(12)

        progress_title = QLabel("Scan")
        progress_title.setObjectName("SectionTitle")
        progress_layout.addWidget(progress_title)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 1)
        self.progress_bar.setValue(0)
        progress_layout.addWidget(self.progress_bar)

        self.progress_label = QLabel()
        self.progress_label.setObjectName("StatusLabel")
        self.progress_label.setWordWrap(True)
        progress_layout.addWidget(self.progress_label)
        action_row.addWidget(progress_card)
        progress_card.setFixedWidth(300)

        splitter = QSplitter(Qt.Vertical)
        content.addWidget(splitter, 1)

        table_card = QFrame()
        table_card.setObjectName("PanelCard")
        table_layout = QVBoxLayout(table_card)
        table_layout.setContentsMargins(12, 12, 12, 12)
        table_layout.setSpacing(10)

        table_header = QHBoxLayout()
        table_title = QLabel(self.i18n.t("details_tab"))
        table_title.setObjectName("SectionTitle")
        table_header.addWidget(table_title)
        table_header.addStretch(1)
        self.table_summary_label = QLabel()
        self.table_summary_label.setObjectName("MutedLabel")
        table_header.addWidget(self.table_summary_label)
        table_layout.addLayout(table_header)

        self.table = QTableWidget(0, 4)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.itemDoubleClicked.connect(self.on_table_item_double_clicked)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self.show_context_menu)
        table_layout.addWidget(self.table)
        splitter.addWidget(table_card)

        log_card = QFrame()
        log_card.setObjectName("PanelCard")
        log_layout = QVBoxLayout(log_card)
        log_layout.setContentsMargins(12, 12, 12, 12)
        log_layout.setSpacing(10)

        log_title = QLabel("Log")
        log_title.setObjectName("SectionTitle")
        log_layout.addWidget(log_title)

        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        log_layout.addWidget(self.log_text)
        splitter.addWidget(log_card)
        splitter.setSizes([520, 220])

        self.content_stack.addWidget(self.overview_page)

        self.details_page = ModDetailsPage(self.i18n)
        self.details_page.back_requested.connect(self.show_overview_page)
        self.details_page.open_dependency.connect(self.show_mod_details)
        self.content_stack.addWidget(self.details_page)

        self.context_menu = QMenu(self)
        self.open_folder_action = QAction(self)
        self.open_folder_action.triggered.connect(self.open_selected_mod_folder)
        self.context_menu.addAction(self.open_folder_action)
        self.context_menu.addSeparator()
        self.delete_action = QAction(self)
        self.delete_action.triggered.connect(self.delete_selected_mod)
        self.context_menu.addAction(self.delete_action)

    def _apply_language(self) -> None:
        self.setWindowTitle(self.i18n.t("app_title"))
        self.window_title_label.setText(self.i18n.t("app_title"))
        self._update_branding()
        self.mods_dir_label.setText(self.i18n.t("mods_dir"))
        self.browse_button.setText(self.i18n.t("browse"))
        self.scan_button.setText(self.i18n.t("scan"))
        self.find_duplicates_button.setText(self.i18n.t("find_duplicates"))
        self.search_edit.setPlaceholderText(self.i18n.t("search"))
        self.clear_button.setText(self.i18n.t("clear"))
        self.install_button.setText(self.i18n.t("install_archives"))
        self.settings_button.setText(self.i18n.t("settings"))
        self.drop_zone.setTexts(self.i18n.t("install_mods"), self.i18n.t("drop_hint"))
        self.status_hint_label.setText(self.i18n.t("status_hint"))
        self.open_folder_action.setText(self.i18n.t("menu_open_folder"))
        self.delete_action.setText(self.i18n.t("menu_delete"))
        self.progress_label.setText(self.i18n.t("scan_prepare"))
        self.table.setHorizontalHeaderLabels(
            [
                self.i18n.t("col_name"),
                self.i18n.t("col_author"),
                self.i18n.t("col_version"),
                self.i18n.t("col_path"),
            ]
        )
        self.table.setColumnWidth(0, 250)
        self.table.setColumnWidth(1, 180)
        self.table.setColumnWidth(2, 100)
        self.table.setColumnWidth(3, 520)
        self.details_page.update_texts()
        if self.current_mod is not None:
            self.details_page.set_mod(
                self.current_mod,
                self.config.get("language", "de"),
                self.config.get("deepl_api_key", ""),
            )
        self.refresh_table()

    def _update_branding(self) -> None:
        self.logo_label.clear()
        if not self.logo_path.exists():
            return
        pixmap = QPixmap(str(self.logo_path))
        if pixmap.isNull():
            return
        self.logo_label.setPixmap(pixmap.scaledToWidth(180, Qt.SmoothTransformation))

    def _persist_all(self) -> None:
        self.config["mods_path"] = self.path_edit.text().strip()
        self.config["language"] = self.config.get("language", "de")
        self.config["fallback_language"] = self.config.get("fallback_language", "en")
        self.config["app_language"] = self.config.get("app_language", "de")
        self.config["deepl_api_key"] = self.config.get("deepl_api_key", "")
        self.config["appworkshop_path"] = self.config.get("appworkshop_path", "")
        self.config["workshop_mods_path"] = self.config.get("workshop_mods_path", "")
        self.config["duplicate_behavior"] = self.config.get("duplicate_behavior", "manual")
        self.config["parallel_install_enabled"] = bool(self.config.get("parallel_install_enabled", False))
        self.config["max_parallel_workers"] = int(self.config.get("max_parallel_workers", 2))
        save_config(self.config_path, self.config)

    def log(self, message: str) -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_text.append(f"[{timestamp}] {message}")

    def pick_folder(self) -> None:
        selected = QFileDialog.getExistingDirectory(self, self.i18n.t("mods_dir"), self.path_edit.text().strip())
        if selected:
            self.path_edit.setText(selected)
            self._persist_all()

    def get_mod_root(self) -> Path | None:
        folder = self.path_edit.text().strip()
        if not folder:
            QMessageBox.warning(self, self.i18n.t("warning"), self.i18n.t("need_mod_dir"))
            return None

        root = Path(folder)
        if not root.exists() or not root.is_dir():
            QMessageBox.critical(self, self.i18n.t("error"), self.i18n.t("invalid_mod_dir"))
            return None

        self._persist_all()
        return root

    def _update_action_state(self) -> None:
        busy = self.scan_in_progress or self.duplicate_scan_in_progress or self.install_in_progress
        for widget in [
            self.scan_button,
            self.find_duplicates_button,
            self.settings_button,
            self.browse_button,
            self.install_button,
        ]:
            widget.setEnabled(not busy)

    def scan(self) -> None:
        if self.scan_in_progress or self.duplicate_scan_in_progress or self.install_in_progress:
            return

        root = self.get_mod_root()
        if root is None:
            return

        self.progress_bar.setRange(0, 1)
        self.progress_bar.setValue(0)
        self.progress_label.setText(self.i18n.t("scan_prepare"))
        self.scan_in_progress = True
        self._update_action_state()

        self.scan_thread = QThread(self)
        self.scan_worker = ScanWorker(root, self.config.get("language", "de"), self.config.get("fallback_language", "en"))
        self.scan_worker.moveToThread(self.scan_thread)
        self.scan_thread.started.connect(self.scan_worker.run)
        self.scan_worker.progress.connect(self.on_scan_progress)
        self.scan_worker.log.connect(self.log)
        self.scan_worker.finished.connect(self.on_scan_finished)
        self.scan_worker.failed.connect(self.on_scan_failed)
        self.scan_worker.finished.connect(self.scan_thread.quit)
        self.scan_worker.failed.connect(self.scan_thread.quit)
        self.scan_thread.finished.connect(self.scan_thread.deleteLater)
        self.scan_thread.start()

    def on_scan_progress(self, done: int, total: int) -> None:
        self.progress_bar.setRange(0, max(1, total))
        self.progress_bar.setValue(done)
        self.progress_label.setText(self.i18n.t("scan_progress", current=done, total=total))

    def on_scan_finished(self, mods: list) -> None:
        self.mods_data = mods
        self.progress_bar.setValue(self.progress_bar.maximum())
        self.progress_label.setText(self.i18n.t("scan_progress_done"))
        self.refresh_table()
        self.log(self.i18n.t("scan_done", count=len(self.mods_data)))
        self._cleanup_scan()

    def on_scan_failed(self, error_text: str) -> None:
        self.log(f"ERROR: Scan aborted: {error_text}")
        QMessageBox.critical(self, self.i18n.t("error"), error_text)
        self._cleanup_scan()

    def _cleanup_scan(self) -> None:
        self.scan_in_progress = False
        self._update_action_state()
        self.scan_worker = None
        self.scan_thread = None

    def find_duplicates(self) -> None:
        if self.scan_in_progress or self.duplicate_scan_in_progress or self.install_in_progress:
            return

        local_root = self.get_mod_root()
        if local_root is None:
            return

        workshop_path_text = self.config.get("workshop_mods_path", "").strip()
        if not workshop_path_text:
            QMessageBox.warning(self, self.i18n.t("warning"), self.i18n.t("missing_workshop_mods_path"))
            return

        workshop_root = Path(workshop_path_text)
        if not workshop_root.exists() or not workshop_root.is_dir():
            QMessageBox.critical(self, self.i18n.t("error"), self.i18n.t("invalid_workshop_mods_path"))
            return

        appworkshop_text = self.config.get("appworkshop_path", "").strip()
        appworkshop_path = Path(appworkshop_text) if appworkshop_text else None
        if appworkshop_path is not None and (not appworkshop_path.exists() or not appworkshop_path.is_file()):
            QMessageBox.critical(self, self.i18n.t("error"), self.i18n.t("invalid_appworkshop_path"))
            return

        self.progress_bar.setRange(0, 1)
        self.progress_bar.setValue(0)
        self.progress_label.setText(self.i18n.t("duplicate_scan_prepare"))
        self.duplicate_scan_in_progress = True
        self._update_action_state()

        self.duplicate_thread = QThread(self)
        self.duplicate_worker = DuplicateScanWorker(
            local_root,
            workshop_root,
            appworkshop_path,
            self.config.get("language", "de"),
            self.config.get("fallback_language", "en"),
        )
        self.duplicate_worker.moveToThread(self.duplicate_thread)
        self.duplicate_thread.started.connect(self.duplicate_worker.run)
        self.duplicate_worker.progress.connect(self.on_duplicate_progress)
        self.duplicate_worker.log.connect(self.log)
        self.duplicate_worker.finished.connect(self.on_duplicate_finished)
        self.duplicate_worker.failed.connect(self.on_duplicate_failed)
        self.duplicate_worker.finished.connect(self.duplicate_thread.quit)
        self.duplicate_worker.failed.connect(self.duplicate_thread.quit)
        self.duplicate_thread.finished.connect(self.duplicate_thread.deleteLater)
        self.duplicate_thread.start()

    def on_duplicate_progress(self, current: int, total: int, status: str) -> None:
        self.progress_bar.setRange(0, max(1, total))
        self.progress_bar.setValue(current)
        self.progress_label.setText(status or self.i18n.t("duplicate_scan_prepare"))

    def on_duplicate_finished(self, matches: list) -> None:
        self.progress_bar.setValue(self.progress_bar.maximum())
        self.progress_label.setText(self.i18n.t("duplicate_scan_done"))
        self.log(self.i18n.t("duplicate_found_count", count=len(matches)))
        self._cleanup_duplicate_scan()
        self._handle_duplicate_matches(matches)

    def on_duplicate_failed(self, error_text: str) -> None:
        self.log(f"ERROR: Duplicate scan aborted: {error_text}")
        QMessageBox.critical(self, self.i18n.t("error"), error_text)
        self._cleanup_duplicate_scan()

    def _cleanup_duplicate_scan(self) -> None:
        self.duplicate_scan_in_progress = False
        self._update_action_state()
        self.duplicate_worker = None
        self.duplicate_thread = None

    def _handle_duplicate_matches(self, matches: list[dict]) -> None:
        if not matches:
            QMessageBox.information(self, self.i18n.t("find_duplicates"), self.i18n.t("duplicate_none_found"))
            return

        behavior = self.config.get("duplicate_behavior", "manual")
        action_count = 0
        auto_count = 0
        manual_count = 0
        appworkshop_path = Path(self.config.get("appworkshop_path", "").strip()) if self.config.get("appworkshop_path", "").strip() else None

        for match in matches:
            if behavior == "auto_above_85" and float(match.get("score", 0)) > 85:
                if self._apply_duplicate_action(match, "delete_local", appworkshop_path):
                    action_count += 1
                    auto_count += 1
                continue

            dialog = DuplicateResolutionDialog(self.i18n, match, self)
            dialog.exec()
            if dialog.selected_action != "skip":
                if self._apply_duplicate_action(match, dialog.selected_action, appworkshop_path):
                    action_count += 1
                    manual_count += 1

        QMessageBox.information(
            self,
            self.i18n.t("find_duplicates"),
            self.i18n.t(
                "duplicate_action_summary",
                found=len(matches),
                actions=action_count,
                auto=auto_count,
                manual=manual_count,
            ),
        )
        if action_count:
            self.scan()

    def _apply_duplicate_action(self, match: dict, action: str, appworkshop_path: Path | None) -> bool:
        local_mod = match.get("local_mod", {})
        workshop_mod = match.get("workshop_mod", {})
        score = match.get("score", 0)
        self.log(
            self.i18n.t(
                "duplicate_action_log",
                action=action,
                local=local_mod.get("name", local_mod.get("id", "-")),
                workshop=workshop_mod.get("name", workshop_mod.get("id", "-")),
                score=score,
            )
        )

        if action == "delete_local":
            ok, message = delete_mod_folder(Path(local_mod.get("path", "")))
        elif action == "delete_workshop":
            ok, message = delete_or_unsubscribe_workshop_mod(workshop_mod, appworkshop_path)
        else:
            return False

        if ok:
            self.log(message)
        else:
            self.log(f"ERROR: {message}")
            QMessageBox.critical(self, self.i18n.t("error"), message)
        return ok

    def format_dependency_cell(self, mod: dict) -> str:
        links = mod.get("dependency_links", [])
        if not links:
            return "-"
        values = []
        for dep in links:
            target = dep.get("target")
            if target:
                values.append(f"{dep['id']} -> {target.get('name', dep['id'])}")
            else:
                values.append(f"{dep['id']} (missing)")
        return ", ".join(values)

    def refresh_table(self) -> None:
        query = self.search_edit.text().strip().lower()
        self.filtered_mods = []
        for mod in self.mods_data:
            text = " ".join(
                [
                    mod.get("name", ""),
                    mod.get("author", ""),
                    mod.get("version", ""),
                    mod.get("path", ""),
                    self.format_dependency_cell(mod),
                    mod.get("description_translated", ""),
                ]
            ).lower()
            if query and query not in text:
                continue
            self.filtered_mods.append(mod)

        self.table.setRowCount(0)
        for row, mod in enumerate(self.filtered_mods):
            self.table.insertRow(row)
            values = [
                mod.get("name", ""),
                mod.get("author", ""),
                mod.get("version", ""),
                mod.get("path", ""),
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                item.setData(Qt.UserRole, mod)
                self.table.setItem(row, column, item)

        if query:
            count_text = self.i18n.t("mods_count_filtered", shown=len(self.filtered_mods), total=len(self.mods_data))
        else:
            count_text = self.i18n.t("mods_count", count=len(self.filtered_mods))
        self.stats_label.setText(count_text)
        self.table_summary_label.setText(count_text)

    def clear_search(self) -> None:
        self.search_edit.clear()

    def get_selected_mod(self) -> dict | None:
        row = self.table.currentRow()
        if row < 0:
            return None
        item = self.table.item(row, 0)
        if item is None:
            return None
        return item.data(Qt.UserRole)

    def show_context_menu(self, pos) -> None:
        index = self.table.indexAt(pos)
        if not index.isValid():
            return
        self.table.selectRow(index.row())
        self.context_menu.exec(self.table.viewport().mapToGlobal(pos))

    def on_table_item_double_clicked(self, item: QTableWidgetItem) -> None:
        mod = item.data(Qt.UserRole)
        if not mod:
            return
        self.show_mod_details(mod)

    def show_mod_details(self, mod: dict) -> None:
        mod_path = Path(mod.get("path", ""))
        mod_lua = mod_path / "mod.lua"
        if not mod_lua.exists():
            QMessageBox.critical(self, self.i18n.t("error"), self.i18n.t("missing_mod_lua", path=str(mod_lua)))
            return

        self.current_mod = mod
        self.details_page.set_mod(
            mod,
            self.config.get("language", "de"),
            self.config.get("deepl_api_key", ""),
        )
        self.content_stack.setCurrentWidget(self.details_page)

    def show_overview_page(self) -> None:
        self.content_stack.setCurrentWidget(self.overview_page)

    def open_selected_mod_folder(self) -> None:
        mod = self.get_selected_mod()
        if not mod:
            return

        mod_path = Path(mod.get("path", ""))
        if not mod_path.exists():
            QMessageBox.critical(self, self.i18n.t("error"), self.i18n.t("missing_mod_lua", path=str(mod_path)))
            return

        os.startfile(str(mod_path))

    def delete_selected_mod(self) -> None:
        mod = self.get_selected_mod()
        if not mod:
            return

        required_by = mod.get("required_by", [])
        if required_by:
            users = ", ".join(sorted({entry.get("name", entry.get("id", "?")) for entry in required_by}))
            answer = QMessageBox.question(
                self,
                self.i18n.t("dependency_warning_title"),
                self.i18n.t("dependency_warning_text", users=users),
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                return

        mod_path = Path(mod.get("path", ""))
        answer = QMessageBox.question(
            self,
            self.i18n.t("menu_delete"),
            self.i18n.t("delete_confirm", name=mod.get("name", mod_path.name)),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return

        try:
            ok, message = delete_mod_folder(mod_path)
            if not ok:
                raise RuntimeError(message)
            self.log(message)
            self.scan()
        except Exception as exc:
            QMessageBox.critical(self, self.i18n.t("error"), str(exc))

    def open_settings_dialog(self) -> None:
        dialog = SettingsDialog(self.i18n, APP_LANGS, SUPPORTED_MOD_LANGS, self.config, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        self.config.update(dialog.values())
        self.i18n.set_language(self.config.get("app_language", "de"))
        self._persist_all()
        self._apply_language()
        self.log(self.i18n.t("settings_saved"))

        if self.mods_data:
            self.scan()

    def install_archives_from_dialog(self) -> None:
        selected, _ = QFileDialog.getOpenFileNames(
            self,
            self.i18n.t("install_archives"),
            "",
            "Archives (*.zip *.7z *.rar);;ZIP (*.zip);;7Z (*.7z);;RAR (*.rar);;All files (*.*)",
        )
        self.install_inputs([Path(path) for path in selected])

    def install_inputs(self, paths: list[Path]) -> None:
        if not paths or self.scan_in_progress or self.duplicate_scan_in_progress or self.install_in_progress:
            return

        mods_root = self.get_mod_root()
        if mods_root is None:
            return

        filtered_paths = []
        for path in paths:
            if path.is_dir() or (path.is_file() and path.suffix.lower() in ARCHIVE_EXTENSIONS):
                filtered_paths.append(path)
            else:
                self.log(f"ERROR: Unsupported input: {path.name}")

        if not filtered_paths:
            return

        self.install_in_progress = True
        self._update_action_state()
        self.progress_bar.setRange(0, max(1, len(filtered_paths)))
        self.progress_bar.setValue(0)
        self.progress_label.setText("Installiere Mods...")

        self.install_thread = QThread(self)
        self.install_worker = InstallWorker(
            filtered_paths,
            mods_root,
            self.i18n.t("no_mod_lua"),
            bool(self.config.get("parallel_install_enabled", False)),
            int(self.config.get("max_parallel_workers", 2)),
        )
        self.install_worker.moveToThread(self.install_thread)
        self.install_thread.started.connect(self.install_worker.run)
        self.install_worker.progress.connect(self.on_install_progress)
        self.install_worker.log.connect(self.log)
        self.install_worker.finished.connect(self.on_install_finished)
        self.install_worker.failed.connect(self.on_install_failed)
        self.install_worker.finished.connect(self.install_thread.quit)
        self.install_worker.failed.connect(self.install_thread.quit)
        self.install_thread.finished.connect(self.install_thread.deleteLater)
        self.install_thread.start()

    def on_install_progress(self, current: int, total: int, status: str) -> None:
        self.progress_bar.setRange(0, max(1, total))
        self.progress_bar.setValue(current)
        self.progress_label.setText(status or self.i18n.t("install_progress", current=current, total=total))

    def on_install_finished(self, any_success: bool) -> None:
        self.progress_bar.setValue(self.progress_bar.maximum())
        self.progress_label.setText(self.i18n.t("install_progress_done"))
        self.install_in_progress = False
        self._update_action_state()
        self.install_worker = None
        self.install_thread = None
        if any_success:
            self.scan()

    def on_install_failed(self, error_text: str) -> None:
        self.log(f"ERROR: Installation aborted: {error_text}")
        QMessageBox.critical(self, self.i18n.t("error"), error_text)
        self.install_in_progress = False
        self._update_action_state()
        self.install_worker = None
        self.install_thread = None
