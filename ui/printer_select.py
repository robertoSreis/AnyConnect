# -*- coding: utf-8 -*-
"""
Printer selection screen
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QFrame, QSizePolicy
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont


BRANDS = [
    {
        "id":       "anycubic",
        "name":     "ANYCUBIC",
        "models":   "Kobra S1 / Kobra 3 / ACE Pro",
        "enabled":  True,
    },
    {
        "id":       "bambu",
        "name":     "BAMBU LAB",
        "models":   "X1C / P1S / A1 Mini",
        "enabled":  False,
    },
    {
        "id":       "creality",
        "name":     "CREALITY",
        "models":   "K1 / K1 Max / Ender series",
        "enabled":  False,
    },
]


class BrandCard(QFrame):
    clicked = pyqtSignal(str)

    def __init__(self, brand: dict, parent=None):
        super().__init__(parent)
        self.brand_id = brand["id"]
        self.enabled  = brand["enabled"]
        self._selected = False

        self.setMinimumSize(220, 130)
        self.setCursor(Qt.CursorShape.PointingHandCursor if self.enabled else Qt.CursorShape.ForbiddenCursor)
        self._apply_style(False)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(6)

        # Brand name
        lbl_name = QLabel(brand["name"])
        lbl_name.setFont(QFont("Courier New", 14, QFont.Weight.Bold))
        lbl_name.setAlignment(Qt.AlignmentFlag.AlignLeft)
        if self.enabled:
            lbl_name.setStyleSheet("color: #C8D0D8; letter-spacing: 3px;")
        else:
            lbl_name.setStyleSheet("color: #2A3540; letter-spacing: 3px;")

        # Models
        lbl_models = QLabel(brand["models"])
        lbl_models.setFont(QFont("Courier New", 10))
        lbl_models.setWordWrap(True)
        if self.enabled:
            lbl_models.setStyleSheet("color: #607080; letter-spacing: 1px;")
        else:
            lbl_models.setStyleSheet("color: #1E2A34; letter-spacing: 1px;")

        # Status badge
        lbl_status = QLabel("AVAILABLE" if self.enabled else "COMING SOON")
        lbl_status.setFont(QFont("Courier New", 9, QFont.Weight.Bold))
        lbl_status.setAlignment(Qt.AlignmentFlag.AlignRight)
        if self.enabled:
            lbl_status.setStyleSheet("color: #00FF88; letter-spacing: 2px;")
        else:
            lbl_status.setStyleSheet("color: #2A3540; letter-spacing: 2px;")

        layout.addWidget(lbl_name)
        layout.addWidget(lbl_models)
        layout.addStretch()
        layout.addWidget(lbl_status)

    def _apply_style(self, selected: bool):
        if not self.enabled:
            self.setStyleSheet("""
                QFrame {
                    background-color: #0A0D10;
                    border: 1px solid #141C24;
                    border-radius: 2px;
                }
            """)
        elif selected:
            self.setStyleSheet("""
                QFrame {
                    background-color: #0A1E2A;
                    border: 2px solid #00E5FF;
                    border-radius: 2px;
                }
            """)
        else:
            self.setStyleSheet("""
                QFrame {
                    background-color: #111820;
                    border: 1px solid #1E2D3D;
                    border-radius: 2px;
                }
                QFrame:hover {
                    border-color: #00E5FF;
                    background-color: #131C26;
                }
            """)

    def set_selected(self, selected: bool):
        self._selected = selected
        self._apply_style(selected)

    def mousePressEvent(self, event):
        if self.enabled:
            self.clicked.emit(self.brand_id)


class PrinterSelectWidget(QWidget):
    brand_selected = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._selected_brand = ""
        self._cards = {}
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(60, 50, 60, 50)
        layout.setSpacing(0)

        # Header
        lbl_title = QLabel("3D PRINT CONTROLLER")
        lbl_title.setObjectName("title")
        lbl_title.setAlignment(Qt.AlignmentFlag.AlignCenter)

        lbl_sub = QLabel("SELECT PRINTER BRAND")
        lbl_sub.setObjectName("subtitle")
        lbl_sub.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Separator
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color: #1A2535; margin: 20px 0;")

        layout.addWidget(lbl_title)
        layout.addSpacing(6)
        layout.addWidget(lbl_sub)
        layout.addWidget(sep)
        layout.addSpacing(10)

        # Cards row
        cards_layout = QHBoxLayout()
        cards_layout.setSpacing(20)
        cards_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        for brand in BRANDS:
            card = BrandCard(brand)
            card.clicked.connect(self._on_brand_clicked)
            self._cards[brand["id"]] = card
            cards_layout.addWidget(card)

        layout.addLayout(cards_layout)
        layout.addSpacing(30)

        # Status line
        self._lbl_selected = QLabel("[ NO BRAND SELECTED ]")
        self._lbl_selected.setObjectName("subtitle")
        self._lbl_selected.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._lbl_selected)

        layout.addSpacing(20)

        # Continue button
        btn_layout = QHBoxLayout()
        btn_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._btn_continue = QPushButton("CONTINUE  →")
        self._btn_continue.setObjectName("primary")
        self._btn_continue.setMinimumWidth(230)
        self._btn_continue.setEnabled(False)
        self._btn_continue.clicked.connect(self._on_continue)
        btn_layout.addWidget(self._btn_continue)
        layout.addLayout(btn_layout)

        layout.addStretch()

        # Footer
        lbl_footer = QLabel("v0.1.0  —  SE3D GESTOR  —  3D PRINT CONTROLLER")
        lbl_footer.setObjectName("subtitle")
        lbl_footer.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(lbl_footer)

    def _on_brand_clicked(self, brand_id: str):
        # Deselect all
        for card in self._cards.values():
            card.set_selected(False)
        # Select clicked
        self._cards[brand_id].set_selected(True)
        self._selected_brand = brand_id
        self._lbl_selected.setText(f"[ {brand_id.upper()} SELECTED ]")
        self._lbl_selected.setStyleSheet("color: #00E5FF; font-size: 11px; letter-spacing: 2px;")
        self._btn_continue.setEnabled(True)

    def _on_continue(self):
        if self._selected_brand:
            self.brand_selected.emit(self._selected_brand)

    def restore_selection(self, brand_id: str):
        """Restores previously saved selection"""
        if brand_id and brand_id in self._cards:
            self._on_brand_clicked(brand_id)
