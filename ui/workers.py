import os

from PySide6.QtCore import QObject, Signal, Slot

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
