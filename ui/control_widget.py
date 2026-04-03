# -*- coding: utf-8 -*-
"""
Control panel - heating, movement, fans, speed, printer info, ACE Pro
"""
import os
import sys

try:
    import numpy as np
    _NP_AVAILABLE = True
except ImportError:
    _NP_AVAILABLE = False


from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QFrame, QGroupBox, QGridLayout,
    QSpinBox, QSlider, QSizePolicy, QTextEdit
)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer, QPointF, QRectF, QThread
from PyQt6.QtGui import (
    QFont, QPainter, QColor, QBrush, QPen, QLinearGradient, QImage, QPixmap,
    QConicalGradient, QPainterPath
)


_CV_AVAILABLE = None

def _ensure_cv2():
    global _CV_AVAILABLE
    if _CV_AVAILABLE is None:
        try:
            import cv2
            _CV_AVAILABLE = True
        except ImportError:
            _CV_AVAILABLE = False
    return _CV_AVAILABLE


def _find_ffmpeg() -> str:
    import shutil
    here = os.path.dirname(os.path.abspath(sys.argv[0]))
    for name in ("ffmpeg.exe", "ffmpeg"):
        local = os.path.join(here, name)
        if os.path.isfile(local):
            return local
    return shutil.which("ffmpeg") or ""


# ─────────────────────────────────────────────
# Temperature color helper
# ─────────────────────────────────────────────
def _temp_color(temp: float, max_temp: int) -> str:
    """
    Returns hex color string based on temperature criticality.
    Hotend (max>=200): cold=blue, warm=green, hot=orange→red
    Bed   (max<200):  cold=blue, warm=green, hot=orange→red
    """
    if temp < 5:
        return "#2A4060"   # off / room temp

    if max_temp >= 200:   # hotend, range 0–320
        if temp <= 40:
            return "#4488FF"   # blue — cold
        if temp <= 65:
            # blue → green
            t = (temp - 40) / 25
            r = int(68  * (1 - t))
            g = int(136 * (1 - t) + 220 * t)
            b = int(255 * (1 - t) + 88  * t)
            return f"#{r:02X}{g:02X}{b:02X}"
        if temp <= 180:
            return "#00CC88"   # green — safe operating
        # 180–320: green → orange → red
        t = min(1.0, (temp - 180) / 140)
        if t < 0.5:
            # green → orange
            t2 = t * 2
            r = int(0   * (1 - t2) + 255 * t2)
            g = int(204 * (1 - t2) + 179 * t2)
            b = int(136 * (1 - t2))
        else:
            # orange → red
            t2 = (t - 0.5) * 2
            r = 255
            g = int(179 * (1 - t2))
            b = 0
        return f"#{r:02X}{g:02X}{b:02X}"

    else:  # bed, range 0–120
        if temp <= 40:
            return "#4488FF"   # blue — cold
        if temp <= 70:
            # blue → green
            t = (temp - 40) / 30
            r = int(68  * (1 - t))
            g = int(136 * (1 - t) + 204 * t)
            b = int(255 * (1 - t) + 88  * t)
            return f"#{r:02X}{g:02X}{b:02X}"
        if temp <= 80:
            # green → orange
            t = (temp - 70) / 10
            r = int(0   * (1 - t) + 255 * t)
            g = int(204 * (1 - t) + 179 * t)
            b = int(88  * (1 - t))
            return f"#{r:02X}{g:02X}{b:02X}"
        # 80–120: orange → red
        t = min(1.0, (temp - 80) / 40)
        r = 255
        g = int(179 * (1 - t))
        b = 0
        return f"#{r:02X}{g:02X}{b:02X}"


# ─────────────────────────────────────────────
# Camera Thread
# ─────────────────────────────────────────────
class CameraThread(QThread):
    change_pixmap_signal = pyqtSignal(QImage)
    error_signal         = pyqtSignal(str)
    log_signal           = pyqtSignal(str)

    TARGET_FPS = 15
    CAM_W      = 640
    CAM_H      = 480

    def __init__(self, url: str, display_w: int = 640, display_h: int = 480):
        super().__init__()
        self._run_flag = True
        self.url       = url
        self._width    = display_w
        self._height   = display_h
        self._proc     = None

    def stop(self):
        self._run_flag = False
        if self._proc is not None:
            try:
                self._proc.kill()
            except Exception:
                pass

    def run(self):
        ffmpeg = _find_ffmpeg()
        if ffmpeg and _NP_AVAILABLE:
            self.log_signal.emit(f"[camera] ffmpeg: {os.path.basename(ffmpeg)}")
            self._run_ffmpeg(ffmpeg)
        else:
            if ffmpeg and not _NP_AVAILABLE:
                self.log_signal.emit("[camera] numpy não instalado — usando opencv")
            else:
                self.log_signal.emit("[camera] ffmpeg não encontrado — usando opencv")
            self._run_opencv()
        self.log_signal.emit("[camera] Thread encerrada.")

    def _run_ffmpeg(self, ffmpeg: str):
        import subprocess, time

        frame_size = self.CAM_W * self.CAM_H * 3
        frame_interval = 1.0 / self.TARGET_FPS
        last_emit = 0.0

        cmd = [
            ffmpeg,
            "-hide_banner", "-loglevel", "error",
            "-fflags",          "nobuffer+discardcorrupt",
            "-flags",           "low_delay",
            "-analyzeduration", "500000",
            "-probesize",       "200000",
            "-i",               self.url,
            "-f",               "rawvideo",
            "-pix_fmt",         "rgb24",
            "-vsync",           "0",
            "-vf",              f"scale={self.CAM_W}:{self.CAM_H}:flags=fast_bilinear",
            "-an",
            "pipe:1",
        ]

        flags = 0
        if sys.platform == "win32":
            flags = 0x08000000

        while self._run_flag:
            proc = None
            try:
                proc = subprocess.Popen(
                    cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                    bufsize=0, creationflags=flags,
                )
                self._proc = proc
                self.log_signal.emit("[camera] ffmpeg iniciado, aguardando frames...")

                buf = bytearray()
                t_start = time.monotonic()
                t_first = None

                while self._run_flag:
                    chunk = proc.stdout.read(65536)
                    if not chunk:
                        if proc.poll() is not None:
                            break
                        continue

                    buf.extend(chunk)
                    max_buf = frame_size * 4
                    if len(buf) > max_buf:
                        discard = (len(buf) - max_buf) // frame_size * frame_size
                        buf = buf[discard:]

                    while len(buf) >= frame_size and self._run_flag:
                        raw = bytes(buf[:frame_size])
                        buf = buf[frame_size:]

                        if t_first is None:
                            t_first = time.monotonic()
                            ms = (t_first - t_start) * 1000
                            self.log_signal.emit(f"[camera] 1º frame em {ms:.0f}ms")

                        now = time.monotonic()
                        if now - last_emit < frame_interval:
                            continue
                        last_emit = now

                        arr = np.frombuffer(raw, dtype=np.uint8).reshape(
                                (self.CAM_H, self.CAM_W, 3))
                        qimg = QImage(
                            arr.data, self.CAM_W, self.CAM_H,
                            self.CAM_W * 3, QImage.Format.Format_RGB888,
                        )
                        self.change_pixmap_signal.emit(
                            qimg.scaled(
                                self._width, self._height,
                                Qt.AspectRatioMode.KeepAspectRatio,
                                Qt.TransformationMode.FastTransformation,
                            ).copy()
                        )

            except Exception as e:
                if self._run_flag:
                    self.log_signal.emit(f"[camera] ffmpeg erro: {e}")
            finally:
                self._proc = None
                if proc:
                    try:
                        proc.kill()
                        proc.wait(timeout=2)
                    except Exception:
                        pass

            if self._run_flag:
                self.log_signal.emit("[camera] Reconectando em 2s...")
                self.msleep(2000)

    def _run_opencv(self):
        import time

        try:
            import cv2
        except ImportError:
            self.error_signal.emit("opencv não instalado\npip install opencv-python")
            return

        frame_interval = 1.0 / self.TARGET_FPS
        last_emit = 0.0

        while self._run_flag:
            self.log_signal.emit(f"[camera] opencv abrindo: {self.url}")
            cap = cv2.VideoCapture(self.url, cv2.CAP_FFMPEG)
            if not cap.isOpened():
                cap = cv2.VideoCapture(self.url, cv2.CAP_ANY)
            if not cap.isOpened():
                self.error_signal.emit("Não foi possível abrir o stream de câmera")
                return

            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            fails = 0

            while self._run_flag:
                ret, frame = cap.read()
                if not ret:
                    fails += 1
                    if fails >= 5:
                        break
                    continue
                fails = 0

                now = time.monotonic()
                if now - last_emit < frame_interval:
                    continue
                last_emit = now

                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                h, w, ch = rgb.shape
                img = QImage(rgb.data, w, h, ch * w, QImage.Format.Format_RGB888)
                self.change_pixmap_signal.emit(
                    img.scaled(self._width, self._height,
                               Qt.AspectRatioMode.KeepAspectRatio,
                               Qt.TransformationMode.FastTransformation).copy()
                )

            cap.release()
            if self._run_flag:
                self.log_signal.emit("[camera] opencv reconectando em 2s...")
                self.msleep(2000)


# ─────────────────────────────────────────────
# Filament Circle (ACE Pro visual)
# ─────────────────────────────────────────────
class FilamentCircle(QWidget):
    clicked_signal = pyqtSignal(int)

    def __init__(self, slot_index: int, color: list, material: str, active: bool = False, parent=None):
        super().__init__(parent)
        self.slot_index = slot_index
        self._color = color
        self._material = material
        self._selected = active
        self._printing = False
        self._consumables_pct = 0
        self._blink_on = True
        self.setFixedSize(80, 118)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._ace_offline = False

        self._blink_timer = QTimer(self)
        self._blink_timer.setInterval(500)
        self._blink_timer.timeout.connect(self._on_blink)

    def set_selected(self, selected: bool):
        self._selected = selected
        self.update()

    def set_ace_offline(self, offline: bool):
        self._ace_offline = offline
        self.update()

    def set_active(self, active: bool):
        self.set_selected(active)

    def set_printing(self, printing: bool):
        self._printing = printing
        if printing:
            self._blink_timer.start()
        else:
            self._blink_timer.stop()
            self._blink_on = True
        self.update()

    def _on_blink(self):
        self._blink_on = not self._blink_on
        self.update()

    def set_color(self, color: list, material: str):
        self._color = color
        self._material = material
        self.update()

    def set_consumables(self, pct: int):
        self._consumables_pct = max(0, min(100, pct))
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        r_val, g_val, b_val = self._color
        fil_color = QColor(r_val, g_val, b_val)
        cx, cy, r = 40, 44, 32

        if self._ace_offline:
            p.setPen(QPen(QColor("#2A3A4A"), 2, Qt.PenStyle.DashLine))
            p.setBrush(QColor("#0D0F11"))
            p.drawEllipse(cx - r, cy - r, r * 2, r * 2)
            inner_r = 22
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(22, 28, 35))
            p.drawEllipse(cx - inner_r, cy - inner_r, inner_r * 2, inner_r * 2)
            p.setBrush(QColor("#0D0F11"))
            p.drawEllipse(cx - 7, cy - 7, 14, 14)
            p.setPen(QColor("#2A4050"))
            p.setFont(QFont("Courier New", 15, QFont.Weight.Bold))
            p.drawText(0, cy - r + 4, 80, r * 2 - 8, Qt.AlignmentFlag.AlignCenter, "?")
            p.setPen(QColor("#2A3A4A"))
            p.setFont(QFont("Courier New", 9))
            p.drawText(0, cy + r + 4, 80, 14, Qt.AlignmentFlag.AlignCenter,
                       f"S{self.slot_index + 1}")
            p.setPen(QColor("#1E2A35"))
            p.setFont(QFont("Courier New", 8))
            p.drawText(0, cy + r + 17, 80, 12, Qt.AlignmentFlag.AlignCenter, "--")
            return

        if self._printing and self._blink_on:
            wire_x = cx
            wire_col = QColor(r_val, g_val, b_val)
            wire_col.setAlpha(200)
            p.setPen(QPen(wire_col, 3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.drawLine(wire_x, cy - r, wire_x, 2)
            tip_col = QColor(r_val, g_val, b_val)
            p.setPen(QPen(tip_col, 2))
            p.drawLine(wire_x - 5, 8, wire_x, 2)
            p.drawLine(wire_x + 5, 8, wire_x, 2)

        if self._printing:
            alpha = 255 if self._blink_on else 120
            ring_color = QColor(r_val, g_val, b_val, alpha)
            ring_width = 4
        elif self._selected:
            ring_color = QColor("#00E5FF")
            ring_width = 3
        else:
            ring_color = QColor("#1E2D3D")
            ring_width = 2

        p.setPen(QPen(ring_color, ring_width))
        p.setBrush(QColor("#0D0F11"))
        p.drawEllipse(cx - r, cy - r, r * 2, r * 2)

        inner_r = 22
        p.setPen(Qt.PenStyle.NoPen)
        if fil_color == QColor(0, 0, 0) or self._color == [40, 40, 40]:
            p.setBrush(QColor(50, 50, 55))
        else:
            p.setBrush(fil_color)
        p.drawEllipse(cx - inner_r, cy - inner_r, inner_r * 2, inner_r * 2)

        p.setBrush(QColor("#0D0F11"))
        p.drawEllipse(cx - 7, cy - 7, 14, 14)

        mat_color = QColor(r_val, g_val, b_val) if self._printing else QColor("#607080")
        p.setPen(mat_color)
        p.setFont(QFont("Courier New", 9))
        p.drawText(0, cy + r + 4, 80, 14, Qt.AlignmentFlag.AlignCenter,
                   f"S{self.slot_index + 1}  {self._material}")

        pct = self._consumables_pct
        if pct > 0:
            pct_color = "#00FF88" if pct > 30 else "#FFB300" if pct > 10 else "#FF4444"
            p.setPen(QColor(pct_color))
            p.setFont(QFont("Courier New", 8))
            p.drawText(0, cy + r + 17, 80, 12, Qt.AlignmentFlag.AlignCenter, f"{pct}%")
        else:
            p.setPen(QColor("#3A4550"))
            p.setFont(QFont("Courier New", 8))
            p.drawText(0, cy + r + 17, 80, 12, Qt.AlignmentFlag.AlignCenter, "0%")

    def mousePressEvent(self, event):
        self.clicked_signal.emit(self.slot_index)


# ─────────────────────────────────────────────
# Slot Display
# ─────────────────────────────────────────────
class SlotDisplay(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._loaded_num  = 0
        self._select_num  = 1
        self._fil_color   = [40, 40, 40]
        self._blink_on    = True
        self._active      = False
        self._ace_offline = False

        self._blink_timer = QTimer(self)
        self._blink_timer.setInterval(600)
        self._blink_timer.timeout.connect(self._on_blink)
        self.setFixedSize(100, 118)

    def set_loaded(self, slot_index: int, color: list = None):
        self._loaded_num = slot_index + 1 if slot_index >= 0 else 0
        if color:
            self._fil_color = color
        self._active = slot_index >= 0
        if self._active:
            self._blink_timer.start()
        else:
            self._blink_timer.stop()
            self._blink_on = True
        self.update()

    def set_select(self, slot_index: int):
        self._select_num = slot_index + 1
        self.update()

    def set_color(self, color: list):
        self._fil_color = color
        self.update()

    def set_ace_offline(self, offline: bool):
        self._ace_offline = offline
        if offline:
            self._blink_timer.stop()
            self._blink_on = True
        self.update()

    def _on_blink(self):
        self._blink_on = not self._blink_on
        self.update()

    def paintEvent(self, event):
        from PyQt6.QtGui import QPainterPath
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)

        w, h = self.width(), self.height()
        r, g, b = self._fil_color
        big_h = h - 26

        if self._ace_offline:
            num_text   = "EH"
            fill_color = QColor(35, 48, 60)
        elif self._loaded_num == 0:
            num_text   = "—"
            fill_color = QColor(55, 65, 75)
        else:
            num_text   = str(self._loaded_num)
            fill_color = QColor(r, g, b) if (r, g, b) != (40, 40, 40) else QColor(75, 85, 95)

        font = QFont("Arial Black", 72, QFont.Weight.Black)
        font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
        path = QPainterPath()
        path.addText(0, 0, font, num_text)
        br = path.boundingRect()
        margin = 6
        scale_x = (w - margin * 2) / br.width()  if br.width()  > 0 else 1
        scale_y = (big_h - margin * 2) / br.height() if br.height() > 0 else 1
        scale   = min(scale_x, scale_y)
        tx = (w - br.width()  * scale) / 2 - br.x() * scale
        ty = (big_h - br.height() * scale) / 2 - br.y() * scale

        p.save()
        p.translate(tx, ty)
        p.scale(scale, scale)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(fill_color)
        p.drawPath(path)

        stroke_w  = max(3.0, 8.0 / scale)
        brightness = (r + g + b) / 3
        is_neutral = abs(r - g) < 35 and abs(g - b) < 35 and abs(r - b) < 35

        if self._ace_offline:
            c_light = QColor(55, 80, 100); c_mid = QColor(30, 48, 62); c_dark = QColor(15, 22, 30)
        elif is_neutral or brightness > 190:
            c_light = QColor(210, 215, 220); c_mid = QColor(130, 140, 150); c_dark = QColor(50, 55, 65)
        else:
            c_light = QColor(min(255, int(r*1.35+55)), min(255, int(g*1.35+55)), min(255, int(b*1.35+55)))
            c_mid   = QColor(r, g, b)
            c_dark  = QColor(max(0, int(r*0.40)), max(0, int(g*0.40)), max(0, int(b*0.40)))

        grad = QLinearGradient(br.left(), br.top(), br.right(), br.bottom())
        grad.setColorAt(0.0, c_light); grad.setColorAt(0.5, c_mid); grad.setColorAt(1.0, c_dark)
        pen = QPen(QBrush(grad), stroke_w)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen); p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)
        p.restore()

        p.setPen(QColor("#2A3A50"))
        p.setFont(QFont("Courier New", 8))
        label_y = big_h + 4
        p.drawText(0, label_y, w, 10, Qt.AlignmentFlag.AlignCenter, "SELECT")
        p.setPen(QColor("#607080"))
        p.setFont(QFont("Courier New", 9, QFont.Weight.Bold))
        p.drawText(0, label_y + 11, w, 12, Qt.AlignmentFlag.AlignCenter, str(self._select_num))


# ─────────────────────────────────────────────
# Temperature Control Row
# ─────────────────────────────────────────────
class TempControl(QWidget):
    command_ready = pyqtSignal(str, object)

    def __init__(self, label: str, cmd_set: str, cmd_off: str,
                 default_temp: int, max_temp: int, parent=None):
        super().__init__(parent)
        self._cmd_set  = cmd_set
        self._cmd_off  = cmd_off
        self._max_temp = max_temp

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        lbl = QLabel(label)
        lbl.setFont(QFont("Courier New", 11, QFont.Weight.Bold))
        lbl.setStyleSheet("color: #607080; letter-spacing: 1px;")
        lbl.setMinimumWidth(110)

        self._spin = QSpinBox()
        self._spin.setRange(0, max_temp)
        self._spin.setValue(default_temp)
        self._spin.setSuffix(" C")
        self._spin.setFont(QFont("Courier New", 11))
        self._spin.setMinimumWidth(85)

        lbl_arrow = QLabel("->")
        lbl_arrow.setFont(QFont("Courier New", 11))
        lbl_arrow.setStyleSheet("color: #1E2D3D;")

        self._lbl_actual = QLabel("-- C")
        self._lbl_actual.setFont(QFont("Courier New", 11, QFont.Weight.Bold))
        self._lbl_actual.setStyleSheet("color: #2A4060;")
        self._lbl_actual.setMinimumWidth(65)

        self._btn_set = QPushButton("HEAT")
        self._btn_set.setFont(QFont("Courier New", 11, QFont.Weight.Bold))
        self._btn_set.setMinimumSize(80, 34)
        self._btn_set.clicked.connect(self._on_heat)

        self._btn_off = QPushButton("OFF")
        self._btn_off.setObjectName("danger")
        self._btn_off.setFont(QFont("Courier New", 11, QFont.Weight.Bold))
        self._btn_off.setMinimumSize(65, 34)
        self._btn_off.clicked.connect(self._on_off)

        self._spin.editingFinished.connect(self._on_heat)

        layout.addWidget(lbl)
        layout.addWidget(self._spin)
        layout.addWidget(lbl_arrow)
        layout.addWidget(self._lbl_actual)
        layout.addWidget(self._btn_set)
        layout.addWidget(self._btn_off)
        layout.addStretch()

    def _on_heat(self):
        self.command_ready.emit(self._cmd_set, self._spin.value())

    def _on_off(self):
        self.command_ready.emit(self._cmd_off, 0)

    def update_actual(self, temp: float):
        self._lbl_actual.setText(f"{temp:.0f} C")
        color = _temp_color(temp, self._max_temp)
        self._lbl_actual.setStyleSheet(
            f"color: {color}; font-weight: bold;"
        )


# ─────────────────────────────────────────────
# Pizza Progress Widget
# ─────────────────────────────────────────────
class _PizzaProgress(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._value = 0
        self.setMinimumSize(80, 80)

    def set_value(self, v: int):
        self._value = max(0, min(100, v))
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        cx, cy = w // 2, h // 2
        r = min(cx, cy) - 6

        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#0A0D10"))
        p.drawEllipse(cx - r, cy - r, r * 2, r * 2)

        pen_bg = QPen(QColor("#0D1520"), 8)
        pen_bg.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen_bg); p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(cx - r + 4, cy - r + 4, (r - 4) * 2, (r - 4) * 2)

        if self._value > 0:
            t  = self._value / 100.0
            pr = int(0   * (1 - t) + 0   * t)
            pg = int(229 * (1 - t) + 255 * t)
            pb = int(255 * (1 - t) + 136 * t)
            pen_arc = QPen(QColor(pr, pg, pb), 8)
            pen_arc.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(pen_arc)
            span = int(-self._value * 360 * 16 / 100)
            p.drawArc(cx - r + 4, cy - r + 4, (r - 4) * 2, (r - 4) * 2, 90 * 16, span)

        p.setPen(QColor("#C8D0D8"))
        p.setFont(QFont("Courier New", 14, QFont.Weight.Bold))
        p.drawText(0, 0, w, h, Qt.AlignmentFlag.AlignCenter, f"{self._value}%")
        p.setPen(QColor("#1E3550"))
        p.setFont(QFont("Courier New", 7))
        p.drawText(0, cy + r - 2, w, 14, Qt.AlignmentFlag.AlignCenter, "PROGRESS")


# ─────────────────────────────────────────────
# Temperature Gauge Widget (expanded camera sidebar)
# ─────────────────────────────────────────────
class _TempGauge(QWidget):
    def __init__(self, label: str, accent: str = "#00E5FF", max_temp: int = 300, parent=None):
        super().__init__(parent)
        self._label    = label
        self._accent   = accent
        self._max_temp = max_temp
        self._actual   = 0.0
        self._target   = 0.0
        self.setFixedHeight(44)

    def set_temps(self, actual: float, target: float):
        self._actual = actual
        self._target = target
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()

        p.setPen(QColor("#1E3550"))
        p.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
        p.drawText(0, 0, w, 14, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, self._label)

        # Color based on actual temperature
        color = _temp_color(self._actual, self._max_temp)
        p.setPen(QColor(color))
        p.setFont(QFont("Courier New", 16, QFont.Weight.Bold))
        p.drawText(0, 12, w // 2, 24, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   f"{self._actual:.0f}°")

        p.setPen(QColor("#2A4050"))
        p.setFont(QFont("Courier New", 9))
        p.drawText(w // 2, 14, w // 2, 20, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                   f"→ {self._target:.0f}°C")

        max_t = float(self._max_temp)
        pct   = min(1.0, self._actual / max_t) if max_t > 0 else 0
        bar_y = 38; bar_h = 3; bar_w = w - 4
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#0D1520"))
        p.drawRoundedRect(2, bar_y, bar_w, bar_h, 2, 2)
        if pct > 0:
            p.setBrush(QColor(color))
            p.drawRoundedRect(2, bar_y, int(bar_w * pct), bar_h, 2, 2)


# ─────────────────────────────────────────────
# Main control widget
# ─────────────────────────────────────────────
class ControlWidget(QWidget):
    command_ready = pyqtSignal(str, object)

    # Stylesheet for disabled primary buttons (gray instead of blue)
    _SS_HOME_DISABLED = (
        "QPushButton { background-color:#0D0F11; border:1px solid #1A2535; "
        "color:#2A3540; border-radius:2px; }"
    )
    _SS_HOME_ENABLED = ""  # revert to theme

    def __init__(self, settings: dict, parent=None):
        super().__init__(parent)
        self._settings         = settings
        self._current_step     = 10.0
        self._step_btns        = {}
        self._filament_circles = []
        self._cam_thread: CameraThread | None = None
        self._fan_sliders: dict = {}
        self._fan_labels:  dict = {}
        self._last_print_data: dict = {}
        self._home_btns: list  = []
        self._is_printing      = False   # tracks printing state for button/warning logic
        self._build_ui()

    def _build_ui(self):
        main = QVBoxLayout(self)
        main.setContentsMargins(10, 10, 10, 10)
        main.setSpacing(8)

        row1 = QHBoxLayout()
        row1.setSpacing(8)
        row1.addWidget(self._build_printer_info(), 18)
        row1.addWidget(self._build_ace_pro(),      40)
        row1.addWidget(self._build_jog(),          26)
        row1.addWidget(self._build_controls(),     16)
        main.addLayout(row1, 55)

        row2 = QHBoxLayout()
        row2.setSpacing(8)
        row2.addWidget(self._build_camera(), 1)

        from ui.print_widget import PrintWidget
        self._print_widget = PrintWidget(self._settings)
        self._print_widget.command_ready.connect(self.command_ready)
        row2.addWidget(self._print_widget, 3)

        main.addLayout(row2, 45)

    # ── Printer Info + Temperature ──
    def _build_printer_info(self) -> QGroupBox:
        grp = QGroupBox("PRINTER")
        layout = QVBoxLayout(grp)
        layout.setSpacing(6)
        layout.setContentsMargins(10, 20, 10, 10)

        self._lbl_model = QLabel("Anycubic Kobra S1")
        self._lbl_model.setFont(QFont("Courier New", 11, QFont.Weight.Bold))
        self._lbl_model.setStyleSheet("color: #C8D0D8;")
        self._lbl_model.setWordWrap(True)

        self._lbl_status_badge = QLabel("OFFLINE")
        self._lbl_status_badge.setFont(QFont("Courier New", 9, QFont.Weight.Bold))
        self._lbl_status_badge.setStyleSheet(
            "color: #FF4444; background: #2A0A0A; border: 1px solid #FF4444;"
            "padding: 2px 6px; letter-spacing: 2px;"
        )

        badge_row = QHBoxLayout()
        badge_row.addWidget(self._lbl_status_badge)
        badge_row.addStretch()

        def info_row(label, attr):
            row = QHBoxLayout()
            lbl = QLabel(label)
            lbl.setFont(QFont("Courier New", 9))
            lbl.setStyleSheet("color: #607080;")
            lbl.setMinimumWidth(72)
            val = QLabel("--")
            val.setFont(QFont("Courier New", 9))
            val.setStyleSheet("color: #C8D0D8;")
            setattr(self, attr, val)
            row.addWidget(lbl); row.addWidget(val, 1)
            return row

        layout.addWidget(self._lbl_model)
        layout.addLayout(badge_row)

        sep = QFrame(); sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color: #1A2535;"); layout.addWidget(sep)

        layout.addLayout(info_row("IP", "_lbl_ip"))
        layout.addLayout(info_row("FIRMWARE", "_lbl_firmware"))
        layout.addLayout(info_row("CN CODE", "_lbl_cn"))

        sep2 = QFrame(); sep2.setFrameShape(QFrame.Shape.HLine)
        sep2.setStyleSheet("color: #1A2535;"); layout.addWidget(sep2)

        lbl_temp_hdr = QLabel("TEMPERATURE")
        lbl_temp_hdr.setFont(QFont("Courier New", 9, QFont.Weight.Bold))
        lbl_temp_hdr.setStyleSheet("color: #607080; letter-spacing: 2px;")
        layout.addWidget(lbl_temp_hdr)

        self._temp_bed = TempControl("BED", "set_bed_temp", "bed_off", 60, 120)
        self._temp_bed.command_ready.connect(self.command_ready)
        self._temp_e0 = TempControl("HOTEND  T0", "set_hotend0_temp", "hotend0_off", 210, 300)
        self._temp_e0.command_ready.connect(self.command_ready)
        self._temp_e1 = TempControl("HOTEND  T1", "set_hotend1_temp", "hotend1_off", 210, 300)
        self._temp_e1.command_ready.connect(self.command_ready)
        self._temp_e1.setVisible(False)
        layout.addWidget(self._temp_bed)
        layout.addWidget(self._temp_e0)
        layout.addWidget(self._temp_e1)

        self._lbl_bed_info = QLabel("--")
        self._lbl_noz_info = QLabel("--")
        self._lbl_bed_info.setVisible(False)
        self._lbl_noz_info.setVisible(False)

        sep3 = QFrame(); sep3.setFrameShape(QFrame.Shape.HLine)
        sep3.setStyleSheet("color: #1A2535;"); layout.addWidget(sep3)

        btn_preheat = QPushButton("ONE-CLICK  PREHEAT")
        btn_preheat.setFont(QFont("Courier New", 10, QFont.Weight.Bold))
        btn_preheat.setObjectName("primary")
        btn_preheat.setMinimumHeight(34)
        btn_preheat.clicked.connect(lambda: self.command_ready.emit("preheat", None))
        layout.addWidget(btn_preheat)
        layout.addStretch()

        ip = self._settings.get("printer_ip", "--")
        self._lbl_ip.setText(ip if ip else "--")
        cn = self._settings.get("printer_cn", "--")
        self._lbl_cn.setText(cn if cn else "--")
        return grp

    # ── Camera inline ──
    def _build_camera(self) -> QGroupBox:
        grp = QGroupBox("CAMERA")
        layout = QVBoxLayout(grp)
        layout.setSpacing(4)
        layout.setContentsMargins(8, 18, 8, 8)

        ip = self._settings.get("printer_ip", "")
        self._cam_url = f"http://{ip}:18088/flv" if ip else ""

        self._cam_label = QLabel()
        self._cam_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._cam_label.setMinimumHeight(120)
        self._cam_label.setStyleSheet("background:#000; color:#2A3540;")
        self._cam_label.setText("■  NO  SIGNAL")
        self._cam_label.setFont(QFont("Courier New", 9))
        layout.addWidget(self._cam_label, 1)

        lbl_url = QLabel(self._cam_url or "— configure IP —")
        lbl_url.setFont(QFont("Courier New", 7))
        lbl_url.setStyleSheet("color:#2A3540;")
        lbl_url.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(lbl_url)
        self._cam_url_label = lbl_url

        btn_row = QHBoxLayout()
        btn_row.setSpacing(4)

        self._btn_camera_toggle = QPushButton("▶  START CAMERA")
        self._btn_camera_toggle.setFont(QFont("Courier New", 9, QFont.Weight.Bold))
        self._btn_camera_toggle.setObjectName("primary")
        self._btn_camera_toggle.setMinimumHeight(28)
        self._btn_camera_toggle.setCheckable(True)
        self._btn_camera_toggle.setChecked(False)
        self._btn_camera_toggle.clicked.connect(self._on_camera_toggle)

        self._btn_camera_expand = QPushButton("⛶")
        self._btn_camera_expand.setFont(QFont("Courier New", 12, QFont.Weight.Bold))
        self._btn_camera_expand.setFixedSize(28, 28)
        self._btn_camera_expand.setToolTip("Open camera in expanded tab")
        self._btn_camera_expand.setStyleSheet("""
            QPushButton { background:#0A1520; border:1px solid #1E3550;
                          color:#607080; border-radius:2px; }
            QPushButton:hover { border-color:#00E5FF; color:#00E5FF; }
        """)
        self._btn_camera_expand.clicked.connect(self._on_camera_expand)

        btn_row.addWidget(self._btn_camera_toggle, 1)
        btn_row.addWidget(self._btn_camera_expand)
        layout.addLayout(btn_row)

        if not _find_ffmpeg() and not _ensure_cv2():
            self._cam_label.setText("ffmpeg.exe or opencv required")

        return grp

    def _on_camera_toggle(self):
        if self._btn_camera_toggle.isChecked():
            self._cam_start()
            self._btn_camera_toggle.setText("■  STOP CAMERA")
            self._btn_camera_toggle.setObjectName("danger")
        else:
            self._cam_stop()
            self._btn_camera_toggle.setText("▶  START CAMERA")
            self._btn_camera_toggle.setObjectName("primary")
        self._btn_camera_toggle.style().polish(self._btn_camera_toggle)

    def _cam_start(self):
        if not self._cam_url:
            self._cam_label.setText("Configure printer IP first")
            return

        self._cam_stop_local()
        self.command_ready.emit("camera_start", None)
        self._cam_first_frame = False
        self._cam_is_retry    = False
        self._cam_do_start()

        self._cam_countdown = 30
        self._cam_label.setText(f"● WAITING FOR CAMERA...  ({self._cam_countdown}s)")
        self._cam_cdt = QTimer(self)
        self._cam_cdt.setInterval(1000)

        def _tick():
            if self._cam_first_frame:
                self._cam_cdt.stop()
                return
            self._cam_countdown -= 1
            if self._cam_countdown > 0:
                self._cam_label.setText(f"● WAITING FOR CAMERA...  ({self._cam_countdown}s)")
            elif not self._cam_is_retry:
                self._cam_is_retry = True
                self._cam_countdown = 30
                self._cam_label.setText(f"● RECONNECTING...  ({self._cam_countdown}s)")
                self._cam_stop_local()
                self.command_ready.emit("camera_start", None)
                self._cam_do_start()
            else:
                self._cam_cdt.stop()
                self._cam_stop_local()
                self._btn_camera_toggle.setChecked(False)
                self._btn_camera_toggle.setText("▶  START CAMERA")
                self._btn_camera_toggle.setObjectName("primary")
                self._btn_camera_toggle.style().polish(self._btn_camera_toggle)
                self._cam_label.setText("⚠  Failed to open stream\nCheck printer connection")

        self._cam_cdt.timeout.connect(_tick)
        self._cam_cdt.start()

    def _cam_do_start(self):
        if hasattr(self, '_cam_cdt') and self._cam_cdt:
            self._cam_cdt.stop()
        if not self._btn_camera_toggle.isChecked():
            return
        if self._cam_thread is not None:
            return

        self._cam_thread = CameraThread(self._cam_url, display_w=640, display_h=480)
        self._cam_thread.change_pixmap_signal.connect(self._on_cam_frame)
        self._cam_thread.error_signal.connect(self._on_cam_error)
        self._cam_thread.log_signal.connect(
            lambda msg: self.command_ready.emit("__log__", msg)
        )
        self._cam_label.setText("● CONECTANDO...")
        self._cam_thread.start()

    def stop_camera_on_disconnect(self):
        if self._cam_thread is not None:
            self._cam_stop_local()
            self._btn_camera_toggle.setChecked(False)
            self._btn_camera_toggle.setText("▶  START CAMERA")
            self._btn_camera_toggle.setObjectName("primary")
            self._btn_camera_toggle.style().polish(self._btn_camera_toggle)

    def _cam_stop_local(self):
        if hasattr(self, '_cam_cdt') and self._cam_cdt:
            self._cam_cdt.stop()
        if self._cam_thread is not None:
            thread = self._cam_thread
            self._cam_thread = None
            try:
                thread.change_pixmap_signal.disconnect()
                thread.error_signal.disconnect()
                if hasattr(thread, 'log_signal'):
                    thread.log_signal.disconnect()
            except Exception:
                pass
            thread.stop()
            thread.finished.connect(thread.deleteLater)
        self._cam_label.clear()
        self._cam_label.setText("■  NO  SIGNAL")

    def _cam_stop(self):
        self.command_ready.emit("camera_stop", None)
        if hasattr(self, '_cam_cdt') and self._cam_cdt:
            self._cam_cdt.stop()
        if self._cam_thread is not None:
            thread = self._cam_thread
            self._cam_thread = None
            try:
                thread.change_pixmap_signal.disconnect()
                thread.error_signal.disconnect()
            except Exception:
                pass
            thread.stop()
            thread.finished.connect(thread.deleteLater)
        self._cam_label.clear()
        self._cam_label.setText("■  NO  SIGNAL")

    def _on_cam_frame(self, image: QImage):
        self._cam_first_frame = True
        lw = self._cam_label.width()
        lh = self._cam_label.height()
        if lw > 10 and lh > 10:
            pix = QPixmap.fromImage(image).scaled(
                lw, lh,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.FastTransformation,
            )
        else:
            pix = QPixmap.fromImage(image)
        self._cam_label.setPixmap(pix)

    def _on_cam_error(self, msg: str):
        self._cam_label.setText(f"⚠  {msg}")
        if self._cam_thread is None:
            self._btn_camera_toggle.setChecked(False)
            self._btn_camera_toggle.setText("▶  START CAMERA")
            self._btn_camera_toggle.setObjectName("primary")
            self._btn_camera_toggle.style().polish(self._btn_camera_toggle)

    # ── Camera expanded tab ──
    def _on_camera_expand(self):
        tabs = self._find_parent_tabs()
        if tabs is None:
            return

        for i in range(tabs.count()):
            if tabs.tabText(i).startswith("CAMERA"):
                self._close_expanded_tab(tabs, i)
                return

        tab_w = self._build_expanded_camera_tab(tabs)
        idx = tabs.addTab(tab_w, "CAMERA  ●")
        tabs.setCurrentIndex(idx)
        self._setup_tab_close_button(tabs, idx, tab_w)
        self._set_inline_cam_enabled(False)
        self._start_expanded_stream(tab_w)

    def _close_expanded_tab(self, tabs, idx: int):
        w = tabs.widget(idx)
        if hasattr(w, "_exp_thread") and w._exp_thread is not None:
            t = w._exp_thread
            w._exp_thread = None
            try:
                t.change_pixmap_signal.disconnect()
                t.error_signal.disconnect()
                t.log_signal.disconnect()
            except Exception:
                pass
            t.stop()
            t.finished.connect(t.deleteLater)
        if hasattr(w, "_fps_timer"):
            w._fps_timer.stop()
        if hasattr(w, "_print_update_timer"):
            w._print_update_timer.stop()
        tabs.removeTab(idx)
        self._set_inline_cam_enabled(True)
        self._btn_camera_expand.setToolTip("Open camera in expanded tab")
        self._btn_camera_expand.setStyleSheet("""
            QPushButton { background:#0A1520; border:1px solid #1E3550;
                          color:#607080; border-radius:2px; }
            QPushButton:hover { border-color:#00E5FF; color:#00E5FF; }
        """)

    def _set_inline_cam_enabled(self, enabled: bool):
        self._btn_camera_toggle.setEnabled(enabled)
        self._btn_camera_expand.setStyleSheet("""
            QPushButton { background:#003D52; border:1px solid #00E5FF;
                          color:#00E5FF; border-radius:2px; }
            QPushButton:hover { background:#005070; }
        """ if not enabled else """
            QPushButton { background:#0A1520; border:1px solid #1E3550;
                          color:#607080; border-radius:2px; }
            QPushButton:hover { border-color:#00E5FF; color:#00E5FF; }
        """)
        if enabled:
            if not self._btn_camera_toggle.isChecked():
                self._cam_label.setText("■  NO  SIGNAL")
            self._btn_camera_toggle.setToolTip("")
        else:
            if self._btn_camera_toggle.isChecked():
                self._cam_stop()
                self._btn_camera_toggle.setChecked(False)
                self._btn_camera_toggle.setText("▶  START CAMERA")
                self._btn_camera_toggle.setObjectName("primary")
                self._btn_camera_toggle.style().polish(self._btn_camera_toggle)
            self._cam_label.setText("📺  VIDEO IN EXPANDED TAB")
            self._cam_label.setStyleSheet("background:#080C0F; color:#1E4060; font-size:9px;")
            self._btn_camera_toggle.setToolTip("Close expanded tab to re-enable")

    def _setup_tab_close_button(self, tabs, idx: int, tab_w: QWidget):
        from PyQt6.QtWidgets import QTabBar
        close_btn = QPushButton("✕")
        close_btn.setFixedSize(16, 16)
        close_btn.setStyleSheet("""
            QPushButton { background:transparent; border:none; color:#607080;
                          font-size:10px; font-weight:bold; }
            QPushButton:hover { color:#FF4444; }
        """)
        close_btn.clicked.connect(lambda: self._on_camera_expand())
        tabs.tabBar().setTabButton(idx, QTabBar.ButtonPosition.RightSide, close_btn)

    def _find_parent_tabs(self):
        from PyQt6.QtWidgets import QTabWidget as _QTW
        w = self.parent()
        while w is not None:
            if isinstance(w, _QTW):
                return w
            w = w.parent()
        return None

    def _build_expanded_camera_tab(self, tabs) -> QWidget:
        tab = QWidget()
        tab._exp_thread   = None
        tab._cam_running  = False
        tab._fps_count    = 0
        tab._frames_total = 0
        tab._tabs_ref     = tabs

        root = QHBoxLayout(tab)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Video area ──
        video_col = QWidget()
        video_col.setStyleSheet("background:#000;")
        video_vl = QVBoxLayout(video_col)
        video_vl.setContentsMargins(0, 0, 0, 0)
        video_vl.setSpacing(0)

        vid_hdr = QWidget()
        vid_hdr.setFixedHeight(36)
        vid_hdr.setStyleSheet("background:#080C0F; border-bottom:1px solid #0A1520;")
        vid_hdr_l = QHBoxLayout(vid_hdr)
        vid_hdr_l.setContentsMargins(12, 0, 8, 0)

        lbl_live = QLabel("■  CAMERA  LIVE")
        lbl_live.setFont(QFont("Courier New", 10, QFont.Weight.Bold))
        lbl_live.setStyleSheet("color:#00E5FF; letter-spacing:3px;")

        tab._lbl_status = QLabel("⟳  CONNECTING...")
        tab._lbl_status.setFont(QFont("Courier New", 9))
        tab._lbl_status.setStyleSheet("color:#FFB300;")

        tab._lbl_fps = QLabel("FPS: --")
        tab._lbl_fps.setFont(QFont("Courier New", 9))
        tab._lbl_fps.setStyleSheet("color:#2A4050;")

        tab._btn_play = QPushButton("■  STOP")
        tab._btn_play.setFont(QFont("Courier New", 9, QFont.Weight.Bold))
        tab._btn_play.setFixedHeight(24)
        tab._btn_play.setMinimumWidth(80)
        tab._btn_play.setStyleSheet("""
            QPushButton { background:#2A0A0A; border:1px solid #FF4444;
                          color:#FF4444; font-family:'Courier New'; font-size:9px;
                          border-radius:2px; padding:0 8px; }
            QPushButton:hover { background:#3A1010; }
        """)
        tab._btn_play.clicked.connect(lambda: self._toggle_expanded_stream(tab))

        btn_close_tab = QPushButton("✕  CLOSE TAB")
        btn_close_tab.setFont(QFont("Courier New", 9))
        btn_close_tab.setFixedHeight(24)
        btn_close_tab.setStyleSheet("""
            QPushButton { background:#111820; border:1px solid #1E2D3D;
                          color:#607080; font-family:'Courier New'; font-size:9px;
                          border-radius:2px; padding:0 8px; }
            QPushButton:hover { border-color:#FF4444; color:#FF4444; }
        """)
        btn_close_tab.clicked.connect(lambda: self._on_camera_expand())

        vid_hdr_l.addWidget(lbl_live)
        vid_hdr_l.addSpacing(16)
        vid_hdr_l.addWidget(tab._lbl_status)
        vid_hdr_l.addSpacing(16)
        vid_hdr_l.addWidget(tab._lbl_fps)
        vid_hdr_l.addStretch()
        vid_hdr_l.addWidget(tab._btn_play)
        vid_hdr_l.addSpacing(6)
        vid_hdr_l.addWidget(btn_close_tab)
        video_vl.addWidget(vid_hdr)

        tab._video = QLabel()
        tab._video.setAlignment(Qt.AlignmentFlag.AlignCenter)
        tab._video.setStyleSheet("background:#000;")
        video_vl.addWidget(tab._video, 1)
        root.addWidget(video_col, 3)

        # ── Sidebar ──
        sidebar = QWidget()
        sidebar.setFixedWidth(400)
        sidebar.setStyleSheet("background:#080C0F; border-left:1px solid #0D1520;")
        sb_l = QVBoxLayout(sidebar)
        sb_l.setContentsMargins(0, 0, 0, 0)
        sb_l.setSpacing(0)

        # Print Progress block
        prog_block = QWidget()
        prog_block.setStyleSheet("background:#080C0F;")
        pb_l = QVBoxLayout(prog_block)
        pb_l.setContentsMargins(12, 12, 12, 8)
        pb_l.setSpacing(10)

        lbl_prog_hdr = QLabel("PRINT  PROGRESS")
        lbl_prog_hdr.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        lbl_prog_hdr.setStyleSheet("color:#1E3550; letter-spacing:2px;")
        pb_l.addWidget(lbl_prog_hdr)

        tab._pizza = _PizzaProgress(parent=sidebar)
        tab._pizza.setFixedSize(150, 150)
        pizza_row = QHBoxLayout()
        pizza_row.addStretch(); pizza_row.addWidget(tab._pizza); pizza_row.addStretch()
        pb_l.addLayout(pizza_row)

        eta_row = QHBoxLayout()
        eta_row.setSpacing(8)
        def _sb_metric(label_txt):
            col = QVBoxLayout(); col.setSpacing(1)
            l = QLabel(label_txt); l.setFont(QFont("Courier New", 7))
            l.setStyleSheet("color:#1E3550; letter-spacing:1px;")
            v = QLabel("--"); v.setFont(QFont("Courier New", 11, QFont.Weight.Bold))
            v.setStyleSheet("color:#607080;")
            col.addWidget(l); col.addWidget(v)
            return col, v

        c1, tab._lbl_eta     = _sb_metric("ETA")
        c2, tab._lbl_elapsed = _sb_metric("ELAPSED")
        c3, tab._lbl_layer   = _sb_metric("LAYER")
        for c in (c1, c2, c3):
            eta_row.addLayout(c)
        pb_l.addLayout(eta_row)

        sep0 = QFrame(); sep0.setFrameShape(QFrame.Shape.HLine)
        sep0.setStyleSheet("color:#0D1520; margin:4px 0;"); pb_l.addWidget(sep0)
        sb_l.addWidget(prog_block)

        # Temperatures block
        temp_block = QWidget()
        temp_block.setStyleSheet("background:#080C0F;")
        tb_l = QVBoxLayout(temp_block)
        tb_l.setSpacing(2)
        lbl_temp_hdr = QLabel("TEMPERATURES")
        lbl_temp_hdr.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        lbl_temp_hdr.setStyleSheet("color:#1E3550; letter-spacing:2px;")
        tb_l.addWidget(lbl_temp_hdr)

        tab._tw_bed = _TempGauge("BED", accent="#FF6E40", max_temp=120, parent=sidebar)
        tab._tw_bed.setFixedHeight(70)
        tab._tw_noz = _TempGauge("NOZZLE", accent="#00E5FF", max_temp=300, parent=sidebar)
        tab._tw_noz.setFixedHeight(70)
        tb_l.addWidget(tab._tw_bed)
        tb_l.addWidget(tab._tw_noz)

        def _quick_temp_row(label, cmd_set, cmd_off, default, max_t):
            row = QHBoxLayout(); row.setSpacing(4)
            lbl = QLabel(label); lbl.setFont(QFont("Courier New", 8))
            lbl.setStyleSheet("color:#2A4050;"); lbl.setFixedWidth(52)
            from PyQt6.QtWidgets import QSpinBox as _QSB
            sp = _QSB(); sp.setRange(0, max_t); sp.setValue(default)
            sp.setFont(QFont("Courier New", 9)); sp.setFixedHeight(26)
            sp.setStyleSheet("""
                QSpinBox { background:#0D1520; border:1px solid #1A2535;
                           color:#C8D0D8; border-radius:2px; padding:2px 4px; }
                QSpinBox:focus { border-color:#00E5FF; }
                QSpinBox::up-button, QSpinBox::down-button { width:0; border:none; }
            """)
            btn_set = QPushButton("SET"); btn_set.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
            btn_set.setFixedHeight(26); btn_set.setFixedWidth(40)
            btn_set.setStyleSheet("""
                QPushButton { background:#003D52; border:1px solid #00E5FF;
                              color:#00E5FF; border-radius:2px; font-size:8px; }
                QPushButton:hover { background:#005070; }
            """)
            btn_off = QPushButton("OFF"); btn_off.setFont(QFont("Courier New", 8))
            btn_off.setFixedHeight(26); btn_off.setFixedWidth(34)
            btn_off.setStyleSheet("""
                QPushButton { background:#2A0A0A; border:1px solid #FF4444;
                              color:#FF4444; border-radius:2px; font-size:8px; }
                QPushButton:hover { background:#3A1010; }
            """)
            # Determine cache key from command name
            cache_key = "bed_target" if "bed" in cmd_set else "noz_target"
            ts_key    = "_user_bed_target_ts"  if "bed" in cmd_set else "_user_noz_target_ts"
            val_key   = "_user_bed_target_val" if "bed" in cmd_set else "_user_noz_target_val"

            def _do_set():
                import time
                v = sp.value()
                self.command_ready.emit(cmd_set, v)
                # Stamp user-set time so update_temperatures won't overwrite for 8s
                setattr(self, ts_key,  time.monotonic())
                setattr(self, val_key, v)
                self._last_print_data[cache_key] = v
                # Update gauge directly if tab is open
                if "bed" in cmd_set and hasattr(tab, "_tw_bed"):
                    tab._tw_bed.set_temps(
                        self._last_print_data.get("bed_actual", 0), v)
                elif hasattr(tab, "_tw_noz"):
                    tab._tw_noz.set_temps(
                        self._last_print_data.get("noz_actual", 0), v)

            def _do_off():
                import time
                self.command_ready.emit(cmd_off, 0)
                # OFF is intentional — clear protection and set target to 0
                setattr(self, ts_key,  0)
                setattr(self, val_key, None)
                self._last_print_data[cache_key] = 0
                if "bed" in cmd_off and hasattr(tab, "_tw_bed"):
                    tab._tw_bed.set_temps(
                        self._last_print_data.get("bed_actual", 0), 0)
                elif hasattr(tab, "_tw_noz"):
                    tab._tw_noz.set_temps(
                        self._last_print_data.get("noz_actual", 0), 0)

            btn_set.clicked.connect(_do_set)
            btn_off.clicked.connect(_do_off)
            row.addWidget(lbl); row.addWidget(sp, 1)
            row.addWidget(btn_set); row.addWidget(btn_off)
            return row

        tb_l.addLayout(_quick_temp_row("BED", "set_bed_temp", "bed_off", 60, 120))
        tb_l.addLayout(_quick_temp_row("NOZZLE", "set_hotend0_temp", "hotend0_off", 210, 300))
        sep1 = QFrame(); sep1.setFrameShape(QFrame.Shape.HLine)
        sep1.setStyleSheet("color:#0D1520; margin:4px 0;"); tb_l.addWidget(sep1)
        sb_l.addWidget(temp_block)

        # Fans block
        fan_block = QWidget()
        fan_block.setStyleSheet("background:#080C0F;")
        fb_l = QVBoxLayout(fan_block)
        fb_l.setContentsMargins(12, 6, 12, 6); fb_l.setSpacing(6)
        lbl_fan_hdr = QLabel("FANS")
        lbl_fan_hdr.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        lbl_fan_hdr.setStyleSheet("color:#1E3550; letter-spacing:2px;")
        fb_l.addWidget(lbl_fan_hdr)

        # Store fan slider + label refs so _refresh_expanded_print_data can update them
        tab._exp_fan_sliders: dict = {}
        tab._exp_fan_labels:  dict = {}

        def _fan_mini(label, cmd, key):
            row = QHBoxLayout(); row.setSpacing(6)
            lbl = QLabel(label); lbl.setFont(QFont("Courier New", 8))
            lbl.setStyleSheet("color:#2A4050;"); lbl.setFixedWidth(56)
            sl = QSlider(Qt.Orientation.Horizontal)
            sl.setRange(0, 100); sl.setValue(0); sl.setFixedHeight(18)
            val_lbl = QLabel("  0%"); val_lbl.setFont(QFont("Courier New", 8))
            val_lbl.setStyleSheet("color:#00E5FF;"); val_lbl.setFixedWidth(32)
            sl.valueChanged.connect(
                lambda v, l=val_lbl, c=cmd: (
                    l.setText(f"{v:3d}%"),
                    self.command_ready.emit(c, v)
                )
            )
            row.addWidget(lbl); row.addWidget(sl, 1); row.addWidget(val_lbl)
            # Register in tab dicts for later refresh
            tab._exp_fan_sliders[key] = sl
            tab._exp_fan_labels[key]  = val_lbl
            return row

        fb_l.addLayout(_fan_mini("PART", "fan_part",    "fan_speed_pct"))
        fb_l.addLayout(_fan_mini("AUX",  "fan_aux",     "aux_fan_speed_pct"))
        fb_l.addLayout(_fan_mini("BOX",  "fan_chamber", "box_fan_level"))
        sep2 = QFrame(); sep2.setFrameShape(QFrame.Shape.HLine)
        sep2.setStyleSheet("color:#0D1520; margin:4px 0;"); fb_l.addWidget(sep2)
        sb_l.addWidget(fan_block)

        # Log block
        log_block = QWidget()
        log_block.setStyleSheet("background:#080C0F;")
        lb_l = QVBoxLayout(log_block)
        lb_l.setContentsMargins(12, 6, 12, 6); lb_l.setSpacing(4)
        log_hdr = QHBoxLayout()
        lbl_log_hdr = QLabel("STREAM  &  PRINT  LOG")
        lbl_log_hdr.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        lbl_log_hdr.setStyleSheet("color:#1E3550; letter-spacing:2px;")
        btn_clr = QPushButton("clear")
        btn_clr.setStyleSheet(
            "QPushButton{background:transparent;border:none;"
            "color:#1A2535;font-size:8px;font-family:'Courier New';}"
            "QPushButton:hover{color:#607080;}"
        )
        btn_clr.setFixedHeight(16)
        log_hdr.addWidget(lbl_log_hdr); log_hdr.addStretch(); log_hdr.addWidget(btn_clr)
        lb_l.addLayout(log_hdr)

        tab._log = QTextEdit()
        tab._log.setReadOnly(True)
        tab._log.setFont(QFont("Courier New", 8))
        tab._log.setStyleSheet(
            "QTextEdit{background:#050810;color:#2A4560;border:none;padding:4px;}"
        )
        btn_clr.clicked.connect(tab._log.clear)
        lb_l.addWidget(tab._log, 1)
        sb_l.addWidget(log_block, 1)
        root.addWidget(sidebar)

        # FPS timer
        tab._fps_timer = QTimer(tab)
        tab._fps_timer.setInterval(1000)
        tab._fps_timer.timeout.connect(
            lambda: (tab._lbl_fps.setText(f"FPS: {tab._fps_count}"),
                     setattr(tab, "_fps_count", 0))
        )
        tab._fps_timer.start()

        tab._print_update_timer = QTimer(tab)
        tab._print_update_timer.setInterval(2000)
        tab._print_update_timer.timeout.connect(
            lambda: self._refresh_expanded_print_data(tab)
        )
        tab._print_update_timer.start()

        return tab

    def _toggle_expanded_stream(self, tab: QWidget):
        if tab._cam_running:
            if hasattr(tab, "_exp_thread") and tab._exp_thread:
                t = tab._exp_thread
                tab._exp_thread = None
                try:
                    t.change_pixmap_signal.disconnect()
                    t.error_signal.disconnect()
                    t.log_signal.disconnect()
                except Exception:
                    pass
                t.stop()
                t.finished.connect(t.deleteLater)
            tab._cam_running = False
            tab._lbl_status.setText("■  STOPPED")
            tab._lbl_status.setStyleSheet("color:#607080; font-family:'Courier New'; font-size:9px;")
            tab._btn_play.setText("▶  START")
            tab._btn_play.setStyleSheet("""
                QPushButton { background:#003D52; border:1px solid #00E5FF;
                              color:#00E5FF; font-family:'Courier New'; font-size:9px;
                              border-radius:2px; padding:0 8px; }
                QPushButton:hover { background:#005070; }
            """)
            tab._video.clear()
            tab._video.setText("■  STREAM STOPPED")
            tab._video.setFont(QFont("Courier New", 11))
        else:
            self._start_expanded_stream(tab)
            tab._btn_play.setText("■  STOP")
            tab._btn_play.setStyleSheet("""
                QPushButton { background:#2A0A0A; border:1px solid #FF4444;
                              color:#FF4444; font-family:'Courier New'; font-size:9px;
                              border-radius:2px; padding:0 8px; }
                QPushButton:hover { background:#3A1010; }
            """)

    def _refresh_expanded_print_data(self, tab: QWidget):
        data = getattr(self, "_last_print_data", {})
        pct  = data.get("progress", 0)
        if hasattr(tab, "_pizza"):
            tab._pizza.set_value(pct)
        if hasattr(tab, "_lbl_eta"):
            tab._lbl_eta.setText(data.get("eta", "--") or "--")
        if hasattr(tab, "_lbl_elapsed"):
            tab._lbl_elapsed.setText(data.get("elapsed", "--") or "--")
        if hasattr(tab, "_lbl_layer"):
            tab._lbl_layer.setText(data.get("layer", "--") or "--")
        if hasattr(tab, "_tw_bed"):
            tab._tw_bed.set_temps(data.get("bed_actual", 0), data.get("bed_target", 0))
        if hasattr(tab, "_tw_noz"):
            tab._tw_noz.set_temps(data.get("noz_actual", 0), data.get("noz_target", 0))
        # Update fan sliders in expanded tab from cached values
        fan_map = {
            "fan_speed_pct":     "fan_speed_pct",
            "aux_fan_speed_pct": "aux_fan_speed_pct",
            "box_fan_level":     "box_fan_level",
        }
        if hasattr(tab, "_exp_fan_sliders"):
            for key in fan_map:
                if key in data and key in tab._exp_fan_sliders:
                    val = int(data[key])
                    sl  = tab._exp_fan_sliders[key]
                    sl.blockSignals(True)
                    sl.setValue(val)
                    sl.blockSignals(False)
                    if key in tab._exp_fan_labels:
                        tab._exp_fan_labels[key].setText(f"{val:3d}%")

    def _start_expanded_stream(self, tab: QWidget):
        if not self._cam_url:
            tab._lbl_status.setText("⚠  IP not configured")
            return

        thread = CameraThread(self._cam_url, display_w=1280, display_h=720)
        tab._cam_running = True

        def _on_frame(img: QImage):
            tab._fps_count += 1
            tab._frames_total = getattr(tab, "_frames_total", 0) + 1
            lw = tab._video.width(); lh = tab._video.height()
            if lw > 10 and lh > 10:
                pix = QPixmap.fromImage(img).scaled(
                    lw, lh, Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.FastTransformation)
            else:
                pix = QPixmap.fromImage(img)
            tab._video.setPixmap(pix)
            if tab._lbl_status.text() != "● LIVE":
                tab._lbl_status.setText("● LIVE")
                tab._lbl_status.setStyleSheet("color:#00FF88; font-family:'Courier New'; font-size:9px;")

        def _on_error(msg: str):
            tab._lbl_status.setText(f"⚠  {msg[:60]}")
            tab._lbl_status.setStyleSheet("color:#FF4444; font-family:'Courier New'; font-size:9px;")

        def _on_log(msg: str):
            tab._log.append(f'<span style="color:#1A3050">{msg}</span>')
            tab._log.verticalScrollBar().setValue(tab._log.verticalScrollBar().maximum())

        thread.change_pixmap_signal.connect(_on_frame)
        thread.error_signal.connect(_on_error)
        thread.log_signal.connect(_on_log)
        tab._exp_thread = thread
        self.command_ready.emit("camera_start", None)
        thread.start()

    # ── Jog panel ──
    def _build_jog(self) -> QGroupBox:
        grp = QGroupBox("AXIS  MOVE")
        layout = QVBoxLayout(grp)
        layout.setSpacing(4)
        layout.setContentsMargins(10, 20, 10, 10)

        step_row = QHBoxLayout()
        step_row.setSpacing(3)
        lbl_step = QLabel("STEP")
        lbl_step.setFont(QFont("Courier New", 9))
        lbl_step.setStyleSheet("color: #607080;")
        step_row.addWidget(lbl_step)
        for step in [0.1, 1, 10, 50]:
            lbl = "0.1" if step == 0.1 else str(int(step))
            btn = QPushButton(lbl)
            btn.setFont(QFont("Courier New", 9, QFont.Weight.Bold))
            btn.setMinimumSize(32, 22)
            btn.setMaximumWidth(44)
            btn.setCheckable(True)
            btn.clicked.connect(lambda _, s=step: self._select_step(s))
            self._step_btns[step] = btn
            step_row.addWidget(btn)
        self._step_btns[10].setChecked(True)
        layout.addLayout(step_row)

        def jog_btn(text, axis, direction):
            b = QPushButton(text)
            b.setFont(QFont("Courier New", 9, QFont.Weight.Bold))
            b.setMinimumSize(42, 34)
            b.clicked.connect(lambda: self.command_ready.emit(
                "jog", {"axis": axis, "distance": direction * self._current_step}))
            return b

        def home_btn(text, cmd):
            b = QPushButton(text)
            b.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
            b.setMinimumSize(42, 34)
            b.setObjectName("primary")
            b.clicked.connect(lambda: self.command_ready.emit(cmd, None))
            self._home_btns.append(b)
            return b

        grid = QGridLayout()
        grid.setSpacing(2)
        self._jog_btns = []

        def tracked_jog_btn(text, axis, direction):
            b = jog_btn(text, axis, direction)
            self._jog_btns.append(b)
            return b

        grid.addWidget(tracked_jog_btn("Y+", "Y", -1),   0, 1)
        grid.addWidget(tracked_jog_btn("X-", "X", -1),   1, 0)
        grid.addWidget(home_btn("HOME\nALL", "home_all"), 1, 1)
        grid.addWidget(tracked_jog_btn("X+", "X", 1),    1, 2)
        grid.addWidget(tracked_jog_btn("Y-", "Y", 1),    2, 1)
        grid.addWidget(tracked_jog_btn("Z+", "Z", 1),    0, 3)
        grid.addWidget(home_btn("HOME\nZ",  "home_z"),    1, 3)
        grid.addWidget(tracked_jog_btn("Z-", "Z", -1),   2, 3)
        layout.addLayout(grid)

        btn_hxy = home_btn("HOME  XY", "home_xy")
        btn_hxy.setMinimumHeight(26)
        layout.addWidget(btn_hxy)

        self._lbl_motors_off = QLabel("⚡ Motores em repouso — pressione HOME ALL para reativar")
        self._lbl_motors_off.setFont(QFont("Courier New", 8))
        self._lbl_motors_off.setStyleSheet(
            "color:#FFB300; background:#1A1000; border:1px solid #3A2800;"
            "padding:4px 8px; border-radius:3px;"
        )
        self._lbl_motors_off.setWordWrap(True)
        self._lbl_motors_off.setVisible(False)
        layout.addWidget(self._lbl_motors_off)

        self._lbl_jog_warn = QLabel("⚠ Operate in front of printer.  Watch nozzle/bed.")
        self._lbl_jog_warn.setFont(QFont("Courier New", 8))
        self._lbl_jog_warn.setStyleSheet("color: #FF8C00;")
        self._lbl_jog_warn.setWordWrap(True)
        layout.addWidget(self._lbl_jog_warn)
        layout.addStretch()
        return grp

    # ── ACE Pro panel ──
    def _build_ace_pro(self) -> QGroupBox:
        grp = QGroupBox("ACE  PRO  —  FILAMENT  MANAGEMENT")
        layout = QVBoxLayout(grp)
        layout.setSpacing(8)
        layout.setContentsMargins(12, 0, 12, 0)

        circles_row = QHBoxLayout()
        circles_row.setSpacing(8)
        circles_row.setAlignment(Qt.AlignmentFlag.AlignLeft)

        slots = self._settings.get("slots", [
            {"paint_index": 0, "paint_color": [255, 255, 255], "material_type": "PLA"},
            {"paint_index": 1, "paint_color": [40,  40,  40 ], "material_type": "PLA"},
            {"paint_index": 2, "paint_color": [255, 0,   0  ], "material_type": "PLA"},
            {"paint_index": 3, "paint_color": [0,   0,   255], "material_type": "PLA"},
        ])

        self._filament_circles = []
        for i, slot in enumerate(slots):
            circle = FilamentCircle(
                i,
                slot.get("paint_color", [255, 255, 255]),
                slot.get("material_type", "PLA"),
                active=(i == 0)
            )
            circle.clicked_signal.connect(self._on_slot_clicked)
            circles_row.addWidget(circle)
            self._filament_circles.append(circle)

        self._slot_display = SlotDisplay()
        self._slot_display.set_select(0)
        circles_row.addStretch()
        circles_row.addWidget(self._slot_display)
        layout.addLayout(circles_row)

        extrude_row = QHBoxLayout()
        extrude_row.setSpacing(10)
        extrude_row.setContentsMargins(0, 4, 0, 0)
        self._ace_current_dist = 10

        btn_extrude = QPushButton("▶  EXTRUDE")
        btn_extrude.setFont(QFont("Courier New", 10, QFont.Weight.Bold))
        btn_extrude.setMinimumHeight(30); btn_extrude.setMinimumWidth(130)
        btn_extrude.clicked.connect(lambda: self.command_ready.emit(
            "ace_extrude", {"slot": self._active_slot, "distance": self._ace_current_dist}))

        btn_retract = QPushButton("◀  RETRACT")
        btn_retract.setFont(QFont("Courier New", 10, QFont.Weight.Bold))
        btn_retract.setMinimumHeight(30); btn_retract.setMinimumWidth(130)
        btn_retract.clicked.connect(lambda: self.command_ready.emit(
            "ace_retract", {"slot": self._active_slot, "distance": self._ace_current_dist}))

        extrude_row.addStretch()
        extrude_row.addWidget(btn_extrude); extrude_row.addWidget(btn_retract)
        extrude_row.addStretch()
        layout.addLayout(extrude_row)

        sep = QFrame(); sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color: #1A2535;"); layout.addWidget(sep)

        env_row = QHBoxLayout()
        self._lbl_ace_temp = QLabel("TEMP:  --")
        self._lbl_ace_temp.setFont(QFont("Courier New", 11))
        self._lbl_ace_temp.setStyleSheet("color: #FFB300;")
        self._lbl_ace_hum = QLabel("HUMIDITY:  --")
        self._lbl_ace_hum.setFont(QFont("Courier New", 11))
        self._lbl_ace_hum.setStyleSheet("color: #607080;")
        env_row.addWidget(self._lbl_ace_temp)
        env_row.addSpacing(20)
        env_row.addWidget(self._lbl_ace_hum)
        env_row.addStretch()
        layout.addLayout(env_row)

        sep2 = QFrame(); sep2.setFrameShape(QFrame.Shape.HLine)
        sep2.setStyleSheet("color: #1A2535;"); layout.addWidget(sep2)

        drying_grp_lbl = QLabel("DRYING")
        drying_grp_lbl.setFont(QFont("Courier New", 10, QFont.Weight.Bold))
        drying_grp_lbl.setStyleSheet("color: #607080; letter-spacing: 2px;")
        layout.addWidget(drying_grp_lbl)

        drying_params_row = QHBoxLayout()
        drying_params_row.setSpacing(12)
        lbl_dry_temp = QLabel("TEMP")
        lbl_dry_temp.setFont(QFont("Courier New", 10))
        lbl_dry_temp.setStyleSheet("color: #607080;")
        from PyQt6.QtWidgets import QSpinBox
        self._sp_dry_temp = QSpinBox()
        self._sp_dry_temp.setRange(30, 55); self._sp_dry_temp.setValue(45)
        self._sp_dry_temp.setSuffix(" C"); self._sp_dry_temp.setFont(QFont("Courier New", 10))
        self._sp_dry_temp.setMinimumWidth(72)

        lbl_dry_dur = QLabel("HOURS")
        lbl_dry_dur.setFont(QFont("Courier New", 10))
        lbl_dry_dur.setStyleSheet("color: #607080;")
        self._sp_dry_hours = QSpinBox()
        self._sp_dry_hours.setRange(1, 48); self._sp_dry_hours.setValue(4)
        self._sp_dry_hours.setSuffix(" h"); self._sp_dry_hours.setFont(QFont("Courier New", 10))
        self._sp_dry_hours.setMinimumWidth(72)

        drying_params_row.addWidget(lbl_dry_temp); drying_params_row.addWidget(self._sp_dry_temp)
        drying_params_row.addSpacing(8)
        drying_params_row.addWidget(lbl_dry_dur); drying_params_row.addWidget(self._sp_dry_hours)
        drying_params_row.addStretch()
        layout.addLayout(drying_params_row)

        options_row = QHBoxLayout()
        options_row.setSpacing(0); options_row.setContentsMargins(0, 0, 0, 0)

        self._btn_auto_refill = QPushButton("AUTO  REFILL:  OFF")
        self._btn_auto_refill.setFont(QFont("Courier New", 10))
        self._btn_auto_refill.setMinimumHeight(34); self._btn_auto_refill.setCheckable(True)
        self._btn_auto_refill.setChecked(False)
        def _toggle_refill(v):
            self._btn_auto_refill.setText("AUTO  REFILL:  ON" if v else "AUTO  REFILL:  OFF")
            self.command_ready.emit("ace_auto_refill", v)
        self._btn_auto_refill.toggled.connect(_toggle_refill)

        self._btn_drying = QPushButton("ENABLE  DRYING:  OFF")
        self._btn_drying.setFont(QFont("Courier New", 10))
        self._btn_drying.setMinimumHeight(34); self._btn_drying.setCheckable(True)
        self._btn_drying.setChecked(False)
        def _toggle_drying(v):
            self._btn_drying.setText("ENABLE  DRYING:  ON" if v else "ENABLE  DRYING:  OFF")
            if v:
                self.command_ready.emit("ace_drying", {
                    "enabled": True, "temp": self._sp_dry_temp.value(),
                    "hours": self._sp_dry_hours.value(),
                })
            else:
                self.command_ready.emit("ace_drying", {"enabled": False})
        self._btn_drying.toggled.connect(_toggle_drying)

        options_row.addWidget(self._btn_auto_refill, 1)
        options_row.addSpacing(8)
        options_row.addWidget(self._btn_drying, 1)
        layout.addLayout(options_row)

        self._active_slot = 0
        return grp

    def _on_slot_clicked(self, idx: int):
        self._active_slot = idx
        for i, circle in enumerate(self._filament_circles):
            circle.set_selected(i == idx)
        if hasattr(self, "_slot_display"):
            self._slot_display.set_select(idx)

    # ── Controls panel ──
    def _build_controls(self) -> QGroupBox:
        grp = QGroupBox("CONTROLS")
        layout = QVBoxLayout(grp)
        layout.setSpacing(6)
        layout.setContentsMargins(10, 5, 10, 5)

        from PyQt6.QtWidgets import QComboBox

        btn_estop = QPushButton("⚠️ STOP")
        btn_estop.setFont(QFont("Courier New", 10, QFont.Weight.Bold))
        btn_estop.setMinimumHeight(34); btn_estop.setObjectName("danger")
        btn_estop.clicked.connect(lambda: self.command_ready.emit("emergency_stop", None))
        layout.addWidget(btn_estop)

        sep0 = QFrame(); sep0.setFrameShape(QFrame.Shape.HLine)
        sep0.setStyleSheet("color: #1A2535;"); layout.addWidget(sep0)

        lbl_speed = QLabel("SPEED")
        lbl_speed.setFont(QFont("Courier New", 9))
        lbl_speed.setStyleSheet("color: #607080; letter-spacing: 2px;")
        layout.addWidget(lbl_speed)

        self._cmb_speed = QComboBox()
        self._cmb_speed.setFont(QFont("Courier New", 10))
        self._cmb_speed.addItems(["Quiet (1)", "Standard (2)", "Sport (3)"])
        self._cmb_speed.setCurrentIndex(1)
        self._cmb_speed.currentIndexChanged.connect(
            lambda idx: self.command_ready.emit("set_speed", idx + 1)
        )
        layout.addWidget(self._cmb_speed)

        sep1 = QFrame(); sep1.setFrameShape(QFrame.Shape.HLine)
        sep1.setStyleSheet("color: #1A2535;"); layout.addWidget(sep1)

        self._btn_light = QPushButton("LIGHT  ON")
        self._btn_light.setFont(QFont("Courier New", 10, QFont.Weight.Bold))
        self._btn_light.setMinimumHeight(30); self._btn_light.setCheckable(True)
        self._btn_light.setChecked(False)
        self._light_state = False
        def _toggle_light():
            self._light_state = not self._light_state
            self._btn_light.setText("LIGHT  OFF" if self._light_state else "LIGHT  ON")
            self._btn_light.setStyleSheet(
                "background: #004C60; color: #00E5FF;" if self._light_state else ""
            )
            self.command_ready.emit("light", self._light_state)
        self._btn_light.clicked.connect(_toggle_light)
        layout.addWidget(self._btn_light)

        self._btn_motors_off = QPushButton("MOTORS  OFF")
        self._btn_motors_off.setFont(QFont("Courier New", 10, QFont.Weight.Bold))
        self._btn_motors_off.setMinimumHeight(30)
        self._btn_motors_off.clicked.connect(lambda: self.command_ready.emit("motors_off", None))
        layout.addWidget(self._btn_motors_off)

        sep2 = QFrame(); sep2.setFrameShape(QFrame.Shape.HLine)
        sep2.setStyleSheet("color: #1A2535;"); layout.addWidget(sep2)

        lbl_fans = QLabel("FANS")
        lbl_fans.setFont(QFont("Courier New", 9))
        lbl_fans.setStyleSheet("color: #607080; letter-spacing: 2px;")
        layout.addWidget(lbl_fans)

        fan_defs = [
            ("PART",    "fan_part",    "fan_speed_pct"),
            ("AUX",     "fan_aux",     "aux_fan_speed_pct"),
            ("CHAMBER", "fan_chamber", "box_fan_level"),
        ]
        for lbl_txt, cmd, key in fan_defs:
            fan_row = QHBoxLayout()
            fan_row.setSpacing(4)
            lbl = QLabel(lbl_txt); lbl.setFont(QFont("Courier New", 9))
            lbl.setStyleSheet("color: #607080;"); lbl.setFixedWidth(52)
            slider = QSlider(Qt.Orientation.Horizontal)
            slider.setRange(0, 100); slider.setValue(0)
            lbl_val = QLabel("  0%"); lbl_val.setFont(QFont("Courier New", 9))
            lbl_val.setStyleSheet("color: #00E5FF;"); lbl_val.setFixedWidth(32)
            slider.valueChanged.connect(
                lambda v, l=lbl_val, c=cmd: (
                    l.setText(f"{v:3d}%"),
                    self.command_ready.emit(c, v)
                )
            )
            fan_row.addWidget(lbl); fan_row.addWidget(slider, 1); fan_row.addWidget(lbl_val)
            layout.addLayout(fan_row)
            self._fan_sliders[key] = slider
            self._fan_labels[key]  = lbl_val

        layout.addStretch()
        return grp

    # ── Helpers ──
    def _select_step(self, step: float):
        self._current_step = step
        for s, btn in self._step_btns.items():
            btn.setChecked(s == step)

    def _set_home_btns_enabled(self, enabled: bool):
        """
        Enable/disable HOME buttons.
        Disabled = gray (not blue), so user knows they're inactive.
        """
        for btn in getattr(self, "_home_btns", []):
            btn.setEnabled(enabled)
            if enabled:
                # Restore primary styling via objectName
                btn.setStyleSheet(self._SS_HOME_ENABLED)
                btn.style().polish(btn)
            else:
                # Gray — override primary objectName styling
                btn.setStyleSheet(self._SS_HOME_DISABLED)

    def update_temperatures(self, data: dict):
        import time
        now = time.monotonic()

        if "bed_actual" in data:
            self._temp_bed.update_actual(data["bed_actual"])
            self._lbl_bed_info.setText(f"{data['bed_actual']:.0f} C")
            self._last_print_data["bed_actual"] = data["bed_actual"]

        if "bed_target" in data:
            new_t = data["bed_target"]
            # Protect: if user set a target recently (within 8s), don't let MQTT overwrite it
            # with 0 or a lower value — the printer may not have received the command yet
            user_set_ts = getattr(self, "_user_bed_target_ts", 0)
            user_set_val = getattr(self, "_user_bed_target_val", None)
            if user_set_val is not None and (now - user_set_ts) < 8.0:
                # Keep user-set value until printer confirms it or timeout expires
                if new_t == 0 or (user_set_val > 0 and new_t < user_set_val * 0.5):
                    new_t = user_set_val  # printer hasn't acked yet, keep user value
                else:
                    self._user_bed_target_val = None  # printer confirmed
            self._last_print_data["bed_target"] = new_t

        if "hotend0_actual" in data:
            self._temp_e0.update_actual(data["hotend0_actual"])
            self._lbl_noz_info.setText(f"{data['hotend0_actual']:.0f} C")
            self._last_print_data["noz_actual"] = data["hotend0_actual"]

        if "hotend0_target" in data:
            new_t = data["hotend0_target"]
            user_set_ts = getattr(self, "_user_noz_target_ts", 0)
            user_set_val = getattr(self, "_user_noz_target_val", None)
            if user_set_val is not None and (now - user_set_ts) < 8.0:
                if new_t == 0 or (user_set_val > 0 and new_t < user_set_val * 0.5):
                    new_t = user_set_val
                else:
                    self._user_noz_target_val = None
            self._last_print_data["noz_target"] = new_t

        if "hotend1_actual" in data:
            self._temp_e1.update_actual(data["hotend1_actual"])

    def update_printer_info(self, data: dict):
        if "status" in data:
            raw = data["status"].lower()

            _IDLE_STATES = {
                "ready", "idle", "free", "standby", "connected",
                "stoped", "stopped", "stop", "finish", "complete", "finished",
            }
            _BUSY_STATES = {
                "printing", "busy", "paused",
                "auto_leveling", "leveling", "homing",
                "warming_up", "preheat", "preheating",
                "uploading", "preparing", "calibrating",
            }

            if raw in _IDLE_STATES:
                st, color = "IDLE", "#00FF88"
                self._is_printing = False
                self._set_home_btns_enabled(True)
                self.set_motors_enabled(True)
            elif raw in _BUSY_STATES:
                st, color = raw.upper(), "#FFB300"
                self._is_printing = True
                self._set_home_btns_enabled(False)
                self.set_motors_enabled(False)
            elif raw in ("error",):
                st, color = "ERROR", "#FF4444"
                self._is_printing = False
                self._set_home_btns_enabled(True)
                self.set_motors_enabled(True)
            elif raw in ("disconnected", "offline"):
                st, color = "OFFLINE", "#FF4444"
                self._is_printing = False
                self._set_home_btns_enabled(False)
                self.set_motors_enabled(False)
            else:
                # Unknown/intermediate state — treat as busy to prevent accidental motor kill
                st, color = raw.upper() or "BUSY", "#FFB300"
                self._is_printing = True
                self._set_home_btns_enabled(False)
                self.set_motors_enabled(False)

            # MOTORS OFF button — disabled during printing to prevent accidental motor kill
            if hasattr(self, "_btn_motors_off"):
                self._btn_motors_off.setEnabled(not self._is_printing)
                self._btn_motors_off.setStyleSheet(
                    "QPushButton { background-color:#0D0F11; border:1px solid #1A2535; "
                    "color:#2A3540; border-radius:2px; }"
                    if self._is_printing else ""
                )
            # Jog safety warning — only relevant when NOT printing (idle, motors deactivated)
            if hasattr(self, "_lbl_jog_warn"):
                self._lbl_jog_warn.setVisible(not self._is_printing)
            self._lbl_status_badge.setText(st)
            self._lbl_status_badge.setStyleSheet(
                f"color:{color}; background:#0D0F11; border:1px solid {color};"
                f"padding:2px 8px; letter-spacing:2px; font-family:'Courier New';"
            )
        if "firmware" in data and data["firmware"]:
            self._lbl_firmware.setText(data["firmware"])
        if "ip" in data and data["ip"]:
            self._lbl_ip.setText(data["ip"])
        if "cn" in data and data["cn"]:
            self._lbl_cn.setText(data["cn"])
        if "print_speed_mode" in data and hasattr(self, "_cmb_speed"):
            mode = int(data["print_speed_mode"]) - 1
            self._cmb_speed.blockSignals(True)
            self._cmb_speed.setCurrentIndex(max(0, min(3, mode)))
            self._cmb_speed.blockSignals(False)

    def update_print_progress(self, data: dict):
        for k in ("progress", "eta", "elapsed", "layer", "phase"):
            if k in data:
                self._last_print_data[k] = data[k]

    def update_ace_env(self, temp: float, humidity: float):
        self._lbl_ace_temp.setText(f"TEMP:  {temp:.0f} C")
        self._lbl_ace_hum.setText(f"HUMIDITY:  {humidity:.0f}%")

    def update_fans(self, data: dict):
        for key in ("fan_speed_pct", "aux_fan_speed_pct", "box_fan_level"):
            if key in data:
                val = int(data[key])
                # Cache for expanded tab refresh
                self._last_print_data[key] = val
                if key in self._fan_sliders:
                    sl  = self._fan_sliders[key]
                    sl.blockSignals(True); sl.setValue(val); sl.blockSignals(False)
                    self._fan_labels[key].setText(f"{val:3d}%")

    def set_motors_enabled(self, enabled: bool):
        for btn in getattr(self, "_jog_btns", []):
            btn.setEnabled(enabled)
            if enabled:
                btn.setStyleSheet("")
            else:
                btn.setStyleSheet("color:#2A4050; border:1px solid #1A2535;")
        if hasattr(self, "_lbl_motors_off"):
            # Only show "motors at rest" warning when idle (motors truly deactivated),
            # NOT when disabled because printer is actively printing
            show = not enabled and not getattr(self, "_is_printing", False)
            self._lbl_motors_off.setVisible(show)

    def set_printing_slot(self, slot_index: int):
        for circle in self._filament_circles:
            circle.set_printing(circle.slot_index == slot_index)
        self.set_loaded_slot_label(slot_index)

    def set_loaded_slot_label(self, slot_index: int):
        if not hasattr(self, "_slot_display"):
            return
        color = None
        if slot_index >= 0:
            for circle in self._filament_circles:
                if circle.slot_index == slot_index:
                    color = circle._color
                    break
        self._slot_display.set_loaded(slot_index, color)

    def refresh_slots(self, slots: list):
        slot_by_index = {s.get("index", i): s for i, s in enumerate(slots)}
        for circle in self._filament_circles:
            si = circle.slot_index
            s  = slot_by_index.get(si)
            if s:
                circle.set_color(
                    s.get("paint_color", [255, 255, 255]),
                    s.get("material_type", "PLA")
                )
                circle.set_consumables(s.get("consumables_percent", 0))
        if hasattr(self, "_slot_display") and self._slot_display._loaded_num > 0:
            idx = self._slot_display._loaded_num - 1
            for circle in self._filament_circles:
                if circle.slot_index == idx:
                    self._slot_display.set_color(circle._color)
                    break

    def sync_ace_state(self, box: dict):
        env_temp = float(box.get("temp", box.get("temperature", 0)))
        env_hum  = float(box.get("humidity", 0))
        if env_temp or env_hum:
            self.update_ace_env(env_temp, env_hum)

        dry = box.get("drying_status", {})
        if dry:
            is_drying = bool(dry.get("status", 0))
            self._btn_drying.blockSignals(True)
            self._btn_drying.setChecked(is_drying)
            self._btn_drying.setText(
                "ENABLE  DRYING:  ON" if is_drying else "ENABLE  DRYING:  OFF"
            )
            if is_drying:
                t = dry.get("target_temp", self._sp_dry_temp.value())
                d = dry.get("duration",    self._sp_dry_hours.value() * 60)
                self._sp_dry_temp.blockSignals(True)
                self._sp_dry_temp.setValue(int(t))
                self._sp_dry_temp.blockSignals(False)
                self._sp_dry_hours.blockSignals(True)
                self._sp_dry_hours.setValue(max(1, int(d) // 60))
                self._sp_dry_hours.blockSignals(False)
            self._btn_drying.blockSignals(False)

        loaded = box.get("loaded_slot")
        if loaded is not None:
            self.set_loaded_slot_label(int(loaded))

    def set_ace_connected(self, connected: bool):
        for circle in self._filament_circles:
            circle.set_ace_offline(not connected)
        if hasattr(self, "_slot_display"):
            self._slot_display.set_ace_offline(not connected)

    def set_light_state(self, status: int):
        on = (status == 1)
        self._light_state = on
        self._btn_light.setText("LIGHT  OFF" if on else "LIGHT  ON")
        self._btn_light.setStyleSheet(
            "background: #004C60; color: #00E5FF;" if on else ""
        )
        self._btn_light.blockSignals(True)
        self._btn_light.setChecked(on)
        self._btn_light.blockSignals(False)
