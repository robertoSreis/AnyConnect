# -*- coding: utf-8 -*-
"""
job_state.py — Persiste estado do job atual (filepath, nome, preview PNG)
em arquivo separado do settings.json para não misturar com credenciais.
"""
import os
import json
import tempfile


_JOB_FILE = os.path.join(tempfile.gettempdir(), "se3d_current_job.json")
_PREVIEW_DIR = os.path.join(tempfile.gettempdir(), "se3d_previews")


def save(filepath: str = "", task_name: str = "", preview_png: str = ""):
    """Salva estado do job atual."""
    try:
        data = {
            "filepath":    filepath,
            "task_name":   task_name,
            "preview_png": preview_png,
        }
        with open(_JOB_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def load() -> dict:
    """Carrega estado do job atual. Retorna dict vazio se não existir."""
    try:
        if os.path.isfile(_JOB_FILE):
            with open(_JOB_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def clear():
    """Remove o arquivo de estado e o PNG de preview."""
    try:
        data = load()
        png = data.get("preview_png", "")
        if png and os.path.isfile(png):
            os.remove(png)
    except Exception:
        pass
    try:
        if os.path.isfile(_JOB_FILE):
            os.remove(_JOB_FILE)
    except Exception:
        pass


def preview_dir() -> str:
    """Retorna e garante existência da pasta de previews."""
    os.makedirs(_PREVIEW_DIR, exist_ok=True)
    return _PREVIEW_DIR
