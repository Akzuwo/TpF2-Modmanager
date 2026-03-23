import logging
import sys
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
    from ui.main_window import ModManagerMainWindow
    from ui.theme import APP_STYLE_SHEET, configure_application

    resource_dir, data_dir = get_runtime_paths()
    config = load_config(data_dir / "config.json")
    configure_logging(data_dir, bool(config.get("debug_logging_enabled", False)))
    logging.getLogger(__name__).info("Application startup. resource_dir=%s data_dir=%s", resource_dir, data_dir)

    app = QApplication(sys.argv)
    app.setStyleSheet(APP_STYLE_SHEET)
    configure_application(app)

    app_icon = resource_dir / "media" / "icon.ico"
    if app_icon.exists():
        app.setWindowIcon(QIcon(str(app_icon)))
    window = ModManagerMainWindow(resource_dir=resource_dir, data_dir=data_dir)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
