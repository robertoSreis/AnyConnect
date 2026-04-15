# -*- coding: utf-8 -*-
"""
acha_api_anycubic.py
────────────────────
1. Lê o token do AnycubicSlicerNext.conf
2. Tenta todos os subdomínios e endpoints conhecidos
3. Exibe qual retorna JSON válido com dados de impressora

Rode: python acha_api_anycubic.py
"""
import re, os, json, ssl, urllib.request, urllib.error

# ── Ler token do conf ─────────────────────────────────────────────────────────
conf_path = os.path.join(os.environ.get("APPDATA",""), "AnycubicSlicerNext", "AnycubicSlicerNext.conf")
token = ""
try:
    raw = open(conf_path, "rb").read().decode("utf-8", errors="replace")
    m = re.search(r'"access_token"\s*:\s*"([A-Za-z0-9._\-]+)"', raw)
    if m:
        token = m.group(1)
        print(f"✓ Token: {token[:20]}...{token[-10:]}")
    else:
        print("✗ Token não encontrado no conf")
    # Procurar URLs no conf
    urls = re.findall(r'https?://[^\s"\'<>]+anycubic[^\s"\'<>]*', raw, re.IGNORECASE)
    if urls:
        print(f"\nURLs Anycubic no conf:")
        for u in sorted(set(urls)):
            print(f"  {u}")
except Exception as e:
    print(f"Conf: {e}")

if not token:
    token = input("\nCole o token manualmente: ").strip()

# ── Testar endpoints ──────────────────────────────────────────────────────────
HOSTS = [
    "https://cloud-universe.anycubic.com",
    "https://api-universe.anycubic.com",
    "https://cloud-platform.anycubicloud.com",
    "https://api.anycubic.com",
    "https://cloud-api.anycubic.com",
    "https://universe.anycubic.com",
]
PATHS = [
    "/api/v1/printer/base/list",
    "/api/v1/printer/list",
    "/api/v1/user/printer/list",
    "/api/v1/print/printer/base/list",
    "/api/v1/app/printer/list",
    "/graphql",
]

hdrs = {
    "Authorization": f"Bearer {token}",
    "Content-Type": "application/json",
    "Accept": "application/json",
    "User-Agent": "AnycubicSlicerNext/1.3.9",
}

# Contexto SSL sem verificação
ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

print(f"\n{'='*60}")
print("TESTANDO ENDPOINTS")
print('='*60)

found = []
for host in HOSTS:
    for path in PATHS:
        url = host + path
        try:
            req = urllib.request.Request(url, headers=hdrs)
            with urllib.request.urlopen(req, timeout=6, context=ctx) as r:
                raw = r.read()
                code = r.getcode()
            if raw.strip().startswith(b"<"):
                print(f"  HTML  {url}")
                continue
            try:
                data = json.loads(raw)
                print(f"  ✓ JSON  {url}")
                print(f"    → code={data.get('code')} msg={data.get('msg','')[:60]}")
                # Verificar se tem lista de impressoras
                printers = None
                d = data.get("data") or {}
                if isinstance(d, list):
                    printers = d
                elif isinstance(d, dict):
                    printers = d.get("list") or d.get("printer_list") or d.get("printers")
                if printers:
                    print(f"    ★ IMPRESSORAS ENCONTRADAS: {len(printers)}")
                    p = printers[0]
                    print(f"      Primeira: {p.get('name','?')}")
                    print(f"      Chaves: {list(p.keys())}")
                    found.append((url, printers))
            except Exception as je:
                print(f"  JSON inválido  {url}: {je}")
        except urllib.error.HTTPError as e:
            print(f"  HTTP {e.code}  {url}")
        except Exception as e:
            msg = str(e)[:60]
            print(f"  ERRO  {url}: {msg}")

print(f"\n{'='*60}")
if found:
    print(f"✓ ENCONTRADO: {found[0][0]}")
    p = found[0][1][0]
    print(f"\nChaves disponíveis na impressora:")
    print(json.dumps(p, indent=2, ensure_ascii=False)[:800])
else:
    print("✗ Nenhum endpoint retornou JSON com impressoras.")
    print("\nPróximo passo: use o Fiddler Classic para capturar o tráfego do Slicer Next.")
