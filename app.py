import os
import queue
import shutil
import tempfile
import threading
import tkinter as tk
import webbrowser
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from helpers.archive_helper import (
    ARCHIVE_EXTENSIONS,
    extract_archive,
    find_valid_mod_roots,
    install_mod_folder,
    parse_drop_files,
)
from helpers.config_helper import load_config, save_config
from helpers.deepl_helper import DeepLClient
from helpers.i18n import APP_LANGS, I18N
from helpers.mods_helper import (
    SUPPORTED_MOD_LANGS,
    find_mod_link,
    find_preview_image,
    scan_mods_parallel,
)

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD

    DND_AVAILABLE = True
except ImportError:
    DND_AVAILABLE = False
    DND_FILES = None
    TkinterDnD = None

try:
    from PIL import Image, ImageTk

    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False
    Image = None
    ImageTk = None


BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "config.json"
APP_STRINGS_PATH = BASE_DIR / "resources" / "app_strings.json"
DEEPL_GUIDE_URL = "https://www.deepl.com/en/pro/change-plan#developer"

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

BaseWindow = TkinterDnD.Tk if DND_AVAILABLE else tk.Tk


class TpF2ModManagerApp(BaseWindow):
    def __init__(self) -> None:
        super().__init__()

        self.config = load_config(CONFIG_PATH)
        self.i18n = I18N(APP_STRINGS_PATH, self.config.get("app_language", "de"))

        self.path_var = tk.StringVar(value=self.config.get("mods_path", ""))
        self.search_var = tk.StringVar()
        self.mod_lang_var = tk.StringVar(value=self.config.get("language", "de"))
        self.fallback_lang_var = tk.StringVar(value=self.config.get("fallback_language", "en"))
        self.app_lang_var = tk.StringVar(value=self.config.get("app_language", "de"))
        self.deepl_key_var = tk.StringVar(value=self.config.get("deepl_api_key", ""))

        self.count_var = tk.StringVar(value="")
        self.progress_var = tk.StringVar(value="")

        self.mods_data: list[dict] = []
        self.item_to_mod: dict[str, dict] = {}
        self.settings_window: tk.Toplevel | None = None
        self.scan_queue: queue.Queue = queue.Queue()
        self.scan_thread: threading.Thread | None = None
        self.scan_in_progress = False

        self._setup_style()
        self._build_ui()
        self._apply_language_labels()

        if not DND_AVAILABLE:
            self.log(self.i18n.t("drop_disabled"))

    def _setup_style(self) -> None:
        style = ttk.Style(self)
        if "clam" in style.theme_names():
            style.theme_use("clam")

        default_font = ("Segoe UI", 10)
        style.configure("TLabel", font=default_font)
        style.configure("TButton", font=default_font, padding=6)
        style.configure("TEntry", font=default_font)
        style.configure("Treeview", rowheight=26, font=default_font)
        style.configure("Treeview.Heading", font=("Segoe UI Semibold", 10))
        style.configure("Header.TLabel", font=("Segoe UI Semibold", 15))

    def _build_ui(self) -> None:
        self.geometry("1280x850")
        self.minsize(980, 620)

        root = ttk.Frame(self, padding=12)
        root.pack(fill=tk.BOTH, expand=True)

        header = ttk.Frame(root)
        header.pack(fill=tk.X, pady=(0, 10))
        self.header_label = ttk.Label(header, style="Header.TLabel")
        self.header_label.pack(side=tk.LEFT)
        self.settings_btn = ttk.Button(header, command=self.open_settings_window)
        self.settings_btn.pack(side=tk.RIGHT)

        path_frame = ttk.Frame(root)
        path_frame.pack(fill=tk.X)
        self.path_label = ttk.Label(path_frame)
        self.path_label.pack(side=tk.LEFT)
        ttk.Entry(path_frame, textvariable=self.path_var).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=8)
        self.browse_btn = ttk.Button(path_frame, command=self.pick_folder)
        self.browse_btn.pack(side=tk.LEFT)
        self.scan_btn = ttk.Button(path_frame, command=self.scan)
        self.scan_btn.pack(side=tk.LEFT, padx=(8, 0))

        action_frame = ttk.Frame(root)
        action_frame.pack(fill=tk.X, pady=(10, 8))
        self.install_btn = ttk.Button(action_frame, command=self.install_archives_from_dialog)
        self.install_btn.pack(side=tk.LEFT)

        self.drop_label = ttk.Label(action_frame, anchor="center", relief="ridge", padding=10)
        self.drop_label.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(10, 0))
        if DND_AVAILABLE:
            self.drop_label.drop_target_register(DND_FILES)
            self.drop_label.dnd_bind("<<Drop>>", self.on_drop)

        search_frame = ttk.Frame(root)
        search_frame.pack(fill=tk.X, pady=(0, 8))
        self.search_label = ttk.Label(search_frame)
        self.search_label.pack(side=tk.LEFT)
        search_entry = ttk.Entry(search_frame, textvariable=self.search_var)
        search_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(8, 8))
        search_entry.bind("<KeyRelease>", self.on_search_changed)
        self.clear_btn = ttk.Button(search_frame, command=self.clear_search)
        self.clear_btn.pack(side=tk.LEFT)

        progress_frame = ttk.Frame(root)
        progress_frame.pack(fill=tk.X, pady=(0, 8))
        self.progress = ttk.Progressbar(progress_frame, mode="determinate")
        self.progress.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.progress_label = ttk.Label(progress_frame, textvariable=self.progress_var)
        self.progress_label.pack(side=tk.LEFT, padx=(8, 0))

        paned = ttk.Panedwindow(root, orient=tk.VERTICAL)
        paned.pack(fill=tk.BOTH, expand=True)

        table_container = ttk.Frame(paned)
        paned.add(table_container, weight=4)

        columns = ("name", "author", "version", "dependencies", "path")
        self.tree = ttk.Treeview(table_container, columns=columns, show="headings")
        self.tree.column("name", width=240, anchor=tk.W)
        self.tree.column("author", width=180, anchor=tk.W)
        self.tree.column("version", width=90, anchor=tk.W)
        self.tree.column("dependencies", width=320, anchor=tk.W)
        self.tree.column("path", width=430, anchor=tk.W)
        self.tree.bind("<Double-1>", self.on_tree_double_click)
        self.tree.bind("<Button-3>", self.on_tree_right_click)

        vsb = ttk.Scrollbar(table_container, orient=tk.VERTICAL, command=self.tree.yview)
        hsb = ttk.Scrollbar(table_container, orient=tk.HORIZONTAL, command=self.tree.xview)
        self.tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        table_container.rowconfigure(0, weight=1)
        table_container.columnconfigure(0, weight=1)

        log_container = ttk.Frame(paned)
        paned.add(log_container, weight=1)

        status_frame = ttk.Frame(log_container)
        status_frame.pack(fill=tk.X, pady=(0, 4))
        ttk.Label(status_frame, textvariable=self.count_var).pack(side=tk.LEFT)
        self.status_hint_label = ttk.Label(status_frame, foreground="#4b5563")
        self.status_hint_label.pack(side=tk.RIGHT)

        self.log_text = tk.Text(log_container, height=8, wrap="word", font=("Consolas", 10))
        self.log_text.pack(fill=tk.BOTH, expand=True)
        log_scroll = ttk.Scrollbar(log_container, orient=tk.VERTICAL, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=log_scroll.set)
        log_scroll.place(in_=self.log_text, relx=1.0, rely=0.0, relheight=1.0, anchor="ne")

        self.row_menu = tk.Menu(self, tearoff=0)
        self.row_menu.add_command(command=self.open_selected_mod_folder)
        self.row_menu.add_separator()
        self.row_menu.add_command(command=self.delete_selected_mod)

    def _apply_language_labels(self) -> None:
        self.title(self.i18n.t("app_title"))
        self.header_label.configure(text=self.i18n.t("app_title"))
        self.settings_btn.configure(text=self.i18n.t("settings"))
        self.path_label.configure(text=self.i18n.t("mods_dir"))
        self.browse_btn.configure(text=self.i18n.t("browse"))
        self.scan_btn.configure(text=self.i18n.t("scan"))
        self.install_btn.configure(text=self.i18n.t("install_archives"))
        self.drop_label.configure(text=self.i18n.t("drop_hint") if DND_AVAILABLE else self.i18n.t("drop_disabled"))
        self.search_label.configure(text=self.i18n.t("search"))
        self.clear_btn.configure(text=self.i18n.t("clear"))
        self.status_hint_label.configure(text=self.i18n.t("status_hint"))

        self.tree.heading("name", text=self.i18n.t("col_name"))
        self.tree.heading("author", text=self.i18n.t("col_author"))
        self.tree.heading("version", text=self.i18n.t("col_version"))
        self.tree.heading("dependencies", text=self.i18n.t("col_dependencies"))
        self.tree.heading("path", text=self.i18n.t("col_path"))

        self.row_menu.entryconfigure(0, label=self.i18n.t("menu_open_folder"))
        self.row_menu.entryconfigure(2, label=self.i18n.t("menu_delete"))

    def _persist(self) -> None:
        self.config["mods_path"] = self.path_var.get().strip()
        self.config["language"] = self.mod_lang_var.get().strip()
        self.config["fallback_language"] = self.fallback_lang_var.get().strip()
        self.config["app_language"] = self.app_lang_var.get().strip()
        self.config["deepl_api_key"] = self.deepl_key_var.get().strip()
        save_config(CONFIG_PATH, self.config)

    def log(self, message: str) -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_text.insert(tk.END, f"[{timestamp}] {message}\n")
        self.log_text.see(tk.END)

    def open_settings_window(self) -> None:
        if self.settings_window and self.settings_window.winfo_exists():
            self.settings_window.focus_set()
            return

        win = tk.Toplevel(self)
        self.settings_window = win
        win.title(self.i18n.t("settings_title"))
        win.geometry("620x250")
        win.resizable(False, False)

        temp_app_lang = tk.StringVar(value=self.app_lang_var.get())
        temp_mod_lang = tk.StringVar(value=self.mod_lang_var.get())
        temp_fallback = tk.StringVar(value=self.fallback_lang_var.get())
        temp_key = tk.StringVar(value=self.deepl_key_var.get())

        frm = ttk.Frame(win, padding=12)
        frm.pack(fill=tk.BOTH, expand=True)

        row1 = ttk.Frame(frm)
        row1.pack(fill=tk.X, pady=(0, 8))
        ttk.Label(row1, text=self.i18n.t("app_lang")).pack(side=tk.LEFT)
        app_combo = ttk.Combobox(row1, state="readonly", values=[APP_LANG_LABELS[k] for k in APP_LANGS], width=14)
        app_combo.pack(side=tk.LEFT, padx=(8, 0))
        app_combo.set(APP_LANG_LABELS.get(temp_app_lang.get(), APP_LANG_LABELS["de"]))

        row2 = ttk.Frame(frm)
        row2.pack(fill=tk.X, pady=(0, 8))
        ttk.Label(row2, text=self.i18n.t("mod_lang")).pack(side=tk.LEFT)
        mod_combo = ttk.Combobox(row2, state="readonly", values=[LANG_LABELS[k] for k in SUPPORTED_MOD_LANGS], width=16)
        mod_combo.pack(side=tk.LEFT, padx=(8, 16))
        mod_combo.set(LANG_LABELS.get(temp_mod_lang.get(), LANG_LABELS["de"]))
        ttk.Label(row2, text=self.i18n.t("fallback")).pack(side=tk.LEFT)
        fallback_combo = ttk.Combobox(row2, state="readonly", values=[LANG_LABELS[k] for k in SUPPORTED_MOD_LANGS], width=16)
        fallback_combo.pack(side=tk.LEFT, padx=(8, 0))
        fallback_combo.set(LANG_LABELS.get(temp_fallback.get(), LANG_LABELS["en"]))

        row3 = ttk.Frame(frm)
        row3.pack(fill=tk.X, pady=(0, 8))
        ttk.Label(row3, text=self.i18n.t("deepl_key")).pack(side=tk.LEFT)
        key_entry = ttk.Entry(row3, textvariable=temp_key, width=42, show="*")
        key_entry.pack(side=tk.LEFT, padx=(8, 8))
        ttk.Button(row3, text=self.i18n.t("deepl_help"), command=lambda: webbrowser.open(DEEPL_GUIDE_URL)).pack(side=tk.LEFT)

        ttk.Label(frm, text=self.i18n.t("guide_info"), foreground="#4b5563").pack(anchor="w", pady=(6, 10))

        btn_row = ttk.Frame(frm)
        btn_row.pack(fill=tk.X)

        def save_settings() -> None:
            app_label = app_combo.get()
            mod_label = mod_combo.get()
            fallback_label = fallback_combo.get()

            for code, label in APP_LANG_LABELS.items():
                if label == app_label:
                    self.app_lang_var.set(code)
                    break
            for code, label in LANG_LABELS.items():
                if label == mod_label:
                    self.mod_lang_var.set(code)
                if label == fallback_label:
                    self.fallback_lang_var.set(code)

            self.deepl_key_var.set(temp_key.get().strip())

            self.i18n.set_language(self.app_lang_var.get())
            self._apply_language_labels()
            self._persist()
            self.log(self.i18n.t("settings_saved"))
            win.destroy()

            if self.mods_data:
                self.scan()

        ttk.Button(btn_row, text=self.i18n.t("save"), command=save_settings).pack(side=tk.RIGHT)
        ttk.Button(btn_row, text=self.i18n.t("cancel"), command=win.destroy).pack(side=tk.RIGHT, padx=(0, 8))

    def pick_folder(self) -> None:
        selected = filedialog.askdirectory(title=self.i18n.t("mods_dir"))
        if selected:
            self.path_var.set(selected)
            self._persist()

    def get_mod_root(self) -> Path | None:
        folder = self.path_var.get().strip()
        if not folder:
            messagebox.showwarning(self.i18n.t("warning"), self.i18n.t("need_mod_dir"))
            return None

        root = Path(folder)
        if not root.exists() or not root.is_dir():
            messagebox.showerror(self.i18n.t("error"), self.i18n.t("invalid_mod_dir"))
            return None

        self._persist()
        return root

    def _set_scan_state(self, in_progress: bool) -> None:
        self.scan_in_progress = in_progress
        state = "disabled" if in_progress else "normal"
        self.scan_btn.configure(state=state)
        self.settings_btn.configure(state=state)
        self.browse_btn.configure(state=state)
        self.install_btn.configure(state=state)

    def _scan_worker(self, root: Path, primary_lang: str, fallback_lang: str) -> None:
        try:
            cpu = os.cpu_count() or 4
            max_workers = max(4, min(20, cpu * 2))

            # Performance: Skip DeepL during scan. Translate lazily in details view.
            deepl_client = None

            def on_progress(done: int, total: int) -> None:
                self.scan_queue.put(("progress", done, total))

            mods = scan_mods_parallel(
                root,
                primary_lang,
                fallback_lang,
                deepl_client=deepl_client,
                max_workers=max_workers,
                progress_callback=on_progress,
            )
            self.scan_queue.put(("done", mods))
        except Exception as exc:
            self.scan_queue.put(("error", str(exc)))

    def _process_scan_queue(self) -> None:
        has_terminal_message = False

        while True:
            try:
                message = self.scan_queue.get_nowait()
            except queue.Empty:
                break

            kind = message[0]
            if kind == "progress":
                _, done, total = message
                self.progress.configure(maximum=max(1, total), value=done)
                self.progress_var.set(self.i18n.t("scan_progress", current=done, total=total))
            elif kind == "done":
                _, mods = message
                self.mods_data = mods
                self.refresh_tree()
                self.progress_var.set(self.i18n.t("scan_progress_done"))
                self.progress.configure(value=self.progress.cget("maximum"))
                self.log(self.i18n.t("scan_done", count=len(self.mods_data)))
                has_terminal_message = True
            elif kind == "error":
                _, error_text = message
                self.log(f"FEHLER: Scan abgebrochen: {error_text}")
                messagebox.showerror(self.i18n.t("error"), error_text)
                has_terminal_message = True

        if has_terminal_message:
            self._set_scan_state(False)
            self.scan_thread = None
            return

        if self.scan_in_progress:
            self.after(50, self._process_scan_queue)

    def scan(self) -> None:
        if self.scan_in_progress:
            return

        root = self.get_mod_root()
        if root is None:
            return

        self.progress.configure(value=0, maximum=1)
        self.progress_var.set(self.i18n.t("scan_prepare"))
        self._set_scan_state(True)

        self.scan_thread = threading.Thread(
            target=self._scan_worker,
            args=(root, self.mod_lang_var.get(), self.fallback_lang_var.get()),
            daemon=True,
        )
        self.scan_thread.start()
        self.after(50, self._process_scan_queue)

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

    def refresh_tree(self) -> None:
        for item in self.tree.get_children():
            self.tree.delete(item)
        self.item_to_mod = {}

        query = self.search_var.get().strip().lower()
        shown = 0
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

            item_id = self.tree.insert(
                "",
                tk.END,
                values=(
                    mod.get("name", ""),
                    mod.get("author", ""),
                    mod.get("version", ""),
                    self.format_dependency_cell(mod),
                    mod.get("path", ""),
                ),
            )
            self.item_to_mod[item_id] = mod
            shown += 1

        if query:
            self.count_var.set(self.i18n.t("mods_count_filtered", shown=shown, total=len(self.mods_data)))
        else:
            self.count_var.set(self.i18n.t("mods_count", count=shown))

    def on_search_changed(self, _event=None) -> None:
        self.refresh_tree()

    def clear_search(self) -> None:
        self.search_var.set("")
        self.refresh_tree()

    def get_selected_mod(self) -> dict | None:
        selected = self.tree.selection()
        if not selected:
            return None
        return self.item_to_mod.get(selected[0])

    def on_tree_right_click(self, event) -> None:
        row = self.tree.identify_row(event.y)
        if not row:
            return
        self.tree.selection_set(row)
        self.tree.focus(row)
        try:
            self.row_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.row_menu.grab_release()

    def open_selected_mod_folder(self) -> None:
        mod = self.get_selected_mod()
        if not mod:
            return

        mod_path = Path(mod.get("path", ""))
        if not mod_path.exists():
            messagebox.showerror(self.i18n.t("error"), self.i18n.t("missing_mod_lua", path=str(mod_path)))
            return

        os.startfile(str(mod_path))

    def delete_selected_mod(self) -> None:
        mod = self.get_selected_mod()
        if not mod:
            return

        required_by = mod.get("required_by", [])
        if required_by:
            users = ", ".join(sorted({entry.get("name", entry.get("id", "?")) for entry in required_by}))
            if not messagebox.askyesno(
                self.i18n.t("dependency_warning_title"),
                self.i18n.t("dependency_warning_text", users=users),
            ):
                return

        mod_path = Path(mod.get("path", ""))
        if not messagebox.askyesno(self.i18n.t("menu_delete"), self.i18n.t("delete_confirm", name=mod.get("name", mod_path.name))):
            return

        try:
            shutil.rmtree(mod_path)
            self.scan()
        except Exception as exc:
            messagebox.showerror(self.i18n.t("error"), str(exc))

    def on_tree_double_click(self, event) -> None:
        row = self.tree.identify_row(event.y)
        if not row:
            return

        self.tree.selection_set(row)
        self.tree.focus(row)
        mod = self.item_to_mod.get(row)
        if not mod:
            return

        column = self.tree.identify_column(event.x)
        if column == "#4" and self.open_dependency_from_mod(mod):
            return
        self.show_mod_details(mod)

    def open_dependency_from_mod(self, mod: dict) -> bool:
        links = [d for d in mod.get("dependency_links", []) if d.get("target")]
        if not links:
            return False
        if len(links) == 1:
            self.show_mod_details(links[0]["target"])
            return True

        picker = tk.Toplevel(self)
        picker.title(self.i18n.t("dependencies_label"))
        picker.geometry("460x280")

        listbox = tk.Listbox(picker)
        listbox.pack(fill=tk.BOTH, expand=True, padx=12, pady=12)
        for dep in links:
            t = dep["target"]
            listbox.insert(tk.END, f"{dep['id']} -> {t.get('name', dep['id'])}")

        def open_selected() -> None:
            sel = listbox.curselection()
            if not sel:
                return
            target = links[sel[0]]["target"]
            picker.destroy()
            self.show_mod_details(target)

        listbox.bind("<Double-1>", lambda _e: open_selected())
        return True

    def on_drop(self, event) -> str:
        self.install_inputs(parse_drop_files(event.data))
        return event.action

    def install_archives_from_dialog(self) -> None:
        selected = filedialog.askopenfilenames(
            title=self.i18n.t("install_archives"),
            filetypes=[
                ("Archive", "*.zip *.7z *.rar"),
                ("ZIP", "*.zip"),
                ("7Z", "*.7z"),
                ("RAR", "*.rar"),
                ("All", "*.*"),
            ],
        )
        self.install_inputs([Path(path) for path in selected])

    def install_inputs(self, paths: list[Path]) -> None:
        if not paths:
            return

        mods_root = self.get_mod_root()
        if mods_root is None:
            return

        for path in paths:
            if not path.exists():
                self.log(f"FEHLER: Datei nicht gefunden: {path}")
                continue

            if path.is_file() and path.suffix.lower() in ARCHIVE_EXTENSIONS:
                self.install_from_archive(path, mods_root)
            elif path.is_dir():
                self.install_from_directory(path, mods_root)
            else:
                self.log(f"FEHLER: Nicht unterstuetzt: {path.name}")

        self.scan()

    def install_from_archive(self, archive_path: Path, mods_root: Path) -> bool:
        with tempfile.TemporaryDirectory(prefix="tpf2_mod_install_") as temp_dir:
            temp_path = Path(temp_dir)
            extracted, message = extract_archive(archive_path, temp_path)
            if not extracted:
                self.log(f"FEHLER: {archive_path.name}: {message}")
                return False
            return self._install_from_extracted_root(temp_path, archive_path.name, mods_root)

    def install_from_directory(self, source_dir: Path, mods_root: Path) -> bool:
        return self._install_from_extracted_root(source_dir, source_dir.name, mods_root)

    def _install_from_extracted_root(self, root: Path, label: str, mods_root: Path) -> bool:
        valid_mods = find_valid_mod_roots(root)
        if not valid_mods:
            self.log(f"FEHLER: {label}: {self.i18n.t('no_mod_lua')}")
            return False

        all_ok = True
        for mod_dir in valid_mods:
            ok, message = install_mod_folder(mod_dir, mods_root)
            self.log(("OK: " if ok else "FEHLER: ") + message)
            if not ok:
                all_ok = False
        return all_ok

    def show_mod_details(self, mod: dict) -> None:
        mod_path = Path(mod.get("path", ""))
        mod_lua = mod_path / "mod.lua"
        if not mod_lua.exists():
            messagebox.showerror(self.i18n.t("error"), self.i18n.t("missing_mod_lua", path=str(mod_lua)))
            return

        content = mod_lua.read_text(encoding="utf-8", errors="ignore")
        raw_fields = mod.get("raw_fields", {})
        fields = mod.get("resolved_fields", raw_fields)
        link = find_mod_link(fields)

        win = tk.Toplevel(self)
        win.title(self.i18n.t("details_title", name=mod.get("name", mod_path.name)))
        win.geometry("1100x740")

        notebook = ttk.Notebook(win)
        notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        info_tab = ttk.Frame(notebook, padding=10)
        raw_tab = ttk.Frame(notebook, padding=10)
        notebook.add(info_tab, text=self.i18n.t("details_tab"))
        notebook.add(raw_tab, text=self.i18n.t("lua_tab"))

        header = ttk.Frame(info_tab)
        header.pack(fill=tk.X, pady=(0, 10))

        ttk.Label(header, text=mod.get("name", "-"), style="Header.TLabel").pack(anchor="w")
        ttk.Label(header, text=self.i18n.t("author", value=mod.get("author", "-"))).pack(anchor="w")
        ttk.Label(header, text=self.i18n.t("version", value=mod.get("version", "-"))).pack(anchor="w")
        ttk.Label(header, text=self.i18n.t("path", value=str(mod_path))).pack(anchor="w")

        # Lazy translation in detail view keeps scans fast.
        if self.deepl_key_var.get().strip() and mod.get("description") and not mod.get("_deepl_done", False):
            deepl = DeepLClient(self.deepl_key_var.get().strip())
            translated, deepl_error = deepl.translate(mod.get("description", ""), self.mod_lang_var.get())
            mod["description_translated"] = translated
            mod["deepl_error"] = deepl_error
            mod["_deepl_done"] = True

        desc = mod.get("description_translated") or mod.get("description") or ""
        if desc:
            ttk.Label(header, text=self.i18n.t("description", value=desc)).pack(anchor="w")

        if mod.get("translation_notice"):
            ttk.Label(header, text=self.i18n.t("translation_notice", value=mod.get("translation_notice")), foreground="#9a3412").pack(anchor="w")
        if mod.get("translation_available_languages"):
            ttk.Label(header, text=self.i18n.t("available_languages", value=", ".join(mod.get("translation_available_languages")))).pack(anchor="w")
        if mod.get("translation_effective_language"):
            ttk.Label(header, text=self.i18n.t("effective_language", value=mod.get("translation_effective_language"))).pack(anchor="w")
        if mod.get("deepl_error"):
            ttk.Label(header, text=self.i18n.t("deepl_note", value=mod.get("deepl_error")), foreground="#9a3412").pack(anchor="w")

        if link:
            link_label = ttk.Label(header, text=f"Link: {link}", foreground="#1d4ed8", cursor="hand2")
            link_label.pack(anchor="w", pady=(4, 0))
            link_label.bind("<Button-1>", lambda _e: webbrowser.open(link))

        body = ttk.Panedwindow(info_tab, orient=tk.HORIZONTAL)
        body.pack(fill=tk.BOTH, expand=True)

        fields_frame = ttk.Frame(body)
        preview_frame = ttk.Frame(body, padding=(10, 0, 0, 0))
        body.add(fields_frame, weight=3)
        body.add(preview_frame, weight=2)

        fields_tree = ttk.Treeview(fields_frame, columns=("key", "value", "raw"), show="headings")
        fields_tree.heading("key", text=self.i18n.t("field"))
        fields_tree.heading("value", text=self.i18n.t("value_resolved"))
        fields_tree.heading("raw", text=self.i18n.t("value_raw"))
        fields_tree.column("key", width=180, anchor=tk.W)
        fields_tree.column("value", width=420, anchor=tk.W)
        fields_tree.column("raw", width=280, anchor=tk.W)
        fields_tree.pack(fill=tk.BOTH, expand=True)

        for key in sorted(fields.keys()):
            fields_tree.insert("", tk.END, values=(key, fields.get(key, ""), raw_fields.get(key, "")))

        dep_links = mod.get("dependency_links", [])
        if dep_links:
            dep_frame = ttk.Frame(preview_frame)
            dep_frame.pack(fill=tk.X, pady=(0, 10))
            ttk.Label(dep_frame, text=self.i18n.t("dependencies_label"), font=("Segoe UI Semibold", 10)).pack(anchor="w")
            for dep in dep_links:
                target = dep.get("target")
                if target:
                    dep_label = ttk.Label(dep_frame, text=f"{dep['id']} -> {target.get('name', dep['id'])}", foreground="#1d4ed8", cursor="hand2")
                    dep_label.pack(anchor="w")
                    dep_label.bind("<Button-1>", lambda _e, t=target: self.show_mod_details(t))
                else:
                    ttk.Label(dep_frame, text=f"{dep['id']} (missing)", foreground="#9f1239").pack(anchor="w")

        ttk.Label(preview_frame, text=self.i18n.t("preview_label"), font=("Segoe UI Semibold", 10)).pack(anchor="w")
        image_holder = ttk.Label(preview_frame, text=self.i18n.t("no_preview"), anchor="center")
        image_holder.pack(fill=tk.BOTH, expand=True, pady=(8, 0))

        preview_path = find_preview_image(mod_path)
        if preview_path and PIL_AVAILABLE:
            try:
                with Image.open(preview_path) as img:
                    img.thumbnail((360, 360))
                    photo = ImageTk.PhotoImage(img.copy())
                image_holder.configure(image=photo, text="")
                image_holder.image = photo
            except Exception:
                pass

        raw_text = tk.Text(raw_tab, wrap="none", font=("Consolas", 10))
        raw_text.pack(fill=tk.BOTH, expand=True)
        raw_text.insert("1.0", content)
        raw_text.configure(state="disabled")


if __name__ == "__main__":
    app = TpF2ModManagerApp()
    app.mainloop()
