# -*- coding: utf-8 -*-
"""
Camera Widget - FLV stream from Anycubic Kobra S1
Stream URL: http://<printer_ip>:18088/flv
Uses QWebEngineView with flv.js to render the stream
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QLineEdit, QFrame
)
from PyQt6.QtCore import Qt, QUrl, QTimer, pyqtSignal
from PyQt6.QtGui import QFont

try:
    from PyQt6.QtWebEngineWidgets import QWebEngineView
    WEB_ENGINE_AVAILABLE = True
except ImportError:
    WEB_ENGINE_AVAILABLE = False


CAMERA_HTML = """
<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<style>
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  body {{ background:#0D0F11; display:flex; flex-direction:column;
          align-items:center; justify-content:center; height:100vh; }}
  #container {{ position:relative; width:100%; max-width:960px; }}
  video {{ width:100%; background:#000; display:block; }}
  #status {{ color:#607080; font-family:'Courier New',monospace;
             font-size:12px; letter-spacing:2px; margin-top:10px; text-align:center; }}
  #status.ok {{ color:#00FF88; }}
  #status.err {{ color:#FF4444; }}
</style>
</head>
<body>
<div id="container">
  <video id="video" muted autoplay controls></video>
  <div id="status">INITIALIZING STREAM...</div>
</div>
<script src="https://cdn.jsdelivr.net/npm/flv.js@latest/dist/flv.min.js"></script>
<script>
  const url = "{stream_url}";
  const status = document.getElementById('status');

  if (flvjs.isSupported()) {{
    const player = flvjs.createPlayer({{
      type: 'flv',
      url: url,
      isLive: true,
    }});
    player.attachMediaElement(document.getElementById('video'));
    player.load();
    player.play();
    player.on(flvjs.Events.ERROR, (err) => {{
      status.textContent = 'STREAM ERROR: ' + err;
      status.className = 'err';
    }});
    player.on(flvjs.Events.MEDIA_INFO, () => {{
      status.textContent = '● LIVE  —  ' + url;
      status.className = 'ok';
    }});
  }} else {{
    status.textContent = 'FLV NOT SUPPORTED IN THIS BROWSER';
    status.className = 'err';
  }}
</script>
</body>
</html>
"""


class CameraWidget(QWidget):
    command_ready = pyqtSignal(str, object)   # emite "camera_start" / "camera_stop"

    def __init__(self, settings: dict, parent=None):
        super().__init__(parent)
        self._settings = settings
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        # ── Top bar: URL + controls ──
        top = QHBoxLayout()
        top.setSpacing(10)

        lbl = QLabel("STREAM  URL")
        lbl.setFont(QFont("Courier New", 11, QFont.Weight.Bold))
        lbl.setStyleSheet("color:#607080; letter-spacing:2px;")

        self._inp_url = QLineEdit()
        self._inp_url.setFont(QFont("Courier New", 12))
        self._inp_url.setPlaceholderText("http://192.168.1.100:18088/flv")
        ip = self._settings.get("printer_ip", "")
        if ip:
            self._inp_url.setText(f"http://{ip}:18088/flv")

        self._streaming = False
        self._btn_toggle = QPushButton("▶  START")
        self._btn_toggle.setObjectName("primary")
        self._btn_toggle.setFont(QFont("Courier New", 11, QFont.Weight.Bold))
        self._btn_toggle.setFixedWidth(160)
        self._btn_toggle.setCheckable(True)  # Torna o botão toggle
        self._btn_toggle.setChecked(False)   # Estado inicial: não checado (STOP)
        self._btn_toggle.clicked.connect(self._toggle_stream)

        self._dot_timer = QTimer(self)
        self._dot_timer.setInterval(500)
        self._dot_timer.timeout.connect(self._tick_dots)
        self._dot_count = 0

        top.addWidget(lbl)
        top.addWidget(self._inp_url)
        top.addWidget(self._btn_toggle)
        layout.addLayout(top)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color:#1A2535;")
        layout.addWidget(sep)

        # ── Video area ──
        if WEB_ENGINE_AVAILABLE:
            self._web = QWebEngineView()
            self._web.setStyleSheet("background:#000;")
            layout.addWidget(self._web, 1)
            self._lbl_status = QLabel("● NOT  CONNECTED  —  Enter IP and click CONNECT")
            self._lbl_status.setFont(QFont("Courier New", 11))
            self._lbl_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._lbl_status.setStyleSheet("color:#607080; letter-spacing:1px;")
            layout.addWidget(self._lbl_status)
        else:
            # Fallback if WebEngine not installed
            lbl_no_web = QLabel(
                "PyQt6-WebEngine not installed.\n\n"
                "To enable camera:\n"
                "pip install PyQt6-WebEngine\n\n"
                "Or open the stream directly in a browser:\n"
                f"http://{self._settings.get('printer_ip','<ip>')}:18088/flv"
            )
            lbl_no_web.setFont(QFont("Courier New", 12))
            lbl_no_web.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl_no_web.setStyleSheet("color:#607080; letter-spacing:1px;")
            layout.addWidget(lbl_no_web, 1)

    def _tick_dots(self):
        self._dot_count = (self._dot_count + 1) % 4
        self._lbl_status.setText("● CONECTANDO" + "." * self._dot_count)

    def _toggle_stream(self):
        if self._btn_toggle.isChecked():
            self._start_stream()
        else:
            self._stop_stream()

    def _start_stream(self):
        if not WEB_ENGINE_AVAILABLE:
            self._btn_toggle.setChecked(False)  # Reverte o estado se não for possível
            return
        url = self._inp_url.text().strip()
        if not url:
            self._btn_toggle.setChecked(False)  # Reverte se URL estiver vazia
            return
        self._streaming = True
        self._btn_toggle.setText("■  STOP")
        self._btn_toggle.setObjectName("danger")
        self._btn_toggle.setStyle(self._btn_toggle.style())
        self._dot_count = 0
        self._dot_timer.start()
        self._lbl_status.setText("● CONECTANDO...")
        self._lbl_status.setStyleSheet("color:#FFB300; letter-spacing:1px; font-size:11px;")
        self.command_ready.emit("camera_start", url)
        QTimer.singleShot(1200, lambda: self._load_stream(url))

    def _load_stream(self, url: str):
        if not WEB_ENGINE_AVAILABLE:
            return
        self._dot_timer.stop()
        html = CAMERA_HTML.format(stream_url=url)
        self._web.setHtml(html, QUrl("about:blank"))
        self._lbl_status.setText(f"● {url}")
        self._lbl_status.setStyleSheet("color:#00E5FF; letter-spacing:1px; font-size:11px;")

    def _stop_stream(self):
        if not WEB_ENGINE_AVAILABLE:
            return
        self._streaming = False
        self._dot_timer.stop()
        self._btn_toggle.setText("▶  START")
        self._btn_toggle.setObjectName("primary")
        self._btn_toggle.setStyle(self._btn_toggle.style())
        # Garante que o botão não está checado
        self._btn_toggle.setChecked(False)
        self._web.setHtml("<html><body style='background:#000'></body></html>")
        self._lbl_status.setText("● STREAM  PARADO")
        self._lbl_status.setStyleSheet("color:#607080; letter-spacing:1px; font-size:11px;")
        self.command_ready.emit("camera_stop", None)

    def update_ip(self, ip: str):
        """Called when printer IP changes in settings"""
        if ip:
            self._inp_url.setText(f"http://{ip}:18088/flv")