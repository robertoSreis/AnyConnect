# -*- coding: utf-8 -*-
"""
slicer_token.py
───────────────
Lê o access_token do Anycubic Slicer Next automaticamente.

O Anycubic Slicer Next é baseado na mesma engine do Bambu Studio / OrcaSlicer
(Prusa Slicer fork). O token de login fica salvo em:

    Windows : %APPDATA%\\AnycubicSlicerNext\\AnycubicSlicerNext.conf
    macOS   : ~/Library/Application Support/AnycubicSlicerNext/AnycubicSlicerNext.conf
    Linux   : ~/.AnycubicSlicerNext/AnycubicSlicerNext.conf

O arquivo é um JSON com campos como "access_token", "login_token",
"remember_login", "user_id", etc.
"""

import json
import os
import sys
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class SlicerTokenResult:
    """Resultado da tentativa de leitura do token."""
    success:     bool        = False
    token:       str         = ""
    user_id:     str         = ""
    username:    str         = ""
    conf_path:   str         = ""
    error:       str         = ""
    token_short: str         = ""          # versão truncada para exibição


# ─────────────────────────────────────────────────────────────────────────────
# Caminhos do arquivo de configuração por plataforma
# ─────────────────────────────────────────────────────────────────────────────

def _conf_candidates() -> list[str]:
    """Retorna lista de caminhos possíveis para o conf, do mais ao menos provável."""
    paths = []

    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA", "")
        localappdata = os.environ.get("LOCALAPPDATA", "")
        for base in [appdata, localappdata]:
            if base:
                paths.append(os.path.join(
                    base, "AnycubicSlicerNext", "AnycubicSlicerNext.conf"))
                # Variações alternativas de nome
                paths.append(os.path.join(
                    base, "Anycubic Slicer Next", "AnycubicSlicerNext.conf"))

    elif sys.platform == "darwin":
        home = os.path.expanduser("~")
        paths.append(os.path.join(
            home, "Library", "Application Support",
            "AnycubicSlicerNext", "AnycubicSlicerNext.conf"))

    else:  # Linux
        home = os.path.expanduser("~")
        paths.append(os.path.join(home, ".AnycubicSlicerNext", "AnycubicSlicerNext.conf"))
        paths.append(os.path.join(home, ".config", "AnycubicSlicerNext", "AnycubicSlicerNext.conf"))

    return paths


# ─────────────────────────────────────────────────────────────────────────────
# Função principal
# ─────────────────────────────────────────────────────────────────────────────

def read_slicer_token() -> SlicerTokenResult:
    """
    Tenta ler o access_token do Anycubic Slicer Next.

    Retorna um SlicerTokenResult com .success=True e .token preenchido
    em caso de sucesso, ou .success=False e .error com a mensagem de erro.
    """
    result = SlicerTokenResult()

    # 1. Procurar o arquivo de configuração
    conf_path = None
    for candidate in _conf_candidates():
        if os.path.isfile(candidate):
            conf_path = candidate
            break

    if conf_path is None:
        result.error = (
            "Arquivo de configuração do Anycubic Slicer Next não encontrado.\n\n"
            "Caminhos verificados:\n" +
            "\n".join(f"  • {p}" for p in _conf_candidates()) +
            "\n\nVerifique se o Anycubic Slicer Next está instalado e se você "
            "já fez login pelo menos uma vez."
        )
        return result

    result.conf_path = conf_path

    # 2. Ler o arquivo — o formato é PrusaSlicer/BambuStudio fork:
    #    pode conter múltiplos objetos JSON concatenados (newline-delimited JSON / NDJSON)
    #    ou um único objeto seguido de dados extras.
    #    Estratégia: tentar JSON puro primeiro, depois pegar só o 1º objeto válido.
    try:
        raw = open(conf_path, "r", encoding="utf-8").read().strip()
    except OSError as e:
        result.error = f"Erro ao abrir arquivo:\n{conf_path}\n\nErro: {e}"
        return result

    data = None

    # Tentativa 1: JSON puro
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        pass

    # Tentativa 2: cada linha é um JSON separado (NDJSON) — pegar a que tem o token
    if data is None:
        for line in raw.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                if isinstance(obj, dict):
                    for key in ("access_token", "login_token", "authToken", "auth_token", "token"):
                        if obj.get(key):
                            data = obj
                            break
                if data:
                    break
            except json.JSONDecodeError:
                continue

    # Tentativa 3: extrair o primeiro objeto JSON válido do início do arquivo
    if data is None:
        decoder = json.JSONDecoder()
        try:
            data, _ = decoder.raw_decode(raw)
        except json.JSONDecodeError:
            pass

    # Tentativa 4: regex — extrair o valor do token diretamente sem parsear o JSON completo
    if data is None:
        import re
        for key in ("access_token", "login_token", "authToken", "auth_token"):
            m = re.search(rf'"{key}"\s*:\s*"([^"]+)"', raw)
            if m and len(m.group(1)) > 20:
                result.success     = True
                result.token       = m.group(1)
                result.token_short = result.token[:12] + "..." + result.token[-6:]
                # Tentar extrair user_id e username também
                for uid_key in ("user_id", "userId"):
                    um = re.search(rf'"{uid_key}"\s*:\s*"?(\w+)"?', raw)
                    if um:
                        result.user_id = um.group(1)
                        break
                for uname_key in ("username", "email"):
                    nm = re.search(rf'"{uname_key}"\s*:\s*"([^"]+)"', raw)
                    if nm:
                        result.username = nm.group(1)
                        break
                return result

    if data is None:
        result.error = (
            "Arquivo de configuração encontrado mas não pôde ser interpretado.\n\n"
            f"Arquivo: {conf_path}\n\n"
            "O formato do arquivo não é JSON padrão nem NDJSON.\n"
            "Certifique-se de ter feito login no Anycubic Slicer Next."
        )
        return result

    # 3. Extrair o token — o campo pode variar entre versões
    token = ""
    if data is not None:
        for key in ("access_token", "login_token", "authToken", "auth_token", "token"):
            val = data.get(key, "")
            if val and isinstance(val, str) and len(val) > 20:
                token = val
                break

    # 4. Se mesmo com data parseado o token não foi encontrado (estava em outro objeto
    #    do arquivo multi-JSON), usa regex diretamente no texto bruto
    if not token:
        import re
        for key in ("access_token", "login_token", "authToken", "auth_token"):
            m = re.search(rf'"{key}"\s*:\s*"([A-Za-z0-9._\-]+)"', raw)
            if m and len(m.group(1)) > 20:
                token = m.group(1)
                # Tentar extrair user_id e username do texto bruto também
                for uid_key in ("user_id", "userId"):
                    um = re.search(rf'"{uid_key}"\s*:\s*"?(\w+)"?', raw)
                    if um:
                        result.user_id = um.group(1)
                        break
                for uname_key in ("username", "email"):
                    nm = re.search(rf'"{uname_key}"\s*:\s*"([^"@]+@[^"]+)"', raw)
                    if nm:
                        result.username = nm.group(1)
                        break
                break

    if not token:
        result.error = (
            "Arquivo de configuração encontrado, mas nenhum token de acesso "
            "foi localizado.\n\n"
            f"Arquivo: {conf_path}\n\n"
            "Certifique-se de ter feito login no Anycubic Slicer Next "
            "e que a opção 'Lembrar login' esteja ativa."
        )
        return result

    # 4. Extrair informações extras (user_id, username)
    user_id  = str(data.get("user_id",  data.get("userId",  "")))
    username = str(data.get("username", data.get("email",   "")))

    # 5. Montar resultado
    result.success     = True
    result.token       = token
    result.user_id     = user_id
    result.username    = username
    result.token_short = token[:12] + "..." + token[-6:] if len(token) > 20 else token

    return result


# ─────────────────────────────────────────────────────────────────────────────
# Verificação de disponibilidade (sem ler o token)
# ─────────────────────────────────────────────────────────────────────────────

def is_slicer_installed() -> bool:
    """Retorna True se o arquivo de configuração existir (slicer provavelmente instalado)."""
    return any(os.path.isfile(p) for p in _conf_candidates())


def get_conf_path() -> Optional[str]:
    """Retorna o caminho do conf se existir, ou None."""
    for p in _conf_candidates():
        if os.path.isfile(p):
            return p
    return None
