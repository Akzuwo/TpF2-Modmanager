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

    from ui.main_window import ModManagerMainWindow
    from ui.theme import APP_STYLE_SHEET, configure_application

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )

    app = QApplication(sys.argv)
    app.setStyleSheet(APP_STYLE_SHEET)
    configure_application(app)

    resource_dir, data_dir = get_runtime_paths()
    app_icon = resource_dir / "media" / "icon.ico"
    if app_icon.exists():
        app.setWindowIcon(QIcon(str(app_icon)))
    window = ModManagerMainWindow(resource_dir=resource_dir, data_dir=data_dir)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
