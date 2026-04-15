# -*- coding: utf-8 -*-
"""
Settings manager - saves/loads preferences to JSON
"""

import os
import json

# Settings file location next to executable
SETTINGS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "settings.json")

DEFAULT_SETTINGS = {
    "printer_brand":    "",
    "printer_ip":       "",
    "printer_cn":       "",
    "connection_mode":  "lan",
    "moonraker_port":   7125,
    "mqtt_port":        8883,
    "mqtt_user":        "",
    "mqtt_pass":        "",
    "device_id":        "",
    "device_cert":      "",   # PEM multiline — mTLS client certificate
    "device_key":       "",   # PEM multiline — mTLS private key
    "slicer_token":     "",   # JWT do Anycubic Slicer Next
    "cloud_region":     "global",
    "remember_login":   False,
    "anycubic_email":   "",
    "anycubic_pass":    "",
    "anycubic_token":   "",
    "slots": [
        {"material_type": "PLA", "paint_color": [255, 255, 255], "paint_index": 0},
        {"material_type": "PLA", "paint_color": [40,  40,  40 ], "paint_index": 1},
        {"material_type": "PLA", "paint_color": [255, 0,   0  ], "paint_index": 2},
        {"material_type": "PLA", "paint_color": [0,   0,   255], "paint_index": 3},
    ],
    "last_options": {
        "auto_leveling":      True,
        "ai_detection":       False,
        "timelapse":          False,
        "flow_calibration":   False,
    },
    "upload_mode": "gcode_only"
}


def load() -> dict:
    """Loads settings from JSON file, filling missing keys with defaults"""
    settings = dict(DEFAULT_SETTINGS)
    try:
        if os.path.exists(SETTINGS_FILE):
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                saved = json.load(f)
            settings.update(saved)
    except Exception:
        pass
    return settings


def _safe_print(msg: str):
    """Print seguro — não crasha se stdout/stderr estiver fechado (Nuitka, redirect)."""
    import sys
    for stream in (sys.stdout, sys.stderr):
        try:
            if stream and not stream.closed:
                stream.write(msg + "\n")
                stream.flush()
                return
        except Exception:
            pass


def save(settings: dict):
    """Saves settings to JSON file — slots NÃO são persistidos (vêm do ACE Pro via MQTT)."""
    import copy
    safe = {}
    # Campos que NÃO devem ser persistidos (estado dinâmico da impressora)
    EXCLUDE = {"slots"}
    for k, v in settings.items():
        if k in EXCLUDE:
            continue
        try:
            import json as _j
            _j.dumps(v)
            safe[k] = v
        except (TypeError, ValueError):
            pass
    try:
        os.makedirs(os.path.dirname(SETTINGS_FILE), exist_ok=True)
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(safe, f, indent=2, ensure_ascii=False)
        _safe_print(f"[settings] saved → {SETTINGS_FILE}")
    except Exception as e:
        _safe_print("Error saving settings: " + str(e))
