# -*- coding: utf-8 -*-
"""
Moonraker WebSocket + REST client for Anycubic Kobra S1 (Rinkhals)

API: ws://ip:7125/websocket  (JSON-RPC 2.0)
REST: http://ip:7125/...

Subscribed objects: heater_bed, extruder, print_stats, display_status,
                    toolhead, fan, output_pin, virtual_sdcard
"""

import json
import threading
import time
import uuid
from typing import Optional

import urllib.request
import urllib.error

from PyQt6.QtCore import QTimer

try:
    import websocket   # websocket-client
    WS_AVAILABLE = True
except ImportError:
    WS_AVAILABLE = False


def _id() -> int:
    return int(uuid.uuid4().int & 0x7FFFFFFF)


from core.printer_client_base import PrinterClientBase

class MoonrakerClient(PrinterClientBase):
    # ── Signals (same interface as old MqttClient) ───────────────────────────
    # signals inherited from PrinterClientBase

    def __init__(self, parent=None):
        super().__init__(parent)
        self._ip         = ""
        self._port       = 7125
        self._ws: Optional[websocket.WebSocketApp] = None
        self._connected  = False
        self._pending    = {}        # id -> callback
        self._lock       = threading.Lock()
        self._poll       = QTimer(self)
        self._poll.timeout.connect(self._subscribe_query)

    # ── Public API ────────────────────────────────────────────────────────────
    def connect_to_printer(self, ip: str, port: int,
                           user="", password="", device_id=""):
        if not WS_AVAILABLE:
            self.connection_error.emit(
                "websocket-client not installed.\n\nRun:\n  pip install websocket-client"
            )
            return
        self._ip   = ip
        self._port = port
        threading.Thread(target=self._connect_thread, daemon=True).start()

    def disconnect_from_printer(self):
        self._poll.stop()
        if self._ws:
            try:
                self._ws.close()
            except Exception:
                pass
        self._connected = False

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def device_id(self) -> str:
        return self._ip   # reuse field for display

    # ── Printer commands ──────────────────────────────────────────────────────
    def set_temperature(self, target: str, value: int):
        """target: 'hotbed' | 'nozzle'"""
        if target == "hotbed":
            self._gcode(f"SET_HEATER_TEMPERATURE HEATER=heater_bed TARGET={value}")
        else:
            self._gcode(f"SET_HEATER_TEMPERATURE HEATER=extruder TARGET={value}")

    def set_fan(self, fan: str, value: int):
        """fan: 'model_fan'|'aux_fan'|'box_fan'  value: 0-255"""
        pct = round(value / 255, 2)
        fan_map = {
            "model_fan": f"M106 S{value}",
            "aux_fan":   f"SET_FAN_SPEED FAN=auxiliary_cooling_fan SPEED={pct}",
            "box_fan":   f"SET_FAN_SPEED FAN=chamber_fan SPEED={pct}",
        }
        cmd = fan_map.get(fan, f"M106 S{value}")
        self._gcode(cmd)

    def set_speed(self, mode: int):
        """mode: 1=quiet 2=normal 3=sport 4=ludicrous"""
        pct_map = {1: 50, 2: 100, 3: 130, 4: 200}
        pct = pct_map.get(mode, 100)
        self._gcode(f"M220 S{pct}")

    def set_light(self, on: bool):
        self._gcode("SET_PIN PIN=LED_pin VALUE=1" if on else "SET_PIN PIN=LED_pin VALUE=0")

    def jog(self, axis: str, distance: float):
        self._gcode(f"G91\nG0 {axis.upper()}{distance:+.2f} F3000\nG90")

    def home(self, axes: str = "XYZ"):
        self._gcode(f"G28 {' '.join(axes.upper())}")

    def emergency_stop(self):
        self._rpc("printer.emergency_stop", {})

    def print_start(self, filename: str, **kwargs):
        self._rest_post("printer/print/start", {"filename": filename})

    def print_pause(self):
        self._rest_post("printer/print/pause", {})

    def print_resume(self):
        self._rest_post("printer/print/resume", {})

    def print_stop(self):
        self._rest_post("printer/print/cancel", {})

    def request_info(self):
        self._subscribe_query()

    # ── WebSocket connection thread ────────────────────────────────────────────
    def _emit_log(self, text: str):
        import sys
        print(f"[Moonraker] {text}", file=sys.stderr)
        self.device_id_found.emit(f"__LOG__:{text}")

    def _connect_thread(self):
        import socket
        self._emit_log(f"Connecting to Moonraker at {self._ip}:{self._port}")
        try:
            s = socket.create_connection((self._ip, self._port), timeout=5)
            s.close()
            self._emit_log("TCP reachable, opening WebSocket...")
        except OSError as e:
            self.connection_error.emit(
                f"Cannot reach Moonraker at {self._ip}:{self._port}\n\n{e}\n\n"
                f"Check:\n• Printer IP is correct\n• Printer is on the same network\n"
                f"• Moonraker/Rinkhals is running"
            )
            return

        url = f"ws://{self._ip}:{self._port}/websocket"
        try:
            self._ws = websocket.WebSocketApp(
                url,
                on_open    = self._on_open,
                on_message = self._on_message,
                on_error   = self._on_ws_error,
                on_close   = self._on_close,
            )
            self._ws.run_forever(ping_interval=20, ping_timeout=10)
        except Exception as e:
            self.connection_error.emit(f"WebSocket error:\n{e}")

    # ── WebSocket handlers ────────────────────────────────────────────────────
    def _on_open(self, ws):
        self._connected = True
        self._emit_log("WebSocket connected, subscribing to printer objects...")
        self._rpc("printer.objects.subscribe", {
            "objects": {
                "heater_bed":      ["temperature", "target"],
                "extruder":        ["temperature", "target"],
                "print_stats":     ["state", "filename", "total_duration",
                                   "print_duration", "filament_used"],
                "display_status":  ["progress", "message"],
                "toolhead":        ["position"],
                "fan":             ["speed"],
                "virtual_sdcard":  ["progress", "is_active"],
            }
        })
        # Get initial printer info
        self._rpc("printer.info", {})
        self.connected.emit()
        self._poll.start(4000)

    def _on_message(self, ws, raw):
        try:
            msg = json.loads(raw)
        except Exception:
            return

        # JSON-RPC response
        if "id" in msg:
            rid = msg["id"]
            with self._lock:
                cb = self._pending.pop(rid, None)
            if cb:
                cb(msg.get("result"), msg.get("error"))
            else:
                # Handle inline responses (printer.info etc.)
                result = msg.get("result", {})
                if "state" in result:          # printer.info response
                    self._handle_printer_info(result)
                elif "status" in result:       # objects.query/subscribe
                    self._handle_status(result["status"])

        # Push notification (subscribe updates)
        elif msg.get("method") == "notify_status_update":
            params = msg.get("params", [{}])
            if params:
                self._handle_status(params[0])

        elif msg.get("method") == "notify_klippy_ready":
            self._rpc("printer.info", {})

    def _on_ws_error(self, ws, error):
        if self._connected:
            self.connection_error.emit(f"WebSocket error:\n{error}")

    def _on_close(self, ws, code, msg):
        was_connected = self._connected
        self._connected = False
        self._poll.stop()
        if was_connected:
            self.disconnected.emit(f"Connection closed (code {code})")

    # ── Status parsing ────────────────────────────────────────────────────────
    def _handle_printer_info(self, info: dict):
        self.printer_info.emit({
            "status":   info.get("state", ""),
            "firmware": info.get("software_version", ""),
            "ip":       self._ip,
        })

    def _handle_status(self, status: dict):
        out = {}

        # Temperatures
        hb = status.get("heater_bed", {})
        ex = status.get("extruder", {})
        if hb or ex:
            out["bed_actual"]     = round(hb.get("temperature", 0), 1)
            out["bed_target"]     = round(hb.get("target", 0), 1)
            out["hotend0_actual"] = round(ex.get("temperature", 0), 1)
            out["hotend0_target"] = round(ex.get("target", 0), 1)

        if out:
            self.printer_info.emit(out)

        # Print progress
        ps = status.get("print_stats", {})
        ds = status.get("display_status", {})
        vs = status.get("virtual_sdcard", {})

        if ps or ds or vs:
            state    = ps.get("state", "")
            progress = round((ds.get("progress") or vs.get("progress") or 0) * 100)
            duration = ps.get("total_duration", 0)
            printed  = ps.get("print_duration", 0)
            remain   = max(0, duration - printed) if printed > 0 else 0

            self.print_report.emit({
                "phase":    state,
                "progress": progress,
                "elapsed":  _fmt(printed),
                "eta":      _fmt(remain),
                "layer":    "-",
                "bed_temp": f"{round(status.get('heater_bed',{}).get('temperature',0),1)} C",
                "noz_temp": f"{round(status.get('extruder',{}).get('temperature',0),1)} C",
                "filename": ps.get("filename", ""),
            })

    # ── Helpers ────────────────────────────────────────────────────────────────
    def _rpc(self, method: str, params: dict, cb=None):
        if not self._ws or not self._connected:
            return
        rid = _id()
        msg = {"jsonrpc": "2.0", "method": method, "params": params, "id": rid}
        if cb:
            with self._lock:
                self._pending[rid] = cb
        try:
            self._ws.send(json.dumps(msg))
        except Exception as e:
            print(f"[WS] Send error: {e}")

    def _gcode(self, script: str):
        if not self._connected:
            return
        self._rpc("printer.gcode.script", {"script": script})

    def _rest_post(self, path: str, body: dict):
        """Fire-and-forget REST POST (runs in thread to avoid blocking UI)"""
        def _do():
            url = f"http://{self._ip}:{self._port}/{path}"
            data = json.dumps(body).encode()
            req  = urllib.request.Request(url, data=data,
                                          headers={"Content-Type": "application/json"},
                                          method="POST")
            try:
                urllib.request.urlopen(req, timeout=5)
            except Exception as e:
                print(f"[REST] {path}: {e}")
        threading.Thread(target=_do, daemon=True).start()

    def _subscribe_query(self):
        """Periodic poll to refresh all values"""
        if not self._connected:
            return
        self._rpc("printer.objects.query", {
            "objects": {
                "heater_bed":     ["temperature", "target"],
                "extruder":       ["temperature", "target"],
                "print_stats":    ["state", "filename", "total_duration",
                                   "print_duration", "filament_used"],
                "display_status": ["progress"],
                "virtual_sdcard": ["progress", "is_active"],
            }
        })


def _fmt(seconds: float) -> str:
    s = int(seconds)
    if s <= 0:
        return "--"
    h, r = divmod(s, 3600)
    m, s = divmod(r, 60)
    return f"{h}h {m:02d}m" if h else f"{m}m {s:02d}s"
