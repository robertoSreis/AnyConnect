# -*- coding: utf-8 -*-
"""
SE3D Gestor — Entry point
  - Sem argumentos : abre como controlador de impressora normalmente
  - Com argumento .gcode : vai para aba PRINT → tela de color mapping / pós-processamento
"""

import sys
import os
import re
import copy
import json

# Fix encoding para Windows com paths internacionais
if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

from PyQt6.QtWidgets import QApplication, QMessageBox
from PyQt6.QtCore import QTimer
from PyQt6.QtGui import QIcon
from ui.main_window import MainWindow
sys.path.append(os.getcwd())


from ui.print_widget import parse_gcode_meta


# ═══════════════════════════════════════════════════════════════════════════
#  GCodePatcher — incorporado nativamente
# ═══════════════════════════════════════════════════════════════════════════

class GCodePatcher:
    """
    Injeta HEADER_BLOCK com paint_info no gcode do OrcaSlicer para
    compatibilidade com Anycubic Kobra S1 / ACE Pro.

    Uso:
        patcher = GCodePatcher(slots_config)
        result  = patcher.process(filepath)
        # result.new_content  → string com gcode processado
        # result.slots_used   → list[int]
        # result.materials    → list[str]
        # result.paint_info   → str JSON
        # result.encoding     → str
    """

    DEFAULT_SLOTS = [
        {"material_type": "ABS", "paint_color": [255, 255, 255], "paint_index": 0},
        {"material_type": "ABS", "paint_color": [40,  40,  40 ], "paint_index": 1},
        {"material_type": "ABS", "paint_color": [255, 0,   0  ], "paint_index": 2},
        {"material_type": "ABS", "paint_color": [0,   0,   255], "paint_index": 3},
    ]

    class Result:
        __slots__ = ("new_content", "slots_used", "materials", "paint_info", "encoding")
        def __init__(self, new_content, slots_used, materials, paint_info, encoding):
            self.new_content = new_content
            self.slots_used  = slots_used
            self.materials   = materials
            self.paint_info  = paint_info
            self.encoding    = encoding

    def __init__(self, slots_config: list | None = None):
        self._slots = slots_config if slots_config else self.DEFAULT_SLOTS

    @staticmethod
    def read_file(filepath: str) -> tuple[str, str]:
        for enc in ("utf-8", "utf-8-sig", "latin-1", "cp1252", "shift_jis", "gbk", "euc-kr"):
            try:
                with open(filepath, "r", encoding=enc) as f:
                    return f.read(), enc
            except (UnicodeDecodeError, LookupError):
                continue
        with open(filepath, "rb") as f:
            raw = f.read()
        return raw.decode("utf-8", errors="replace"), "utf-8"

    @staticmethod
    def has_paint_info(content: str) -> bool:
        return "; paint_info" in content[:1000]

    @staticmethod
    def remove_existing_header(content: str) -> str:
        lines = content.splitlines(keepends=True)
        result, inside = [], False
        for line in lines:
            if "; HEADER_BLOCK_START" in line:
                inside = True
                continue
            if inside and "; HEADER_BLOCK_END" in line:
                inside = False
                continue
            if inside:
                continue
            if "; processed by" in line:
                continue
            result.append(line)
        cleaned, prev_blank = [], False
        for line in result:
            is_blank = line.strip() == ""
            if is_blank and prev_blank:
                continue
            cleaned.append(line)
            prev_blank = is_blank
        return "".join(cleaned)

    @staticmethod
    def detect_used_slots(content: str) -> list[int]:
        used = set()
        for line in content.splitlines():
            m = re.match(r"^T(\d)", line.strip())
            if m:
                used.add(int(m.group(1)))
        return sorted(used)

    @staticmethod
    def detect_materials(content: str) -> list[str]:
        for line in content.splitlines():
            if line.strip().startswith("; filament_type"):
                parts = line.split("=")
                if len(parts) >= 2:
                    return [v.strip() for v in parts[1].strip().split(";")]
        return []

    @staticmethod
    def build_paint_info(slots: list) -> str:
        items = []
        for s in slots:
            r, g, b = s["paint_color"]
            items.append(
                '{"material_type":"' + s["material_type"] + '",'
                '"paint_color":[' + str(r) + ',' + str(g) + ',' + str(b) + '],'
                '"paint_index":'  + str(s["paint_index"]) + '}'
            )
        return "[" + ",".join(items) + "]"

    @staticmethod
    def fix_thumbnail_spacing(content: str) -> str:
        lines = content.splitlines(keepends=True)
        result = []
        for i, line in enumerate(lines):
            if i < 20 and line.strip() == "":
                continue
            result.append(line)
        return "".join(result)

    @staticmethod
    def _find_thumbnail_end(content: str) -> int:
        """Retorna índice após o último '; thumbnail end' (0 se não houver)."""
        last_end = -1
        pos = 0
        while True:
            idx = content.find("; thumbnail end", pos)
            if idx == -1:
                break
            last_end = idx
            pos = idx + 1
        if last_end == -1:
            return 0
        nl = content.find("\n", last_end)
        return nl + 1 if nl != -1 else len(content)

    def inject_object_z(self, content: str) -> str:
        """
        Injeta safe-Z APENAS UMA VEZ por objeto, sem duplicar.
        """
        import re
        
        if "EXCLUDE_OBJECT_START" not in content:
            return content
        
        lines = content.splitlines(keepends=True)
        result = []
        last_z = 0.0
        last_injected_obj = None
        
        for line in lines:
            ls = line.strip()
            
            # Extrai Z atual de qualquer linha G1/G0
            mz = re.search(r'[Zz]([\d.]+)', ls)
            if mz and re.match(r'G[01]\b', ls):
                last_z = float(mz.group(1))
            
            # Injeta safe-Z apenas se for um objeto NOVO (não repetido)
            if ls.startswith("EXCLUDE_OBJECT_START"):
                match = re.search(r'NAME=(\S+)', ls)
                obj_name = match.group(1) if match else None
                
                if obj_name and obj_name != last_injected_obj:
                    result.append(f"G1 Z{last_z:.3f} F900 ; for object exclusion\n")
                    last_injected_obj = obj_name
            
            result.append(line)
        
        return "".join(result)

    def process(self, filepath: str) -> "GCodePatcher.Result":
        """Lê o gcode e detecta slots/materiais usados.
        NÃO injeta paint_info — a impressora usa o arquivo .acm separado.
        O arquivo de saída (.gcode.3mf) é o gcode original sem modificações,
        apenas com a extensão correta para o servidor aceitar.
        """
        content, encoding = self.read_file(filepath)
        #content = self.inject_object_z(content) inject Z
        slots_used = self.detect_used_slots(content)
        materials  = self.detect_materials(content)

        slots = copy.deepcopy(self._slots)
        if slots_used:
            filtered = [s for s in slots if s.get("paint_index") in slots_used]
            if not filtered:
                filtered = slots
        else:
            filtered = slots

        if materials:
            for s in filtered:
                idx = s.get("paint_index", 0)
                if idx < len(materials) and materials[idx]:
                    s["material_type"] = materials[idx]

        paint_info = self.build_paint_info(filtered)

        # Retorna conteúdo original como bytes — extensão .gcode.3mf é aplicada
        # no momento do upload (mqtt_client), não aqui
        new_content = content.encode("utf-8")

        return self.Result(
            new_content = new_content,
            slots_used  = slots_used,
            materials   = materials,
            paint_info  = paint_info,
            encoding    = encoding,
        )

    @staticmethod
    def _patch_paint_info_bytes(raw: bytes, paint_info: str) -> bytes:
        return raw  # não mais utilizado


# ═══════════════════════════════════════════════════════════════════════════
#  GCode3mfPacker — empacota .gcode em .gcode.3mf para a impressora Anycubic
# ═══════════════════════════════════════════════════════════════════════════

class GCode3mfPacker:
    """
    Empacota um .gcode em .gcode.3mf com a estrutura exata gerada pelo
    AnycubicSlicerNext — confirmada por inspeção de arquivos reais.

    Estrutura:
      [Content_Types].xml
      _rels/.rels
      3D/3dmodel.model
      Metadata/_rels/model_settings.config.rels
      Metadata/model_settings.config
      Metadata/plate_1.gcode          ← gcode completo
      Metadata/plate_1.gcode.md5      ← MD5 do gcode
      Metadata/plate_1.gcode.metadata ← header do gcode (até HEADER_BLOCK_END + thumbnail)
      Metadata/slice_info.config
      Metadata/plate_1.png            ← thumbnail (se existir no gcode)
      Metadata/plate_1_small.png
    """

    CONTENT_TYPES = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">\n'
        ' <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>\n'
        ' <Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/>\n'
        ' <Default Extension="png" ContentType="image/png"/>\n'
        ' <Default Extension="gcode" ContentType="text/x.gcode"/>\n'
        ' <Default Extension="config" ContentType="application/xml"/>\n'
        ' <Default Extension="md5" ContentType="text/plain"/>\n'
        ' <Default Extension="metadata" ContentType="text/x.gcode"/>\n'
        '</Types>'
    )

    RELS = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">\n'
        ' <Relationship Target="/3D/3dmodel.model" Id="rel-1"'
        ' Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/>\n'
        ' <Relationship Target="/Metadata/plate_1.png" Id="rel-2"'
        ' Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/thumbnail"/>\n'
        ' <Relationship Target="/Metadata/plate_1.png" Id="rel-4"'
        ' Type="http://schemas.bambulab.com/package/2021/cover-thumbnail-middle"/>\n'
        ' <Relationship Target="/Metadata/plate_1_small.png" Id="rel-5"'
        ' Type="http://schemas.bambulab.com/package/2021/cover-thumbnail-small"/>\n'
        '</Relationships>'
    )

    RELS_NO_THUMB = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">\n'
        ' <Relationship Target="/3D/3dmodel.model" Id="rel-1"'
        ' Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/>\n'
        '</Relationships>'
    )

    MODEL_SETTINGS_RELS = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">\n'
        ' <Relationship Target="/Metadata/plate_1.gcode" Id="rel-1" '
        'Type="http://schemas.bambulab.com/package/2021/gcode"/>'
        
    )

    @staticmethod
    def _make_3dmodel(title: str = "", date: str = "") -> str:
        import datetime
        d = date or datetime.date.today().isoformat()
        return (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<model unit="millimeter" xml:lang="en-US"'
            ' xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02"'
            ' xmlns:BambuStudio="http://schemas.bambulab.com/package/2021"'
            ' xmlns:p="http://schemas.microsoft.com/3dmanufacturing/production/2015/06"'
            ' requiredextensions="p">\n'
            f' <metadata name="Application">SE3D-Gestor</metadata>\n'
            f' <metadata name="BambuStudio:3mfVersion">1</metadata>\n'
            f' <metadata name="CreationDate">{d}</metadata>\n'
            f' <metadata name="ModificationDate">{d}</metadata>\n'
            f' <metadata name="Title">{title}</metadata>\n'
            ' <metadata name="Thumbnail_Middle">/Metadata/plate_1.png</metadata>\n'
            ' <metadata name="Thumbnail_Small">/Metadata/plate_1_small.png</metadata>\n'
            ' <resources>\n </resources>\n <build/>\n</model>'
        )

    @staticmethod
    def _make_model_settings(stats: dict, has_thumb: bool) -> str:
        import re
        import xml.etree.ElementTree as ET
        from xml.dom import minidom

        def time_to_sec(t):
            m = re.search(r'(\d+)m\s*(\d+)s', t)
            return int(m.group(1)) * 60 + int(m.group(2)) if m else 0

        time_sec = time_to_sec(stats.get("estimated_time_raw", "0m 0s"))
        used_g   = stats.get("used_g", "0").replace("g", "").split(",")[0]

        # 🔧 Monta XML com ElementTree
        config = ET.Element("config")
        plate = ET.SubElement(config, "plate")

        def add_meta(key, value):
            ET.SubElement(plate, "metadata", key=key, value=str(value))

        add_meta("plater_id", 1)
        add_meta("plater_name", "plate-1")
        add_meta("locked", "false")
        add_meta("gcode_file", "Metadata/plate_1.gcode")

        if has_thumb:
            add_meta("thumbnail_file", "Metadata/plate_1.png")
            add_meta("top_file", "Metadata/top_1.png")
            add_meta("pick_file", "Metadata/pick_1.png")
            add_meta("pattern_bbox_file", "Metadata/plate_1.json")
            add_meta("prediction", time_sec)
            add_meta("weight", used_g)

        # 🔥 Converte para string bruta
        rough_string = ET.tostring(config, encoding="utf-8")

        # 🔥 Formata corretamente (resolve indentação)
        reparsed = minidom.parseString(rough_string)
        pretty_xml = reparsed.toprettyxml(indent="    ", encoding="UTF-8")

        # 🔧 Remove linhas em branco extras (importante)
        pretty_xml = b"\n".join(
            line for line in pretty_xml.splitlines() if line.strip()
        )

        return pretty_xml.decode("utf-8")
    

    @staticmethod
    def _make_slice_info(filaments: list | None,
                        printer: str = "Anycubic Kobra S1",
                        stats: dict | None = None) -> str:

        import re

        stats = stats or {}
        filaments = filaments or []

        def time_to_sec(t):
            if not isinstance(t, str):
                return 0
            m = re.search(r'(\d+)m\s*(\d+)s', t)
            return int(m.group(1)) * 60 + int(m.group(2)) if m else 0

        # proteção contra valores inválidos
        estimated_raw   = stats.get("estimated_time_raw", "0m 0s")
        used_g_raw      = stats.get("used_g", "0")
        used_m_raw      = stats.get("used_m", "0")
        total_layers    = stats.get("total_layers", "0")
        nozzle_diameter = stats.get("nozzle_diameter", "0.4")

        try:
            time_sec = time_to_sec(estimated_raw)
        except:
            time_sec = 0

        try:
            used_g = str(used_g_raw).replace("g", "").split(",")[0]
        except:
            used_g = "0"

        try:
            used_m = str(used_m_raw)
        except:
            used_m = "0"

        # ── Filamentos ─────────────────────────────
        fil_lines = ""
        for i, f in enumerate(filaments, 1):
            try:
                color = f.get("color", "#000000")
                mat   = f.get("material", "PLA")
            except:
                color = "#000000"
                mat   = "PLA"

            fil_lines += (
                f'        <filament id="{i}" tray_info_idx="GF{mat}" type="{mat}"'
                f' color="{color}" used_m="{used_m}" used_g="{used_g}"/>\n'
                f'        <warning msg="bed_temperature_too_high_than_filament"'
                f' level="1" error_code ="1000C001"  />\n'
            )

        # ── XML FINAL ─────────────────────────────
        return (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<config>\n'
            '    <header>\n'
            '        <header_item key="X-ACNext-Client-Type" value="slicer"/>\n'
            '        <header_item key="X-ACNext-Client-Version" value="1.3.9.4 20260319225535"/>\n'
            '    </header>\n'
            '    <plate>\n'
            '        <metadata key="index" value="1"/>\n'
            f'        <metadata key="printer_model_id" value="{printer}"/>\n'
            f'        <metadata key="nozzle_diameters" value="{nozzle_diameter}"/>\n'
            '        <metadata key="timelapse_type" value="0"/>\n'
            '        <metadata key="support_used" value="true"/>\n'
            '        <metadata key="label_object_enabled" value="false"/>\n'
            f'        <metadata key="nozzle_diameters" value="{nozzle_diameter}"/>\n'
            f'        <metadata key="prediction" value="{time_sec}s"/>\n'
            f'        <metadata key="total_layers" value="{total_layers}"/>\n'
            f'        <metadata key="weight" value="{used_g}"/>\n'
            f'{fil_lines}'
            '    </plate>\n'
            '</config>\n'
        )
            
            

        # ── XML FINAL ─────────────────────────────
        #<print>
        #    <estimated_time>{time_sec}</estimated_time>
        #    <total_layers>{total_layers}</total_layers>
        #</print>
        
        return f'''<?xml version="1.0" encoding="UTF-8"?>
        <config>
        <header>
            <header_item key="X-ACNext-Client-Type" value="slicer"/>
            <header_item key="X-ACNext-Client-Version" value="1.3.9.4 20260319225535"/>
        </header>
        <plate>
            <metadata key="index" value="1"/>
            <metadata key="printer_model_id" value="{printer}"/>
            <metadata key="timelapse_type" value="0"/>
            <metadata key="support_used" value="true"/>
            <metadata key="label_object_enabled" value="false"/>
            <metadata key="prediction" value="{time_sec}s"/>
            <metadata key="total_layers" value="{total_layers}"/>
            <metadata key="weight" value="{used_g}"/>
            {fil_lines}
        </plate>
        </config>
        '''
        

    @staticmethod
    def _extract_thumbnails(gcode: str) -> dict[str, bytes]:
        import base64
        thumbs, current_key, current_data, in_thumb = {}, None, [], False
        for line in gcode.splitlines():
            line = line.strip()
            if line.startswith("; thumbnail begin"):
                parts = line.split()
                current_key  = parts[3] if len(parts) >= 4 else "unknown"
                current_data = []
                in_thumb     = True
            elif line.startswith("; thumbnail end"):
                if current_key and current_data:
                    try:
                        thumbs[current_key] = base64.b64decode("".join(current_data))
                    except Exception:
                        pass
                in_thumb = False
            elif in_thumb and line.startswith(";"):
                current_data.append(line[1:].strip())
        return thumbs

    @staticmethod
    def _best_thumb(thumbs: dict, target_w: int) -> bytes | None:
        best, best_diff = None, 99999
        for key, data in thumbs.items():
            try:
                w    = int(key.split("x")[0])
                diff = abs(w - target_w)
                if diff < best_diff:
                    best_diff, best = diff, data
            except Exception:
                pass
        return best

    @staticmethod
    def _extract_metadata_section(gcode: str) -> str:
        """
        Extrai o conteúdo do plate_1.gcode.metadata conforme gerado pelo
        AnycubicSlicerNext, INCLUINDO o thumbnail top-down como terceiro bloco.

        Estrutura do metadata:
        1. HEADER_BLOCK (com paint_info, source_info, etc.)
        2. THUMBNAIL_BLOCK(s) - TODOS os thumbnails (incluindo o top-down)
        3. Linhas de configuração por extrusor
        4. EXECUTABLE_BLOCK_START
        5. EXCLUDE_OBJECT_DEFINE NAME=...
        6. Setup de máquina até EXECUTABLE_BLOCK_HEAD
        7. EXECUTABLE_BLOCK_END
        8. CONFIG_BLOCK + statistics
        9. CONFIG_BLOCK_END
        """
        lines = gcode.splitlines(keepends=True)
        result = []
        i = 0
        total = len(lines)

        # ── Fase 1: tudo antes de EXECUTABLE_BLOCK_START ────────────────────
        while i < total:
            line = lines[i]
            ls = line.strip()
            i += 1
            if ls == "; EXECUTABLE_BLOCK_START":
                result.append(line)
                break
            result.append(line)

        # ── Fase 2: DEFINEs + setup de máquina até EXECUTABLE_BLOCK_HEAD ────
        has_exec_head = "; EXECUTABLE_BLOCK_HEAD" in gcode
        in_exec_body = False

        while i < total:
            line = lines[i]
            ls = line.strip()
            i += 1

            # CONFIG_BLOCK encontrado — vai para fase 3
            if (ls == "; EXECUTABLE_BLOCK_END" or
                    ls.startswith("; CONFIG_BLOCK_START") or
                    ls.startswith("; AnycubicSlicer_config = begin") or
                    ls.startswith("; OrcaSlicer_config = begin")):
                if not in_exec_body:
                    # Ainda não fechamos o bloco executável — fechar agora
                    result.append("\n")
                    result.append("; EXECUTABLE_BLOCK_HEAD\n")
                    result.append("\n")
                    result.append("; EXECUTABLE_BLOCK_END\n")
                    in_exec_body = True
                # Só emite a linha do CONFIG se não for EXECUTABLE_BLOCK_END
                if ls != "; EXECUTABLE_BLOCK_END":
                    result.append("\n")
                    result.append(line)
                break

            if has_exec_head:
                # Com EXECUTABLE_BLOCK_HEAD: inclui tudo até HEAD e fecha
                if ls == "; EXECUTABLE_BLOCK_HEAD":
                    result.append(line)
                    # Adiciona EXECUTABLE_BLOCK_END logo após HEAD
                    result.append("\n")
                    result.append("; EXECUTABLE_BLOCK_END\n")
                    in_exec_body = True
                    continue
                if not in_exec_body:
                    result.append(line)
            else:
                # Sem EXECUTABLE_BLOCK_HEAD (OrcaSlicer)
                if in_exec_body:
                    continue

                if ls.startswith("EXCLUDE_OBJECT_DEFINE"):
                    result.append(line)
                elif re.match(r'EXCLUDE_OBJECT_START\b', ls):
                    # Chegou no primeiro objeto — fecha o bloco executável
                    result.append("\n")
                    result.append("; EXECUTABLE_BLOCK_HEAD\n")
                    result.append("\n")
                    result.append("; EXECUTABLE_BLOCK_END\n")
                    in_exec_body = True
                elif re.match(r';LAYER_CHANGE\b', ls):
                    result.append("\n")
                    result.append("; EXECUTABLE_BLOCK_HEAD\n")
                    result.append("\n")
                    result.append("; EXECUTABLE_BLOCK_END\n")
                    in_exec_body = True
                elif (re.match(r'M\d+\b', ls) or
                    re.match(r'G9\d+\b', ls) or
                    re.match(r'G9[0-9]', ls) or
                    re.match(r'G[239][0-9]', ls) or
                    re.match(r'[TG]\d+\s*$', ls) or
                    ls.startswith(";") or
                    ls == ""):
                    result.append(line)
                else:
                    result.append("\n")
                    result.append("; EXECUTABLE_BLOCK_HEAD\n")
                    result.append("\n")
                    result.append("; EXECUTABLE_BLOCK_END\n")
                    in_exec_body = True

        # ── Fase 3: CONFIG_BLOCK + statistics ────────────────────────────────
        while i < total:
            line = lines[i]
            ls = line.strip()
            i += 1
            # Pular EXECUTABLE_BLOCK_END do gcode original
            if ls == "; EXECUTABLE_BLOCK_END":
                continue
            result.append(line)

        return "".join(result)


    @staticmethod
    def _inject_paint_info(gcode: str, slots: list) -> str:
        """Garante que paint_info está no HEADER_BLOCK do gcode, na posição correta.

        Posição correta (confirmada pelo AnycubicSlicerNext):
          HEADER_BLOCK_START
          ; generated by ...
          ; total layer number: N
          ...campos de hardware...
          ; exclude_object: 1          ← injetado por _inject_orca_header_fields
          ; model_instances: N
          ; source_info: {...}
          ; paint_info = [...]          ← AQUI, depois de source_info
          ; project_info = {...}
          HEADER_BLOCK_END

        _inject_paint_info é chamado ANTES de _inject_orca_header_fields,
        então quando paint_info já existe não há problema. Quando não existe,
        injeta imediatamente antes do HEADER_BLOCK_END para que fique no final
        do header (posição correta), não no início.
        """
        
        import re as _re

        paint_items = []
        for s in slots:
            r, g, b = s.get("paint_color", [0, 0, 0])[:3]
            mat     = s.get("material_type", "ABS")
            # Slots vindos do MQTT têm campo "index"; settings têm "paint_index"
            idx     = s.get("paint_index", s.get("index", 0))
            paint_items.append(
                f'{{"material_type":"{mat}",'
                f'"paint_color":[{r},{g},{b}],'
                f'"paint_index":{idx}}}'
            )
        paint_line = "; paint_info = [" + ",".join(paint_items) + "]\n"
        gcode = _re.sub(r'; paint_info\s*=\s*\[.*?\]\n?', '', gcode, count=1)

        # Injeta imediatamente antes do HEADER_BLOCK_END → fica no final do header
        if "; HEADER_BLOCK_END" in gcode:
            return gcode.replace(
                "; HEADER_BLOCK_END",
                paint_line + "; HEADER_BLOCK_END",
                1
            )
        # Fallback: sem HEADER_BLOCK, coloca no início
        return paint_line + gcode

    @staticmethod
    def _inject_orca_header_fields(gcode: str, paint_info_line: str = "") -> str:
        """
        Adiciona ao HEADER_BLOCK os campos que o GoKlipper da KS1 exige para
        ativar o skip de objetos no display da impressora.

        Ordem exata confirmada pelo AnycubicSlicerNext (arquivo de referência):
        ; HEADER_BLOCK_START
        ; generated by ...
        ; total layer number: N
        ; filament_density: ...
        ; filament_diameter: ...
        ; max_z_height: ...
        ; exclude_object: {N-1}     ← NÚMERO DE OBJETOS - 1 (0-indexed)
        ; model_instances: N
        ; source_info: {...}
        ; paint_info = [...]        ← entre source_info e project_info
        ; project_info = {...}      ← usa "=" não ":"
        ; flush_multiplier_...: 1
        ; test_mode: 0
        ; HEADER_BLOCK_END
        """
        import re

        names = list(dict.fromkeys(re.findall(r'EXCLUDE_OBJECT_DEFINE NAME=(\S+)', gcode)))
        if not names:
            return gcode

        n = len(names)
        # CORREÇÃO: exclude_object deve ser N-1 (0-indexed para skip máximo)
        exclude_object_value = 1# n - 1 if n > 0 else 0
        
        models_json = ",".join(
            f'{{"file_source":0,"mo_file_id":-1,"name":"{name}"}}'
            for name in names
        )
        source_info = (
            f'{{"models":[{models_json}],'
            f'"models_from":0,"plate_index":1,'
            f'"slice_paras_process":1,'
            f'"software_version":"OrcaSlicer (converted by SE3D Hub System: www.se3d.com.br)"}}'
        )
        # paint_info vai entre source_info e project_info
        paint_block = (paint_info_line + "\n") if paint_info_line else ""
        # project_info usa "=" — confirmado pelo arquivo Anycubic de referência
        
        inject_lines = (
            f"; exclude_object: {exclude_object_value}\n"  # ← CORRIGIDO: N-1
            f"; model_instances: {n}\n"
            f"; source_info: {source_info}\n"
            + paint_block +
            f'; project_info = {{"flush_multiplier":1.0,'
            f'"flush_volumes_chan_multipliers":[1.0,1.0,1.0,1.0],'
            f'"flush_volumes_matrix":[0.0],'
            f'"flush_volumes_vector":[140.0,140.0]}}\n'
            f"; flush_multiplier_calculate_by_acnext: 1\n"
            f"; test_mode: 0\n"
        )

        if "; HEADER_BLOCK_END" in gcode:
            return gcode.replace(
                "; HEADER_BLOCK_END",
                inject_lines + "; HEADER_BLOCK_END",
                1
            )
        else:
            header_block = (
                "; HEADER_BLOCK_START\n"
                "; generated by OrcaSlicer (converted by SE3D Hub System: www.se3d.com.br)\n"
                + inject_lines
                + "; HEADER_BLOCK_END\n\n"
            )
            return header_block + gcode

    @staticmethod
    def _inject_executable_block_head(gcode: str) -> str:
        """
        Injeta '; EXECUTABLE_BLOCK_HEAD' no gcode principal (plate_1.gcode) quando
        ausente. O GoKlipper usa esse marcador no gcode para saber onde o setup
        termina e onde começa a impressão real — sem ele, o skip de objetos não funciona.

        Estratégia: injeta imediatamente antes da primeira linha que seja
        EXCLUDE_OBJECT_START, ;LAYER_CHANGE ou ; FLUSH_START que apareça após
        as linhas de DEFINEs/setup (ou seja, após M83 / G9111 / G90 / G21).
        Se nenhuma dessas âncoras for encontrada, não faz nada.
        """
        import re as _re

        if "; EXECUTABLE_BLOCK_HEAD" in gcode:
            return gcode  # já tem

        if "; EXECUTABLE_BLOCK_START" not in gcode:
            return gcode  # sem estrutura de bloco, não mexe

        lines = gcode.splitlines(keepends=True)
        result = []
        in_exec = False
        injected = False

        # Âncoras que marcam "fim do setup / início da impressão real"
        _anchors = (
            "EXCLUDE_OBJECT_START",
            ";LAYER_CHANGE",
            "; FLUSH_START",
        )

        for line in lines:
            ls = line.strip()

            if ls == "; EXECUTABLE_BLOCK_START":
                in_exec = True
                result.append(line)
                continue

            if in_exec and not injected:
                if any(ls.startswith(a) for a in _anchors):
                    result.append("; EXECUTABLE_BLOCK_HEAD\n")
                    injected = True

            result.append(line)

        return "".join(result)

    @staticmethod
    def _parse_gcode_stats(gcode: str) -> dict:
        import re

        stats = {}

        for line in gcode.splitlines():
            ls = line.strip()

            # Tempo (pega qualquer variação)
            if "estimated printing time" in ls.lower():
                stats["estimated_time_raw"] = ls.split("=", 1)[-1].strip()

            # Filamento em gramas
            elif "filament used [g]" in ls.lower():
                stats["used_g"] = ls.split("=", 1)[-1].strip()

            # Filamento em mm → converte pra metros
            elif "filament used [mm]" in ls.lower():
                val = ls.split("=", 1)[-1].strip()
                try:
                    stats["used_m"] = str(round(float(val) / 1000, 2))
                except:
                    pass

            # Camadas
            elif "total layers count" in ls.lower() or "total layer number" in ls.lower():
                stats["total_layers"] = ls.split("=", 1)[-1].strip()

        return stats

    @staticmethod
    def _parse_filament_info(gcode: str) -> list:
        """
        Extrai lista de filamentos do CONFIG_BLOCK para preencher used_m/used_g
        no slice_info. Retorna lista de dicts {material, color, used_m, used_g}.
        """
        import re

        # Extrai used_filament total
        used_m = "0"
        m = re.search(r"; used_filament\s*=\s*(\S+)", gcode)
        if m:
            used_m = m.group(1)

        # Extrai cor do filamento
        color = "#C8C8C8"
        m = re.search(r"; filament_colour\s*=\s*(#[0-9A-Fa-f]{6,8})", gcode)
        if m:
            hex_c = m.group(1)[:7]  # ignora alpha
            color = hex_c

        # Extrai material
        mat = "PLA"
        m = re.search(r"; filament_type\s*=\s*(\S+)", gcode)
        if m:
            mat = m.group(1).strip().rstrip(";")

        return [{"material": mat, "color": color, "used_m": used_m, "used_g": "0"}]
        """
        Extrai o gcode interno de um .gcode.3mf, salva como .gcode temporário
        e retorna o path. Permite reprocessar arquivos vindos do AnycubicSlicerNext.
        """
        import zipfile, tempfile, os
        with zipfile.ZipFile(gcode_3mf_path, "r") as z:
            # Procura o gcode dentro do zip
            gcode_entry = None
            for name in z.namelist():
                if name.endswith(".gcode") and not name.endswith(".metadata"):
                    gcode_entry = name
                    break
            if not gcode_entry:
                # Fallback: retorna o próprio arquivo (vai falhar no pack, mas não trava)
                return gcode_3mf_path
            gcode_bytes = z.read(gcode_entry)

        # Salva ao lado do .gcode.3mf original
        base = gcode_3mf_path
        for suf in (".gcode.3mf", ".3mf"):
            if base.lower().endswith(suf):
                base = base[:-len(suf)]
                break
        out_path = base + "_extracted.gcode"
        with open(out_path, "wb") as f:
            f.write(gcode_bytes)
        return out_path

    @staticmethod
    def _extract_paint_info_json(gcode: str):
        """Extrai o array JSON do paint_info respeitando brackets aninhados."""
        import json as _j
        marker = "; paint_info = ["
        idx = gcode.find(marker)
        if idx < 0:
            return None
        start = idx + len(marker) - 1  # aponta para o [
        depth = 0
        for i in range(start, len(gcode)):
            if gcode[i] == "[":
                depth += 1
            elif gcode[i] == "]":
                depth -= 1
                if depth == 0:
                    try:
                        return _j.loads(gcode[start:i + 1])
                    except Exception:
                        return None
        return None

    @staticmethod
    def _make_single_color_gcode(gcode: str) -> tuple:
        """
        Para uso sem ACE Pro: garante paint_info de 1 slot (single color)
        e retorna (gcode_modificado, filament_dict) para o slice_info.
        Extrai material do proprio gcode se possivel.
        """
        import re

        # Tentar reusar paint_info ja existente se for exatamente 1 slot
        items = GCode3mfPacker._extract_paint_info_json(gcode)
        if items and len(items) == 1:
            s = items[0]
            rgb = s.get("paint_color", [200, 200, 200])
            mat = s.get("material_type", "PLA")
            filament = {"material": mat, "color": "#{:02X}{:02X}{:02X}".format(*rgb[:3])}
            return gcode, filament

        # Extrair material do footer do gcode
        mat = "PLA"
        m_mat = re.search(r"; filament_type\s*=\s*([A-Za-z0-9+]+)", gcode)
        if m_mat:
            mat = m_mat.group(1).strip()

        rgb = [200, 200, 200]
        filament = {"material": mat, "color": "#{:02X}{:02X}{:02X}".format(*rgb)}

        # Remover paint_info existente (qualquer numero de slots) linha a linha
        lines = gcode.split("\n")
        lines = [l for l in lines if not l.startswith("; paint_info")]
        gcode = "\n".join(lines)

        # Injetar paint_info de 1 slot
        paint_line = (f'; paint_info = [{{"material_type":"{mat}",'
                      f'"paint_color":[{rgb[0]},{rgb[1]},{rgb[2]}],"paint_index":0}}]')
        if "; HEADER_BLOCK_START" in gcode:
            gcode = gcode.replace("; HEADER_BLOCK_START\n",
                                  "; HEADER_BLOCK_START\n" + paint_line + "\n", 1)
        else:
            gcode = paint_line + "\n" + gcode

        return gcode, filament


    @staticmethod
    def _normalize_orca_speeds(gcode: str) -> str:
        """
        Corrige os valores de aceleração/jerk do OrcaSlicer para a Anycubic KS1.
 
        O OrcaSlicer gera perfis para Marlin/RepRap com M204 P600 / M205 X9 Y9
        por camada. No GoKlipper da KS1 esses valores são interpretados literalmente
        e ficam persistentes, reduzindo a velocidade a ~3% do normal e tornando
        Home/Park extremamente lentos após Stop.
 
        Valores corretos da KS1 (do EXECUTABLE_BLOCK_START do AnycubicSlicerNext):
          M201 X20000 Y20000 Z1000 E20000   (max aceleração)
          M204 P20000 R20000 T20000          (print/retract/travel accel)
          M205 X15.00 Y15.00 Z15.00 E15.00  (jerk)
 
        Estratégia: substituir M204 Pn por valores seguros quando n < 5000,
        e M205 Xn Yn quando n < 12. Preserva valores altos (já corretos).
        Remove M566 (comando RRF que o GoKlipper ignora mas pode confundir).
        """
        import re
 
        lines = gcode.splitlines(keepends=True)
        result = []
 
        # Valores mínimos aceitáveis — abaixo disso substitui pelo correto da KS1
        MIN_PRINT_ACCEL  = 5000    # M204 P
        MIN_TRAVEL_ACCEL = 5000    # M204 T
        MIN_RETRACT_ACCEL = 5000   # M204 R
        MIN_JERK         = 12.0    # M205 X / Y
 
        KS1_PRINT_ACCEL   = 20000
        KS1_TRAVEL_ACCEL  = 20000
        KS1_RETRACT_ACCEL = 20000
        KS1_JERK          = 15.0
 
        for line in lines:
            ls = line.strip()
 
            # M204 — aceleração: P=print, T=travel, R=retract
            # Pode vir como "M204 P600" ou "M204 P20000 T20000" ou "M204 T600"
            if re.match(r'M204\b', ls):
                new_parts = ['M204']
                # Extrair cada parâmetro
                for m in re.finditer(r'([PTR])([\d.]+)', ls):
                    flag, val = m.group(1), float(m.group(2))
                    if flag == 'P' and val < MIN_PRINT_ACCEL:
                        val = KS1_PRINT_ACCEL
                    elif flag == 'T' and val < MIN_TRAVEL_ACCEL:
                        val = KS1_TRAVEL_ACCEL
                    elif flag == 'R' and val < MIN_RETRACT_ACCEL:
                        val = KS1_RETRACT_ACCEL
                    new_parts.append(f"{flag}{int(val)}")
                # Preservar comentário inline se existir
                comment = ""
                if ";" in ls:
                    comment = " " + ls[ls.index(";"):]
                result.append(" ".join(new_parts) + comment + "\n")
                continue
 
            # M205 — jerk: X, Y (Z e E podem ficar)
            if re.match(r'M205\b', ls):
                new_parts = ['M205']
                for m in re.finditer(r'([XYZE])([\d.]+)', ls):
                    flag, val = m.group(1), float(m.group(2))
                    if flag in ('X', 'Y') and val < MIN_JERK:
                        val = KS1_JERK
                    if flag in ('X', 'Y'):
                        new_parts.append(f"{flag}{val:.2f}")
                    else:
                        new_parts.append(f"{flag}{m.group(2)}")
                comment = ""
                if ";" in ls:
                    comment = " " + ls[ls.index(";"):]
                result.append(" ".join(new_parts) + comment + "\n")
                continue
 
            # M566 — jerk em mm/min (RRF/Duet) — GoKlipper ignora, mas remove
            # para evitar conflito com M205 já corrigido
            if re.match(r'M566\b', ls):
                result.append(f"; {ls}  ; removed: RRF jerk cmd not used by GoKlipper\n")
                continue
 
            result.append(line)
 
        return "".join(result)



    @staticmethod
    def _convert_orca_to_klipper_objects(gcode: str) -> str:
        """
        Converte os marcadores de objeto do OrcaSlicer (Marlin M486) para
        o protocolo nativo do Klipper/GoKlipper (EXCLUDE_OBJECT_*).
        Versão corrigida - NÃO PULA LINHAS do restante do gcode.
        """
        import re

        lines = gcode.splitlines(keepends=True)
        
        # ── PASSO 1: mapa índice → nome ──────────────────────────────────────
        idx_to_name: dict[int, str] = {}
        for line in lines:
            m = re.match(r'M486 S(\d+) A"([^"]+)"', line.strip())
            if m:
                idx_to_name[int(m.group(1))] = m.group(2)

        if not idx_to_name:
            return gcode  # não é gcode do Orca com objetos definidos

        # ── PASSO 2: coletar coordenadas XY por objeto ───────────────────────
        obj_coords: dict[str, list] = {name: [] for name in idx_to_name.values()}
        current_obj: str | None = None

        for line in lines:
            ls = line.strip()
            m_start = re.match(r'M486 S(\d+)$', ls)
            if m_start:
                idx = int(m_start.group(1))
                current_obj = idx_to_name.get(idx)
                continue
            if ls == 'M486 S-1':
                current_obj = None
                continue
            if current_obj:
                mxy = re.match(r'G[01]\b.*?X([\d.\-]+).*?Y([\d.\-]+)', ls)
                if mxy:
                    obj_coords[current_obj].append(
                        (float(mxy.group(1)), float(mxy.group(2)))
                    )

        # ── PASSO 3: calcular CENTER e POLYGON ───────────────────────────────
        MARGIN = 2.0
        obj_defines: dict[str, str] = {}
        for name, coords in obj_coords.items():
            if coords:
                xs = [c[0] for c in coords]
                ys = [c[1] for c in coords]
                cx = round((min(xs) + max(xs)) / 2, 3)
                cy = round((min(ys) + max(ys)) / 2, 3)
                x0 = round(min(xs) - MARGIN, 3)
                x1 = round(max(xs) + MARGIN, 3)
                y0 = round(min(ys) - MARGIN, 3)
                y1 = round(max(ys) + MARGIN, 3)
                poly = (f"[[{x0},{y0}],[{x1},{y0}],"
                        f"[{x1},{y1}],[{x0},{y1}],[{x0},{y0}]]")
                obj_defines[name] = (
                    f"EXCLUDE_OBJECT_DEFINE NAME={name} "
                    f"CENTER={cx},{cy} POLYGON={poly}\n"
                )
            else:
                obj_defines[name] = (
                    f"EXCLUDE_OBJECT_DEFINE NAME={name} "
                    f"CENTER=0,0 POLYGON=[[0,0],[1,0],[1,1],[0,1],[0,0]]\n"
                )

        # ── PASSO 4: reescrever o gcode ──────────────────────────────────────
        result = []
        defines_injected = False
        i = 0
        total = len(lines)

        while i < total:
            line = lines[i]
            ls = line.strip()
            
            # ── Pular linhas M486 do header (definições) ───────────────────
            if re.match(r'M486 S\d+ A"', ls):
                i += 1
                continue
            
            # Quando encontrar ;TYPE:Custom, mantém ele e adiciona os comandos abaixo SUBSTITUIÇÃO DE PARTE DO CÓDIGO
            if re.match(r';TYPE:Custom', ls):
                result.append(line)  # Mantém o ;TYPE:Custom original
                # Adiciona os comandos personalizados logo abaixo
                result.append("M73 P0 R206.6 QuietR280.2 SportR199.9 ; NormalR12393.505s\n")
                result.append("M201 X20000 Y20000 Z1000 E20000\n")
                result.append("M203 X600 Y600 Z15 E600\n")
                result.append("M204 P20000 R20000 T20000\n")
                i += 1
                continue

            
            # ── Injetar DEFINE logo após EXECUTABLE_BLOCK_START ──────────────
            if '; EXECUTABLE_BLOCK_START' in ls and not defines_injected:
                result.append(line)
                for name in sorted(idx_to_name.values()):
                    if name in obj_defines:
                        result.append(obj_defines[name])
                defines_injected = True
                i += 1
                continue

            # ── Converter M486 Sn (início) → EXCLUDE_OBJECT_START ────────────
            m_start = re.match(r'M486 S(\d+)$', ls)
            if m_start:
                idx = int(m_start.group(1))
                name = idx_to_name.get(idx, f"obj_{idx}")
                # Preserva Z atual (busca no buffer recente)
                current_z = 0.0
                for prev_line in reversed(result[-50:]):
                    mz = re.search(r'[Zz]([\d.]+)', prev_line)
                    if mz and re.match(r'G[01]\b', prev_line.strip()):
                        current_z = float(mz.group(1))
                        break
                safe_z = f"G1 Z{current_z:.3f} F900 ; for object exclusion\n"
                result.append(safe_z)
                result.append(f"EXCLUDE_OBJECT_START NAME={name}\n")
                i += 1
                continue

            # ── Converter M486 S-1 (fim) → EXCLUDE_OBJECT_END ─────────────────
            if ls == 'M486 S-1':
                # Busca nome do objeto ativo (do último START)
                active_name = None
                for prev_line in reversed(result[-100:]):
                    if 'EXCLUDE_OBJECT_START NAME=' in prev_line:
                        match = re.search(r'EXCLUDE_OBJECT_START NAME=(\S+)', prev_line)
                        if match:
                            active_name = match.group(1)
                            break
                if active_name:
                    # Busca Z atual
                    current_z = 0.0
                    for prev_line in reversed(result[-50:]):
                        mz = re.search(r'[Zz]([\d.]+)', prev_line)
                        if mz and re.match(r'G[01]\b', prev_line.strip()):
                            current_z = float(mz.group(1))
                            break
                    safe_z = f"G1 Z{current_z:.3f} F900 ; for object exclusion\n"
                    result.append(safe_z)
                    result.append(f"EXCLUDE_OBJECT_END NAME={active_name}\n")
                i += 1
                continue

            # ── Linha normal - preservar SEMPRE ──────────────────────────────
            result.append(line)
            i += 1

        return "".join(result)

    @staticmethod
    def _generate_topdown_thumb(gcode: str, img_size: int = 512,
                                    bed_size: tuple = (250, 250),
                                    object_scale: float = 1.2,
                                    font_scale: float = 0.5,
                                    output_mode: str = "RGBA",
                                    show_grid: bool = False,
                                    show_bed: bool = False,
                                    add_text: bool = False,
                                    crop_blank: bool = False,
                                    rotation: int = 0,
                                    optimize_compression: bool = True
                                    ) -> bytes | None:
        try:
            from PIL import Image, ImageDraw, ImageFont
        except ImportError:
            return None

        import json as _j
        import re
        import io

        # ── 1. Extrair defines ────────────────────────────────────────────────────
        defines = re.findall(
            r'EXCLUDE_OBJECT_DEFINE NAME=(\S+) CENTER=([\d.\-]+),([\d.\-]+) POLYGON=(\[\[.*?\]\])',
            gcode
        )
        if not defines:
            return None

        # ── 2. Extrair cores do paint_info ────────────────────────────────────────
        colors_rgb: list[tuple] = []
        m = re.search(r'; paint_info = (\[.*?\])', gcode[:5000])
        if m:
            try:
                slots_info = _j.loads(m.group(1))
                colors_rgb = [tuple(s['paint_color'][:3]) for s in slots_info]
            except Exception:
                pass

        # ── 3. Mapear objeto → slot ───────────────────────────────────────────────
        obj_slot_map: dict[str, int] = {}
        last_t = 0
        for line in gcode.splitlines():
            ls = line.strip()
            tm = re.match(r'^T(\d+)\s*$', ls)
            if tm:
                last_t = int(tm.group(1))
            m2 = re.match(r'EXCLUDE_OBJECT_START NAME=(\S+)', ls)
            if m2:
                name = m2.group(1)
                if name not in obj_slot_map:
                    obj_slot_map[name] = last_t

        # ── 4. Parse polígonos — Y invertido ───────────────────────────────────────
        bed_width, bed_height = bed_size
        parsed: list[tuple] = []

        for name, cx, cy, poly_str in defines:
            try:
                poly = _j.loads(poly_str)
                inv_poly = [(float(p[0]), bed_height - float(p[1])) for p in poly]
                inv_cx = float(cx)
                inv_cy = bed_height - float(cy)
                parsed.append((name, inv_cx, inv_cy, inv_poly))
            except Exception:
                pass

        if not parsed:
            return None

        # ── 5. Aplicar object_scale em torno do centro dos objetos ────────────────
        # CORREÇÃO: Calcular centro ANTES de aplicar a escala
        all_pts = [p for _, _, _, poly in parsed for p in poly]
        if all_pts:
            cx_all = (min(p[0] for p in all_pts) + max(p[0] for p in all_pts)) / 2
            cy_all = (min(p[1] for p in all_pts) + max(p[1] for p in all_pts)) / 2
        else:
            cx_all, cy_all = bed_width / 2, bed_height / 2

        # Aplica escala a partir do centro
        if object_scale != 1.0:
            scaled = []
            for name, cx, cy, poly in parsed:
                s_cx = cx_all + (cx - cx_all) * object_scale
                s_cy = cy_all + (cy - cy_all) * object_scale
                s_poly = [(cx_all + (px - cx_all) * object_scale,
                        cy_all + (py - cy_all) * object_scale) for px, py in poly]
                scaled.append((name, s_cx, s_cy, s_poly))
            parsed = scaled

        # ── 6. Calcular bounding box após escala ───────────────────────────────────
        if crop_blank:
            all_pts_final = [p for _, _, _, poly in parsed for p in poly]
            if all_pts_final:
                min_x = min(p[0] for p in all_pts_final)
                max_x = max(p[0] for p in all_pts_final)
                min_y = min(p[1] for p in all_pts_final)
                max_y = max(p[1] for p in all_pts_final)
                
                # Margem de 2% ao redor dos objetos (bem pequena)
                margin_x = (max_x - min_x) * 0.02 if max_x > min_x else 5
                margin_y = (max_y - min_y) * 0.02 if max_y > min_y else 5
                
                world_x0 = min_x - margin_x
                world_x1 = max_x + margin_x
                world_y0 = min_y - margin_y
                world_y1 = max_y + margin_y
            else:
                # Fallback
                pad = 10
                world_x0 = 0 - pad
                world_x1 = bed_width + pad
                world_y0 = 0 - pad
                world_y1 = bed_height + pad
        else:
            pad_x = bed_width * 0.10
            pad_y = bed_height * 0.10
            world_x0 = 0.0 - pad_x
            world_x1 = bed_width + pad_x
            world_y0 = 0.0 - pad_y
            world_y1 = bed_height + pad_y

        world_w = world_x1 - world_x0
        world_h = world_y1 - world_y0

        # ── 7. Escala para imagem ──────────────────────────────────────────────────
        scale = min(img_size / world_w, img_size / world_h)
        drawn_w = world_w * scale
        drawn_h = world_h * scale
        off_x = (img_size - drawn_w) / 2.0
        off_y = (img_size - drawn_h) / 2.0

        def to_px(wx, wy) -> tuple[float, float]:
            px = (wx - world_x0) * scale + off_x
            py = (wy - world_y0) * scale + off_y
            return px, py

        # ── 8. Criar imagem ───────────────────────────────────────────────────────
        img = Image.new(output_mode, (img_size, img_size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)

        # ── 9. Desenhar polígonos ──────────────────────────────────────────────────
        DEFAULT_COLORS = [
            (255, 80, 80), (80, 160, 255), (80, 220, 120),
            (255, 200, 60), (200, 100, 255), (255, 140, 40),
        ]

        font = None
        if add_text:
            try:
                font_size = max(10, int(img_size * font_scale * 0.05))
                font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", font_size)
            except Exception:
                font = ImageFont.load_default()

        for idx, (name, cx, cy, poly) in enumerate(parsed):
            slot = obj_slot_map.get(name, idx % len(DEFAULT_COLORS))
            
            if colors_rgb and slot < len(colors_rgb):
                color = tuple(int(c) for c in colors_rgb[slot])
            else:
                color = DEFAULT_COLORS[idx % len(DEFAULT_COLORS)]

            pts = [to_px(px, py) for px, py in poly]

            # Preenchimento
            if output_mode == "RGBA":
                overlay = Image.new("RGBA", (img_size, img_size), (0, 0, 0, 0))
                ov_draw = ImageDraw.Draw(overlay)
                ov_draw.polygon(pts, fill=(*color, 180))
                img = Image.alpha_composite(img, overlay)
                draw = ImageDraw.Draw(img)
            else:
                draw.polygon(pts, fill=tuple(c // 4 for c in color))

            draw.polygon(pts, outline=(*color, 255) if output_mode == "RGBA" else color, width=2)

            if add_text:
                label = str(idx + 1)
                lx, ly = to_px(cx, cy)
                bbox = draw.textbbox((0, 0), label, font=font)
                tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
                draw.rectangle(
                    [lx - tw/2 - 4, ly - th/2 - 4, lx + tw/2 + 4, ly + th/2 + 4],
                    fill=(0, 0, 0, 128)
                )
                draw.text((lx - tw/2, ly - th/2), label, fill=(255, 255, 255), font=font)

        # ── 10. Crop final ─────────────────────────────────────────────────────────
        if crop_blank and output_mode == "RGBA":
            bbox = img.getbbox()
            if bbox:
                img = img.crop(bbox)

        # ── 11. Crop final ─────────────────────────────────────────────────────────
        if rotation != 0:
            # Pillow usa anti-horário como positivo, então invertimos o sinal
            img = img.rotate(-rotation, expand=True)

        # ── 12. Salvar ────────────────────────────────────────────────────────────
        buf = io.BytesIO()
        if optimize_compression:
            img.save(buf, format='PNG', optimize=True, compress_level=9)
        else:
            img.save(buf, format='PNG')
        
        return buf.getvalue()
    
    @staticmethod
    def _calculate_areas_from_thumbnail(gcode: str, bed_size: tuple = (250, 250), img_size: int = 512) -> dict:
        """
        Gera a imagem top-down e calcula a área real de cada objeto
        baseado na contagem de pixels coloridos.
        
        Retorna: dict mapeando nome_do_objeto -> área em mm²
        """
        try:
            from PIL import Image
            import io
        except ImportError:
            return {}
        
        # Gerar a imagem top-down
        img_bytes = GCode3mfPacker._generate_topdown_thumb(
            gcode, 
            img_size=img_size, 
            bed_size=bed_size,
            object_scale=1.0,
            output_mode="RGB",  # Usar RGB sem transparência para facilitar
            show_grid=False,
            show_bed=False,
            add_text=False,
            crop_blank=False,
            optimize_compression=False
        )
        
        if not img_bytes:
            return {}
        
        # Abrir imagem
        img = Image.open(io.BytesIO(img_bytes))
        if img.mode != 'RGB':
            img = img.convert('RGB')
        
        pixels = img.load()
        width, height = img.size
        
        # A imagem top-down usa cores diferentes para cada objeto
        # Precisamos mapear as cores do paint_info para os objetos
        import re
        import json as _j
        
        # Extrair paint_info para obter cores
        colors_map = {}
        m = re.search(r'; paint_info = (\[.*?\])', gcode[:5000])
        if m:
            try:
                slots_info = _j.loads(m.group(1))
                for idx, slot in enumerate(slots_info):
                    color = tuple(slot['paint_color'][:3])
                    colors_map[color] = idx
            except Exception:
                pass
        
        # Extrair nomes dos objetos
        defines = re.findall(
            r'EXCLUDE_OBJECT_DEFINE NAME=(\S+) CENTER=([\d.\-]+),([\d.\-]+) POLYGON=(\[\[.*?\]\])',
            gcode
        )
        
        # Mapear qual objeto usa qual cor (baseado na ordem Tn)
        obj_slot_map = {}
        last_t = 0
        for line in gcode.splitlines():
            ls = line.strip()
            tm = re.match(r'^T(\d+)\s*$', ls)
            if tm:
                last_t = int(tm.group(1))
            m2 = re.match(r'EXCLUDE_OBJECT_START NAME=(\S+)', ls)
            if m2:
                name = m2.group(1)
                if name not in obj_slot_map:
                    obj_slot_map[name] = last_t
        
        # Contar pixels por cor
        color_counts = {}
        background_color = (0, 0, 0)  # Preto é o fundo
        
        for y in range(height):
            for x in range(width):
                pixel = pixels[x, y]
                if pixel != background_color and pixel != (0, 0, 0):
                    color_counts[pixel] = color_counts.get(pixel, 0) + 1
        
        # Calcular escala (mm² por pixel)
        # A imagem mostra a área total da cama (bed_size)
        bed_area_mm2 = bed_size[0] * bed_size[1]
        image_area_px = width * height
        mm2_per_pixel = bed_area_mm2 / image_area_px
        
        # Mapear áreas para objetos
        areas = {}
        
        for idx, (name, cx, cy, poly_str) in enumerate(defines):
            slot = obj_slot_map.get(name, idx)
            
            # Encontrar a cor correspondente a este slot
            obj_color = None
            for color, color_slot in colors_map.items():
                if color_slot == slot:
                    obj_color = color
                    break
            
            if obj_color and obj_color in color_counts:
                area_px = color_counts[obj_color]
                area_mm2 = area_px * mm2_per_pixel
                areas[name] = area_mm2
            else:
                # Fallback: usar o método anterior (dividir por 2)
                try:
                    poly = _j.loads(poly_str)
                    xs = [p[0] for p in poly]
                    ys = [p[1] for p in poly]
                    bbox_area = (max(xs) - min(xs)) * (max(ys) - min(ys))
                    areas[name] = bbox_area / 2.0 if len(poly) > 5 else bbox_area
                except Exception:
                    areas[name] = 0.0
        
        return areas

    @staticmethod
    def _generate_plate_json(gcode: str, slots: list | None = None, bed_size: tuple = (250, 250)) -> dict:
        """
        Gera o dicionário para o arquivo plate_1.json baseado no conteúdo do G-code.
        Extrai bounding boxes dos objetos definidos via EXCLUDE_OBJECT_DEFINE.
        Usa a imagem top-down para calcular áreas com precisão.
        """
        import re
        import math

        # Valores padrão
        layer_height = 0.2
        nozzle_diameter = 0.4
        filament_colors = ["#26A69A"]
        filament_ids = [0]
        first_extruder = 0
        bed_type = "hot_plate"
        version = 2
        is_seq_print = False

        # Extrair layer_height do header
        m = re.search(r'; layer_height\s*=\s*([\d.]+)', gcode[:5000])
        if m:
            try:
                layer_height = float(m.group(1))
            except ValueError:
                pass

        # Extrair nozzle_diameter
        m = re.search(r'; nozzle_diameter\s*=\s*([\d.]+)', gcode[:5000])
        if m:
            try:
                nozzle_diameter = float(m.group(1))
            except ValueError:
                pass

        # Extrair cores dos filamentos (do paint_info ou do header)
        if slots:
            filament_colors = []
            filament_ids = []
            for i, s in enumerate(slots):
                r, g, b = s.get("paint_color", [200, 200, 200])[:3]
                filament_colors.append(f"#{r:02X}{g:02X}{b:02X}")
                filament_ids.append(i)
            if filament_ids:
                first_extruder = filament_ids[0]
        else:
            # Tentar extrair do header
            m = re.search(r'; filament_colour\s*=\s*([#0-9A-Fa-f,;]+)', gcode[:5000])
            if m:
                colors_str = m.group(1).strip()
                parts = re.split(r'[;,]\s*', colors_str)
                filament_colors = [p.strip() for p in parts if p.strip()]
                filament_ids = list(range(len(filament_colors)))
                if filament_ids:
                    first_extruder = 0

        # NOVO: Calcular áreas usando a imagem top-down
        areas_from_image = {}
        try:
            # Gerar imagem top-down para análise
            img_bytes = GCode3mfPacker._generate_topdown_thumb(
                gcode,
                img_size=512,
                bed_size=bed_size,
                object_scale=1.0,
                output_mode="RGB",
                show_grid=False,
                show_bed=False,
                add_text=False,
                crop_blank=False,
                optimize_compression=False
            )
            
            if img_bytes:
                from PIL import Image
                import io
                import json as _j
                
                img = Image.open(io.BytesIO(img_bytes))
                if img.mode != 'RGB':
                    img = img.convert('RGB')
                
                pixels = img.load()
                width, height = img.size
                
                # Extrair paint_info para mapear cores
                colors_map = {}
                m = re.search(r'; paint_info = (\[.*?\])', gcode[:5000])
                if m:
                    try:
                        slots_info = _j.loads(m.group(1))
                        for idx, slot in enumerate(slots_info):
                            color = tuple(slot['paint_color'][:3])
                            colors_map[color] = idx
                    except Exception:
                        pass
                
                # Mapear objetos para slots
                obj_slot_map = {}
                last_t = 0
                for line in gcode.splitlines():
                    ls = line.strip()
                    tm = re.match(r'^T(\d+)\s*$', ls)
                    if tm:
                        last_t = int(tm.group(1))
                    m2 = re.match(r'EXCLUDE_OBJECT_START NAME=(\S+)', ls)
                    if m2:
                        name = m2.group(1)
                        if name not in obj_slot_map:
                            obj_slot_map[name] = last_t
                
                # Contar pixels por cor (ignorando preto de fundo)
                color_counts = {}
                for y in range(height):
                    for x in range(width):
                        pixel = pixels[x, y]
                        if pixel != (0, 0, 0):
                            color_counts[pixel] = color_counts.get(pixel, 0) + 1
                
                # Calcular escala (mm² por pixel)
                bed_area_mm2 = bed_size[0] * bed_size[1]
                image_area_px = width * height
                mm2_per_pixel = bed_area_mm2 / image_area_px
                
                # Mapear áreas para os nomes dos objetos
                defines_temp = re.findall(
                    r'EXCLUDE_OBJECT_DEFINE NAME=(\S+)',
                    gcode
                )
                
                for idx, name in enumerate(defines_temp):
                    slot = obj_slot_map.get(name, idx)
                    
                    # Encontrar cor deste slot
                    obj_color = None
                    for color, color_slot in colors_map.items():
                        if color_slot == slot:
                            obj_color = color
                            break
                    
                    if obj_color and obj_color in color_counts:
                        area_px = color_counts[obj_color]
                        area_mm2 = area_px * mm2_per_pixel
                        areas_from_image[name] = area_mm2
                        
        except Exception as e:
            print(f"Aviso: Não foi possível calcular áreas pela imagem: {e}")
            areas_from_image = {}

        # MANTER: Extrair objetos definidos com EXCLUDE_OBJECT_DEFINE
        defines = re.findall(
            r'EXCLUDE_OBJECT_DEFINE NAME=(\S+) CENTER=([\d.\-]+),([\d.\-]+) POLYGON=(\[\[.*?\]\])',
            gcode
        )

        bbox_objects = []
        all_min_x, all_min_y = float('inf'), float('inf')
        all_max_x, all_max_y = float('-inf'), float('-inf')
        obj_id = 1130

        if defines:
            import json as _j
            for idx, (name, cx, cy, poly_str) in enumerate(defines):
                try:
                    poly = _j.loads(poly_str)
                    xs = [p[0] for p in poly]
                    ys = [p[1] for p in poly]
                    min_x = min(xs)
                    max_x = max(xs)
                    min_y = min(ys)
                    max_y = max(ys)
                    
                    # Atualizar bbox global
                    all_min_x = min(all_min_x, min_x)
                    all_min_y = min(all_min_y, min_y)
                    all_max_x = max(all_max_x, max_x)
                    all_max_y = max(all_max_y, max_y)
                    
                    # NOVO: Usar área da imagem se disponível
                    if name in areas_from_image:
                        area = areas_from_image[name]
                    else:
                        # Fallback: método da divisão por 2
                        bbox_area = (max_x - min_x) * (max_y - min_y)
                        is_complex = any(keyword in name.lower() for keyword in ["es", "text", "curve", "circle"]) or len(poly) > 5
                        area = bbox_area / 2.0 if is_complex else bbox_area
                    
                    bbox_objects.append({
                        "area": round(area, 2),
                        "bbox": [min_x, min_y, max_x, max_y],
                        "id": obj_id + idx,
                        "layer_height": layer_height,
                        "name": f"{name}.stl" if not name.endswith(".stl") else name
                    })
                except Exception as e:
                    print(f"Erro ao processar objeto {name}: {e}")
                    continue
        else:
            # Fallback: extrair bounding box global dos movimentos G0/G1
            min_x = min_y = float('inf')
            max_x = max_y = float('-inf')
            for line in gcode.splitlines():
                if line.startswith(('G0', 'G1')):
                    mx = re.search(r'X([\d.\-]+)', line)
                    my = re.search(r'Y([\d.\-]+)', line)
                    if mx and my:
                        x = float(mx.group(1))
                        y = float(my.group(1))
                        min_x = min(min_x, x)
                        max_x = max(max_x, x)
                        min_y = min(min_y, y)
                        max_y = max(max_y, y)
            if min_x != float('inf'):
                all_min_x, all_min_y = min_x, min_y
                all_max_x, all_max_y = max_x, max_y
                bbox_objects.append({
                    "area": round((max_x - min_x) * (max_y - min_y), 2),
                    "bbox": [min_x, min_y, max_x, max_y],
                    "id": obj_id,
                    "layer_height": layer_height,
                    "name": "object.stl"
                })

        # Se não encontrou nada, usar valores padrão
        if all_min_x == float('inf'):
            all_min_x, all_min_y = 0, 0
            all_max_x, all_max_y = bed_size[0], bed_size[1]

        return {
            "bbox_all": [all_min_x, all_min_y, all_max_x, all_max_y],
            "bbox_objects": bbox_objects,
            "bed_type": bed_type,
            "filament_colors": filament_colors,
            "filament_ids": filament_ids,
            "first_extruder": first_extruder,
            "is_seq_print": is_seq_print,
            "nozzle_diameter": nozzle_diameter,
            "version": version
        }



    @staticmethod
    def _replace_topdown_in_gcode(gcode: str, topdown_png: bytes) -> str:
        """
        Adiciona o thumbnail top-down como TERCEIRO bloco.
        Procura o SEGUNDO '; THUMBNAIL_BLOCK_END' e insere o novo bloco depois dele.
        Mantém todos os thumbnails existentes intactos.
        """
        import base64, textwrap
        
        b64 = base64.b64encode(topdown_png).decode('ascii')
        wrapped = '\n'.join('; ' + line for line in textwrap.wrap(b64, 76))
        new_block = (
            f'; THUMBNAIL_BLOCK_START\n'
            f'; thumbnail begin 512x512 {len(topdown_png)} top\n'
            f'{wrapped}\n'
            f'; thumbnail end\n'
            f'; THUMBNAIL_BLOCK_END'
            f'\n'
        )

        # Encontra TODOS os '; THUMBNAIL_BLOCK_END'
        all_ends = list(re.finditer(r'; THUMBNAIL_BLOCK_END', gcode))
        
        # Se tem pelo menos 2 blocos, insere depois do SEGUNDO
        if len(all_ends) >= 2:
            second_end = all_ends[0]  # primeiro '; THUMBNAIL_BLOCK_END'
            insert_pos = second_end.end()
            # Pula possíveis quebras de linha
            while insert_pos < len(gcode) and gcode[insert_pos] in ('\n', '\r'):
                insert_pos += 1
            return gcode[:insert_pos] + '\n' + new_block + '\n' + gcode[insert_pos:]
        
        # Se tem apenas 1 bloco, insere depois do primeiro (vai ser o segundo)
        elif len(all_ends) == 1:
            first_end = all_ends[0]
            insert_pos = first_end.end()
            while insert_pos < len(gcode) and gcode[insert_pos] in ('\n', '\r'):
                insert_pos += 1
            return gcode[:insert_pos] + '\n' + new_block + '\n' + gcode[insert_pos:]
        
        # Se não tem nenhum, usa a lógica original de fallback
        exec_pos = gcode.find('; EXECUTABLE_BLOCK_START')
        search_end = exec_pos if exec_pos >= 0 else min(6000, len(gcode))
        last_end = gcode.rfind('; THUMBNAIL_BLOCK_END', 0, search_end)
        if last_end >= 0:
            insert_pos = gcode.find('\n', last_end) + 1
            return gcode[:insert_pos] + '\n' + new_block + '\n' + gcode[insert_pos:]

        hdr_end = gcode.find('; HEADER_BLOCK_END')
        if hdr_end >= 0:
            insert_pos = gcode.find('\n', hdr_end) + 1
            return gcode[:insert_pos] + '\n' + new_block + '\n' + gcode[insert_pos:]

        return gcode

    @staticmethod
    def _make_project_settings(gcode: str, slots: list | None = None) -> str:
        """
        Gera o Metadata/project_settings.config.
        Parte de um template base (configurações fixas da KS1) e sobrescreve
        os campos dinâmicos extraídos do gcode: layer_height, filament_colour,
        filament_type, filament_density, pressure_advance, etc.
        """
        import json as _j
        import re

        # ── Template base — configurações fixas da Anycubic KS1 ──────────────
        # Este é o mesmo conteúdo do project_settings.config de referência.
        # Lê do arquivo ao lado do executável se existir, senão usa o embutido.
        _script_dir = os.path.dirname(os.path.abspath(__file__))
        _template_path = os.path.join(_script_dir, "project_settings.config")
        if os.path.isfile(_template_path):
            try:
                with open(_template_path, "r", encoding="utf-8") as f:
                    cfg = _j.load(f)
            except Exception:
                cfg = {}
        else:
            cfg = {}

        if not cfg:
            # Fallback mínimo se o arquivo não existir
            cfg = {
                "from": "project",
                "name": "project_settings",
                "printer_model": "Anycubic Kobra S1",
                #"printer_settings_id": "Anycubic Kobra S1 0.4 nozzle",
                "pressure_advance": [
                    "0.065"
                ],
                "printable_area": [
                    "0x0",
                    "256x0",
                    "256x256",
                    "0x256"
                ],
                "standby_temperature_delta": "0",
                "start_end_points": [
                    "30x-3",
                    "54x245"
                ],

                "gcode_flavor": "klipper",
                "version": "1.3.9.4",
                "thumbnails": "230x110/PNG, 512x512/PNG",
                "thumbnails_format": "PNG",
                "thumbnails_internal": "512x512/PNG/top",
                "thumbnails_internal_switch": "1",
            }

        # ── Extrai valores dinâmicos do gcode ─────────────────────────────────
        def _get(pattern, default="", flags=0):
            m = re.search(pattern, gcode[:8000], flags)
            return m.group(1).strip() if m else default

        layer_h = _get(r'; layer_height\s*=\s*([\d.]+)')
        if layer_h:
            cfg["layer_height"] = layer_h

        total_layers = _get(r'; total layer number:\s*(\d+)')
        if total_layers:
            cfg["total_layer_number"] = total_layers

        # Nozzle temperature
        nozzle_temp = _get(r'; nozzle_temperature\s*=\s*([\d,]+)')
        if nozzle_temp:
            temps = [t.strip() for t in nozzle_temp.split(",")]
            cfg["nozzle_temperature"] = temps
            cfg["nozzle_temperature_initial_layer"] = temps

        # Bed temperature
        bed_temp = _get(r'; bed_temperature\s*=\s*([\d,]+)')
        if not bed_temp:
            bed_temp = _get(r'; first_layer_bed_temperature\s*=\s*([\d,]+)')
        if bed_temp:
            temps = [t.strip() for t in bed_temp.split(",")]
            cfg["hot_plate_temp"] = temps
            cfg["hot_plate_temp_initial_layer"] = temps

        # Filament type
        fil_type = _get(r'; filament_type\s*=\s*([^\n]+)')
        if fil_type:
            types = [t.strip() for t in fil_type.split(";")]
            cfg["filament_type"] = types

        # Filament colour — suporta múltiplas cores separadas por ;
        fil_colour = _get(r'; filament_colour\s*=\s*([^\n]+)')
        if fil_colour:
            colours = [c.strip() for c in fil_colour.split(";")]
            # OrcaSlicer gera #RRGGBBAA — normaliza para #RRGGBB
            colours = [c[:7] if len(c) >= 7 else c for c in colours]
            cfg["filament_colour"] = colours

        # Filament density
        fil_density = _get(r'; filament_density\s*=\s*([^\n]+)')
        if fil_density:
            cfg["filament_density"] = [d.strip() for d in fil_density.split(";")]

        # Pressure advance
        pa = _get(r'; pressure_advance\s*=\s*([^\n]+)')
        if pa:
            cfg["pressure_advance"] = [p.strip() for p in pa.split(";")]

        # Sparse infill density
        infill = _get(r'; sparse_infill_density\s*=\s*([^\n]+)')
        if infill:
            cfg["sparse_infill_density"] = infill.split(";")[0].strip()

        # Support enabled
        support = _get(r'; enable_support\s*=\s*(\d)')
        if support:
            cfg["enable_support"] = support

        # Overrides de slots (cores do ACE mapeadas)
        if slots:
            colours_from_slots = []
            types_from_slots   = []
            for s in slots:
                r, g, b = s.get("paint_color", [200, 200, 200])[:3]
                colours_from_slots.append(f"#{r:02X}{g:02X}{b:02X}")
                types_from_slots.append(s.get("material_type", "PLA"))
            cfg["filament_colour"] = colours_from_slots
            cfg["extruder_colour"] = [c.lstrip("#") for c in colours_from_slots]
            cfg["filament_type"]   = types_from_slots

        cfg["from"] = "project"
        cfg["name"] = "project_settings"

        return _j.dumps(cfg, indent=4, ensure_ascii=False)
    
    

    @classmethod
    def pack(cls, gcode_path: str, slots: list | None = None) -> str:
        import zipfile, io, hashlib, datetime

        for enc in ("utf-8", "utf-8-sig", "latin-1", "cp1252"):
            try:
                with open(gcode_path, "r", encoding=enc) as f:
                    gcode = f.read()
                break
            except UnicodeDecodeError:
                continue
        else:
            with open(gcode_path, "rb") as f:
                gcode = f.read().decode("utf-8", errors="replace")

        if "M486 S" in gcode and 'A"' in gcode:
            gcode = cls._convert_orca_to_klipper_objects(gcode)

        has_define   = "EXCLUDE_OBJECT_DEFINE" in gcode
        has_excl_hdr = "; exclude_object:" in gcode[:800]
        if has_define and not has_excl_hdr:
            if slots and "; paint_info" not in gcode[:2000]:
                paint_items = []
                for s in slots:
                    r, g, b = s.get("paint_color", [0,0,0])[:3]
                    mat     = s.get("material_type", "ABS")
                    idx     = s.get("paint_index", 0)
                    paint_items.append(
                        f'{{"material_type":"{mat}",'
                        f'"paint_color":[{r},{g},{b}],'
                        f'"paint_index":{idx}}}'
                    )
                paint_info_line = "; paint_info = [" + ",".join(paint_items) + "]"
            else:
                paint_info_line = ""
            gcode = cls._inject_orca_header_fields(gcode, paint_info_line)

        single_color_filament = None
        if slots:
            gcode = cls._inject_paint_info(gcode, slots)
        else:
            gcode, single_color_filament = cls._make_single_color_gcode(gcode)

        gcode = cls._inject_executable_block_head(gcode)

        
        # Gerar plate_1.json
        plate_json = cls._generate_plate_json(gcode, slots)
        plate_json_str = json.dumps(plate_json, indent=2)


        gcode_bytes = gcode.encode("utf-8")
        md5         = hashlib.md5(gcode_bytes).hexdigest().upper()
        metadata    = cls._extract_metadata_section(gcode)

        thumbs      = cls._extract_thumbnails(gcode)
        thumb_large = cls._best_thumb(thumbs, 512)
        thumb_small = cls._best_thumb(thumbs, 230)
        has_thumb   = thumb_large is not None

        thumb_topdown = cls._generate_topdown_thumb(gcode)
        if thumb_topdown:
            gcode = cls._replace_topdown_in_gcode(gcode, thumb_topdown)
            gcode_bytes = gcode.encode("utf-8")
            md5 = hashlib.md5(gcode_bytes).hexdigest().upper()

        metadata = cls._extract_metadata_section(gcode)
        gcode_stats = cls._parse_gcode_stats(gcode)

        
        

        import datetime as _dt
        base = gcode_path
        for suf in ("_se3d.gcode", ".gcode", ".gc", ".bgcode"):
            if base.lower().endswith(suf):
                base = base[: -len(suf)]
                break
        raw_name = os.path.basename(base)
        if raw_name.startswith(".") or (raw_name.count("-") >= 3 and len(raw_name) > 30):
            raw_name = "print"
        title = raw_name

        _localappdata = os.environ.get("LOCALAPPDATA", "")
        if _localappdata and os.path.isdir(_localappdata):
            _base_dir = _localappdata
        else:
            import tempfile as _tmpmod2
            _base_dir = _tmpmod2.gettempdir()
        out_dir = os.path.join(_base_dir, "AnyConnect", "SE3D_Hub", "Anycubic")
        os.makedirs(out_dir, exist_ok=True)

        ts = _dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        out_path = os.path.join(out_dir, f"{raw_name}_{ts}.gcode.3mf")

        filaments = []
        if slots:
            for s in slots:
                r, g, b = s.get("paint_color", [0, 0, 0])[:3]
                filaments.append({
                    "material": s.get("material_type", "ABS"),
                    "color":    f"#{r:02X}{g:02X}{b:02X}",
                    "used_m":   "0",
                    "used_g":   "0",
                })
        elif single_color_filament:
            fil_info = cls._parse_filament_info(gcode)
            if fil_info:
                single_color_filament["used_m"] = fil_info[0].get("used_m", "0")
                if single_color_filament.get("color", "#C8C8C8") == "#C8C8C8":
                    single_color_filament["color"] = fil_info[0].get("color", "#C8C8C8")
                single_color_filament["material"] = fil_info[0].get("material", single_color_filament.get("material", "PLA"))
            filaments.append(single_color_filament)

        # ── Extrai número do gcode para nomear top_N.png ──────────────────────
        gcode_basename = os.path.basename(gcode_path)  # ex: plate_1.gcode
        plate_num_match = re.search(r'plate_(\d+)\.gcode', gcode_basename, re.IGNORECASE)
        plate_num = plate_num_match.group(1) if plate_num_match else "1"
        top_thumb_name = f"Metadata/top_{plate_num}.png"
        pick_thumb_name = f"Metadata/pick_{plate_num}.png"

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as z:
            z.writestr("[Content_Types].xml",                        cls.CONTENT_TYPES)
            z.writestr("_rels/.rels",                                cls.RELS if has_thumb else cls.RELS_NO_THUMB)
            z.writestr("3D/3dmodel.model",                           cls._make_3dmodel(title))
            z.writestr("Metadata/_rels/model_settings.config.rels",  cls.MODEL_SETTINGS_RELS)
            z.writestr(
                "Metadata/model_settings.config",
                cls._make_model_settings(gcode_stats, has_thumb).encode("utf-8")
            )
            z.writestr("Metadata/plate_1.gcode",                     gcode_bytes)
            z.writestr("Metadata/plate_1.json", plate_json_str.encode("utf-8"))
            z.writestr("Metadata/plate_1.gcode.md5",                 md5.encode())
            z.writestr("Metadata/plate_1.gcode.metadata",            metadata.encode("utf-8"))
            z.writestr(
                "Metadata/slice_info.config",
                cls._make_slice_info(filaments, stats=gcode_stats)
            )
            gcode_stats = cls._parse_gcode_stats(gcode)

            
            if thumb_topdown:
                z.writestr(top_thumb_name, thumb_topdown)   # ex: Metadata/top_1.png
                z.writestr(pick_thumb_name, thumb_topdown)   # ex: Metadata/top_1.png

            if thumb_large:
                z.writestr("Metadata/plate_1.png", thumb_large)   # agora é a 512x512
                z.writestr("Metadata/plate_1_small.png", thumb_small)  # thumb_small = 230x110
                
            if thumb_small:
                z.writestr("Metadata/plate_1_small.png", thumb_small)
                z.writestr("Metadata/thumbnail_1_small.png", thumb_small)
                
            
            project_settings_content = cls._make_project_settings(gcode, slots)
            z.writestr("Metadata/project_settings.config", project_settings_content.encode("utf-8"))

        with open(out_path, "wb") as f:
            f.write(buf.getvalue())

        return out_path

    @staticmethod
    def extract_gcode(gcode_3mf_path: str) -> str:
        """
        Extrai o gcode interno de um .gcode.3mf, salva como .gcode temporário
        e retorna o path.
        """
        import zipfile, tempfile, os
        with zipfile.ZipFile(gcode_3mf_path, "r") as z:
            gcode_entry = None
            for name in z.namelist():
                if name.endswith(".gcode") and not name.endswith(".metadata"):
                    gcode_entry = name
                    break
            if not gcode_entry:
                raise ValueError("No gcode found inside .gcode.3mf")
            gcode_bytes = z.read(gcode_entry)

        base = gcode_3mf_path
        for suf in (".gcode.3mf", ".3mf"):
            if base.lower().endswith(suf):
                base = base[:-len(suf)]
                break
        out_path = base + "_extracted.gcode"
        with open(out_path, "wb") as f:
            f.write(gcode_bytes)
        return out_path



# ═══════════════════════════════════════════════════════════════════════════
#  Argumento do OrcaSlicer / Slicer Next
# ═══════════════════════════════════════════════════════════════════════════

def _get_gcode_path() -> str | None:
    """
    Recebe arquivo de qualquer slicer via linha de comando:
      - OrcaSlicer / AnycubicSlicerNext:  main.exe "C:/path/to/file.gcode"
      - BambuStudio:                      main.exe "C:/path/to/file.gcode"
      - Qualquer slicer com post-script:  main.exe "C:/path/to/file.3mf"
                                          main.exe "C:/path/to/file.gcode.3mf"

    Aceita paths com espaços, com ou sem aspas.
    Aceita qualquer extensão — o Hub detecta e trata cada formato.
    """
    if len(sys.argv) < 2:
        return None
    candidate = " ".join(sys.argv[1:])
    if os.path.isfile(candidate):
        return candidate
    for arg in sys.argv[1:]:
        if os.path.isfile(arg):
            return arg
    return None


def _detect_file_type(filepath: str) -> str:
    """
    Detecta o tipo do arquivo recebido do slicer:
      'gcode'      — .gcode / .gc / .bgcode
      'gcode_3mf'  — .gcode.3mf (gerado pelo AnycubicSlicerNext)
      '3mf'        — .3mf puro (projeto do BambuStudio/OrcaSlicer)
      'unknown'    — outro
    """
    name = os.path.basename(filepath).lower()
    if name.endswith(".gcode.3mf"):
        return "gcode_3mf"
    if name.endswith(".3mf"):
        return "3mf"
    if name.endswith((".gcode", ".gc", ".bgcode")):
        return "gcode"
    return "unknown"


def _open_print_screen(filepath: str, window: MainWindow, _retry: int = 0) -> None:
    """
    Navega para a aba PRINT e abre a tela de color mapping.
    Aceita .gcode, .gcode.3mf e .3mf de qualquer slicer.
    Tenta até 10x com intervalo de 500ms se o arquivo ainda não existir
    (pode ter sido copiado para temp e o FS ainda não sincronizou).
    """
    log = window._screen_login.append_log

    if not os.path.isfile(filepath):
        if _retry < 10:
            QTimer.singleShot(500, lambda: _open_print_screen(filepath, window, _retry + 1))
            if _retry == 0:
                log(f"[SLICER] Aguardando arquivo: {os.path.basename(filepath)}")
        else:
            log(f"[SLICER] ERRO: arquivo não encontrado após {_retry} tentativas")
            log(f"[SLICER]   Path: {filepath}")
        return

    size_bytes = os.path.getsize(filepath)
    filename   = os.path.basename(filepath)
    ftype      = _detect_file_type(filepath)

    log("─" * 60)
    log(f"[SLICER] Arquivo recebido: {filename}")
    log(f"[SLICER]   Tipo   : {ftype.upper()}")
    log(f"[SLICER]   Tamanho: {size_bytes:,} bytes  ({size_bytes / 1024 / 1024:.1f} MB)")
    log("─" * 60)

    # Normaliza para .gcode se necessário (extrai do .gcode.3mf ou .3mf)
    load_path = filepath
    if ftype == "gcode_3mf":
        # .gcode.3mf já é o formato correto — passa direto, o Hub envia como está
        log("[SLICER]   Formato .gcode.3mf detectado — envio direto")
    elif ftype == "3mf":
        # .3mf puro do BambuStudio/OrcaSlicer — o Hub vai enviar como .gcode.3mf
        # O conteúdo interno pode ter o gcode embutido
        log("[SLICER]   Formato .3mf detectado — será enviado como .gcode.3mf")
    elif ftype == "gcode":
        log("[SLICER]   Formato .gcode detectado — será renomeado para .gcode.3mf no upload")
    else:
        log(f"[SLICER]   AVISO: extensão desconhecida — tentando mesmo assim")

    # Ir para aba PRINT e abrir arquivo
    if hasattr(window, "_open_file"):
        window._open_file(load_path)
    elif hasattr(window, "_print"):
        if hasattr(window, "_tabs"):
            window._tabs.setCurrentIndex(0)
        window._print.load_file_from_arg(load_path)


# ═══════════════════════════════════════════════════════════════════════════
#  Entry point
# ═══════════════════════════════════════════════════════════════════════════

def _ipc_file() -> str:
    import tempfile
    return os.path.join(tempfile.gettempdir(), "se3d_gestor_ipc.txt")


def _send_to_existing_instance(filepath: str) -> bool:
    """Escreve filepath no IPC file para a instancia ativa consumir.
    Verifica se o app está vivo lendo o conteúdo ALIVE:<timestamp>,
    não apenas o mtime, para evitar envio a instância já fechada.
    """
    try:
        import time
        ipc = _ipc_file()
        if not os.path.exists(ipc):
            return False
        with open(ipc, "r", encoding="utf-8") as f:
            content = f.read().strip()
        # App vivo = arquivo contém "ALIVE:<ts>" recente
        if not content.startswith("ALIVE:"):
            return False
        ts = float(content.split(":", 1)[1])
        if (time.time() - ts) >= 3.0:
            return False
        # App está vivo — escreve o filepath para ele processar
        with open(ipc, "w", encoding="utf-8") as f:
            f.write(filepath)
        return True
    except Exception:
        return False


def _write_lock_file():
    pass  # não usado mais


def _remove_lock_file():
    pass  # não usado mais


def main():
    gcode_path = _get_gcode_path()

    # Se tem arquivo do slicer e já há instância aberta, envia para ela e sai
    if gcode_path and _send_to_existing_instance(gcode_path):
        return  # Instância existente vai abrir o arquivo

    # Se foi chamado pelo slicer sem instancia existente, lanca detached.
    # O arquivo recebido ja e uma copia segura em AnyConnect\Bridge
    # (feita pelo bridge.py) — pode usar diretamente.
    if gcode_path:
        try:
            import subprocess
            flags = 0
            if sys.platform == "win32":
                flags = 0x00000008 | 0x00000200  # DETACHED | NEW_PROCESS_GROUP
            if "--detached" not in sys.argv:
                subprocess.Popen(
                    [sys.executable, sys.argv[0], gcode_path, "--detached"],
                    creationflags=flags,
                    close_fds=True,
                    start_new_session=True if sys.platform != "win32" else False,
                )
                return
        except Exception:
            pass

    app = QApplication(sys.argv)
    app.setApplicationName("SE3D Gestor")
    app.setOrganizationName("SE3D")

    try:
        # Resolve icon path — funciona em desenvolvimento e compilado (Nuitka/PyInstaller)
        _base = os.path.dirname(os.path.abspath(__file__))
        for _candidate in [
            os.path.join(_base, "icon.ico"),
            os.path.join(_base, "assets", "icon.ico"),
            os.path.join(_base, "..", "icon.ico"),
            os.path.join(os.getcwd(), "icon.ico"),
        ]:
            if os.path.exists(_candidate):
                _icon = QIcon(_candidate)
                app.setWindowIcon(_icon)
                break
    except Exception:
        pass

    window = MainWindow()
    window.showMaximized()

    # Registra lock de instância única
    _write_lock_file()
    import atexit
    atexit.register(_remove_lock_file)

    gcode_path = _get_gcode_path()
    if gcode_path:
        QTimer.singleShot(600, lambda: _open_print_screen(gcode_path, window))

    sys.exit(app.exec())


if __name__ == "__main__":
    main()

