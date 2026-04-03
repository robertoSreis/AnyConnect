# -*- coding: utf-8 -*-
"""
bridge.py — Ponte entre OrcaSlicer e SE3D Gestor
=================================================
  1. Garante que o orca_sink.exe esta rodando (lanca se necessario)
  2. Recebe o arquivo do slicer via argv
  3. Copia para %LOCALAPPDATA%\AnyConnect\Bridge\ com nome legivel + timestamp
  4. Repassa o path da COPIA para instancia aberta via IPC, ou lanca SE3D_Hub.exe
  5. Sai imediatamente — OrcaSlicer pode deletar o original a vontade
"""

import sys
import os
import time
import shutil
import tempfile
import subprocess
import datetime

# Nomes do executavel principal e do sink
APP_NAMES  = ["SE3D_Hub.exe", "AnyConnect.exe", "SE3D_Gestor.exe"]
SINK_NAMES = ["orca_sink.exe"]


# ── Logging ───────────────────────────────────────────────────────────────────
def _log(msg: str) -> None:
    try:
        log_path = os.path.join(os.path.dirname(os.path.abspath(sys.argv[0])), "bridge_error.log")
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}\n")
    except Exception:
        pass


# ── Sink Server ───────────────────────────────────────────────────────────────
def _pid_path() -> str:
    return os.path.join(tempfile.gettempdir(), "se3d_orca_sink.pid")

def _sink_running() -> bool:
    """Retorna True se o sink_server ja esta rodando (via PID file)."""
    try:
        with open(_pid_path(), "r") as f:
            pid_str, port_str = f.read().strip().split(":")
            pid  = int(pid_str)
            port = int(port_str)

        # Verifica se o processo ainda existe
        try:
            import ctypes
            handle = ctypes.windll.kernel32.OpenProcess(0x100000, False, pid)
            alive  = handle != 0
            if handle:
                ctypes.windll.kernel32.CloseHandle(handle)
        except Exception:
            # Fallback: tenta conexao TCP na porta
            import socket
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                alive = True

        if alive:
            _log(f"Sink ja rodando — PID {pid} porta {port}")
            return True
        return False
    except Exception:
        return False

def _ensure_sink() -> None:
    """Garante que o orca_sink.exe esta rodando. Lanca se necessario."""
    if _sink_running():
        return

    here = os.path.dirname(os.path.abspath(sys.argv[0]))
    sink_exe = None
    for name in SINK_NAMES:
        candidate = os.path.join(here, name)
        if os.path.isfile(candidate):
            sink_exe = candidate
            break

    if not sink_exe:
        _log("orca_sink.exe nao encontrado — continuando sem ele")
        return

    try:
        kwargs: dict = {"close_fds": True}
        if sys.platform == "win32":
            kwargs["creationflags"] = (
                0x00000008 |   # DETACHED_PROCESS
                0x00000200 |   # CREATE_NEW_PROCESS_GROUP
                0x08000000     # CREATE_NO_WINDOW
            )
        else:
            kwargs["start_new_session"] = True
        subprocess.Popen([sink_exe, "--minimized"], **kwargs)
        _log(f"Sink lancado: {sink_exe}")
        # Aguarda ate 2s para o sink subir
        for _ in range(20):
            time.sleep(0.1)
            if _sink_running():
                break
    except Exception as exc:
        _log(f"Falha ao lancar sink: {exc}")


# ── Pasta Bridge ──────────────────────────────────────────────────────────────
def _bridge_dir() -> str:
    localappdata = os.environ.get("LOCALAPPDATA", "")
    base = localappdata if (localappdata and os.path.isdir(localappdata)) else tempfile.gettempdir()
    folder = os.path.join(base, "AnyConnect", "Bridge")
    os.makedirs(folder, exist_ok=True)
    return folder

def _copy_to_bridge(filepath: str) -> str:
    bridge = _bridge_dir()

    if filepath.lower().endswith(".gcode.3mf"):
        ext = ".gcode.3mf"
        base_no_ext = os.path.basename(filepath)[:-len(".gcode.3mf")]
    else:
        base_no_ext, ext = os.path.splitext(os.path.basename(filepath))
        if not ext:
            ext = ".gcode"

    raw = base_no_ext
    if raw.startswith(".") or (raw.count("-") >= 3 and len(raw) > 30):
        raw = "print"

    safe = "".join(c for c in raw if c.isalnum() or c in "._- ").strip() or "print"
    safe = safe[:40]

    ts   = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = os.path.join(bridge, f"{safe}_{ts}{ext}")
    shutil.copy2(filepath, dest)
    _log(f"Copiado para Bridge: {dest}")
    return dest


# ── IPC ───────────────────────────────────────────────────────────────────────
def _ipc_file() -> str:
    return os.path.join(tempfile.gettempdir(), "se3d_gestor_ipc.txt")

def _instance_alive() -> bool:
    ipc = _ipc_file()
    if not os.path.exists(ipc):
        return False
    age = time.time() - os.path.getmtime(ipc)
    return age < 10

def _send_to_instance(filepath: str) -> bool:
    if not _instance_alive():
        return False
    try:
        with open(_ipc_file(), "w", encoding="utf-8") as f:
            f.write(filepath)
        _log(f"Enviado via IPC para instancia ativa: {filepath}")
        return True
    except Exception as exc:
        _log(f"Falha ao escrever IPC: {exc}")
        return False


# ── Resolve executavel principal ──────────────────────────────────────────────
def _resolve_app() -> str | None:
    here = os.path.dirname(os.path.abspath(sys.argv[0]))
    candidates = []
    for name in APP_NAMES:
        candidates.append(os.path.join(here, name))
        candidates.append(os.path.join(os.getcwd(), name))

    _log(f"Procurando app em: {candidates[:len(APP_NAMES)]}")
    for c in candidates:
        if os.path.isfile(c):
            _log(f"App encontrado: {c}")
            return c

    _log(f"ERRO: nenhum executavel encontrado em {here}")
    return None

def _launch_detached(filepath: str, app: str) -> None:
    _log(f"Tentando lancar: '{app}' com '{filepath}'")
    try:
        kwargs: dict = {"close_fds": True}
        if sys.platform == "win32":
            kwargs["creationflags"] = 0x00000008 | 0x00000200
        else:
            kwargs["start_new_session"] = True
        subprocess.Popen([app, filepath], **kwargs)
        _log(f"Popen OK: {app}")
    except Exception as exc:
        _log(f"Popen FALHOU: {exc}")


# ── Entry point ───────────────────────────────────────────────────────────────
def main() -> None:
    _log(f"bridge iniciado — argv: {sys.argv}")

    # PASSO 0: garante que o sink_server esta rodando
    _ensure_sink()

    # Coleta filepath do slicer
    filepath = ""
    if len(sys.argv) >= 2:
        candidate = " ".join(sys.argv[1:])
        if os.path.isfile(candidate):
            filepath = candidate
        else:
            filepath = next((a for a in sys.argv[1:] if os.path.isfile(a)), "")

    if not filepath:
        _log("ERRO: nenhum arquivo valido recebido como argumento.")
        return

    _log(f"filepath resolvido: '{filepath}'")

    # PASSO 1: copia para AnyConnect\Bridge
    try:
        bridge_copy = _copy_to_bridge(filepath)
    except Exception as exc:
        _log(f"AVISO: falha ao copiar para Bridge ({exc}) — usando path original")
        bridge_copy = filepath

    # PASSO 2: envia para instancia aberta, ou lanca o app
    if _send_to_instance(bridge_copy):
        _log("bridge encerrando (enviado para instancia ativa).")
        return

    app = _resolve_app()
    if not app:
        _log("ERRO FATAL: SE3D_Hub.exe nao encontrado.")
        return

    _log(f"Nenhuma instancia ativa. Lancando: {app}")
    _launch_detached(bridge_copy, app)
    _log("bridge encerrando.")


if __name__ == "__main__":
    main()
