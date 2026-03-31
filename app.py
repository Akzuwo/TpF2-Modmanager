import logging
import sys
import traceback
from pathlib import Path


def get_runtime_paths() -> tuple[Path, Path]:
    if getattr(sys, "frozen", False):
        resource_dir = Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
        data_dir = Path(sys.executable).resolve().parent
        return resource_dir, data_dir

    base_dir = Path(__file__).resolve().parent
    return base_dir, base_dir


def main() -> int:
    try:
        from PySide6.QtGui import QIcon
        from PySide6.QtWidgets import QApplication
    except ImportError as exc:
        print("PySide6 is required. Install it with: pip install PySide6")
        raise SystemExit(1) from exc

    from helpers.config_helper import load_config
    from helpers.logging_helper import configure_logging
    from helpers.platform_helper import get_app_icon_path
    from ui.main_window import ModManagerMainWindow
    from ui.theme import APP_STYLE_SHEET, configure_application

    resource_dir, data_dir = get_runtime_paths()
    config = load_config(data_dir / "config.json")
    configure_logging(data_dir, bool(config.get("debug_logging_enabled", False)))
    logging.getLogger(__name__).info("Application startup. resource_dir=%s data_dir=%s", resource_dir, data_dir)

    app = QApplication(sys.argv)
    app.setStyleSheet(APP_STYLE_SHEET)
    configure_application(app)

    app_icon = get_app_icon_path(resource_dir)
    if app_icon is not None:
        app.setWindowIcon(QIcon(str(app_icon)))
    window = ModManagerMainWindow(resource_dir=resource_dir, data_dir=data_dir)
    window.show()
    return app.exec()


def _format_startup_error(exc: BaseException) -> str:
    return "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)).strip()


def _write_startup_error_log(text: str) -> Path:
    _, data_dir = get_runtime_paths()
    data_dir.mkdir(parents=True, exist_ok=True)
    log_path = data_dir / "startup-error.log"
    log_path.write_text(text + "\n", encoding="utf-8")
    return log_path


def _show_startup_error(message: str) -> None:
    try:
        from PySide6.QtWidgets import QApplication, QMessageBox

        existing_app = QApplication.instance()
        app = existing_app or QApplication(sys.argv[:1])
        QMessageBox.critical(None, "TpF2 Modmanager", message)
        if existing_app is None:
            app.quit()
        return
    except Exception:
        pass

    if sys.platform.startswith("win"):
        try:
            import ctypes

            ctypes.windll.user32.MessageBoxW(None, message, "TpF2 Modmanager", 0x10)
            return
        except Exception:
            pass

    sys.stderr.write(message + "\n")


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception as exc:
        details = _format_startup_error(exc)
        log_path = _write_startup_error_log(details)
        startup_message = (
            "Die Anwendung konnte nicht gestartet werden.\n\n"
            f"Details wurden in\n{log_path}\n\ngespeichert.\n\n"
            f"{exc}"
        )
        logging.critical("Startup failed: %s", details)
        _show_startup_error(startup_message)
        raise SystemExit(1) from exc
