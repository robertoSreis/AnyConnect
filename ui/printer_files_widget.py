# -*- coding: utf-8 -*-
"""
PrinterFilesWidget — Explorador de arquivos da impressora Anycubic
Lista arquivos via MQTT (web/file action=fileList).
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QFrame, QTreeWidget, QTreeWidgetItem,
    QHeaderView, QMessageBox, QProgressBar
)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer
from PyQt6.QtGui import QFont, QColor


class PrinterFilesWidget(QWidget):
    """Explorador de arquivos da impressora via MQTT."""

    file_selected = pyqtSignal(str)

    def __init__(self, settings: dict, parent=None):
        super().__init__(parent)
        self._settings = settings
        self._mqtt     = None
        self._files    = []
        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        hdr = QFrame()
        hdr.setFixedHeight(40)
        hdr.setStyleSheet("background:#080C0F; border-bottom:1px solid #1A2535;")
        hl = QHBoxLayout(hdr)
        hl.setContentsMargins(12, 0, 12, 0)

        lbl = QLabel("ARQUIVOS  DA  IMPRESSORA")
        lbl.setFont(QFont("Courier New", 10, QFont.Weight.Bold))
        lbl.setStyleSheet("color:#00E5FF; letter-spacing:3px;")

        self._lbl_status = QLabel("Aguardando conexão...")
        self._lbl_status.setFont(QFont("Courier New", 9))
        self._lbl_status.setStyleSheet("color:#607080;")

        self._btn_refresh = QPushButton("⟳  ATUALIZAR")
        self._btn_refresh.setFont(QFont("Courier New", 9, QFont.Weight.Bold))
        self._btn_refresh.setFixedHeight(26)
        self._btn_refresh.clicked.connect(self.refresh)

        hl.addWidget(lbl)
        hl.addSpacing(16)
        hl.addWidget(self._lbl_status, 1)
        hl.addWidget(self._btn_refresh)
        root.addWidget(hdr)

        self._progress = QProgressBar()
        self._progress.setRange(0, 0)
        self._progress.setFixedHeight(3)
        self._progress.setStyleSheet(
            "QProgressBar { background:#0A0D10; border:none; }"
            "QProgressBar::chunk { background:#00E5FF; }"
        )
        self._progress.setVisible(False)
        root.addWidget(self._progress)

        self._tree = QTreeWidget()
        self._tree.setColumnCount(2)
        self._tree.setHeaderLabels(["ARQUIVO", "TIPO"])
        self._tree.header().setFont(QFont("Courier New", 9))
        self._tree.header().setStyleSheet("color:#607080;")
        self._tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._tree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self._tree.setFont(QFont("Courier New", 9))
        self._tree.setStyleSheet("""
            QTreeWidget { background:#0A0D10; border:none; color:#C8D0D8; }
            QTreeWidget::item:selected { background:#0D2535; color:#00E5FF; }
            QTreeWidget::item:hover    { background:#0D1A28; }
        """)
        self._tree.setAlternatingRowColors(True)
        self._tree.currentItemChanged.connect(self._on_item_changed)
        root.addWidget(self._tree, 1)

        btn_row = QHBoxLayout()
        btn_row.setContentsMargins(8, 4, 8, 4)
        btn_delete = QPushButton("DELETAR")
        btn_delete.setFont(QFont("Courier New", 9, QFont.Weight.Bold))
        btn_delete.setObjectName("danger")
        btn_delete.setMinimumHeight(28)
        btn_delete.clicked.connect(self._on_delete)
        btn_row.addStretch()
        btn_row.addWidget(btn_delete)
        root.addLayout(btn_row)

    def set_mqtt(self, mqtt_client):
        if self._mqtt:
            try:
                self._mqtt.file_list.disconnect(self._on_files_received)
            except Exception:
                pass
        self._mqtt = mqtt_client
        if self._mqtt and hasattr(self._mqtt, "file_list"):
            self._mqtt.file_list.connect(self._on_files_received)

    def update_settings(self, settings: dict):
        self._settings = settings

    def refresh(self):
        if not self._mqtt or not self._mqtt.is_connected:
            self._lbl_status.setText("Não conectado")
            return
        self._progress.setVisible(True)
        self._lbl_status.setText("Solicitando lista...")
        self._mqtt.request_file_list()
        QTimer.singleShot(6000, self._on_timeout)

    def _on_timeout(self):
        if self._progress.isVisible():
            self._progress.setVisible(False)
            if not self._files:
                self._lbl_status.setText("Sem resposta do MQTT — verifique conexão")

    def _on_files_received(self, files: list):
        self._progress.setVisible(False)
        self._files = files
        if not files:
            self._lbl_status.setText("Nenhum arquivo")
            return
        self._lbl_status.setText(f"{len(files)} arquivo(s)")
        self._tree.clear()
        for f in files:
            name = (f.get("filename") or f.get("name") or
                    f.get("file_name") or str(f))
            low = name.lower()
            if low.endswith(".gcode.3mf"):
                tipo, color = "3MF", "#FFB300"
            elif low.endswith(".acm"):
                tipo, color = "ACM", "#607080"
            elif low.endswith((".gcode", ".gc")):
                tipo, color = "GCODE", "#00E5FF"
            else:
                ext = name.rsplit(".", 1)[-1].upper() if "." in name else "?"
                tipo, color = ext, "#607080"
            item = QTreeWidgetItem([name, tipo])
            item.setData(0, Qt.ItemDataRole.UserRole, f)
            item.setForeground(0, QColor(color))
            self._tree.addTopLevelItem(item)

    def _on_item_changed(self, current, previous):
        if current:
            self.file_selected.emit(current.text(0))

    def _on_delete(self):
        item = self._tree.currentItem()
        if not item:
            return
        name = item.text(0)
        ans  = QMessageBox.question(
            self, "Confirmar exclusão",
            f"Deletar '{name}' da impressora?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if ans != QMessageBox.StandardButton.Yes:
            return
        if self._mqtt and self._mqtt.is_connected:
            try:
                self._mqtt._pub_web_file("fileDelete",
                                         {"root": "local", "filename": name})
                QTimer.singleShot(1200, self.refresh)
            except Exception:
                pass
