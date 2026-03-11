import sys
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent


def main() -> int:
    try:
        from PySide6.QtWidgets import QApplication
    except ImportError as exc:
        print("PySide6 is required. Install it with: pip install PySide6")
        raise SystemExit(1) from exc

    from ui.main_window import ModManagerMainWindow
    from ui.theme import APP_STYLE_SHEET, configure_application

    app = QApplication(sys.argv)
    app.setStyleSheet(APP_STYLE_SHEET)
    configure_application(app)

    window = ModManagerMainWindow(base_dir=BASE_DIR)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
