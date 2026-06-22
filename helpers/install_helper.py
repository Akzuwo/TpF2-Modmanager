import logging
import os
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from helpers.archive_helper import ARCHIVE_EXTENSIONS, extract_archive, find_valid_mod_roots, install_mod_folder

logger = logging.getLogger(__name__)


def install_inputs(
    paths: list[Path],
    mods_root: Path,
    no_mod_lua_message: str,
    parallel_enabled: bool = False,
    delete_download_archives: bool = False,
    max_workers: int = 2,
    progress_callback=None,
    log_callback=None,
) -> bool:
    installer = ModInstaller(
        paths,
        mods_root,
        no_mod_lua_message,
        parallel_enabled,
        delete_download_archives,
        max_workers,
        progress_callback,
        log_callback,
    )
    return installer.run()


class ModInstaller:
    def __init__(
        self,
        paths: list[Path],
        mods_root: Path,
        no_mod_lua_message: str,
        parallel_enabled: bool,
        delete_download_archives: bool,
        max_workers: int,
        progress_callback=None,
        log_callback=None,
    ) -> None:
        self.paths = paths
        self.mods_root = mods_root
        self.no_mod_lua_message = no_mod_lua_message
        self.parallel_enabled = parallel_enabled
        self.delete_download_archives = delete_download_archives
        self.max_workers = max(1, max_workers)
        self.progress_callback = progress_callback
        self.log_callback = log_callback
        self.downloads_dir = self._resolve_downloads_dir()

    def run(self) -> bool:
        total = len(self.paths)
        self._progress(0, max(1, total), "Installiere Mods...")
        if self.parallel_enabled and total > 1:
            return self._run_parallel(total)
        return self._run_sequential(total)

    def _run_sequential(self, total: int) -> bool:
        any_success = False
        for index, path in enumerate(self.paths, start=1):
            self._progress(index - 1, total, f"Verarbeite {path.name}...")
            success, messages = self._process_path(path)
            self._log_many(messages)
            if success:
                any_success = True
            self._progress(index, total, f"{index}/{total} abgeschlossen")
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

                self._log_many(messages)
                if success:
                    any_success = True
                done_count += 1
                self._progress(done_count, total, f"{done_count}/{total} abgeschlossen")

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
            success, messages = self._install_from_extracted_root(temp_path, archive_path.name)

        if success:
            deleted, delete_message = self._delete_download_archive_if_needed(archive_path)
            if delete_message:
                prefix = "OK: " if deleted else "ERROR: "
                messages.append(prefix + delete_message)

        return success, messages

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

    def _delete_download_archive_if_needed(self, archive_path: Path) -> tuple[bool, str]:
        if not self.delete_download_archives or self.downloads_dir is None:
            return False, ""

        resolved_archive = archive_path.resolve()
        if not resolved_archive.is_relative_to(self.downloads_dir):
            return False, ""

        try:
            resolved_archive.unlink()
        except Exception as exc:
            logger.exception("Could not delete installed archive from downloads: %s", archive_path)
            return False, f"Archiv konnte nach Installation nicht geloescht werden: {archive_path.name} ({exc})"

        return True, f"Archiv aus Downloads geloescht: {archive_path.name}"

    def _progress(self, current: int, total: int, status: str) -> None:
        if self.progress_callback:
            self.progress_callback(current, total, status)

    def _log_many(self, messages: list[str]) -> None:
        for message in messages:
            if self.log_callback:
                self.log_callback(message)

    @staticmethod
    def _resolve_downloads_dir() -> Path | None:
        if os.name == "nt":
            try:
                import ctypes
                from uuid import UUID

                class GUID(ctypes.Structure):
                    _fields_ = [
                        ("Data1", ctypes.c_uint32),
                        ("Data2", ctypes.c_uint16),
                        ("Data3", ctypes.c_uint16),
                        ("Data4", ctypes.c_ubyte * 8),
                    ]

                    @classmethod
                    def from_uuid(cls, value: UUID) -> "GUID":
                        data4 = (ctypes.c_ubyte * 8).from_buffer_copy(value.bytes[8:])
                        return cls(value.time_low, value.time_mid, value.time_hi_version, data4)

                downloads_guid = GUID.from_uuid(UUID("{374DE290-123F-4565-9164-39C4925E467B}"))
                path_ptr = ctypes.c_wchar_p()
                result = ctypes.windll.shell32.SHGetKnownFolderPath(
                    ctypes.byref(downloads_guid),
                    0,
                    None,
                    ctypes.byref(path_ptr),
                )
                if result == 0 and path_ptr.value:
                    try:
                        return Path(path_ptr.value).resolve()
                    finally:
                        ctypes.windll.ole32.CoTaskMemFree(path_ptr)
            except Exception:
                logger.exception("Could not resolve Windows Downloads folder via SHGetKnownFolderPath")

        downloads_dir = Path.home() / "Downloads"
        try:
            return downloads_dir.resolve()
        except Exception:
            return downloads_dir if downloads_dir.exists() else None
