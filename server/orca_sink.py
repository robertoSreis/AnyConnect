# -*- coding: utf-8 -*-
"""
orca_sink.py — Servidor HTTP sumidouro para OrcaSlicer
======================================================
Dois modos:
  1) Importado pelo main_window: start_sink_server() / stop_sink_server()
  2) Standalone com systray:     python orca_sink.py  (ou orca_sink.exe)

Compilar:
  pip install pystray pillow
  pyinstaller --onefile --noconsole --icon=icon.ico orca_sink.py
"""

import sys
import os
import json
import socket
import threading
import tempfile
from http.server import BaseHTTPRequestHandler, HTTPServer


# ── Config ────────────────────────────────────────────────────────────────────
def _config_path() -> str:
    base = os.environ.get("LOCALAPPDATA", tempfile.gettempdir())
    folder = os.path.join(base, "AnyConnect")
    os.makedirs(folder, exist_ok=True)
    return os.path.join(folder, "orca_sink.json")

def _load_port() -> int:
    try:
        with open(_config_path(), "r") as f:
            return int(json.load(f).get("port", 7126))
    except Exception:
        return 7126

def _save_port(port: int):
    try:
        with open(_config_path(), "w") as f:
            json.dump({"port": port}, f)
    except Exception:
        pass


# ── PID file ──────────────────────────────────────────────────────────────────
def _pid_path() -> str:
    return os.path.join(tempfile.gettempdir(), "se3d_orca_sink.pid")

def _write_pid(port: int):
    try:
        with open(_pid_path(), "w") as f:
            f.write(f"{os.getpid()}:{port}")
    except Exception:
        pass

def _clear_pid():
    try:
        os.remove(_pid_path())
    except Exception:
        pass

def is_running() -> bool:
    """True se já há instância standalone rodando."""
    try:
        with open(_pid_path(), "r") as f:
            pid_str, port_str = f.read().strip().split(":")
        pid  = int(pid_str)
        port = int(port_str)
        # Testa porta TCP — mais confiável que checar PID no Windows
        with socket.create_connection(("127.0.0.1", port), timeout=0.5):
            return True
    except Exception:
        return False


# ── HTTP Handler ──────────────────────────────────────────────────────────────
SINK_HOST = "127.0.0.1"
SINK_PORT = 7126

_server: HTTPServer | None = None
_thread: threading.Thread | None = None


class _SinkHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, format, *args):
        pass

    def _consume_body(self):
        length = int(self.headers.get("Content-Length", 0) or 0)
        if length > 0:
            self.rfile.read(length)

    def _reply(self, body: bytes, status: int = 200,
               content_type: str = "application/json"):
        self._consume_body()
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        p = self.path.split("?")[0].rstrip("/")
        if p in ("/api/version", "/api/v1/version", ""):
            body = b'{"api":"0.1","server":"1.9.0","version":"1.9.0","text":"OctoPrint 1.9.0"}'
        elif p == "/api/printer":
            body = b'{"temperature":{},"state":{"text":"Operational","flags":{"operational":true,"printing":false,"ready":true}}}'
        elif p.startswith("/api/files"):
            body = b'{"files":[],"free":1073741824}'
        elif p == "/api/job":
            body = b'{"state":"Operational","job":{"file":{"name":null}}}'
        elif p == "/api/connection":
            body = b'{"current":{"state":"Operational"},"options":{"ports":[],"baudrates":[]}}'
        elif p in ("/rr_connect", "/rr_status"):
            body = b'{"err":0}'
        else:
            body = b'{"result":"ok"}'
        self._reply(body)

    def do_POST(self):
        p = self.path.split("?")[0].rstrip("/")
        if p.startswith("/api/files"):
            self._reply(
                b'{"files":{"local":{"name":"print.gcode","origin":"local"}},"done":true}',
                status=201)
        elif p in ("/api/printer/command", "/rr_gcode"):
            self._reply(b'', status=204)
        else:
            self._reply(b'{"result":"ok"}')

    def do_PUT(self):
        self._reply(b'{"result":"ok"}')

    def do_DELETE(self):
        self._consume_body()
        self.send_response(204)
        self.send_header("Content-Length", "0")
        self.send_header("Connection", "close")
        self.end_headers()

    def do_OPTIONS(self):
        self._consume_body()
        self.send_response(204)
        self.send_header("Content-Length", "0")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.send_header("Connection", "close")
        self.end_headers()


# ── API pública (importado pelo main_window) ──────────────────────────────────
def start_sink_server(host: str = SINK_HOST, port: int = SINK_PORT) -> bool:
    global _server, _thread
    if _server is not None:
        return True
    if is_running():
        return True  # standalone já cobre
    try:
        _server = HTTPServer((host, port), _SinkHandler)
    except OSError:
        _server = None
        return False
    _thread = threading.Thread(target=_server.serve_forever, daemon=True)
    _thread.start()
    return True

def stop_sink_server():
    global _server, _thread
    if _server is not None:
        _server.shutdown()
        _server = None
    _thread = None


# ── Standalone ────────────────────────────────────────────────────────────────
def _run_standalone():
    global _server, _thread

    port = _load_port()

    # Sobe o servidor HTTP — sem fallback para porta+1 (evita confusão)
    try:
        _server = HTTPServer(("127.0.0.1", port), _SinkHandler)
    except OSError:
        # Porta ocupada — já está rodando? Sai silenciosamente
        sys.exit(0)

    _thread = threading.Thread(target=_server.serve_forever, daemon=True)
    _thread.start()
    _write_pid(port)

    # ── Systray ──────────────────────────────────────────────────────────────
    try:
        import pystray
        from PIL import Image, ImageDraw
    except ImportError:
        # Sem pystray: roda silencioso
        import time
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass
        stop_sink_server()
        _clear_pid()
        return

    # Ícone
    here = os.path.dirname(os.path.abspath(sys.argv[0]))
    icon_file = next(
        (os.path.join(here, n) for n in ["icon.ico", "icon.png"]
         if os.path.isfile(os.path.join(here, n))), None)

    if icon_file:
        try:
            img = Image.open(icon_file).resize((64, 64)).convert("RGBA")
        except Exception:
            icon_file = None

    if not icon_file:
        img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        d.ellipse([4, 4, 60, 60], fill=(0, 229, 255, 220))
        d.ellipse([18, 18, 46, 46], fill=(8, 12, 17, 255))

    # Estado mutável sem closure de variável
    state = {"port": port, "tray": None}

    def _change_port(icon, item):
        """Abre janela simples para alterar porta — sem tkinter, usa input via thread."""
        def _ask():
            try:
                import tkinter as tk
                from tkinter import simpledialog, messagebox
                root = tk.Tk()
                root.withdraw()
                root.attributes("-topmost", True)
                new_port = simpledialog.askinteger(
                    "OrcaSink — Porta",
                    f"Porta atual: {state['port']}\nNova porta (1024–65535):",
                    minvalue=1024, maxvalue=65535,
                    initialvalue=state['port'],
                )
                if new_port and new_port != state['port']:
                    _save_port(new_port)
                    messagebox.showinfo(
                        "OrcaSink",
                        f"Porta salva: {new_port}\nReinicie o OrcaSink para aplicar.",
                        parent=root,
                    )
                root.destroy()
            except Exception:
                pass
        t = threading.Thread(target=_ask, daemon=True)
        t.start()

    def _quit(icon, item):
        icon.stop()

    menu = pystray.Menu(
        pystray.MenuItem(f"OrcaSink  :{state['port']}", None, enabled=False),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Alterar porta...", _change_port),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Sair", _quit),
    )

    tray = pystray.Icon("orca_sink", img, f"OrcaSink :{state['port']}", menu)
    state["tray"] = tray
    tray.run()          # bloqueia na thread principal até _quit

    stop_sink_server()
    _clear_pid()


# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    if is_running():
        sys.exit(0)
    _run_standalone()
