# -*- coding: utf-8 -*-
"""
Dark Industrial CNC Theme
"""

STYLESHEET = """
* {
    font-family: 'Courier New', monospace;
    color: #C8D0D8;
}

QMainWindow, QDialog, QWidget {
    background-color: #0D0F11;
}

/* ── LABELS ── */
QLabel {
    color: #C8D0D8;
    font-size: 13px;
}
QLabel#title {
    color: #00E5FF;
    font-size: 22px;
    font-weight: bold;
    letter-spacing: 4px;
}
QLabel#subtitle {
    color: #607080;
    font-size: 11px;
    letter-spacing: 2px;
}
QLabel#section {
    color: #00E5FF;
    font-size: 11px;
    font-weight: bold;
    letter-spacing: 3px;
    border-bottom: 1px solid #1A2535;
    padding-bottom: 4px;
}
QLabel#status_ok {
    color: #00FF88;
    font-size: 11px;
    letter-spacing: 1px;
}
QLabel#status_err {
    color: #FF4444;
    font-size: 11px;
    letter-spacing: 1px;
}
QLabel#status_warn {
    color: #FFB300;
    font-size: 11px;
    letter-spacing: 1px;
}

/* ── LINE EDIT ── */
QLineEdit {
    background-color: #111820;
    border: 1px solid #1E2D3D;
    border-radius: 2px;
    padding: 8px 12px;
    color: #C8D0D8;
    font-size: 13px;
    selection-background-color: #00E5FF;
    selection-color: #000;
}
QLineEdit:focus {
    border: 1px solid #00E5FF;
    background-color: #131C26;
}
QLineEdit:disabled {
    background-color: #0D0F11;
    color: #3A4550;
    border-color: #141C24;
}

/* ── BUTTONS ── */
QPushButton {
    background-color: #111820;
    border: 1px solid #1E2D3D;
    border-radius: 2px;
    padding: 9px 14px;
    color: #C8D0D8;
    font-size: 12px;
    font-weight: bold;
    letter-spacing: 1px;
    min-width: 50px;
}
QPushButton:hover {
    background-color: #1A2535;
    border-color: #00E5FF;
    color: #00E5FF;
}
QPushButton:pressed {
    background-color: #00E5FF;
    color: #000000;
    border-color: #00E5FF;
}
QPushButton:disabled {
    background-color: #0D0F11;
    color: #2A3540;
    border-color: #141C24;
}
QPushButton:checked {
    background-color: #004C60;
    border: 1px solid #00E5FF;
    color: #00E5FF;
}
QPushButton:checked:hover {
    background-color: #005A70;
    border-color: #00E5FF;
    color: #00E5FF;
}
QPushButton#primary {
    background-color: #003D52;
    border: 1px solid #00E5FF;
    color: #00E5FF;
    letter-spacing: 2px;
}
QPushButton#primary:hover {
    background-color: #005070;
}
QPushButton#primary:pressed {
    background-color: #00E5FF;
    color: #000;
}
QPushButton#danger {
    background-color: #2A0A0A;
    border: 1px solid #FF4444;
    color: #FF4444;
}
QPushButton#danger:hover {
    background-color: #3D1010;
}

/* ── COMBO BOX ── */
QComboBox {
    background-color: #111820;
    border: 1px solid #1E2D3D;
    border-radius: 2px;
    padding: 8px 12px;
    color: #C8D0D8;
    font-size: 13px;
}
QComboBox:focus {
    border-color: #00E5FF;
}
QComboBox::drop-down {
    border: none;
    padding-right: 12px;
}
QComboBox::down-arrow {
    width: 10px;
    height: 10px;
    border-left: 5px solid transparent;
    border-right: 5px solid transparent;
    border-top: 6px solid #00E5FF;
}
QComboBox QAbstractItemView {
    background-color: #111820;
    border: 1px solid #00E5FF;
    selection-background-color: #003D52;
    color: #C8D0D8;
    padding: 4px;
}

/* ── TABS ── */
QTabWidget::pane {
    border: 1px solid #1E2D3D;
    background-color: #0D0F11;
}
QTabBar::tab {
    background-color: #0D0F11;
    border: 1px solid #1E2D3D;
    border-bottom: none;
    padding: 8px 20px;
    color: #607080;
    font-size: 11px;
    letter-spacing: 2px;
    font-weight: bold;
    min-width: 100px;
}
QTabBar::tab:selected {
    background-color: #111820;
    color: #00E5FF;
    border-top: 2px solid #00E5FF;
}
QTabBar::tab:hover:!selected {
    color: #C8D0D8;
    background-color: #111820;
}

/* ── SLIDER ── */
QSlider::groove:horizontal {
    height: 4px;
    background-color: #1E2D3D;
    border-radius: 2px;
}
QSlider::handle:horizontal {
    background-color: #00E5FF;
    width: 14px;
    height: 14px;
    margin: -5px 0;
    border-radius: 7px;
}
QSlider::sub-page:horizontal {
    background-color: #00E5FF;
    border-radius: 2px;
}

/* ── SPIN BOX ── */
QSpinBox, QDoubleSpinBox {
    background-color: #111820;
    border: 1px solid #1E2D3D;
    border-radius: 2px;
    padding: 6px 10px;
    color: #C8D0D8;
    font-size: 13px;
}
QSpinBox:focus, QDoubleSpinBox:focus {
    border-color: #00E5FF;
}
QSpinBox::up-button, QSpinBox::down-button,
QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {
    background-color: #1A2535;
    border: none;
    width: 20px;
}
QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover,
QSpinBox::down-button:hover, QDoubleSpinBox::down-button:hover {
    background-color: #003D52;
}

/* ── CHECK BOX ── */
QCheckBox {
    spacing: 8px;
    font-size: 12px;
    color: #C8D0D8;
}
QCheckBox::indicator {
    width: 16px;
    height: 16px;
    background-color: #111820;
    border: 1px solid #1E2D3D;
    border-radius: 2px;
}
QCheckBox::indicator:checked {
    background-color: #003D52;
    border-color: #00E5FF;
}

/* ── SCROLL BAR ── */
QScrollBar:vertical {
    background-color: #0D0F11;
    width: 8px;
    border: none;
}
QScrollBar::handle:vertical {
    background-color: #1E2D3D;
    border-radius: 4px;
    min-height: 30px;
}
QScrollBar::handle:vertical:hover {
    background-color: #00E5FF;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0px;
}

/* ── GROUP BOX ── */
QGroupBox {
    border: 1px solid #1E2D3D;
    border-radius: 2px;
    margin-top: 16px;
    padding: 12px 8px 8px 8px;
    font-size: 11px;
    font-weight: bold;
    letter-spacing: 2px;
    color: #607080;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 12px;
    top: -1px;
    padding: 0 6px;
    color: #00E5FF;
    background-color: #0D0F11;
}

/* ── PROGRESS BAR ── */
QProgressBar {
    background-color: #111820;
    border: 1px solid #1E2D3D;
    border-radius: 2px;
    height: 8px;
    text-align: center;
    font-size: 10px;
    color: #607080;
}
QProgressBar::chunk {
    background-color: #00E5FF;
    border-radius: 2px;
}

/* ── SEPARATOR ── */
QFrame[frameShape="4"], QFrame[frameShape="5"] {
    color: #1A2535;
}

/* ── TOOLTIP ── */
QToolTip {
    background-color: #111820;
    border: 1px solid #00E5FF;
    color: #C8D0D8;
    padding: 4px 8px;
    font-size: 11px;
}
"""

# Color constants
COLOR_ACCENT     = "#00E5FF"
COLOR_BG         = "#0D0F11"
COLOR_BG2        = "#111820"
COLOR_BORDER     = "#1E2D3D"
COLOR_TEXT       = "#C8D0D8"
COLOR_TEXT_DIM   = "#607080"
COLOR_OK         = "#00FF88"
COLOR_WARN       = "#FFB300"
COLOR_ERR        = "#FF4444"
COLOR_ACCENT_BG  = "#003D52"
