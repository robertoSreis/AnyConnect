# -*- coding: utf-8 -*-
"""
print_queue_widget.py — Fila de Impressão
==========================================
v4:
  - Thumbnail extraído diretamente do arquivo .gcode.3mf/.gcode ao enfileirar
  - PNG salvo junto ao arquivo fonte (mesmo nome + .queue_thumb.png)
  - Remove PNG ao remover job (remove_at, clear, dequeue)
  - Remove All também apaga os arquivos temporários .gcode.3mf da pasta Bridge
"""

import os
import json
import tempfile
import threading

from PyQt6.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QFrame, QScrollArea, QMessageBox,
    QSizePolicy,
)
from PyQt6.QtCore import Qt, pyqtSignal, QObject, QTimer
from PyQt6.QtGui import QFont, QPixmap


def _queue_file() -> str:
    return os.path.join(tempfile.gettempdir(), "se3d_print_queue.json")


# ─────────────────────────────────────────────────────────────────────────────
# Thumbnail helpers
# ─────────────────────────────────────────────────────────────────────────────

def _thumb_path_for(filepath: str) -> str:
    """Retorna o caminho do PNG de thumbnail para um dado arquivo de fila."""
    return filepath + ".queue_thumb.png"


def _extract_and_save_thumb(filepath: str) -> str:
    """
    Extrai thumbnail de dentro do .gcode.3mf ou .gcode e salva como PNG.
    Retorna o path do PNG salvo, ou "" se não encontrou thumbnail.
    Chamado em thread de background.
    """
    try:
        from ui.print_widget import _extract_thumb_bytes
        img_data = _extract_thumb_bytes(filepath)
        if not img_data:
            return ""
        out = _thumb_path_for(filepath)
        with open(out, "wb") as f:
            f.write(img_data)
        return out
    except Exception:
        return ""


def _delete_thumb(filepath: str):
    """Remove o PNG de thumbnail associado ao filepath, se existir."""
    try:
        p = _thumb_path_for(filepath)
        if os.path.isfile(p):
            os.remove(p)
    except Exception:
        pass


def _delete_job_files(job: dict):
    """Remove o PNG de thumbnail e o arquivo .gcode.3mf temporário (se na pasta Bridge/temp)."""
    fp = job.get("filepath", "")
    if not fp:
        return
    # Apaga PNG de thumbnail
    _delete_thumb(fp)
    # Apaga o .gcode.3mf se estiver em pasta temporária gerenciada pelo app
    _bridge_prefixes = []
    try:
        local = os.environ.get("LOCALAPPDATA", "")
        if local:
            _bridge_prefixes.append(os.path.join(local, "AnyConnect"))
    except Exception:
        pass
    try:
        _bridge_prefixes.append(os.path.join(tempfile.gettempdir(), "AnyConnect"))
    except Exception:
        pass
    for prefix in _bridge_prefixes:
        if fp.startswith(prefix):
            try:
                if os.path.isfile(fp):
                    os.remove(fp)
            except Exception:
                pass
            break


# ═══════════════════════════════════════════════════════════════════════════
#  PrintQueue
# ═══════════════════════════════════════════════════════════════════════════

class PrintQueue(QObject):
    next_job_ready = pyqtSignal(dict)
    queue_changed  = pyqtSignal(int)
    play_requested = pyqtSignal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._jobs: list[dict] = []
        self._load()
        if self._jobs:
            QTimer.singleShot(500, lambda: self.queue_changed.emit(self.count()))

    def _load(self):
        try:
            path = _queue_file()
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self._jobs = [j for j in data if os.path.isfile(j.get("filepath", ""))]
            else:
                self._jobs = []
        except Exception:
            self._jobs = []

    def _save(self):
        try:
            safe_jobs = []
            for j in self._jobs:
                safe = {k: v for k, v in j.items()
                        if isinstance(v, (str, int, float, bool, list, dict, type(None)))}
                safe_jobs.append(safe)
            with open(_queue_file(), "w", encoding="utf-8") as f:
                json.dump(safe_jobs, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def _clear_file(self):
        try:
            path = _queue_file()
            if os.path.exists(path):
                os.remove(path)
        except Exception:
            pass

    def count(self) -> int:
        return len(self._jobs)

    def is_empty(self) -> bool:
        return len(self._jobs) == 0

    def enqueue(self, job: dict):
        """Adiciona job à fila e extrai thumbnail em background."""
        self._jobs.append(job)
        self._save()
        self.queue_changed.emit(self.count())

        filepath = job.get("filepath", "")
        if not filepath or not os.path.isfile(filepath):
            return

        # Se PNG já existe, usa sem re-extrair
        existing = _thumb_path_for(filepath)
        if os.path.isfile(existing):
            job["preview_png"] = existing
            self._save()
            return

        # Extrai em background
        def _bg(fp=filepath, j=job):
            png = _extract_and_save_thumb(fp)
            if png:
                j["preview_png"] = png
                self._save()
                self.queue_changed.emit(self.count())
        threading.Thread(target=_bg, daemon=True).start()

    def peek(self) -> dict | None:
        return self._jobs[0] if self._jobs else None

    def dequeue(self) -> dict | None:
        if not self._jobs:
            return None
        job = self._jobs.pop(0)
        if self._jobs:
            self._save()
        else:
            self._clear_file()
        self.queue_changed.emit(self.count())
        # NÃO apaga arquivos ao dequeue — job vai ser impresso
        return job

    def remove_at(self, index: int):
        if 0 <= index < len(self._jobs):
            job = self._jobs.pop(index)
            if self._jobs:
                self._save()
            else:
                self._clear_file()
            self.queue_changed.emit(self.count())
            threading.Thread(target=_delete_job_files, args=(job,), daemon=True).start()

    def move_up(self, index: int):
        if 0 < index < len(self._jobs):
            self._jobs[index - 1], self._jobs[index] = self._jobs[index], self._jobs[index - 1]
            self._save()
            self.queue_changed.emit(self.count())

    def move_down(self, index: int):
        if 0 <= index < len(self._jobs) - 1:
            self._jobs[index], self._jobs[index + 1] = self._jobs[index + 1], self._jobs[index]
            self._save()
            self.queue_changed.emit(self.count())

    def clear(self):
        jobs = list(self._jobs)
        self._jobs.clear()
        self._clear_file()
        self.queue_changed.emit(0)
        threading.Thread(
            target=lambda: [_delete_job_files(j) for j in jobs],
            daemon=True
        ).start()

    def jobs(self) -> list[dict]:
        return list(self._jobs)

    def on_print_finished(self):
        if not self.is_empty():
            job = self.peek()
            self.next_job_ready.emit(job)

    def on_printer_idle(self):
        if not self.is_empty():
            job = self.peek()
            self.next_job_ready.emit(job)


# ═══════════════════════════════════════════════════════════════════════════
#  BedClearDialog
# ═══════════════════════════════════════════════════════════════════════════

class BedClearDialog(QDialog):
    RESULT_OK     = 1
    RESULT_SKIP   = 2
    RESULT_WAIT   = 3
    RESULT_CANCEL = 4

    def __init__(self, job: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Next queue job")
        self.setModal(True)
        self.setMinimumWidth(520)
        self.setStyleSheet("QDialog { background:#0B1015; } QLabel { color:#C0D0E0; }")
        self._action = self.RESULT_WAIT
        self._build_ui(job)

    def closeEvent(self, event):
        self._action = self.RESULT_WAIT
        event.accept()

    def _resolve_thumb(self, job: dict) -> str:
        """Tenta encontrar o PNG de thumbnail do job."""
        png = job.get("preview_png", "")
        if png and os.path.isfile(png):
            return png
        fp = job.get("filepath", "")
        if fp:
            c = _thumb_path_for(fp)
            if os.path.isfile(c):
                return c
        return ""

    def _build_ui(self, job: dict):
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(14)

        title = QLabel("⚠  VERIFY YOUR HEATED BED BEFORE PRINT")
        title.setFont(QFont("Courier New", 11, QFont.Weight.Bold))
        title.setStyleSheet("color:#FFB300; letter-spacing:2px;")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(title)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color:#1A2535;")
        root.addWidget(sep)

        info_row = QHBoxLayout()
        info_row.setSpacing(16)

        thumb_lbl = QLabel()
        thumb_lbl.setFixedSize(90, 90)
        thumb_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        thumb_lbl.setStyleSheet(
            "background:#0D1520; border:1px solid #1E2D3D; border-radius:4px;"
            "color:#2A4050; font-family:'Courier New'; font-size:8px;")
        thumb_lbl.setText("NO\nPREVIEW")

        png = self._resolve_thumb(job)
        if png:
            px = QPixmap(png)
            if not px.isNull():
                thumb_lbl.setPixmap(
                    px.scaled(88, 88, Qt.AspectRatioMode.KeepAspectRatio,
                               Qt.TransformationMode.SmoothTransformation))
                thumb_lbl.setStyleSheet(
                    "background:#0D1520; border:1px solid #1E2D3D; border-radius:4px;")
        info_row.addWidget(thumb_lbl)

        details = QVBoxLayout()
        details.setSpacing(4)
        fname = os.path.basename(job.get("filepath", "Unknown File"))
        task  = job.get("task_name", fname)
        lbl_task = QLabel(task)
        lbl_task.setFont(QFont("Courier New", 10, QFont.Weight.Bold))
        lbl_task.setStyleSheet("color:#00E5FF;")
        lbl_task.setWordWrap(True)
        details.addWidget(lbl_task)
        lbl_path = QLabel(job.get("filepath", ""))
        lbl_path.setFont(QFont("Courier New", 8))
        lbl_path.setStyleSheet("color:#2A4050;")
        lbl_path.setWordWrap(True)
        details.addWidget(lbl_path)
        details.addStretch()
        info_row.addLayout(details, 1)
        root.addLayout(info_row)

        sep2 = QFrame()
        sep2.setFrameShape(QFrame.Shape.HLine)
        sep2.setStyleSheet("color:#1A2535;")
        root.addWidget(sep2)

        msg = QLabel(
            "Please ensure that:\n\n"
            "  •  The print bed is clean and free of previous parts\n"
            "  •  The filament is loaded correctly\n"
            "  •  There is no obstruction in the nozzle or on the bed\n\n"
            "Confirm only when the bed is ready."
        )
        msg.setFont(QFont("Courier New", 9))
        msg.setStyleSheet("color:#8090A0;")
        msg.setWordWrap(True)
        root.addWidget(msg)

        sep3 = QFrame()
        sep3.setFrameShape(QFrame.Shape.HLine)
        sep3.setStyleSheet("color:#1A2535;")
        root.addWidget(sep3)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        btn_wait = QPushButton("⏸  Wait")
        btn_wait.setFont(QFont("Courier New", 9))
        btn_wait.setFixedHeight(36)
        btn_wait.setToolTip("Keep job in queue — ask again later")
        btn_wait.setStyleSheet("""
            QPushButton { background:#0A1520; border:1px solid #1E3550;
                color:#607080; border-radius:4px; padding:0 12px; }
            QPushButton:hover { background:#0D1E30; color:#8090A0; border-color:#2A4060; }
        """)
        btn_wait.clicked.connect(self._on_wait)

        btn_skip = QPushButton("⏭  Skip to next")
        btn_skip.setFont(QFont("Courier New", 9))
        btn_skip.setFixedHeight(36)
        btn_skip.setStyleSheet("""
            QPushButton { background:#1A2535; border:1px solid #2A3545;
                color:#607080; border-radius:4px; padding:0 12px; }
            QPushButton:hover { background:#222F40; color:#8090A0; }
        """)
        btn_skip.clicked.connect(self._on_skip)

        btn_cancel = QPushButton("✕  Remove from queue")
        btn_cancel.setFont(QFont("Courier New", 9))
        btn_cancel.setFixedHeight(36)
        btn_cancel.setStyleSheet("""
            QPushButton { background:#2A1010; border:1px solid #FF4444;
                color:#FF4444; border-radius:4px; padding:0 12px; }
            QPushButton:hover { background:#3A1818; }
        """)
        btn_cancel.clicked.connect(self._on_cancel)

        btn_ok = QPushButton("✔  Bed OK — Start Print")
        btn_ok.setFont(QFont("Courier New", 10, QFont.Weight.Bold))
        btn_ok.setFixedHeight(42)
        btn_ok.setMinimumWidth(170)
        btn_ok.setStyleSheet("""
            QPushButton { background:#003520; border:1px solid #00FF88;
                color:#00FF88; border-radius:4px; letter-spacing:1px; padding:0 16px; }
            QPushButton:hover { background:#005030; }
        """)
        btn_ok.clicked.connect(self._on_ok)
        btn_ok.setDefault(True)

        btn_row.addWidget(btn_wait)
        btn_row.addWidget(btn_skip)
        btn_row.addWidget(btn_cancel)
        btn_row.addStretch()
        btn_row.addWidget(btn_ok)
        root.addLayout(btn_row)

    def _on_ok(self):
        self._action = self.RESULT_OK
        self.accept()

    def _on_skip(self):
        self._action = self.RESULT_SKIP
        self.done(self.RESULT_SKIP)

    def _on_wait(self):
        self._action = self.RESULT_WAIT
        self.done(self.RESULT_WAIT)

    def _on_cancel(self):
        msg = QMessageBox(self)
        msg.setWindowTitle("Remove from queue?")
        msg.setIcon(QMessageBox.Icon.Question)
        msg.setText("Permanently remove this job from the print queue?\n\nThis cannot be undone.")
        msg.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        msg.setDefaultButton(QMessageBox.StandardButton.No)
        if msg.exec() == QMessageBox.StandardButton.Yes:
            self._action = self.RESULT_CANCEL
            self.done(self.RESULT_CANCEL)

    def get_action(self) -> int:
        return self._action

    def was_skipped(self) -> bool:
        return self._action == self.RESULT_SKIP


# ═══════════════════════════════════════════════════════════════════════════
#  QueuedNoticeDialog
# ═══════════════════════════════════════════════════════════════════════════

class QueuedNoticeDialog(QDialog):
    def __init__(self, job: dict, queue_position: int, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Busy — Print queue")
        self.setModal(True)
        self.setMinimumWidth(500)
        self.setStyleSheet("QDialog { background:#0B1015; } QLabel { color:#C0D0E0; }")
        self._build_ui(job, queue_position)

    def _build_ui(self, job: dict, pos: int):
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(14)

        title = QLabel("🖨  PRINTER BUSY — PROJECT ADDED TO QUEUE")
        title.setFont(QFont("Courier New", 10, QFont.Weight.Bold))
        title.setStyleSheet("color:#FFB300; letter-spacing:1px;")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(title)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color:#1A2535;")
        root.addWidget(sep)

        # Thumbnail — verifica preview_png e PNG junto ao arquivo
        preview_png = job.get("preview_png", "")
        if not preview_png or not os.path.isfile(preview_png):
            fp = job.get("filepath", "")
            if fp:
                c = _thumb_path_for(fp)
                if os.path.isfile(c):
                    preview_png = c
        if preview_png and os.path.isfile(preview_png):
            thumb_row = QHBoxLayout()
            thumb_lbl = QLabel()
            thumb_lbl.setFixedSize(72, 72)
            px = QPixmap(preview_png)
            if not px.isNull():
                thumb_lbl.setPixmap(
                    px.scaled(70, 70, Qt.AspectRatioMode.KeepAspectRatio,
                               Qt.TransformationMode.SmoothTransformation))
                thumb_lbl.setStyleSheet(
                    "border:1px solid #1E2D3D; border-radius:3px; background:#0D1520;")
            thumb_row.addWidget(thumb_lbl)
            thumb_row.addStretch()
            root.addLayout(thumb_row)

        fname = os.path.basename(job.get("filepath", "arquivo"))
        task  = job.get("task_name", fname)
        ordinal = {1: "st", 2: "nd", 3: "rd"}.get(pos, "th")

        info = QLabel(
            f"The file <b style='color:#00E5FF'>{task}</b> has been added to the queue.<br><br>"
            f"Queue position: <b style='color:#FFB300'>{pos}{ordinal}</b><br><br>"
            "When the current print finishes, you will be notified to confirm "
            "that the bed is clean before starting the next job."
        )
        info.setFont(QFont("Courier New", 9))
        info.setStyleSheet("color:#8090A0;")
        info.setWordWrap(True)
        root.addWidget(info)

        sep2 = QFrame()
        sep2.setFrameShape(QFrame.Shape.HLine)
        sep2.setStyleSheet("color:#1A2535;")
        root.addWidget(sep2)

        btn_row = QHBoxLayout()
        btn_ok = QPushButton("OK — understood")
        btn_ok.setFont(QFont("Courier New", 9, QFont.Weight.Bold))
        btn_ok.setFixedHeight(38)
        btn_ok.setStyleSheet("""
            QPushButton { background:#003520; border:1px solid #00FF88;
                color:#00FF88; border-radius:4px; padding:0 20px; }
            QPushButton:hover { background:#005030; }
        """)
        btn_ok.clicked.connect(self.accept)
        btn_ok.setDefault(True)
        btn_row.addStretch()
        btn_row.addWidget(btn_ok)
        root.addLayout(btn_row)


# ═══════════════════════════════════════════════════════════════════════════
#  PrintQueueDialog
# ═══════════════════════════════════════════════════════════════════════════

class PrintQueueDialog(QDialog):
    """Lista completa da fila com thumbnails extraídos dos arquivos fonte."""

    def __init__(self, queue: PrintQueue, parent=None, is_printing: bool = False):
        super().__init__(parent)
        self._queue = queue
        self._is_printing = is_printing
        self.setWindowTitle("Print queue")
        self.setModal(True)
        self.setMinimumSize(680, 400)
        self.resize(680, 450)
        self.setStyleSheet("QDialog { background:#0B1015; } QLabel { color:#C0D0E0; }")
        self._build_ui()
        self._queue.queue_changed.connect(self._refresh_list)

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(8)

        hdr = QHBoxLayout()
        title = QLabel("PRINT QUEUE")
        title.setFont(QFont("Courier New", 12, QFont.Weight.Bold))
        title.setStyleSheet("color:#00E5FF; letter-spacing:3px;")
        self._lbl_count = QLabel("")
        self._lbl_count.setFont(QFont("Courier New", 9))
        self._lbl_count.setStyleSheet("color:#607080;")
        hdr.addWidget(title)
        hdr.addSpacing(12)
        hdr.addWidget(self._lbl_count)
        hdr.addStretch()
        root.addLayout(hdr)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color:#1A2535;")
        root.addWidget(sep)

        lbl_hint = QLabel("▲ ▼ to reorder  ·  ▶ to print now  ·  ✕ to remove  ·  📄 file info")
        lbl_hint.setFont(QFont("Courier New", 8))
        lbl_hint.setStyleSheet("color:#2A3540; letter-spacing:1px;")
        root.addWidget(lbl_hint)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border:none; background:#060A0D; }")
        container = QWidget()
        container.setStyleSheet("background:#060A0D;")
        self._list_layout = QVBoxLayout(container)
        self._list_layout.setContentsMargins(6, 6, 6, 6)
        self._list_layout.setSpacing(4)
        self._list_layout.addStretch()
        scroll.setWidget(container)
        root.addWidget(scroll)

        self._refresh_list()

        sep2 = QFrame()
        sep2.setFrameShape(QFrame.Shape.HLine)
        sep2.setStyleSheet("color:#1A2535;")
        root.addWidget(sep2)

        btn_row = QHBoxLayout()

        btn_clear = QPushButton("Remove All")
        btn_clear.setFont(QFont("Courier New", 9))
        btn_clear.setFixedHeight(32)
        btn_clear.setStyleSheet("""
            QPushButton { background:#2A1010; border:1px solid #FF4444;
                          color:#FF4444; border-radius:4px; padding:0 14px; }
            QPushButton:hover { background:#3A1818; }
        """)
        btn_clear.clicked.connect(self._on_clear)

        btn_close = QPushButton("Close")
        btn_close.setFont(QFont("Courier New", 9))
        btn_close.setFixedHeight(32)
        btn_close.setStyleSheet("""
            QPushButton { background:#1A2535; border:1px solid #2A3545;
                          color:#607080; border-radius:4px; padding:0 14px; }
            QPushButton:hover { background:#222F40; color:#8090A0; }
        """)
        btn_close.clicked.connect(self.accept)

        btn_row.addWidget(btn_clear)
        btn_row.addStretch()
        btn_row.addWidget(btn_close)
        root.addLayout(btn_row)

    def _refresh_list(self, *_):
        layout = self._list_layout
        while layout.count() > 1:
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        jobs  = self._queue.jobs()
        total = len(jobs)

        if total == 0:
            lbl = QLabel("  Queue is empty.")
            lbl.setFont(QFont("Courier New", 10))
            lbl.setStyleSheet("color:#3A4550;")
            layout.insertWidget(0, lbl)
            self._lbl_count.setText("")
            return

        self._lbl_count.setText(f"{total} job{'s' if total != 1 else ''} pending")
        for i, job in enumerate(jobs):
            row = self._make_job_row(i, job, total)
            layout.insertWidget(i, row)

    def _load_thumb_async(self, job: dict, thumb_lbl: QLabel, size: int):
        """
        Carrega thumbnail no QLabel em cascata:
          1. preview_png já salvo no job dict
          2. <filepath>.queue_thumb.png (extraído anteriormente)
          3. Extração nova em background thread
        """
        filepath = job.get("filepath", "")

        # Fonte 1 & 2: PNG já existe
        for candidate in [job.get("preview_png", ""),
                          _thumb_path_for(filepath) if filepath else ""]:
            if candidate and os.path.isfile(candidate):
                self._apply_pixmap(thumb_lbl, candidate, size)
                return

        # Fonte 3: extrair em background
        if not filepath or not os.path.isfile(filepath):
            thumb_lbl.setText("?")
            return

        def _bg(fp=filepath, j=job, lbl=thumb_lbl, s=size):
            png = _extract_and_save_thumb(fp)
            if png:
                j["preview_png"] = png
                QTimer.singleShot(0, lambda: self._apply_pixmap(lbl, png, s))
                self._queue._save()
            else:
                QTimer.singleShot(0, lambda: lbl.setText("—"))
        threading.Thread(target=_bg, daemon=True).start()

    @staticmethod
    def _apply_pixmap(lbl: QLabel, png_path: str, size: int):
        try:
            if not os.path.isfile(png_path):
                return
            px = QPixmap(png_path)
            if px.isNull():
                return
            lbl.setPixmap(px.scaled(size - 2, size - 2,
                                     Qt.AspectRatioMode.KeepAspectRatio,
                                     Qt.TransformationMode.SmoothTransformation))
            lbl.setText("")
            lbl.setStyleSheet(
                "background:#080C10; border:1px solid #1A2535; border-radius:3px;")
        except Exception:
            pass

    def _show_file_info(self, job: dict):
        filepath = job.get("filepath", "Unknown path")
        task_name = job.get("task_name", os.path.basename(filepath))
        msg = QMessageBox(self)
        msg.setWindowTitle("File Information")
        msg.setIcon(QMessageBox.Icon.Information)
        msg.setText(f"<b>Task:</b> {task_name}<br><br>"
                   f"<b>Path:</b><br>{filepath}")
        msg.setStandardButtons(QMessageBox.StandardButton.Ok)
        msg.exec()

    def _make_job_row(self, index: int, job: dict, total: int) -> QFrame:
        frame = QFrame()
        frame.setStyleSheet(
            "QFrame { background:#0D1520; border:1px solid #1A2535; border-radius:4px; }"
        )
        hl = QHBoxLayout(frame)
        hl.setContentsMargins(6, 6, 6, 6)
        hl.setSpacing(8)

        SIZE = 56  # px quadrado para thumbnail

        # ── Thumbnail ──
        thumb_lbl = QLabel()
        thumb_lbl.setFixedSize(SIZE, SIZE)
        thumb_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        thumb_lbl.setStyleSheet(
            "background:#080C10; border:1px solid #1A2535; border-radius:3px;"
            "color:#2A4050; font-family:'Courier New'; font-size:14px;")
        thumb_lbl.setText("⏳")
        hl.addWidget(thumb_lbl)
        self._load_thumb_async(job, thumb_lbl, SIZE)

        # ── Posição ──
        lbl_pos = QLabel(f"#{index + 1}")
        lbl_pos.setFont(QFont("Courier New", 12, QFont.Weight.Bold))
        lbl_pos.setStyleSheet("color:#FFB300; min-width:28px;")
        lbl_pos.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hl.addWidget(lbl_pos)

        # ── Nome ──
        fname = os.path.basename(job.get("filepath", "—"))
        task  = job.get("task_name", fname)
        lbl_name = QLabel(task)
        lbl_name.setFont(QFont("Courier New", 9, QFont.Weight.Bold))
        lbl_name.setStyleSheet("color:#C0D0E0;")
        lbl_name.setToolTip(job.get("filepath", ""))
        lbl_name.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        hl.addWidget(lbl_name, 1)

        # ── Info ──
        btn_info = QPushButton("📄")
        btn_info.setFixedSize(28, 28)
        btn_info.setToolTip("Show file path")
        btn_info.setStyleSheet("""
            QPushButton { background:#0A1828; border:1px solid #1E3550;
                          color:#00E5FF; border-radius:3px; font-size:12px; }
            QPushButton:hover { background:#0D2030; color:#33FFFF; }
        """)
        btn_info.clicked.connect(lambda: self._show_file_info(job))
        hl.addWidget(btn_info)

        # ── Reordenação ▲▼ ──
        def _oss(enabled: bool) -> str:
            if enabled:
                return ("QPushButton { background:#0A1828; border:1px solid #1E3550;"
                        " color:#00E5FF; border-radius:3px; font-size:9px; }"
                        "QPushButton:hover { background:#0D2030; }")
            return ("QPushButton { background:#080C10; border:1px solid #111820;"
                    " color:#1A2535; border-radius:3px; font-size:9px; }")

        order_col = QVBoxLayout()
        order_col.setSpacing(2)
        btn_up = QPushButton("▲")
        btn_up.setFixedSize(24, 24)
        btn_up.setEnabled(index > 0)
        btn_up.setStyleSheet(_oss(index > 0))
        btn_up.setToolTip("Move up")
        btn_up.clicked.connect(lambda _=False, idx=index: self._on_move_up(idx))
        btn_dn = QPushButton("▼")
        btn_dn.setFixedSize(24, 24)
        btn_dn.setEnabled(index < total - 1)
        btn_dn.setStyleSheet(_oss(index < total - 1))
        btn_dn.setToolTip("Move down")
        btn_dn.clicked.connect(lambda _=False, idx=index: self._on_move_down(idx))
        order_col.addWidget(btn_up)
        order_col.addWidget(btn_dn)
        hl.addLayout(order_col)

        # ── Play (só primeiro) ──
        if index == 0:
            btn_play = QPushButton("▶")
            btn_play.setFixedSize(32, SIZE)
            if self._is_printing:
                btn_play.setEnabled(False)
                btn_play.setStyleSheet("""
                    QPushButton { background:#1A2535; border:1px solid #2A3545;
                                  color:#3A4550; border-radius:4px; font-size:12px; }
                """)
                btn_play.setToolTip("Wait for current print to finish")
            else:
                btn_play.setStyleSheet("""
                    QPushButton { background:#003520; border:1px solid #00FF88;
                                  color:#00FF88; border-radius:4px; font-size:12px; }
                    QPushButton:hover { background:#005030; }
                """)
                btn_play.setToolTip("Start this job now")
                btn_play.clicked.connect(lambda _=False, j=job: self._on_play(j))
            hl.addWidget(btn_play)

        # ── Remover ──
        btn_rm = QPushButton("✕")
        btn_rm.setFixedSize(26, SIZE)
        btn_rm.setStyleSheet("""
            QPushButton { background:#2A1010; border:1px solid #FF4444;
                          color:#FF4444; border-radius:4px; font-size:10px; }
            QPushButton:hover { background:#3A1818; }
        """)
        btn_rm.setToolTip("Remove from queue (deletes temp files)")
        btn_rm.clicked.connect(lambda _=False, idx=index: self._on_remove(idx))
        hl.addWidget(btn_rm)

        return frame

    def _on_move_up(self, index: int):
        self._queue.move_up(index)

    def _on_move_down(self, index: int):
        self._queue.move_down(index)

    def _on_play(self, job: dict):
        self._queue.play_requested.emit(job)
        self.accept()

    def _on_remove(self, index: int):
        msg = QMessageBox(self)
        msg.setWindowTitle("Remove job?")
        msg.setIcon(QMessageBox.Icon.Question)
        msg.setText(
            "Remove this job from the print queue?\n\n"
            "The thumbnail and temporary files will also be deleted."
        )
        msg.setStandardButtons(
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        msg.setDefaultButton(QMessageBox.StandardButton.No)
        if msg.exec() == QMessageBox.StandardButton.Yes:
            self._queue.remove_at(index)

    def _on_clear(self):
        msg = QMessageBox(self)
        msg.setWindowTitle("Empty queue")
        msg.setIcon(QMessageBox.Icon.Question)
        msg.setText(
            "Remove all jobs from queue?\n\n"
            "All thumbnails and temporary files will also be deleted."
        )
        msg.setStandardButtons(
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        msg.setDefaultButton(QMessageBox.StandardButton.No)
        if msg.exec() == QMessageBox.StandardButton.Yes:
            self._queue.clear()
