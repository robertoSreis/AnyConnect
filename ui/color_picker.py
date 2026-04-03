# -*- coding: utf-8 -*-
"""
Color Picker Widget - PyQt6
Paleta básica + favoritos salvos + roda de cores com brilho + RGB/HEX
"""

import json
import os
import math

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QLineEdit, QSpinBox, QFrame,
    QGridLayout, QWidget, QScrollArea
)
from PyQt6.QtCore import Qt, pyqtSignal, QPoint, QRect
from PyQt6.QtGui import (
    QColor, QPainter, QConicalGradient, QRadialGradient,
    QLinearGradient, QImage, QPen, QBrush, QPixmap, QFont
)

# Favorites file saved next to executable
FAV_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "fav_colors.json")

# Basic palette: (R, G, B, Name)
BASIC_COLORS = [
    (255, 255, 255, "White"),        (240, 240, 235, "Natural White"),
    (200, 200, 200, "Light Gray"),   (100, 100, 100, "Dark Gray"),
    (40,  40,  40,  "Graphite"),     (0,   0,   0,   "Black"),
    (255, 80,  80,  "Light Red"),    (200, 20,  20,  "Red"),
    (255, 160, 80,  "Light Orange"), (230, 100, 0,   "Orange"),
    (255, 230, 80,  "Light Yellow"), (220, 180, 0,   "Yellow"),
    (120, 230, 80,  "Light Green"),  (30,  160, 30,  "Green"),
    (80,  220, 200, "Mint"),         (0,   160, 140, "Teal"),
    (80,  180, 255, "Light Blue"),   (0,   80,  200, "Blue"),
    (150, 100, 255, "Lavender"),     (80,  0,   180, "Purple"),
    (255, 120, 200, "Pink"),         (200, 0,   120, "Magenta"),
    (220, 170, 100, "Light Brown"),  (140, 80,  20,  "Brown"),
    (255, 210, 120, "Gold"),         (180, 140, 60,  "Dark Gold"),
]


def load_favorites() -> list:
    try:
        if os.path.exists(FAV_FILE):
            with open(FAV_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return []


def save_favorites(favs: list):
    try:
        with open(FAV_FILE, "w", encoding="utf-8") as f:
            json.dump(favs, f)
    except Exception:
        pass


def hsv_to_rgb(h: float, s: float, v: float):
    """H 0-360, S 0-1, V 0-1 → R,G,B 0-255"""
    c = v * s
    x = c * (1 - abs((h / 60) % 2 - 1))
    m = v - c
    if   h < 60:  r, g, b = c, x, 0
    elif h < 120: r, g, b = x, c, 0
    elif h < 180: r, g, b = 0, c, x
    elif h < 240: r, g, b = 0, x, c
    elif h < 300: r, g, b = x, 0, c
    else:         r, g, b = c, 0, x
    return int((r + m) * 255), int((g + m) * 255), int((b + m) * 255)


def rgb_to_hsv(r: int, g: int, b: int):
    """R,G,B 0-255 → H 0-360, S 0-1, V 0-1"""
    r, g, b = r / 255, g / 255, b / 255
    mx, mn = max(r, g, b), min(r, g, b)
    d = mx - mn
    v = mx
    s = d / mx if mx else 0
    if d == 0:
        h = 0.0
    elif mx == r:
        h = ((g - b) / d % 6) * 60
    elif mx == g:
        h = ((b - r) / d + 2) * 60
    else:
        h = ((r - g) / d + 4) * 60
    return h, s, v


class ColorWheel(QWidget):
    """Interactive HSV color wheel with brightness bar"""
    color_changed = pyqtSignal(int, int, int)

    WHEEL_SIZE = 150
    BAR_H = 16

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(self.WHEEL_SIZE, self.WHEEL_SIZE + self.BAR_H + 8)
        self._hue = 0.0
        self._sat = 0.0
        self._val = 1.0
        self._dragging_wheel = False
        self._dragging_bar = False
        self._wheel_img = None
        self._rebuild_wheel()

    def _rebuild_wheel(self):
        size = self.WHEEL_SIZE
        img = QImage(size, size, QImage.Format.Format_ARGB32)
        img.fill(Qt.GlobalColor.transparent)
        r = size // 2
        for y in range(size):
            for x in range(size):
                dx, dy = x - r, y - r
                dist = math.sqrt(dx * dx + dy * dy)
                if dist <= r:
                    angle = (math.atan2(dy, dx) * 180 / math.pi + 360) % 360
                    sat = dist / r
                    cr, cg, cb = hsv_to_rgb(angle, sat, self._val)
                    img.setPixel(x, y, QColor(cr, cg, cb).rgb())
        self._wheel_img = img

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        size = self.WHEEL_SIZE

        # Draw wheel
        if self._wheel_img:
            p.drawImage(0, 0, self._wheel_img)

        # Draw cursor on wheel
        r = size // 2
        angle_rad = self._hue * math.pi / 180
        cx = int(r + self._sat * r * math.cos(angle_rad))
        cy = int(r + self._sat * r * math.sin(angle_rad))
        p.setPen(QPen(QColor("#ffffff"), 2))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(cx - 6, cy - 6, 12, 12)
        p.setPen(QPen(QColor("#000000"), 1))
        p.drawEllipse(cx - 7, cy - 7, 14, 14)

        # Draw brightness bar
        bar_y = size + 8
        bar_rect = QRect(0, bar_y, size, self.BAR_H)
        grad = QLinearGradient(0, 0, size, 0)
        grad.setStart(0, bar_y)
        grad.setFinalStop(size, bar_y)
        grad.setColorAt(0, QColor(0, 0, 0))
        cr, cg, cb = hsv_to_rgb(self._hue, 1.0, 1.0)
        grad.setColorAt(1, QColor(cr, cg, cb))
        p.fillRect(bar_rect, QBrush(grad))

        # Bar border
        p.setPen(QPen(QColor("#1E2D3D"), 1))
        p.drawRect(bar_rect)

        # Bar cursor
        bx = int(self._val * size)
        p.setPen(QPen(QColor("#ffffff"), 2))
        p.drawLine(bx, bar_y, bx, bar_y + self.BAR_H)

    def _pick_wheel(self, x: int, y: int):
        r = self.WHEEL_SIZE // 2
        dx, dy = x - r, y - r
        dist = math.sqrt(dx * dx + dy * dy)
        self._hue = (math.atan2(dy, dx) * 180 / math.pi + 360) % 360
        self._sat = min(dist / r, 1.0)
        cr, cg, cb = hsv_to_rgb(self._hue, self._sat, self._val)
        self.update()
        self.color_changed.emit(cr, cg, cb)

    def _pick_bar(self, x: int):
        self._val = max(0.0, min(1.0, x / self.WHEEL_SIZE))
        self._rebuild_wheel()
        cr, cg, cb = hsv_to_rgb(self._hue, self._sat, self._val)
        self.update()
        self.color_changed.emit(cr, cg, cb)

    def mousePressEvent(self, event):
        y = event.position().y()
        bar_y = self.WHEEL_SIZE + 8
        if y >= bar_y:
            self._dragging_bar = True
            self._pick_bar(int(event.position().x()))
        else:
            self._dragging_wheel = True
            self._pick_wheel(int(event.position().x()), int(y))

    def mouseMoveEvent(self, event):
        if self._dragging_wheel:
            self._pick_wheel(int(event.position().x()), int(event.position().y()))
        elif self._dragging_bar:
            self._pick_bar(int(event.position().x()))

    def mouseReleaseEvent(self, event):
        self._dragging_wheel = False
        self._dragging_bar = False

    def set_color(self, r: int, g: int, b: int):
        self._hue, self._sat, self._val = rgb_to_hsv(r, g, b)
        self._rebuild_wheel()
        self.update()


class SwatchButton(QPushButton):
    """A single color swatch button"""
    right_clicked = pyqtSignal()

    def __init__(self, r: int, g: int, b: int, tooltip: str = "", parent=None):
        super().__init__(parent)
        self.setFixedSize(26, 26)
        self.setToolTip(tooltip)
        self.set_color(r, g, b)

    def set_color(self, r: int, g: int, b: int):
        self._rgb = (r, g, b)
        self.setStyleSheet(f"""
            QPushButton {{
                background-color: rgb({r},{g},{b});
                border: 2px solid #1E2D3D;
                border-radius: 2px;
            }}
            QPushButton:hover {{
                border-color: #00E5FF;
            }}
        """)

    def get_rgb(self):
        return self._rgb

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.RightButton:
            self.right_clicked.emit()
        else:
            super().mousePressEvent(event)


class ColorPickerDialog(QDialog):
    """Full color picker dialog"""
    color_selected = pyqtSignal(int, int, int)

    def __init__(self, initial_rgb: tuple = (255, 255, 255), slot_label: str = "", parent=None):
        super().__init__(parent)
        self._slot_label = slot_label
        self.setWindowTitle("COLOR  PICKER")
        self.setModal(True)
        self.setFixedWidth(400)
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setStyleSheet("""
            QDialog {
                background-color: #111820;
                border: 1px solid #00E5FF;
            }
        """)
        self._current = list(initial_rgb)
        self._favorites = load_favorites()
        self._fav_buttons = []
        self._build_ui()
        self._set_color(*initial_rgb, update_wheel=True)

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Header ──
        header = QFrame()
        header.setFixedHeight(44)
        header.setStyleSheet("background:#080C0F; border-bottom:1px solid #1A2535;")
        hlay = QHBoxLayout(header)
        hlay.setContentsMargins(14, 0, 14, 0)
        lbl_text = f"COLOR  PICKER  —  {self._slot_label}" if self._slot_label else "COLOR  PICKER"
        lbl = QLabel(lbl_text)
        lbl.setFont(QFont("Courier New", 11, QFont.Weight.Bold))
        lbl.setStyleSheet("color:#00E5FF; letter-spacing:3px;")
        btn_close = QPushButton("×")
        btn_close.setFixedSize(28, 28)
        btn_close.setStyleSheet("""
            QPushButton { background:none; border:none; color:#607080; font-size:20px; }
            QPushButton:hover { color:#FF4444; }
        """)
        btn_close.clicked.connect(self.reject)
        hlay.addWidget(lbl)
        hlay.addStretch()
        hlay.addWidget(btn_close)
        root.addWidget(header)

        # ── Body ──
        body = QWidget()
        body.setStyleSheet("background:#111820;")
        blay = QVBoxLayout(body)
        blay.setContentsMargins(14, 12, 14, 12)
        blay.setSpacing(10)

        # Basic palette
        lbl_basic = QLabel("BASIC  COLORS")
        lbl_basic.setStyleSheet("color:#607080; font-size:10px; letter-spacing:2px;")
        blay.addWidget(lbl_basic)

        palette_wrap = QWidget()
        palette_layout = QGridLayout(palette_wrap)
        palette_layout.setSpacing(4)
        palette_layout.setContentsMargins(0, 0, 0, 0)
        cols = 13
        for i, (r, g, b, name) in enumerate(BASIC_COLORS):
            sw = SwatchButton(r, g, b, name)
            sw.clicked.connect(lambda _, cr=r, cg=g, cb=b: self._set_color(cr, cg, cb, update_wheel=True))
            palette_layout.addWidget(sw, i // cols, i % cols)
        blay.addWidget(palette_wrap)

        # Separator
        sep1 = QFrame(); sep1.setFrameShape(QFrame.Shape.HLine)
        sep1.setStyleSheet("color:#1A2535;")
        blay.addWidget(sep1)

        # Favorites
        fav_header = QHBoxLayout()
        lbl_fav = QLabel("MY  COLORS")
        lbl_fav.setStyleSheet("color:#607080; font-size:10px; letter-spacing:2px;")
        lbl_fav_hint = QLabel("right-click to remove")
        lbl_fav_hint.setStyleSheet("color:#2A3540; font-size:9px; letter-spacing:1px;")
        fav_header.addWidget(lbl_fav)
        fav_header.addWidget(lbl_fav_hint)
        fav_header.addStretch()
        blay.addLayout(fav_header)

        self._fav_container = QWidget()
        self._fav_layout = QHBoxLayout(self._fav_container)
        self._fav_layout.setSpacing(4)
        self._fav_layout.setContentsMargins(0, 0, 0, 0)
        self._fav_layout.setAlignment(Qt.AlignmentFlag.AlignLeft)
        blay.addWidget(self._fav_container)
        self._rebuild_favorites()

        # Separator
        sep2 = QFrame(); sep2.setFrameShape(QFrame.Shape.HLine)
        sep2.setStyleSheet("color:#1A2535;")
        blay.addWidget(sep2)

        # Custom color
        lbl_custom = QLabel("CUSTOM  COLOR")
        lbl_custom.setStyleSheet("color:#607080; font-size:10px; letter-spacing:2px;")
        blay.addWidget(lbl_custom)

        custom_row = QHBoxLayout()
        custom_row.setSpacing(12)

        # Wheel
        self._wheel = ColorWheel()
        self._wheel.color_changed.connect(lambda r, g, b: self._set_color(r, g, b, update_wheel=False))
        custom_row.addWidget(self._wheel)

        # Right side: preview + inputs
        right = QVBoxLayout()
        right.setSpacing(8)

        # Preview box
        self._preview = QFrame()
        self._preview.setFixedHeight(60)
        self._preview.setStyleSheet("background:#ffffff; border:1px solid #1E2D3D; border-radius:2px;")
        right.addWidget(self._preview)

        # RGB inputs
        rgb_row = QHBoxLayout()
        rgb_row.setSpacing(6)
        self._spins = {}
        for ch, lbl_txt, color in [("r","RED","#FF5555"), ("g","GRN","#55FF88"), ("b","BLU","#55AAFF")]:
            col = QVBoxLayout()
            col.setSpacing(2)
            l = QLabel(lbl_txt)
            l.setStyleSheet(f"color:{color}; font-size:9px; letter-spacing:2px; font-weight:bold;")
            sp = QSpinBox()
            sp.setRange(0, 255)
            sp.setAlignment(Qt.AlignmentFlag.AlignCenter)
            sp.setStyleSheet("""
                QSpinBox { background:#0D0F11; border:1px solid #1E2D3D; color:#C8D0D8;
                           font-family:'Courier New'; font-size:12px; padding:4px; border-radius:2px; }
                QSpinBox:focus { border-color:#00E5FF; }
                QSpinBox::up-button, QSpinBox::down-button { width:0; border:none; }
            """)
            sp.valueChanged.connect(self._from_spinbox)
            self._spins[ch] = sp
            col.addWidget(l)
            col.addWidget(sp)
            rgb_row.addLayout(col)
        right.addLayout(rgb_row)

        # HEX input
        hex_row = QHBoxLayout()
        hex_row.setSpacing(6)
        lbl_hex = QLabel("HEX")
        lbl_hex.setStyleSheet("color:#607080; font-size:10px; letter-spacing:1px;")
        lbl_hex.setFixedWidth(28)
        self._hex_inp = QLineEdit()
        self._hex_inp.setMaxLength(7)
        self._hex_inp.setPlaceholderText("#FFFFFF")
        self._hex_inp.setStyleSheet("""
            QLineEdit { background:#0D0F11; border:1px solid #1E2D3D; color:#C8D0D8;
                        font-family:'Courier New'; font-size:12px; padding:5px 8px; border-radius:2px; }
            QLineEdit:focus { border-color:#00E5FF; }
        """)
        self._hex_inp.editingFinished.connect(self._from_hex)
        hex_row.addWidget(lbl_hex)
        hex_row.addWidget(self._hex_inp)
        right.addLayout(hex_row)
        right.addStretch()

        custom_row.addLayout(right)
        blay.addLayout(custom_row)
        root.addWidget(body)

        # ── Footer ──
        footer = QFrame()
        footer.setFixedHeight(52)
        footer.setStyleSheet("background:#080C0F; border-top:1px solid #1A2535;")
        flay = QHBoxLayout(footer)
        flay.setContentsMargins(14, 0, 14, 0)
        flay.setSpacing(10)

        btn_add_fav = QPushButton("+  SAVE TO MY COLORS")
        btn_add_fav.setFixedHeight(32)
        btn_add_fav.setStyleSheet("""
            QPushButton { background:#111820; border:1px solid #1E2D3D; color:#607080;
                          font-family:'Courier New'; font-size:10px; letter-spacing:1px;
                          padding:0 12px; border-radius:2px; }
            QPushButton:hover { border-color:#00E5FF; color:#00E5FF; }
        """)
        btn_add_fav.clicked.connect(self._add_favorite)

        btn_cancel = QPushButton("CANCEL")
        btn_cancel.setFixedSize(90, 32)
        btn_cancel.setStyleSheet("""
            QPushButton { background:#111820; border:1px solid #1E2D3D; color:#C8D0D8;
                          font-family:'Courier New'; font-size:11px; font-weight:bold;
                          letter-spacing:1px; border-radius:2px; }
            QPushButton:hover { border-color:#607080; }
        """)
        btn_cancel.clicked.connect(self.reject)

        btn_apply = QPushButton("APPLY  →")
        btn_apply.setFixedSize(110, 32)
        btn_apply.setStyleSheet("""
            QPushButton { background:#003D52; border:1px solid #00E5FF; color:#00E5FF;
                          font-family:'Courier New'; font-size:11px; font-weight:bold;
                          letter-spacing:2px; border-radius:2px; }
            QPushButton:hover { background:#005070; }
            QPushButton:pressed { background:#00E5FF; color:#000; }
        """)
        btn_apply.clicked.connect(self._apply)

        flay.addWidget(btn_add_fav)
        flay.addStretch()
        flay.addWidget(btn_cancel)
        flay.addWidget(btn_apply)
        root.addWidget(footer)

    def _rebuild_favorites(self):
        # Clear existing
        while self._fav_layout.count():
            item = self._fav_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._fav_buttons.clear()

        for i, (r, g, b) in enumerate(self._favorites):
            sw = SwatchButton(r, g, b, f"rgb({r},{g},{b})")
            sw.clicked.connect(lambda _, cr=r, cg=g, cb=b: self._set_color(cr, cg, cb, update_wheel=True))
            sw.right_clicked.connect(lambda idx=i: self._remove_favorite(idx))
            self._fav_layout.addWidget(sw)
            self._fav_buttons.append(sw)

        # Empty hint
        if not self._favorites:
            lbl = QLabel("no saved colors yet")
            lbl.setStyleSheet("color:#2A3540; font-size:10px; letter-spacing:1px;")
            self._fav_layout.addWidget(lbl)

    def _add_favorite(self):
        rgb = tuple(self._current)
        if rgb not in [tuple(f) for f in self._favorites]:
            self._favorites.append(list(rgb))
            save_favorites(self._favorites)
            self._rebuild_favorites()

    def _remove_favorite(self, idx: int):
        if 0 <= idx < len(self._favorites):
            self._favorites.pop(idx)
            save_favorites(self._favorites)
            self._rebuild_favorites()

    def _set_color(self, r: int, g: int, b: int, update_wheel: bool = True):
        self._current = [r, g, b]
        self._preview.setStyleSheet(f"background:rgb({r},{g},{b}); border:1px solid #1E2D3D; border-radius:2px;")

        # Update inputs without triggering signals
        for sp in self._spins.values():
            sp.blockSignals(True)
        self._spins["r"].setValue(r)
        self._spins["g"].setValue(g)
        self._spins["b"].setValue(b)
        for sp in self._spins.values():
            sp.blockSignals(False)

        self._hex_inp.setText(f"#{r:02X}{g:02X}{b:02X}")

        if update_wheel:
            self._wheel.set_color(r, g, b)

    def _from_spinbox(self):
        r = self._spins["r"].value()
        g = self._spins["g"].value()
        b = self._spins["b"].value()
        self._set_color(r, g, b, update_wheel=True)

    def _from_hex(self):
        text = self._hex_inp.text().strip().replace("#", "")
        if len(text) == 6:
            try:
                r = int(text[0:2], 16)
                g = int(text[2:4], 16)
                b = int(text[4:6], 16)
                self._set_color(r, g, b, update_wheel=True)
            except ValueError:
                pass

    def _apply(self):
        self.color_selected.emit(*self._current)
        self.accept()

    def get_rgb(self) -> tuple:
        return tuple(self._current)
