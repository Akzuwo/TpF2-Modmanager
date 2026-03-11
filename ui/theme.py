from PySide6.QtGui import QColor, QFont, QPalette


APP_STYLE_SHEET = """
QWidget {
    background: #0b0f14;
    color: #e7edf5;
    font-family: "Segoe UI", "Arial";
    font-size: 10pt;
}
QMainWindow, QDialog {
    background: #0b0f14;
}
QFrame#SidebarCard, QFrame#PanelCard, QFrame#DropZone, QFrame#DetailCard {
    background: #141a22;
    border: 1px solid #232c38;
    border-radius: 16px;
}
QFrame#DropZone {
    border: 1px dashed #2f8cff;
    background: #101923;
}
QFrame#DropZone[dragActive="true"] {
    border: 1px solid #52a1ff;
    background: #132235;
}
QLabel#WindowTitle {
    font-size: 20pt;
    font-weight: 700;
    color: #f5f9ff;
}
QLabel#SectionTitle {
    font-size: 12pt;
    font-weight: 700;
    color: #f4f7fb;
}
QLabel#MutedLabel, QLabel#StatusLabel {
    color: #8f9db0;
}
QLabel#ValueLabel {
    color: #c9d4e3;
}
QLineEdit, QTextEdit, QPlainTextEdit, QComboBox, QListWidget, QTreeWidget, QTableWidget, QTabWidget::pane {
    background: #0f141b;
    border: 1px solid #263141;
    border-radius: 12px;
    padding: 6px 8px;
    color: #edf3fb;
    selection-background-color: #2f8cff;
    selection-color: #ffffff;
}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QComboBox:focus, QListWidget:focus, QTreeWidget:focus, QTableWidget:focus {
    border: 1px solid #2f8cff;
}
QTableWidget {
    gridline-color: #1e2733;
}
QHeaderView::section {
    background: #151c25;
    color: #8ea2b7;
    border: none;
    border-bottom: 1px solid #243041;
    padding: 8px;
    font-weight: 600;
}
QPushButton {
    background: #18212d;
    color: #edf3fb;
    border: 1px solid #273241;
    border-radius: 12px;
    padding: 8px 14px;
    font-weight: 600;
}
QPushButton:hover {
    background: #1c2a3b;
    border-color: #355070;
}
QPushButton:pressed {
    background: #111923;
}
QPushButton:disabled {
    background: #121821;
    color: #657487;
    border-color: #1d2632;
}
QPushButton[accent="true"] {
    background: #2f8cff;
    border: 1px solid #2f8cff;
    color: #ffffff;
}
QPushButton[accent="true"]:hover {
    background: #4a9bff;
    border-color: #4a9bff;
}
QPushButton[accent="true"]:pressed {
    background: #1f78ef;
    border-color: #1f78ef;
}
QPushButton[subtle="true"] {
    background: transparent;
    border: 1px solid #28313e;
    color: #b8c6d8;
}
QProgressBar {
    background: #0f141b;
    border: 1px solid #243041;
    border-radius: 10px;
    text-align: center;
    min-height: 18px;
}
QProgressBar::chunk {
    border-radius: 9px;
    background: #2f8cff;
}
QScrollBar:vertical {
    background: transparent;
    width: 12px;
    margin: 4px 0;
}
QScrollBar::handle:vertical {
    background: #293445;
    border-radius: 6px;
    min-height: 24px;
}
QScrollBar:horizontal {
    background: transparent;
    height: 12px;
    margin: 0 4px;
}
QScrollBar::handle:horizontal {
    background: #293445;
    border-radius: 6px;
    min-width: 24px;
}
QScrollBar::add-line, QScrollBar::sub-line {
    border: none;
    background: none;
}
QTabBar::tab {
    background: #121821;
    color: #96a7bb;
    padding: 8px 14px;
    margin-right: 6px;
    border-top-left-radius: 10px;
    border-top-right-radius: 10px;
}
QTabBar::tab:selected {
    background: #1a2533;
    color: #f4f8ff;
}
QMenu {
    background: #111822;
    border: 1px solid #243041;
    padding: 6px;
}
QMenu::item {
    padding: 8px 18px;
    border-radius: 8px;
}
QMenu::item:selected {
    background: #1b2b41;
}
QSplitter::handle {
    background: #0d1218;
}
QGroupBox {
    border: 1px solid #243041;
    border-radius: 14px;
    margin-top: 12px;
    padding-top: 10px;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 4px;
    color: #d8e3f0;
}
"""


def configure_application(app) -> None:
    font = QFont("Segoe UI", 10)
    app.setFont(font)

    palette = QPalette()
    palette.setColor(QPalette.Window, QColor("#0b0f14"))
    palette.setColor(QPalette.WindowText, QColor("#e7edf5"))
    palette.setColor(QPalette.Base, QColor("#0f141b"))
    palette.setColor(QPalette.AlternateBase, QColor("#141a22"))
    palette.setColor(QPalette.Text, QColor("#e7edf5"))
    palette.setColor(QPalette.Button, QColor("#18212d"))
    palette.setColor(QPalette.ButtonText, QColor("#edf3fb"))
    palette.setColor(QPalette.Highlight, QColor("#2f8cff"))
    palette.setColor(QPalette.HighlightedText, QColor("#ffffff"))
    app.setPalette(palette)
