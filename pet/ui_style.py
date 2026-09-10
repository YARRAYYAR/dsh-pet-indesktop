"""Window-scoped control-panel styling; no global palette or compositor."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QPushButton

STYLE = '''
QDialog, QWidget#panel { background: #f6f5f2; color: #253247; }
QLabel { color: #253247; background: transparent; }
QLabel#title { font-size: 23px; font-weight: 600; }
QLabel#sectionTitle { font-size: 15px; font-weight: 600; }
QLabel#muted { color: #657184; font-size: 12px; }
QLabel#hero { background: #edf1f9; border-radius: 14px; }
QFrame#card { background: white; border: 1px solid #e2e5eb; border-radius: 12px; }
QScrollArea { border: none; background: transparent; }
QScrollArea > QWidget > QWidget { background: #f6f5f2; }
QListWidget { background: white; color: #253247; border: 1px solid #e2e5eb; border-radius: 10px; outline: 0; padding: 5px; }
QListWidget::item { min-height: 35px; padding: 4px 8px; border-radius: 6px; }
QListWidget::item:selected { color: #254f97; background: #e5ecfa; }
QListWidget::item:hover { background: #f0f3f9; }
QListWidget#navigation { background: #eeede9; border: none; padding: 8px; }
QListWidget#navigation::item { min-height: 37px; padding-left: 12px; }
QPushButton, QToolButton { background: white; color: #35445a; border: 1px solid #d8dee8; border-radius: 7px; padding: 7px 13px; }
QPushButton:hover, QToolButton:hover { background: #edf2fc; border-color: #a7b9d7; }
QPushButton:pressed, QToolButton:pressed { background: #dce6f8; }
QPushButton:disabled { color: #929cab; background: #f0f0ee; border-color: #e2e5eb; }
QPushButton#primary { background: #4066b3; color: white; border-color: #4066b3; }
QPushButton#primary:hover { background: #33599f; }
QPushButton#primary:disabled { color: #929cab; background: #f0f0ee; border-color: #e2e5eb; }
QLineEdit, QSpinBox, QComboBox { color: #253247; background: white; border: 1px solid #d8dee8; border-radius: 7px; padding: 6px 9px; min-height: 21px; }
QLineEdit:focus, QSpinBox:focus, QComboBox:focus { border-color: #4066b3; }
QComboBox QAbstractItemView { color: #253247; background: white; selection-background-color: #e5ecfa; selection-color: #254f97; }
QCheckBox { color: #253247; spacing: 9px; padding: 5px 0; }
QCheckBox::indicator { width: 17px; height: 17px; }
QSlider::groove:horizontal { height: 5px; background: #dfe4ee; border-radius: 2px; }
QSlider::sub-page:horizontal { background: #4066b3; border-radius: 2px; }
QSlider::handle:horizontal { background: white; border: 1px solid #9aaccb; width: 17px; margin: -6px 0; border-radius: 8px; }
QSplitter::handle { background: transparent; width: 12px; }
QToolButton:checked { background: #e5ecfa; color: #254f97; }
'''

def apply_style(widget):
    font = widget.font()
    font.setPointSize(12)
    widget.setFont(font)
    widget.setStyleSheet(STYLE)

def label(text, role='muted'):
    result = QLabel(text)
    result.setObjectName(role)
    result.setTextFormat(Qt.TextFormat.PlainText)
    result.setWordWrap(True)
    return result

def button(text, callback=None, primary=False):
    result = QPushButton(text)
    result.setAutoDefault(False)
    if primary:
        result.setObjectName('primary')
    if callback is not None:
        result.clicked.connect(callback)
    return result
