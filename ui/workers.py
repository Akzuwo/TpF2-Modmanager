import os
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from PySide6.QtCore import QObject, Signal, Slot

from helpers.archive_helper import ARCHIVE_EXTENSIONS, extract_archive, find_valid_mod_roots, install_mod_folder
from helpers.mods_helper import scan_mods_parallel


class ScanWorker(QObject):
    progress = Signal(int, int)
    finished = Signal(list)
    failed = Signal(str)

    def __init__(self, mod_root, primary_lang: str, fallback_lang: str) -> None:
        super().__init__()
        self.mod_root = mod_root
        self.primary_lang = primary_lang
        self.fallback_lang = fallback_lang

    @Slot()
    def run(self) -> None:
        try:
            cpu = os.cpu_count() or 4
            max_workers = max(4, min(20, cpu * 2))

            def on_progress(done: int, total: int) -> None:
                self.progress.emit(done, total)

            mods = scan_mods_parallel(
                self.mod_root,
                self.primary_lang,
                self.fallback_lang,
                deepl_client=None,
                max_workers=max_workers,
                progress_callback=on_progress,
            )
            self.finished.emit(mods)
        except Exception as exc:
            self.failed.emit(str(exc))


class InstallWorker(QObject):
    progress = Signal(int, int, str)
    log = Signal(str)
    finished = Signal(bool)
    failed = Signal(str)

    def __init__(
        self,
        paths: list[Path],
        mods_root: Path,
        no_mod_lua_message: str,
        parallel_enabled: bool,
        max_workers: int,
    ) -> None:
        super().__init__()
        self.paths = paths
        self.mods_root = mods_root
        self.no_mod_lua_message = no_mod_lua_message
        self.parallel_enabled = parallel_enabled
        self.max_workers = max(1, max_workers)

    @Slot()
    def run(self) -> None:
        try:
            total = len(self.paths)
            self.progress.emit(0, max(1, total), "Installiere Mods...")
            any_success = False

            if self.parallel_enabled and total > 1:
                any_success = self._run_parallel(total)
            else:
                any_success = self._run_sequential(total)

            self.finished.emit(any_success)
        except Exception as exc:
            self.failed.emit(str(exc))

    def _run_sequential(self, total: int) -> bool:
        any_success = False
        for index, path in enumerate(self.paths, start=1):
            self.progress.emit(index - 1, total, f"Verarbeite {path.name}...")
            success, messages = self._process_path(path)
            for message in messages:
                self.log.emit(message)
            if success:
                any_success = True
            self.progress.emit(index, total, f"{index}/{total} abgeschlossen")
        return any_success

    def _run_parallel(self, total: int) -> bool:
        any_success = False
        done_count = 0
        worker_count = min(self.max_workers, total)

        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            futures = {executor.submit(self._process_path, path): path for path in self.paths}
            for future in as_completed(futures):
                path = futures[future]
                try:
                    success, messages = future.result()
                except Exception as exc:
                    success, messages = False, [f"ERROR: {path.name}: {exc}"]

                for message in messages:
                    self.log.emit(message)

                if success:
                    any_success = True

                done_count += 1
                self.progress.emit(done_count, total, f"{done_count}/{total} abgeschlossen")

        return any_success

    def _process_path(self, path: Path) -> tuple[bool, list[str]]:
        if not path.exists():
            return False, [f"ERROR: File not found: {path}"]

        if path.is_file() and path.suffix.lower() in ARCHIVE_EXTENSIONS:
            return self._install_from_archive(path)
        if path.is_dir():
            return self._install_from_directory(path)
        return False, [f"ERROR: Unsupported input: {path.name}"]

    def _install_from_archive(self, archive_path: Path) -> tuple[bool, list[str]]:
        with tempfile.TemporaryDirectory(prefix="tpf2_mod_install_") as temp_dir:
            temp_path = Path(temp_dir)
            extracted, message = extract_archive(archive_path, temp_path)
            if not extracted:
                return False, [f"ERROR: {archive_path.name}: {message}"]
            return self._install_from_extracted_root(temp_path, archive_path.name)

    def _install_from_directory(self, source_dir: Path) -> tuple[bool, list[str]]:
        return self._install_from_extracted_root(source_dir, source_dir.name)

    def _install_from_extracted_root(self, root: Path, label: str) -> tuple[bool, list[str]]:
        messages: list[str] = []
        valid_mods = find_valid_mod_roots(root)
        if not valid_mods:
            return False, [f"ERROR: {label}: {self.no_mod_lua_message}"]

        all_ok = True
        for mod_dir in valid_mods:
            ok, message = install_mod_folder(mod_dir, self.mods_root)
            messages.append(("OK: " if ok else "ERROR: ") + message)
            if not ok:
                all_ok = False
        return all_ok, messages
