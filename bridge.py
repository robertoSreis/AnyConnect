# -*- coding: utf-8 -*-
"""
bridge.py — Ponte entre OrcaSlicer e SE3D Gestor
=================================================
  1. Garante que o orca_sink.exe esta rodando (lanca se necessario)
  2. Recebe o arquivo do slicer via argv
  3. Detecta o tipo real do arquivo (ZIP/3MF mesmo sem extensão)
  4. Copia para %LOCALAPPDATA%\AnyConnect\Bridge\ com nome legível + timestamp
     e extensão correta (.gcode.3mf se for ZIP, .gcode se for texto gcode)
  5. Repassa o path da COPIA para instancia aberta via IPC, ou lanca SE3D_Hub.exe
  6. Sai imediatamente — OrcaSlicer pode deletar o original a vontade
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


# ── Detecção de tipo de arquivo ───────────────────────────────────────────────
def _is_zip(filepath: str) -> bool:
    """Verifica se o arquivo é um ZIP válido pelos magic bytes (PK\\x03\\x04)."""
    try:
        with open(filepath, "rb") as f:
            magic = f.read(4)
        return magic == b'PK\x03\x04'
    except Exception:
        return False


def _is_gcode_text(filepath: str) -> bool:
    """Verifica se o arquivo parece ser gcode de texto (começa com ; ou G ou T ou M)."""
    try:
        with open(filepath, "rb") as f:
            chunk = f.read(512)
        # Tenta decodificar como UTF-8
        text = chunk.decode("utf-8", errors="replace").lstrip()
        if not text:
            return False
        first_char = text[0]
        return first_char in (';', 'G', 'g', 'T', 'M', 'm', 'N', 'n', '\n', '\r')
    except Exception:
        return False


def _detect_real_extension(filepath: str, original_name: str) -> str:
    """
    Detecta a extensão real do arquivo baseado no conteúdo (magic bytes).
    Retorna a extensão correta a usar na cópia.

    Prioridade:
      1. Se o nome original já tem extensão reconhecível, usa ela
      2. Se os magic bytes indicam ZIP → .gcode.3mf
      3. Se o conteúdo parece gcode de texto → .gcode
      4. Fallback: mantém extensão original ou sem extensão
    """
    name_lower = original_name.lower()

    # 1. Extensão já conhecida no nome original
    if name_lower.endswith(".gcode.3mf"):
        return ".gcode.3mf"
    if name_lower.endswith(".3mf"):
        return ".3mf"
    if name_lower.endswith((".gcode", ".gc")):
        return ".gcode"
    if name_lower.endswith(".bgcode"):
        return ".bgcode"
    if name_lower.endswith(".pp"):
        # .pp é um formato de gcode pós-processado do OrcaSlicer — tratar como gcode
        return ".gcode"

    # 2. Detecta pelo conteúdo
    if _is_zip(filepath):
        _log(f"  Detectado ZIP → extensão .gcode.3mf")
        return ".gcode.3mf"

    if _is_gcode_text(filepath):
        _log(f"  Detectado texto gcode → extensão .gcode")
        return ".gcode"

    # 3. Fallback: sem extensão (app tenta abrir mesmo assim)
    _log(f"  Tipo não reconhecido — sem extensão adicional")
    return ""


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

        try:
            import ctypes
            handle = ctypes.windll.kernel32.OpenProcess(0x100000, False, pid)
            alive  = handle != 0
            if handle:
                ctypes.windll.kernel32.CloseHandle(handle)
        except Exception:
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

    original_name = os.path.basename(filepath)

    # Detecta extensão real pelo conteúdo
    real_ext = _detect_real_extension(filepath, original_name)

    # Deriva o nome base do arquivo
    # Remove extensões conhecidas do nome original
    base = original_name
    for suf in (".gcode.3mf", ".3mf", ".gcode", ".gc", ".bgcode", ".pp"):
        if base.lower().endswith(suf):
            base = base[:-len(suf)]
            break

    # Nomes aleatórios/temporários do OrcaSlicer viram "print"
    if (base.startswith(".") or
            (base.count("-") >= 3 and len(base) > 20) or
            base.startswith(".")):
        base = "print"

    safe = "".join(c for c in base if c.isalnum() or c in "._- ").strip() or "print"
    safe = safe[:40]

    ts   = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = os.path.join(bridge, f"{safe}_{ts}{real_ext}")
    shutil.copy2(filepath, dest)
    _log(f"Copiado para Bridge: {dest}  (extensão detectada: '{real_ext}')")
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

    # PASSO 1: copia para AnyConnect\Bridge com extensão correta
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
