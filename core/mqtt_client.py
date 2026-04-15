# -*- coding: utf-8 -*-
"""
Anycubic MQTT Client — Kobra S1
=================================
Baseado em engenharia reversa + documentação oficial Rinkhals:
  https://jbatonnet.github.io/Rinkhals/firmware/mqtt/

TÓPICOS (MODEL_ID = "20025" para Kobra S1):
  Comandos slicer : anycubic/anycubicCloud/v1/slicer/printer/20025/{device_id}
  Comandos web    : anycubic/anycubicCloud/v1/web/printer/20025/{device_id}
  Info da printer : anycubic/anycubicCloud/v1/printer/public/20025/{device_id}

DIFERENÇA CRÍTICA (descoberta no wiki Rinkhals):
  • Temperatura, luz, velocidade → tópico WEB  (.../web/printer/...)
  • Start/stop/pause print       → tópico SLICER (.../slicer/printer/.../print)
  • Info query                   → tópico SLICER (.../slicer/printer/.../info)
  • Luz: payload {"type":3, "status":0/1, "brightness":0/100} via .../web/.../light
  • Temperatura: dentro de "settings" com taskid "-1"

CONEXÃO LAN (Kobra S1 stock firmware):
  Host: <printer_ip>:9883  TLS (CERT_NONE, SECLEVEL=0)
  Credenciais: username/password do device_account.json (SSH)
"""

import json, ssl, uuid, time, threading
from PyQt6.QtCore import QTimer, QMetaObject, Qt, pyqtSlot, pyqtSignal
from core.printer_client_base import PrinterClientBase

try:
    import paho.mqtt.client as mqtt
    PAHO_OK = True
except ImportError:
    PAHO_OK = False

LAN_PORT  = 9883
MODEL_ID  = "20025"   # Kobra S1

def _mid(): return str(uuid.uuid4())
def _ts():  return int(time.time() * 1000)


class MqttClient(PrinterClientBase):

    file_list          = pyqtSignal(list)   # emite lista de arquivos da impressora
    _start_print_sig   = pyqtSignal(str, dict)  # (filename, job) — cross-thread safe
    message_received   = pyqtSignal(str, dict)
    print_error        = pyqtSignal(int, str)   # (code, msg) — erros de print/report
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._client         = None
        self._device_id      = ""
        self._host           = ""
        self._mqtt_user      = ""
        self._mqtt_pass      = ""
        self._mqtt_cid       = f"se3d_{uuid.uuid4().hex[:8]}"
        self._connected_flag = False
        self._mode           = "lan"
        self._stopping       = False
        self._current_taskid = "-1"   # atualizado pelo print/report
        self._upload_url     = ""     # fileUploadurl do info/report
        self._lan_fail_count = 0

        self._poll = QTimer(self)
        self._poll.timeout.connect(self._request_info)

        # Heartbeat leve — mantém a impressora acordada entre os polls completos
        self._heartbeat = QTimer(self)
        self._heartbeat.timeout.connect(self._send_heartbeat)

        # Rastreia quando a impressora respondeu pela última vez
        self._last_response_ts = 0.0


        self._start_print_sig.connect(self._on_start_print_signal)

    # ── API pública ───────────────────────────────────────────────────────
    def connect_to_printer(self, ip="", mqtt_user="", mqtt_pass="",
                           device_id="", connection_mode="lan",
                           slicer_token="", device_ca="", **kw):
        if not PAHO_OK:
            self.connection_error.emit("paho-mqtt não instalado.\npip install paho-mqtt")
            return

        self._mode      = connection_mode.lower().strip()
        self._host      = ip.strip()
        self._device_id = device_id.strip()
        self._mqtt_user = mqtt_user.strip()
        self._mqtt_pass = mqtt_pass.strip()
        self._stopping  = False

        if self._mode == "cloud":
            self.connection_error.emit(
                "Modo Cloud está em desenvolvimento.\n\nUse o modo LAN (Mochi) para conectar agora."
            ); return

        if not self._host:
            self.connection_error.emit("IP da impressora não configurado."); return

        if not self._mqtt_user or not self._mqtt_pass:
            self.connection_error.emit(
                "Credenciais MQTT não configuradas.\nVá em CONFIG → SSH FETCH."
            ); return

        self._destroy_client()
        self._emit_log(f"→ Modo LAN — conectando {self._host}:{LAN_PORT}")
        threading.Thread(target=self._do_connect_lan, daemon=True).start()

    def disconnect_from_printer(self):
        self._stopping = True
        self._poll.stop()
        self._connected_flag = False
        self._destroy_client()
        self.disconnected.emit("Desconectado")

    @property
    def is_connected(self): return self._connected_flag
    @property
    def device_id(self):    return self._device_id

    # ── Comandos — payloads corretos conforme Rinkhals wiki ───────────────

    def set_temperature(self, target, value):
        """
        Temperatura via WEB tópico /tempature action=set
        Confirmado pelo sniffer:
          nozzle → {"type": 0, "target_hotbed_temp": 0, "target_nozzle_temp": N}
          hotbed → {"type": 1, "target_hotbed_temp": N, "target_nozzle_temp": 0}
        """
        if target == "hotbed":
            data = {"type": 1, "target_hotbed_temp": int(value), "target_nozzle_temp": 0}
        else:
            data = {"type": 0, "target_hotbed_temp": 0, "target_nozzle_temp": int(value)}

        if not self._check_ready("tempature/set"): return
        topic = f"anycubic/anycubicCloud/v1/web/printer/{self._model_id}/{self._device_id}/tempature"
        self._publish(topic, "tempature", "set", data)

    def set_fan(self, fan, value):
        """
        Fans via WEB tópico /fan action=setSpeed
        Confirmado pelo sniffer:
          fan_speed_pct     → {"fan_speed_pct": N}       (0-100)
          aux_fan_speed_pct → {"aux_fan_speed_pct": N}   (0-100)
          box_fan_level     → {"box_fan_level": N}        (0-100, slicer envia 0-100 direto)
        """
        if fan == "fan":
            data = {"fan_speed_pct": int(value)}
        elif fan == "aux_fan":
            data = {"aux_fan_speed_pct": int(value)}
        elif fan == "box_fan":
            data = {"box_fan_level": int(value)}
        else:
            return

        if not self._check_ready("fan/setSpeed"): return
        topic = f"anycubic/anycubicCloud/v1/web/printer/{self._model_id}/{self._device_id}/fan"
        self._publish(topic, "fan", "setSpeed", data)

    def set_speed(self, mode):
        """
        Velocidade: 1=Quiet 2=Standard 3=Sport
        Ref: Rinkhals wiki — print_speed_mode via WEB /print
        Envia com taskid atual E com -1 para cobrir os dois casos (idle/printing)
        """
        payload = {"settings": {"print_speed_mode": int(mode)}}
        self._pub_web("print", "update", {"taskid": self._current_taskid, **payload})
        if self._current_taskid != "-1":
            self._pub_web("print", "update", {"taskid": "-1", **payload})

    def set_flow(self, value):
        """
        Flow rate / extrusion multiplier
        Tenta via web/print com ambos nomes possíveis
        """
        v = int(value)
        for key in ["flow_rate", "flow_ratio", "filament_extrusion_factor"]:
            self._pub_web("print", "update", {
                "taskid": self._current_taskid,
                "settings": {key: v}
            })

    def set_light(self, value):
        """
        Luz via WEB tópico /light
        Rinkhals wiki: type=3 = câmera/chamber light
        No Kobra S1, o light/report respondeu com type=2 nos testes
        → tentar type=2 primeiro (câmera KS1), depois type=3
        """
        status     = 1 if value else 0
        brightness = 100 if value else 0
        # type=2 = luz da câmera/câmara (confirmado no light/report do KS1)
        self._pub_web_light({"type": 2, "status": status, "brightness": brightness})

    def pause_print(self):
        self._pub_slicer_print("pause", {"taskid": self._current_taskid})

    def resume_print(self):
        self._pub_slicer_print("resume", {"taskid": self._current_taskid})

    def stop_print(self):
        self._pub_slicer_print("stop", {"taskid": self._current_taskid})

    # mqtt_client.py - dentro de start_print(), substitua a chamada _do_upload_and_start
    def _upload_gcode_via_mqtt(self, filepath: str, filename: str, job: dict | None):
        """Envia arquivo GCode diretamente via MQTT (sem HTTP)."""
        import os, base64, hashlib, json as _json, uuid, time
        
        if not self._check_ready("file/upload"):
            return
        
        with open(filepath, "rb") as f:
            data = f.read()
        
        filesize = len(data)
        file_b64 = base64.b64encode(data).decode('ascii')
        file_md5 = hashlib.md5(data).hexdigest()
        
        payload = {
            "type": "file",
            "action": "upload",
            "msgid": str(uuid.uuid4()),
            "timestamp": int(time.time() * 1000),
            "data": {
                "filename": filename,
                "filesize": filesize,
                "filedata": file_b64,
                "md5": file_md5
            }
        }
        
        topic = f"anycubic/anycubicCloud/v1/slicer/printer/{self._model_id}/{self._device_id}/file"
        self._client.publish(topic, json.dumps(payload), qos=0)
        self._emit_log(f"[MQTT] Upload via MQTT: {filename} ({filesize} bytes)")
        
        # Após o upload, envia o comando print/start
        self._mqtt_start_print(filename, filesize, file_md5, job)


    def start_print(self, filename, file_id="", filepath="", job=None, **kw):
        if not self._check_ready("print/start"):
            return

        if not filepath and job:
            filepath = job.get("filepath", "")

        if not filepath:
            self._emit_log("  start_print: filepath não fornecido — enviando só MQTT sem upload")
            self._mqtt_start_print(filename, 0, "", job)
            return

        if not self._upload_url:
            self._emit_log("  start_print: aguardando fileUploadurl (pedindo info)...")
            self._request_info()
            QMetaObject.invokeMethod(self, "_retry_start_print", Qt.ConnectionType.QueuedConnection)
            self._pending_start = (filename, file_id, filepath, job)
            return

        upload_url = self._upload_url
        threading.Thread(
            target=self._do_upload_and_start,
            args=(filepath, filename, upload_url, job),
            daemon=True
        ).start()
    
    def _do_upload_and_start(self, filepath: str, filename: str,
                              upload_url: str, job: dict | None):
        """Thread: faz HTTP upload e depois dispara MQTT print/start."""
        import os, hashlib, re, json as _json
        try:
            with open(filepath, "rb") as f:
                data = f.read()
            filesize = len(data)

            raw_name = os.path.basename(filepath)
            upload_mode = (job or {}).get("upload_mode", "full")
            task_name   = (job or {}).get("task_name", "").strip()

            if upload_mode == "gcode_only":
                # Usa o nome escolhido pelo usuário + .gcode
                if task_name:
                    fname = task_name + ".gcode"
                else:
                    fname = raw_name
            elif raw_name.lower().endswith(".gcode.3mf"):
                if task_name:
                    fname = task_name + ".gcode.3mf"
                else:
                    fname = raw_name.replace("_se3d.gcode.3mf", ".gcode.3mf")
            else:
                if task_name:
                    fname = task_name + ".gcode.3mf"
                else:
                    base = raw_name
                    for suf in ("_se3d.gcode", ".gcode", ".gc"):
                        if base.lower().endswith(suf):
                            base = base[:-len(suf)]
                            break
                    fname = base + ".gcode.3mf"

            

            self._emit_log(f"  upload → {upload_url}")
            self._emit_log(f"  arquivo local : {raw_name}  ({filesize:,} bytes)")
            self._emit_log(f"  nome enviado  : {fname}")

            import urllib.request

            boundary = "------------------------" + uuid.uuid4().hex[:16]
            b = boundary.encode()
            body = (
                b"--" + b + b"\r\n"
                b'Content-Disposition: form-data; name="filename"\r\n\r\n' +
                fname.encode("utf-8") + b"\r\n"
                b"--" + b + b"\r\n"
                b'Content-Disposition: form-data; name="gcode"; filename="' +
                fname.encode("utf-8") + b'"\r\n'
                b"Content-Type: application/octet-stream\r\n\r\n" +
                data +
                b"\r\n--" + b + b"--\r\n"
            )

            req = urllib.request.Request(
                upload_url, data=body, method="POST",
                headers={
                    "Content-Type":         f"multipart/form-data; boundary={boundary}",
                    "Content-Length":       str(len(body)),
                    "User-Agent":           "AnycubicSlicerNext/1.3.9.3",
                    "Accept":               "*/*",
                    "X-BBL-Client-Name":    "AnycubicSlicerNext",
                    "X-BBL-Client-Type":    "slicer",
                    "X-BBL-Client-Version": "01.03.09.03",
                    "X-BBL-Device-ID":      "1ef48254-bd6e-4176-bee8-954461c082c1",
                    "X-BBL-Language":       "en-US",
                    "X-BBL-OS-Type":        "windows",
                    "X-BBL-OS-Version":     "10.0.26100",
                    "X-File-Length":        str(filesize),
                }
            )
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            ctx.check_hostname = False
            ctx.verify_mode    = ssl.CERT_NONE
            try:
                resp = urllib.request.urlopen(req, timeout=120, context=ctx)
            except Exception:
                resp = urllib.request.urlopen(req, timeout=120)

            resp_body = resp.read().decode("utf-8", errors="replace")
            self._emit_log(f"  upload resp {resp.status}: {resp_body[:200]}")

            try:
                code = _json.loads(resp_body).get("code", -1)
                if code not in (0, 200):
                    self._emit_log(f"  upload rejeitado code={code}")
                    return
                self._emit_log(f"  upload aceito ✓")
            except Exception:
                pass

            # Passa nome ORIGINAL para o MQTT (com espaços/parênteses)
            # md5 e filesize são constantes fictícias (confirmado pelo sniffer)
            job_safe = {k: v for k, v in (job or {}).items()
                        if not hasattr(v, '__class__') or
                        v.__class__.__name__ not in ('QPixmap', 'QImage')}

            # Emite signal para chamar na thread principal (cross-thread safe)
            self._start_print_sig.emit(fname, job_safe)

        except Exception as exc:
            import traceback
            self._emit_log(f"  upload ERRO: {exc}\n{traceback.format_exc()[-400:]}")

    @pyqtSlot(str, str, str, str)
    def _mqtt_start_print_slot(self, filename: str, filesize_str: str,
                                md5: str, job_json: str):
        job = json.loads(job_json) if job_json else {}
        self._mqtt_start_print(filename, int(filesize_str or "0"), md5, job)

    @pyqtSlot(str, dict)
    def _on_start_print_signal(self, filename: str, job: dict):
        self._mqtt_start_print(filename, 0, "", job)

    def _mqtt_start_print(self, filename: str, filesize: int,
                           md5: str, job: dict | None):
        """Envia MQTT print/start — formato confirmado pelo sniffer AnycubicSlicerNext.
        Filesystem confirmado: /useremain/app/gk/gcodes/<nome>.gcode.3mf
        """
        job = job or {}

        # Slots config para ams_box_mapping
        # ace_connected=False -> nao envia slots, impressora usa single color
        ace_connected = job.get("ace_connected", False)
        slots_config  = job.get("slots_config", [])
        ace_slots     = []
        if ace_connected:
            for m in job.get("color_mapping", []):
                slicer_idx = m.get("slicer", 0)
                ace_idx    = m.get("ace",    0)

                # Pega dados reais do slot ACE mapeado
                ace_slot = slots_config[ace_idx] if ace_idx < len(slots_config) else {}
                rgb      = ace_slot.get("paint_color", [255, 255, 255])[:3]
                mat      = ace_slot.get("material_type", "PLA")

                # ams_index deve ser o índice FÍSICO do slot no ACE Pro
                # O campo "index" do slot contém o índice real (0-3)
                # Se não existir, usa ace_idx como fallback
                physical_index = ace_slot.get("index", ace_slot.get("paint_index", ace_idx))

                ace_slots.append({
                    "paint_index":   slicer_idx,
                    "ams_index":     int(physical_index),
                    "paint_color":   [int(rgb[0]), int(rgb[1]), int(rgb[2])],
                    "ams_color":     [int(rgb[0]), int(rgb[1]), int(rgb[2])],
                    "material_type": mat,
                })

        # Sniffer confirma: md5 e filesize são constantes fictícias no slicer original
        data = {
            "taskid":       "-1",
            "url":          "https://anycubic.com/store/aaa.gcode",
            "filename":     filename,   # nome ORIGINAL com espaços/parênteses
            "md5":          "943c0dff568dd508e21af2d894bb6b49",  # valor fixo do slicer
            "filepath":     None,
            "filetype":     1,
            "project_type": 1,
            "filesize":     188000,     # valor fixo do slicer
        }

        # task_settings — estrutura confirmada pelo sniffer do AnycubicSlicerNext
        ai_enabled        = bool(job.get("ai_detection",     False))
        timelapse_enabled = bool(job.get("timelapse",        False))
        flow_cal_enabled  = bool(job.get("flow_calibration", False))
        dry_mode          = int(job.get("dry_mode",  0))   # 0=off 1=while 2=after
        dry_temp          = int(job.get("dry_temp",  35))
        dry_hours         = int(job.get("dry_hours", 12))
        dry_duration_min  = dry_hours * 60             # impressora usa minutos

        # model_objects_skip_parts: lista de nomes de objetos do gcode.
        # Confirmado pelo sniffer: o AnycubicSlicerNext preenche com os nomes dos
        # EXCLUDE_OBJECT_DEFINE — isso sinaliza ao firmware que o arquivo suporta
        # skip de partes e habilita a opção no display durante a impressão.
        # Lista vazia = firmware não mostra a opção de skip.
        filepath_for_scan = job.get("filepath", "")
        skip_parts = []
        if filepath_for_scan:
            try:
                import zipfile as _zf, re as _re
                _fn_lower = filepath_for_scan.lower()
                if _fn_lower.endswith(".3mf") or _fn_lower.endswith(".gcode.3mf"):
                    zf = _zf.ZipFile(filepath_for_scan)
                    for entry in zf.namelist():
                        if entry.endswith(".gcode") and "metadata" not in entry:
                            gcode_bytes = zf.read(entry)
                            gcode_text  = gcode_bytes[:20000].decode("utf-8", errors="replace")
                            skip_parts  = _re.findall(r'EXCLUDE_OBJECT_DEFINE NAME=(\S+)', gcode_text)
                            if skip_parts:
                                break
                    zf.close()
                else:
                    # .gcode direto — lê primeiras 30k chars
                    with open(filepath_for_scan, "r", encoding="utf-8", errors="replace") as _fg:
                        gcode_text = _fg.read(30000)
                    skip_parts = _re.findall(r'EXCLUDE_OBJECT_DEFINE NAME=(\S+)', gcode_text)
            except Exception:
                pass

        data["task_settings"] = {
            "auto_leveling":          1 if job.get("auto_leveling",    True)  else 0,
            "vibration_compensation": 1 if job.get("resonance",        False) else 0,
            "flow_calibration":       1 if flow_cal_enabled else 0,
            "dry_mode":               dry_mode,
            "ai_settings": {
                "status": 1 if ai_enabled else 0,
                "count":  481 if ai_enabled else 0,
                "type":   1,
            },
            "timelapse": {
                "status": 1 if timelapse_enabled else 0,
                "count":  0,
                "type":   48,
            },
            "drying_settings": {
                "status":      1 if dry_mode > 0 else 0,
                "target_temp": dry_temp  if dry_mode > 0 else 0,
                "duration":    dry_duration_min if dry_mode > 0 else 0,
                "remain_time": 0,
            },
            "model_objects_skip_parts": skip_parts,
        }

        # ams_settings — só ativa ACE se tiver mapeamento configurado
        if ace_slots:
            data["ams_settings"] = {
                "use_ams":         True,
                "ams_box_mapping": ace_slots,
            }
        else:
            data["ams_settings"] = {"use_ams": False, "ams_box_mapping": []}

        self._emit_log(f"  MQTT print/start: {json.dumps(data)[:500]}")
        self._pub_slicer_print("start", data)

    @pyqtSlot()
    def _retry_start_print(self):
        """Chamado na thread Qt após aguardar upload_url — retenta start_print em 3s."""
        pending = getattr(self, "_pending_start", None)
        if pending is None:
            return
        self._pending_start = None
        filename, file_id, filepath, job = pending
        QTimer.singleShot(3000, lambda: self.start_print(
            filename, file_id=file_id, filepath=filepath, job=job))

    def set_filament_slot(self, slot):
        self._pub_slicer("multiColor", "set", {"index": slot})

    def _pub_gcode(self, script: str):
        """Envia GCode via tópico MQTT nativo do GoKlipper.
        O GoKlipper (firmware Anycubic) pode aceitar GCode via:
          slicer/.../gcode  action=run  data={"gcode":"G28"}
        Não documentado oficialmente, mas inferido da arquitetura Klipper.
        Também tenta via tópico web como fallback.
        """
        ts  = int(time.time() * 1000)
        mid = str(uuid.uuid4())
        payload = json.dumps({
            "type":      "gcode",
            "action":    "run",
            "timestamp": ts,
            "msgid":     mid,
            "data":      {"gcode": script}
        })
        base = (f"anycubic/anycubicCloud/v1/slicer/printer/"
                f"20025/{self._device_id}")
        self._client.publish(f"{base}/gcode", payload, qos=0)
        self._emit_log(f"  PUB gcode → {script!r}")

    def _pub_web_axis(self, action, data=None):
        """Tópico axis — confirmado pelo sniffer do Slicer Next."""
        if not self._check_ready(f"axis/{action}"): return
        topic = (f"anycubic/anycubicCloud/v1/web/printer/"
                 f"{self._model_id}/{self._device_id}/axis")
        self._publish(topic, "axis", action, data or {})

    def _pub_web_file(self, action, data=None):
        """Tópico file — listagem e gerenciamento de arquivos."""
        if not self._check_ready(f"file/{action}"): return
        topic = (f"anycubic/anycubicCloud/v1/web/printer/"
                 f"{self._model_id}/{self._device_id}/file")
        self._publish(topic, "file", action, data or {})

    def motors_off(self):
        """Desligar motores.
        Tópico confirmado pelo sniffer: web/.../axis  action=turnOff
        """
        self._pub_web_axis("turnOff")
        self.motors_state.emit(False)

    def home(self, axes="XYZ"):
        """Home via tópico web/.../axis confirmado pelo sniffer.
        Mapeamento axis confirmado:
          axis=3  → Z
          axis=4  → XY
          axis=5  → XYZ (All)
        move_type=2 e distance=0 sempre.
        """
        axes = axes.upper()
        if axes in ("XYZ", "ALL", ""):
            axis_code = 5
        elif axes == "XY":
            axis_code = 4
        elif axes == "Z":
            axis_code = 3
        else:
            axis_code = 2
        self._pub_web_axis("move", {"axis": axis_code, "move_type": 2, "distance": 0})

    def jog(self, axis: str, distance: float):
        """Movimento relativo via MQTT axis/move — confirmado pelo sniffer."""
        axis_map = {"X": 1, "Y": 2, "Z": 3}
        axis_code = axis_map.get(axis.upper(), 1)
        move_type = 1 if distance > 0 else 0
        self._pub_web_axis("move", {
            "axis":      axis_code,
            "move_type": move_type,
            "distance":  abs(distance),
        })

    def camera_start(self):
        """Iniciar stream de câmera.
        Tópico confirmado pelo sniffer: web/.../video  action=startCapture
        """
        if not self._check_ready("video/startCapture"): return
        topic = (f"anycubic/anycubicCloud/v1/web/printer/"
                 f"{self._model_id}/{self._device_id}/video")
        self._publish(topic, "video", "startCapture", {})

    def camera_stop(self):
        """Parar stream de câmera.
        Tópico confirmado pelo sniffer: web/.../video  action=stopCapture
        """
        if not self._check_ready("video/stopCapture"): return
        topic = (f"anycubic/anycubicCloud/v1/web/printer/"
                 f"{self._model_id}/{self._device_id}/video")
        self._publish(topic, "video", "stopCapture", {})

    def _pub_web_ace(self, action, data):
        """Tópico correto para ACE Pro — confirmado pelo sniffer do Slicer Next.
        Usa: .../web/printer/{self._model_id}/{device_id}/multiColorBox
        Action names corretos: getInfo, setDry, setAutoFeed, feedFilament
        """
        if not self._check_ready(f"multiColorBox/{action}"): return
        topic = (f"anycubic/anycubicCloud/v1/web/printer/"
                 f"{self._model_id}/{self._device_id}/multiColorBox")
        self._publish(topic, "multiColorBox", action, data)

    def ace_auto_refill(self, enabled):
        """Auto feed/refill ACE Pro.
        Tópico: web/.../multiColorBox  action=setAutoFeed (confirmado sniffer)
        """
        val = 1 if enabled else 0
        self._pub_web_ace("setAutoFeed", {
            "multi_color_box": [{"id": 0, "auto_feed": val}]
        })

    def ace_drying(self, enabled, target_temp=45, duration=240):
        """Enable/disable drying ACE Pro.
        Tópico: web/.../multiColorBox  action=setDry (confirmado sniffer)
        Payload confirmado: {"multi_color_box": [{"id":0, "drying_status":{...}}]}
        """
        if enabled:
            data = {
                "multi_color_box": [{
                    "id": 0,
                    "drying_status": {
                        "status":      1,
                        "target_temp": target_temp,
                        "duration":    duration,   # minutos
                    }
                }]
            }
        else:
            data = {
                "multi_color_box": [{
                    "id": 0,
                    "drying_status": {"status": 0}
                }]
            }
        self._pub_web_ace("setDry", data)

    def ace_feed(self, slot_index=0):
        """Alimentar filamento no slot N.
        Tópico: web/.../multiColorBox  action=feedFilament (a confirmar com sniffer)
        """
        self._pub_web_ace("feedFilament", {
            "multi_color_box": [{
                "id": 0,
                "feed_status": {"slot_index": slot_index, "type": 1}
            }]
        })

    def ace_unfeed(self, slot_index=0):
        """Retrair filamento do ACE Pro.
        Tópico: web/.../multiColorBox  action=feedFilament type=2
        """
        self._pub_web_ace("feedFilament", {
            "multi_color_box": [{
                "id": 0,
                "feed_status": {"slot_index": -1, "type": 2}
            }]
        })

    def ace_extrude(self, slot_index=0, distance=10):
        """Extrudar filamento via ACE Pro feedFilament (MQTT).
        type=1 = alimentar para frente.
        """
        self._pub_web_ace("feedFilament", {
            "multi_color_box": [{
                "id": 0,
                "feed_status": {"slot_index": slot_index, "type": 1}
            }]
        })

    def ace_retract(self, slot_index=0, distance=10):
        """Retrair filamento via ACE Pro feedFilament (MQTT).
        type=2 = retrair.
        """
        self._pub_web_ace("feedFilament", {
            "multi_color_box": [{
                "id": 0,
                "feed_status": {"slot_index": slot_index, "type": 2}
            }]
        })

    def ace_set_slot(self, slot_index):
        """Selecionar slot ativo do ACE Pro"""
        self._pub_web_ace("setSlot", {"index": slot_index})

    def request_info(self):
        self._request_info()

    def request_file_list(self):
        """Solicita listagem de arquivos via MQTT."""
        self._pub_web_file("fileList", {"root": "local"})

    # ── Conexão LAN ───────────────────────────────────────────────────────
    def _do_connect_lan(self):
        # Incrementa contador a cada tentativa
        

        # Só mostra o log inicial na 1ª tentativa e a cada 20
        if self._lan_fail_count == 1 or self._lan_fail_count % 20 == 0:
            self._emit_log(f"→ TLS {self._host}:{LAN_PORT}  user={self._mqtt_user}")

        try:
            ssl_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            ssl_ctx.set_ciphers('ALL:@SECLEVEL=0')
            ssl_ctx.check_hostname = False
            ssl_ctx.verify_mode = ssl.CERT_NONE

            try:
                client = mqtt.Client(
                    mqtt.CallbackAPIVersion.VERSION1,
                    client_id=self._mqtt_cid,
                    clean_session=True,
                    protocol=mqtt.MQTTv311
                )
            except AttributeError:
                client = mqtt.Client(
                    client_id=self._mqtt_cid,
                    clean_session=True,
                    protocol=mqtt.MQTTv311
                )

            client.reconnect_delay_set(min_delay=0, max_delay=0)

            client.username_pw_set(self._mqtt_user, self._mqtt_pass)
            client.tls_set_context(ssl_ctx)
            client.tls_insecure_set(True)
            client.on_connect = self._on_connect
            client.on_disconnect = self._on_disconnect
            client.on_message = self._on_message

            def on_log(c, ud, level, buf):
                if level <= 8:
                    self._emit_log(f"  paho: {buf}")
            client.on_log = on_log

            self._client = client
            client.connect(self._host, LAN_PORT, keepalive=60)
            client.loop_start()

            # Conectou com sucesso: reseta contador
            self._lan_fail_count = 0

        except OSError as e:
            
            # Só mostra erro na 1ª tentativa e a cada 20
            if self._lan_fail_count == 1 or self._lan_fail_count % 6 == 0:
                self.connection_error.emit(
                    f"Não foi possível conectar a {self._host}:{LAN_PORT}\n\n"
                    f"IP correto? ({self._host})\nImpressora ligada e na rede?\n\nErro: {e}"
                )
            # Reseta contador ao atingir 20
            self._lan_fail_count += 1
            if self._lan_fail_count >= 6:
                self._lan_fail_count = 0
            
        except Exception as e:
            import traceback
            if self._lan_fail_count == 9 or self._lan_fail_count % 15 == 0:
                self.connection_error.emit(f"MQTT erro:\n{type(e).__name__}: {e}\n\n{traceback.format_exc()[-600:]}")
            self._lan_fail_count += 1
            if self._lan_fail_count >= 15:
                self._lan_fail_count = 0



    def _do_connect_lan_OLD(self):
        self._emit_log(f"→ TLS {self._host}:{LAN_PORT}  user={self._mqtt_user}")
        try:
            ssl_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            ssl_ctx.set_ciphers('ALL:@SECLEVEL=0')
            ssl_ctx.check_hostname = False
            ssl_ctx.verify_mode    = ssl.CERT_NONE

            try:
                client = mqtt.Client(
                    mqtt.CallbackAPIVersion.VERSION1,
                    client_id=self._mqtt_cid,
                    clean_session=True,
                    protocol=mqtt.MQTTv311
                )
            except AttributeError:
                client = mqtt.Client(
                    client_id=self._mqtt_cid,
                    clean_session=True,
                    protocol=mqtt.MQTTv311
                )

            # Desabilitar reconexão automática — broker Mochi cria loop infinito
            client.reconnect_delay_set(min_delay=0, max_delay=0)

            client.username_pw_set(self._mqtt_user, self._mqtt_pass)
            client.tls_set_context(ssl_ctx)
            client.tls_insecure_set(True)
            client.on_connect    = self._on_connect
            client.on_disconnect = self._on_disconnect
            client.on_message    = self._on_message

            def on_log(c, ud, level, buf):
                if level <= 8:
                    self._emit_log(f"  paho: {buf}")
            client.on_log = on_log

            self._client = client
            client.connect(self._host, LAN_PORT, keepalive=60)
            client.loop_start()

        except OSError as e:
            self.connection_error.emit(
                f"Não foi possível conectar a {self._host}:{LAN_PORT}\n\n"
                f"IP correto? ({self._host})\nImpressora ligada e na rede?\n\nErro: {e}"
            )
        except Exception as e:
            import traceback
            self.connection_error.emit(f"MQTT erro:\n{type(e).__name__}: {e}\n\n{traceback.format_exc()[-600:]}")

    def _destroy_client(self):
        c = self._client
        self._client = None
        self._connected_flag = False
        if c:
            self._stopping = True   # evita que on_disconnect dispare o signal
            try: c.loop_stop()
            except: pass
            try: c.disconnect()
            except: pass
            self._stopping = False

    # ── Callbacks ─────────────────────────────────────────────────────────
    def _on_connect(self, client, ud, flags, rc, *args):
        rc_int = rc if isinstance(rc, int) else (rc.value if hasattr(rc, 'value') else int(str(rc)))
        msgs   = {0:"OK", 1:"Protocolo inválido", 2:"Client ID rejeitado",
                  3:"Broker indisponível", 4:"Credenciais inválidas", 5:"Não autorizado"}
        self._emit_log(f"  CONNACK rc={rc_int} ({msgs.get(rc_int, str(rc))})")

        if rc_int != 0:
            self.connection_error.emit(
                f"Broker recusou: rc={rc_int} — {msgs.get(rc_int,'?')}\n\n"
                "rc=4/5: execute SSH FETCH novamente."
            ); return

        self._emit_log(f"✓ CONECTADO (LAN)  cid={self._mqtt_cid}")
        self._connected_flag = True

        did = self._device_id
        subs = [
            f"anycubic/anycubicCloud/v1/printer/public/{self._model_id}/{did or '+'}/#",
            f"anycubic/anycubicCloud/v1/printer/app/{self._model_id}/{did or '+'}/#",
        ]
        for t in subs:
            self._emit_log(f"  subscribe: {t}")
            client.subscribe(t)

        self._request_info()       # pedir estado imediatamente
        self._poll.start(10_000)   # poll completo a cada 10s
        self._heartbeat.start(15_000)  # heartbeat leve a cada 15s
        self.connected.emit()

    def _on_disconnect(self, client, ud, rc, *args):
        self._connected_flag = False
        self._poll.stop()
        self._heartbeat.stop()
        rc_int = rc if isinstance(rc, int) else (rc.value if hasattr(rc, 'value') else 0)
        self._emit_log(f"Disconnect rc={rc_int}")
        if not self._stopping:
            self.disconnected.emit(
                "Conexão perdida — clique Reconectar" if rc_int != 0 else "Desconectado"
            )
    @property
    def _model_id(self) -> str:
        return getattr(self, "_detected_model_id", MODEL_ID)

    def _on_message(self, client, ud, msg):
        # Atualiza timestamp de resposta — evita wake() falso
        self._last_response_ts = time.time()
        try:
            payload = json.loads(msg.payload)
        except Exception:
            return

        topic = msg.topic

        # Atualiza timestamp da última resposta — usado pelo wake() para detectar standby
        self._last_response_ts = time.time()

        # EMITE O SINAL message_received PARA QUALQUER TÓPICO
        # Isso é importante - FAÇA ISSO PRIMEIRO
        self.message_received.emit(topic, payload)

        # Auto-detectar device_id
        if not self._device_id:
            parts = topic.split("/")
            if len(parts) >= 7 and parts[4] in ("public", "app"):
                detected_model = parts[5]   # ← model_id está aqui
                did = parts[6]
                if did and did != "+":
                    self._device_id = did
                    self._emit_log(f"  device_id detectado: {did}")
                    self.device_id_found.emit(did)
                    for t in [
                        f"anycubic/anycubicCloud/v1/printer/public/{self._model_id}/{did}/#",
                        f"anycubic/anycubicCloud/v1/printer/app/{self._model_id}/{did}/#",
                    ]:
                        client.subscribe(t)

        suffix = "/".join(topic.split("/")[7:]) if len(topic.split("/")) > 7 else topic
        data   = payload.get("data", {}) or {}

        # ── info/report — contém temp, status, fans ────────────────────────
        if topic.endswith("/info/report"):
            # Capturar URL de upload de arquivo (renovada a cada info/report)
            urls = data.get("urls", {})
            if urls and urls.get("fileUploadurl"):
                self._upload_url = urls["fileUploadurl"]
                self._emit_log(f"  fileUploadurl atualizada: {self._upload_url[:80]}...")

            # Extrair temperaturas do campo "temp" que vem dentro de data
            temp = data.get("temp", {})
            if temp:
                self.printer_info.emit({"_source": "temp", "data": {
                    "bed_actual":     temp.get("curr_hotbed_temp",   0),
                    "bed_target":     temp.get("target_hotbed_temp", 0),
                    "hotend0_actual": temp.get("curr_nozzle_temp",   0),
                    "hotend0_target": temp.get("target_nozzle_temp", 0),
                }})
            self.printer_info.emit(payload)

        # ── tempature/report — push automático de temperatura ─────────────
        elif topic.endswith("/tempature/report"):
            if data:
                temp_payload = {
                    "bed_actual":     data.get("curr_hotbed_temp",   0),
                    "bed_target":     data.get("target_hotbed_temp", 0),
                    "hotend0_actual": data.get("curr_nozzle_temp",   0),
                    "hotend0_target": data.get("target_nozzle_temp", 0),
                }
                self.printer_info.emit({"_source": "temp", "data": temp_payload})
                # Emite também como print_report para atualizar widget de progresso
                self.print_report.emit({"data": {
                    "curr_hotbed_temp":  data.get("curr_hotbed_temp",   0),
                    "curr_nozzle_temp":  data.get("curr_nozzle_temp",   0),
                    "target_hotbed_temp": data.get("target_hotbed_temp", 0),
                    "target_nozzle_temp": data.get("target_nozzle_temp", 0),
                }})

        # ── axis/report — resultado de jog/home ───────────────────────────
        elif topic.endswith("/axis/report"):
            state_ax = data.get("state", "") if data else ""
            code_ax  = data.get("code",  0)  if data else 0

            if state_ax == "failed" and code_ax == 10901:
                # 10901 = home não executado = motores desabilitados
                self._emit_log("  axis/report: motores desabilitados (10901)")
                self._set_motors_state(False)
            elif state_ax == "done":
                self._set_motors_state(True)
                self._emit_log("  axis/report: done → motores habilitados")
            elif state_ax == "failed":
                self._emit_log(f"  axis/report: falha code={code_ax}")

        # ── print/report — atualizar taskid atual ─────────────────────────
        elif topic.endswith("/print/report"):
            tid = data.get("taskid")
            if tid and str(tid) != "-1":
                self._current_taskid = str(tid)
            action_pr = payload.get("action", "")
            state_pr  = data.get("state", "") if data else ""
            code_pr   = data.get("code",  0)  if data else 0
            msg_pr    = data.get("msg",   "") if data else ""

            # Emite erro de print apenas uma vez por ocorrência (evita spam)
            if code_pr and code_pr != 200 and state_pr in ("failed", "stoped"):
                last_err = getattr(self, "_last_print_error_code", None)
                if last_err != code_pr:
                    self._last_print_error_code = code_pr
                    self.print_error.emit(code_pr, msg_pr)
            elif state_pr not in ("failed", "stoped"):
                # Reset ao sair de estado de erro
                self._last_print_error_code = None

            if action_pr in ("finish", "complete", "stop", "cancel", "failed", "stoped"):
                self._current_taskid = "-1"
                self.printer_info.emit({"_source": "status", "status": "idle"})
            self.print_report.emit(payload)

        # ── status/report — heartbeat de estado da impressora ─────────────
        elif topic.endswith("/status/report"):
            action_sr = payload.get("action", "")
            state_sr  = data.get("state", "") if data else ""
            if action_sr == "workReport" and not data:
                self.printer_info.emit({"_source": "status", "status": "idle"})
            elif state_sr:
                self.printer_info.emit({"_source": "status", "status": state_sr})

        # ── multiColorBox/report — ACE Pro ────────────────────────────────
        elif topic.endswith("/multiColorBox/report"):
            action = payload.get("action", "?")
            if data:
                # Logar primeira vez ou mudanças de drying/autoFeed
                if action in ("getInfo", "query") and not getattr(self, "_multicolor_logged", False):
                    self._multicolor_logged = True
                    self._emit_log(f"  multiColorBox [{action}]: {json.dumps(data)[:1000]}")
                elif action in ("setDry", "autoUpdateDryStatus"):
                    dry = data.get("multi_color_box", [{}])[0].get("drying_status", {})
                    self._emit_log(f"  multiColorBox [{action}]: drying={dry}")
                self.printer_info.emit({"_source": "multicolor", "data": data})
            else:
                self._emit_log(f"  multiColorBox [{action}] data vazio (ACK)")

        # ── light/report ──────────────────────────────────────────────────
        elif topic.endswith("/light/report"):
            if data:
                # Formato: {"lights": [{"type":2,"status":1,"brightness":100}]}
                # type=2 = luz principal KS1 (controlamos)
                # type=3 = report automático de status
                lights = data.get("lights", [])
                if lights:
                    l = lights[0]
                    lt, ls, lb = l.get("type"), l.get("status"), l.get("brightness", 0)
                    self._emit_log(f"  light: type={lt} status={ls} bright={lb}")
                    # Emitir estado real para sincronizar botão na UI
                    self.printer_info.emit({
                        "_source": "light",
                        "status":  ls,
                        "brightness": lb,
                        "type": lt,
                    })
                else:
                    # Formato antigo: data direto
                    lt = data.get("type")
                    ls = data.get("status")
                    lb = data.get("brightness", 0)
                    self._emit_log(f"  light: type={lt} status={ls} bright={lb}")
                    self.printer_info.emit({
                        "_source": "light",
                        "status":  ls,
                        "brightness": lb,
                        "type": lt,
                    })

        # ── fan/report — push automático de fans ──────────────────────────
        elif topic.endswith("/fan/report"):
            if data:
                self._emit_log(f"  RCV [fan/report] fan/query data={json.dumps(data)}")
                self.printer_info.emit({"_source": "fan", "data": data})

        # ── file/report — listagem de arquivos ────────────────────────────
        elif topic.endswith("/file/report"):
            action = payload.get("action", "")
            if action == "fileList" and data:
                files = data.get("files") or data.get("file_list") or []
                if isinstance(files, list):
                    self._emit_log(f"  file/report: {len(files)} arquivo(s)")
                    self.file_list.emit(files)
                else:
                    self._emit_log(f"  file/report data: {json.dumps(data)[:200]}")

        # ── video/report — resposta ao startCapture com URL real do stream ───
        elif topic.endswith("/video/report"):
            action = payload.get("action", "")
            if data:
                stream_url = (
                    data.get("url") or data.get("stream_url") or
                    data.get("videoUrl") or data.get("video_url") or ""
                )
                if stream_url:
                    self._emit_log(f"  video/report: stream_url={stream_url}")
                    self.printer_info.emit({"_source": "video", "stream_url": stream_url})
                else:
                    self._emit_log(f"  video/report [{action}]: data={json.dumps(data)[:200]}")
            else:
                self._emit_log(f"  video/report [{action}]: ACK (sem data)")

        # ── response vazio = ACK de sucesso (normal) — ignorar silenciosamente ─
        elif suffix == "response" and not data:
            pass   # ACK normal do broker/impressora

        # ── tópicos não mapeados → logar para diagnóstico ───────────────────
        else:
            self._emit_log(
                f"  RCV [{suffix}] {payload.get('type','?')}/{payload.get('action','?')}"
                f" data={json.dumps(data)[:300]}"
            )

    
    # ── Helpers ───────────────────────────────────────────────────────────
    def _emit_log(self, text):
        import sys
        print(text, file=sys.stderr)
        self.device_id_found.emit(f"__LOG__:{text}")

    def _check_ready(self, action=""):
        if not self._client or not self._connected_flag:
            self._emit_log(f"  ignorado (desconectado): {action}")
            return False
        if not self._device_id:
            self._emit_log(f"  ignorado (sem device_id): {action}")
            return False
        return True

    # ── Publishers com os tópicos corretos conforme Rinkhals wiki ─────────

    def _pub_slicer(self, type_, action, data):
        """Tópico slicer — comandos gerais"""
        if not self._check_ready(f"{type_}/{action}"): return
        topic = f"anycubic/anycubicCloud/v1/slicer/printer/{self._model_id}/{self._device_id}"
        self._publish(topic, type_, action, data)

    def _pub_slicer_info(self):
        """Info query — tópico especial .../info"""
        if not self._check_ready("info/query"): return
        topic = f"anycubic/anycubicCloud/v1/slicer/printer/{self._model_id}/{self._device_id}/info"
        payload = {"type": "info", "action": "query", "msgid": _mid(), "timestamp": _ts()}
        self._emit_log(f"  PUB info/query → {self._device_id[:8]}")
        try:
            self._client.publish(topic, json.dumps(payload), qos=0)
        except Exception as e:
            self._emit_log(f"  Publish error: {e}")

    def _pub_slicer_print(self, action, data):
        """Print control — tópico .../slicer/.../print"""
        if not self._check_ready(f"print/{action}"): return
        topic = f"anycubic/anycubicCloud/v1/slicer/printer/{self._model_id}/{self._device_id}/print"
        self._publish(topic, "print", action, data)

    def _pub_web(self, type_, action, data, path="print"):
        """Temperatura, velocidade, fans, flow — tópico .../web/.../{path}"""
        if not self._check_ready(f"{type_}/{action}"): return
        topic = f"anycubic/anycubicCloud/v1/web/printer/{self._model_id}/{self._device_id}/{path}"
        self._publish(topic, type_, action, data)

    def _pub_web_light(self, data):
        """Luz — tópico .../web/.../light"""
        if not self._check_ready("light/control"): return
        topic = f"anycubic/anycubicCloud/v1/web/printer/{self._model_id}/{self._device_id}/light"
        self._publish(topic, "light", "control", data)

    def _publish(self, topic, type_, action, data):
        payload = {
            "type":      type_,
            "action":    action,
            "msgid":     _mid(),
            "timestamp": _ts(),
            "data":      data,
        }
        short = topic.split("/")[-1]
        self._emit_log(f"  PUB {type_}/{action} → .../{short}  data={json.dumps(data)}")
        try:
            self._client.publish(topic, json.dumps(payload), qos=0)
        except Exception as e:
            self._emit_log(f"  Publish error: {e}")

    def _set_motors_state(self, enabled: bool):
        """Emite motors_state apenas quando o estado muda — evita spam de signals."""
        current = getattr(self, "_motors_enabled_state", None)
        if current != enabled:
            self._motors_enabled_state = enabled
            self.motors_state.emit(enabled)
            self._emit_log(f"  motors_state → {'HABILITADO' if enabled else 'DESABILITADO'}")

    def wake(self) -> bool:
        """Acorda a impressora enviando lastWill + info/query.
        O sniffer confirmou que o AnycubicSlicer envia lastWill antes dos queries.
        Retorna True se a impressora parece estar dormindo (sem resposta há >20s).
        """
        if not self._connected_flag or not self._device_id:
            return False
        elapsed = time.time() - self._last_response_ts
        is_sleeping = elapsed > 60.0   # 60s — evita wake falso durante inicializacao da camera
        # lastWill — confirmado pelo sniffer como primeiro query do slicer
        self._pub_last_will()
        self._pub_slicer_info()
        if self._heartbeat.isActive():
            self._heartbeat.start(15_000)
        if is_sleeping:
            self._emit_log(f"  wake: impressora sem resposta há {elapsed:.0f}s — aguardando acordar")
        return is_sleeping

    def _send_heartbeat(self):
        """Heartbeat leve — lastWill + info/query para manter a impressora acordada."""
        if not self._connected_flag or not self._device_id:
            return
        self._pub_last_will()
        self._pub_slicer_info()

    def _pub_last_will(self):
        """lastWill query — confirmado pelo sniffer como parte do ciclo de wake do slicer."""
        if not self._check_ready("lastWill/query"): return
        topic = f"anycubic/anycubicCloud/v1/web/printer/{self._model_id}/{self._device_id}/lastWill"
        payload = {"type": "lastWill", "action": "query",
                   "msgid": _mid(), "timestamp": _ts(), "data": None}
        try:
            self._client.publish(topic, json.dumps(payload), qos=0)
        except Exception:
            pass

    def _request_info(self):
        """
        Pede status geral, igual ao Slicer Next ao conectar.
        Sequência confirmada pelo sniffer:
          web/.../lastWill (query)  ← primeiro, confirmado pelo sniffer
          web/.../status, info, tempature, fan, peripherie, light (query)
          slicer/.../info (query)
          web/.../multiColorBox (getInfo) — com delay 2.5s
        """
        # lastWill primeiro — exatamente como o AnycubicSlicer faz
        self._pub_last_will()
        base_w = f"anycubic/anycubicCloud/v1/web/printer/{self._model_id}/{self._device_id}"
        for path in ("status", "info", "tempature", "fan", "peripherie", "light"):
            if not self._connected_flag:
                return
            topic = f"{base_w}/{path}"
            payload = {"type": path, "action": "query",
                       "msgid": _mid(), "timestamp": _ts(), "data": {}}
            try:
                self._client.publish(topic, json.dumps(payload), qos=0)
            except Exception:
                pass
        self._pub_slicer_info()
        QMetaObject.invokeMethod(
            self,
            "_schedule_ace_query",
            Qt.ConnectionType.QueuedConnection,
        )

    @pyqtSlot()
    def _schedule_ace_query(self):
        """Sempre chamado na thread Qt — agenda query ACE Pro com delay."""
        QTimer.singleShot(2500, self._request_ace_info)

    def _request_ace_info(self):
        """Solicitar status completo do ACE Pro.
        Tópico confirmado pelo sniffer: web/.../multiColorBox  action=getInfo
        Retorna todos os slots + drying_status + auto_feed + loaded_slot.
        """
        if not self._connected_flag:
            return
        self._pub_web_ace("getInfo", {})