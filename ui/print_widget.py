# -*- coding: utf-8 -*-
"""
Print Widget — three screens:
  0  SetupScreen    : drag+drop gcode, file info + status panel
  1  ColorMapScreen : thumbnail + color mapping + print options
  2  WorkbenchScreen: live print progress
  3  UploadScreen   : upload progress
"""

import os

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QFrame, QGroupBox, QFileDialog,
    QCheckBox, QProgressBar, QGridLayout,
    QComboBox, QStackedWidget, QLineEdit, QMessageBox,
    QSizePolicy, QScrollArea, QTextEdit, QSplitter
)
from PyQt6.QtCore import Qt, pyqtSignal,pyqtSlot, QTimer,QMetaObject, Qt
from PyQt6.QtGui import QFont, QPixmap, QImage, QColor, QPainter, QPen, QBrush


# ─────────────────────────────────────────────
# Thumbnail extractor
# ─────────────────────────────────────────────
def extract_thumbnail(filepath: str) -> QPixmap | None:
    try:
        thumbnails = {}
        current_size = None
        current_data = []
        in_thumb = False
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if line.startswith("; thumbnail begin"):
                    parts = line.split()
                    if len(parts) >= 4:
                        current_size = parts[3]
                    in_thumb = True
                    current_data = []
                elif line.startswith("; thumbnail end"):
                    if current_size and current_data:
                        thumbnails[current_size] = "".join(current_data)
                    in_thumb = False
                    current_size = None
                    current_data = []
                elif in_thumb and line.startswith(";"):
                    current_data.append(line[1:].strip())
        if not thumbnails:
            return None
        def size_key(s):
            try:
                w, h = s.split("x")
                return int(w) * int(h)
            except Exception:
                return 0
        best = max(thumbnails.keys(), key=size_key)
        import base64
        png_data = base64.b64decode(thumbnails[best])
        img = QImage.fromData(png_data)
        if img.isNull():
            return None
        return QPixmap.fromImage(img)
    except Exception:
        return None


# ─────────────────────────────────────────────
# GCode metadata parser — lê as primeiras 3000 linhas
# Apenas processa linhas de comentário (;), ignorando G-code sem parar.
# ─────────────────────────────────────────────

def _extract_thumb_bytes(filepath: str) -> bytes | None:
    """
    Extrai thumbnail como bytes PNG de qualquer fonte:
      1. PNG dentro do zip (.gcode.3mf / .3mf) — entry com "thumbnail" no nome
      2. Gcode dentro do zip (.gcode.3mf) — parse dos comentários ; thumbnail begin
      3. Arquivo .gcode direto — parse dos comentários ; thumbnail begin
      4. FALLBACK: tenta abrir como ZIP mesmo sem extensão reconhecível
         (caso do OrcaSlicer que envia arquivo sem extensão via bridge)
    Retorna bytes PNG prontos para QImage.fromData(), ou None se não encontrou.
    """
    import zipfile, base64

    if not filepath or not os.path.isfile(filepath):
        return None

    name_lower = filepath.lower()

    # ── Fontes via ZIP (.gcode.3mf / .3mf ou sem extensão) ──────────────
    is_named_zip = (name_lower.endswith(".3mf") or
                    name_lower.endswith(".gcode.3mf"))

    # Detecta ZIP pelos magic bytes mesmo sem extensão reconhecível
    def _file_is_zip(fp: str) -> bool:
        try:
            with open(fp, "rb") as f:
                return f.read(4) == b'PK\x03\x04'
        except Exception:
            return False

    if is_named_zip or _file_is_zip(filepath):
        try:
            with zipfile.ZipFile(filepath, "r") as z:
                entries = z.namelist()

                # Fonte 1: PNG já pronto dentro do zip
                for entry in entries:
                    el = entry.lower()
                    if el.endswith(".png") and (
                        "thumbnail" in el or "plate_1" in el or "preview" in el
                    ):
                        data = z.read(entry)
                        if data:
                            return data

                # Fonte 2: gcode dentro do zip → parse comentários
                for entry in entries:
                    el = entry.lower()
                    if el.endswith(".gcode") and not el.endswith(".metadata"):
                        try:
                            gcode_text = z.read(entry).decode("utf-8", errors="replace")
                            data = _parse_gcode_thumb(gcode_text)
                            if data:
                                return data
                        except Exception:
                            pass

                # Fonte 3: qualquer entrada que pareça gcode (sem extensão também)
                for entry in entries:
                    el = entry.lower()
                    if "metadata" in el and not el.endswith(".png") and not el.endswith(".xml") and not el.endswith(".rels") and not el.endswith(".config") and not el.endswith(".md5"):
                        try:
                            gcode_text = z.read(entry).decode("utf-8", errors="replace")
                            if "; thumbnail begin" in gcode_text[:4096]:
                                data = _parse_gcode_thumb(gcode_text)
                                if data:
                                    return data
                        except Exception:
                            pass
        except Exception:
            pass

    # ── Fonte 4: .gcode direto ou arquivo de texto ────────────────────────
    if (name_lower.endswith((".gcode", ".gc", ".bgcode", ".pp")) or
            not any(name_lower.endswith(e) for e in
                    (".3mf", ".gcode.3mf", ".png", ".jpg", ".xml",
                     ".json", ".zip", ".exe", ".dll"))):
        try:
            with open(filepath, "r", encoding="utf-8", errors="replace") as f:
                # Lê só o suficiente para encontrar thumbnails (primeiros 2MB)
                gcode_text = f.read(2 * 1024 * 1024)
            if "; thumbnail begin" in gcode_text:
                return _parse_gcode_thumb(gcode_text)
        except Exception:
            pass

    return None


def _extract_thumb_bytes_old(filepath: str) -> bytes | None:
    """
    Extrai thumbnail como bytes PNG de qualquer fonte:
      1. PNG dentro do zip (.gcode.3mf / .3mf) — entry com "thumbnail" no nome
      2. Gcode dentro do zip (.gcode.3mf) — parse dos comentários ; thumbnail begin
      3. Arquivo .gcode direto — parse dos comentários ; thumbnail begin
    Retorna bytes PNG prontos para QImage.fromData(), ou None se não encontrou.
    """
    import zipfile, base64

    if not filepath or not os.path.isfile(filepath):
        return None

    name_lower = filepath.lower()

    # ── Fontes via ZIP (.gcode.3mf / .3mf) ──────────────────────────────
    if name_lower.endswith(".3mf") or name_lower.endswith(".gcode.3mf"):
        try:
            with zipfile.ZipFile(filepath, "r") as z:
                entries = z.namelist()

                # Fonte 1: PNG já pronto dentro do zip
                for entry in entries:
                    el = entry.lower()
                    if el.endswith(".png") and (
                        "thumbnail" in el or "plate_1" in el or "preview" in el
                    ):
                        data = z.read(entry)
                        if data:
                            return data

                # Fonte 2: gcode dentro do zip → parse comentários
                for entry in entries:
                    if entry.lower().endswith(".gcode") and "plate" in entry.lower():
                        try:
                            gcode_text = z.read(entry).decode("utf-8", errors="replace")
                            data = _parse_gcode_thumb(gcode_text)
                            if data:
                                return data
                        except Exception:
                            pass
        except Exception:
            pass

    # ── Fonte 3: .gcode direto ────────────────────────────────────────────
    if name_lower.endswith((".gcode", ".gc", ".bgcode")):
        try:
            with open(filepath, "r", encoding="utf-8", errors="replace") as f:
                gcode_text = f.read()
            return _parse_gcode_thumb(gcode_text)
        except Exception:
            pass

    return None


def _parse_gcode_thumb(gcode_text: str) -> bytes | None:
    """Extrai o maior thumbnail dos comentários de um gcode como bytes PNG."""
    import base64
    thumbs: dict[str, str] = {}
    cur_size, cur_data, in_thumb = None, [], False
    for line in gcode_text.splitlines():
        l = line.strip()
        if l.startswith("; thumbnail begin"):
            parts = l.split()
            cur_size = parts[3] if len(parts) >= 4 else "0x0"
            in_thumb, cur_data = True, []
        elif l.startswith("; thumbnail end"):
            if cur_size and cur_data:
                thumbs[cur_size] = "".join(cur_data)
            in_thumb = False
        elif in_thumb and l.startswith(";"):
            cur_data.append(l[1:].strip())
    if not thumbs:
        return None
    def _area(s):
        try: w, h = s.split("x"); return int(w) * int(h)
        except: return 0
    best = max(thumbs, key=_area)
    try:
        return base64.b64decode(thumbs[best])
    except Exception:
        return None


def _hex_to_rgb(hx: str) -> list:
    """Converte string hex para [R, G, B].
    Suporta: #RGB, #RRGGBB, #RRGGBBAA (OrcaSlicer — alpha no final, ignorado).
    """
    try:
        h = hx.strip().lstrip("#")
        if len(h) == 8:   # RRGGBBAA — ignora AA
            return [int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)]
        elif len(h) == 6:
            return [int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)]
        elif len(h) == 3:
            return [int(h[0:1]*2, 16), int(h[1:2]*2, 16), int(h[2:3]*2, 16)]
    except Exception:
        pass
    return [200, 200, 200]


def parse_gcode_meta(filepath: str) -> dict:
    """
    Varre o arquivo INTEIRO linha por linha em uma única passagem.
    Coleta metadados e cores independente da posição no arquivo.

    Fontes de cor suportadas (em ordem de prioridade):
      1. ; filament_colour / ; filament_color   — OrcaSlicer / BambuStudio / AnycubicSlicerNext
      2. ; paint_info = [...]                   — AnycubicSlicerNext (JSON com RGB direto)
      3. extruder_colour / extruder_color        — fallback de configs de impressora
    """
    import json as _json
    import re as _re

    meta = {
        "estimated_time":    "--",
        "filament_used_g":   "--",
        "filament_used_m":   "--",
        "material":          "--",
        "layer_count":       "--",
        "filament_colors":     [],
        "filament_colors_rgb": [],
        "filament_types":      [],
    }

    # Acumuladores — última ocorrência de cada fonte vence
    _colours_hex:   list[str]  = []   # de filament_colour
    _colours_rgb:   list[list] = []   # de paint_info (já em RGB)
    _extruder_hex:  list[str]  = []   # de extruder_colour (fallback)
    _types:         list[str]  = []
    _paint_types:   list[str]  = []

    try:
        for enc in ("utf-8", "utf-8-sig", "latin-1", "cp1252"):
            try:
                fh = open(filepath, "r", encoding=enc, errors="replace")
                break
            except Exception:
                continue
        else:
            return meta

        with fh:
            for raw in fh:
                l = raw.strip()
                if not l or not l.startswith(";"):
                    continue

                # ── Tempo estimado ─────────────────────────────────────────
                if l.startswith("; estimated printing time"):
                    meta["estimated_time"] = l.split("=", 1)[-1].strip()

                # ── Peso do filamento ──────────────────────────────────────
                elif l.startswith("; filament used [g]"):
                    val = l.split("=", 1)[-1].strip()
                    try:
                        vals = [f"{float(v.strip()):.1f}g" for v in val.split(",")]
                        meta["filament_used_g"] = ", ".join(vals)
                    except Exception:
                        meta["filament_used_g"] = val

                # ── Comprimento do filamento ───────────────────────────────
                elif l.startswith("; filament used [mm]"):
                    val = l.split("=", 1)[-1].strip()
                    try:
                        vals = [f"{float(v.strip())/1000:.2f}m" for v in val.split(",")]
                        meta["filament_used_m"] = ", ".join(vals)
                    except Exception:
                        meta["filament_used_m"] = val
                elif l.startswith("; filament used [m]"):
                    if meta["filament_used_m"] == "--":   # não sobrescreve se mm já veio
                        val = l.split("=", 1)[-1].strip()
                        try:
                            vals = [f"{float(v.strip()):.2f}m" for v in val.split(",")]
                            meta["filament_used_m"] = ", ".join(vals)
                        except Exception:
                            meta["filament_used_m"] = val

                # ── Tipo de filamento ──────────────────────────────────────
                elif l.startswith("; filament_type"):
                    val = l.split("=", 1)[-1].strip()
                    meta["material"] = val
                    _types = [v.strip() for v in val.split(";") if v.strip()]

                # ── Total de camadas ───────────────────────────────────────
                elif l.startswith("; total layer number") or l.startswith("; total layers"):
                    meta["layer_count"] = l.split("=", 1)[-1].strip()

                # ── FONTE 1: filament_colour / filament_color ──────────────
                # OrcaSlicer: #RRGGBBAA separados por ;
                # BambuStudio: #RRGGBB separados por ;
                elif l.startswith("; filament_colour") or l.startswith("; filament_color"):
                    val = l.split("=", 1)[-1].strip()
                    parsed = []
                    for tok in val.split(";"):
                        tok = tok.strip()
                        if tok.startswith("#") and len(tok) >= 4:
                            parsed.append(tok)
                    if parsed:
                        _colours_hex = parsed   # última ocorrência vence

                # ── FONTE 2: paint_info JSON (AnycubicSlicerNext) ──────────
                elif "; paint_info" in l:
                    try:
                        val = l.split("= ", 1)[1].strip() if "= " in l else l.split("=", 1)[1].strip()
                        slots = _json.loads(val)
                        if isinstance(slots, list) and slots:
                            _colours_rgb = []
                            _colours_hex = []
                            _paint_types = []
                            for s in slots:
                                rgb = s.get("paint_color", [200, 200, 200])[:3]
                                r, g, b = int(rgb[0]), int(rgb[1]), int(rgb[2])
                                _colours_rgb.append([r, g, b])
                                _colours_hex.append(f"#{r:02X}{g:02X}{b:02X}")
                                _paint_types.append(s.get("material_type", "ABS"))
                    except Exception:
                        pass

                # ── FONTE 3: extruder_colour (fallback, configs de máquina) ─
                elif ("extruder_colour" in l.lower() or "extruder_color" in l.lower()) and not _colours_hex:
                    val = None
                    if "=" in l:
                        val = l.split("=", 1)[-1].strip()
                        val = val.strip('"').strip("'").strip()
                    elif ":" in l:
                        val = l.split(":", 1)[-1].strip()
                        val = val.strip('"').strip("'").strip()
                    if val:
                        for tok in val.split(";"):
                            tok = tok.strip()
                            if tok.startswith("#") and len(tok) >= 4:
                                _extruder_hex.append(tok)

    except Exception as e:
        print(f"[parse_gcode_meta] Erro: {e}")
        return meta

    # ── Resolve tipos ──────────────────────────────────────────────────────
    if _paint_types:
        meta["filament_types"] = _paint_types
    elif _types:
        meta["filament_types"] = _types

    # ── Resolve cores ──────────────────────────────────────────────────────
    # paint_info já tem RGB direto — usa se disponível
    if _colours_rgb:
        meta["filament_colors"]     = _colours_hex
        meta["filament_colors_rgb"] = _colours_rgb
    elif _colours_hex:
        # filament_colour — converte hex para RGB
        meta["filament_colors"]     = _colours_hex
        meta["filament_colors_rgb"] = [_hex_to_rgb(h) for h in _colours_hex]
    elif _extruder_hex:
        # fallback extruder_colour
        meta["filament_colors"]     = _extruder_hex
        meta["filament_colors_rgb"] = [_hex_to_rgb(h) for h in _extruder_hex]

    # ── Fallback: cria placeholders se tem tipos mas não tem cores ─────────
    if not meta["filament_colors"] and meta["filament_types"]:
        n = len(meta["filament_types"])
        meta["filament_colors"]     = ["#C8C8C8"] * n
        meta["filament_colors_rgb"] = [[200, 200, 200]] * n

    return meta


# ─────────────────────────────────────────────
# Slot color pill — small colored circle widget
# ─────────────────────────────────────────────
class ColorPill(QWidget):
    """Small colored circle with slot number label."""
    def __init__(self, color_rgb: list, label: str, size: int = 28, parent=None):
        super().__init__(parent)
        # Garante que _color é sempre [R, G, B] (3 valores int)
        c = color_rgb if color_rgb else [200, 200, 200]
        self._color = [int(c[0]), int(c[1]), int(c[2])]
        self._label = label
        self.setFixedSize(size + 32, size + 18)

    def set_color(self, color_rgb: list):
        c = color_rgb if color_rgb else [200, 200, 200]
        self._color = [int(c[0]), int(c[1]), int(c[2])]
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        # Safe unpack — cor pode ter alpha extra (ex: RGBA do OrcaSlicer)
        col = self._color if self._color else [200, 200, 200]
        r, g, b = col[0], col[1], col[2]
        cx = self.width() // 2
        cy = 16
        radius = 12
        p.setPen(QPen(QColor(30, 45, 61), 2))
        p.setBrush(QBrush(QColor(r, g, b)))
        p.drawEllipse(cx - radius, cy - radius, radius * 2, radius * 2)
        p.setPen(QColor("#607080"))
        p.setFont(QFont("Courier New", 8))
        p.drawText(0, cy + radius + 2, self.width(), 14,
                   Qt.AlignmentFlag.AlignCenter, self._label)


# ─────────────────────────────────────────────
# Color mapping row — one slicer slot → ACE slot selector
# ─────────────────────────────────────────────
class ColorMapRow(QWidget):
    """[slicer color pill] [material] [→] [ACE slot combo] [ace color pill]"""

    def __init__(self, slot_idx: int, slicer_color: list, slicer_material: str,
                 ace_slots: list, parent=None):
        super().__init__(parent)
        self._slot_idx  = slot_idx
        self._ace_slots = ace_slots

        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(10)

        # Slicer color circle — garante 3 valores RGB
        _sc = slicer_color if slicer_color else [200, 200, 200]
        _sc = [int(_sc[0]), int(_sc[1]), int(_sc[2])] if len(_sc) >= 3 else [200, 200, 200]
        self._pill = ColorPill(_sc, f"T{slot_idx}", size=32)  # maior para destaque
        layout.addWidget(self._pill)

        # Material name
        lbl_mat = QLabel(slicer_material or "—")
        lbl_mat.setFont(QFont("Courier New", 11, QFont.Weight.Bold))
        lbl_mat.setStyleSheet("color: #C8D0D8;")
        lbl_mat.setMinimumWidth(55)
        layout.addWidget(lbl_mat)

        # Arrow
        lbl_arrow = QLabel("→")
        lbl_arrow.setFont(QFont("Courier New", 13))
        lbl_arrow.setStyleSheet("color: #1E4D60;")
        layout.addWidget(lbl_arrow)

        # ACE slot combo
        self._combo = QComboBox()
        self._combo.setFont(QFont("Courier New", 11))
        self._combo.setMinimumWidth(160)
        self._combo.setMinimumHeight(32)
        for i, s in enumerate(ace_slots):
            mat      = s.get("material_type", "?")
            real_idx = s.get("index", i)
            self._combo.addItem(f"  S{real_idx + 1}  {mat}", userData=i)

        # Auto-match por cor RGB + tipo de filamento
        # Estratégia: prioriza slots com mesmo tipo; dentro de cada grupo, escolhe
        # o de menor distância de cor. Se nenhum slot tem o mesmo tipo, usa só cor.
        def _color_dist(c1, c2):
            return sum((a - b) ** 2 for a, b in zip(c1[:3], c2[:3]))

        def _normalize_mat(m: str) -> str:
            return (m or "").upper().strip()

        if slicer_color and ace_slots and slicer_color not in ([200, 200, 200], []):
            slicer_mat = _normalize_mat(slicer_material)
            # Candidatos com mesmo tipo
            same_type = [(i, s) for i, s in enumerate(ace_slots)
                         if _normalize_mat(s.get("material_type", "")) == slicer_mat]
            # Se há candidatos do mesmo tipo, escolhe o de menor distância de cor
            if same_type:
                best_idx = min(same_type,
                               key=lambda t: _color_dist(slicer_color,
                                                         t[1].get("paint_color", [0, 0, 0])))[0]
            else:
                # Sem correspondência de tipo — usa só cor
                best_idx = min(range(len(ace_slots)),
                               key=lambda i: _color_dist(slicer_color,
                                                         ace_slots[i].get("paint_color", [0, 0, 0])))
            default = best_idx
        else:
            default = min(slot_idx, len(ace_slots) - 1) if ace_slots else 0

        self._combo.setCurrentIndex(default)
        layout.addWidget(self._combo, 1)

        # ACE color preview pill
        ace_color = ace_slots[default].get("paint_color", [255, 255, 255]) if ace_slots else [40, 40, 40]
        self._ace_pill = ColorPill(ace_color, f"S{default + 1}")
        layout.addWidget(self._ace_pill)

        self._combo.currentIndexChanged.connect(self._on_combo_changed)

    def _on_combo_changed(self, idx: int):
        if 0 <= idx < len(self._ace_slots):
            s = self._ace_slots[idx]
            self._ace_pill.set_color(s.get("paint_color", [255, 255, 255]))
            self._ace_pill._label = f"S{idx + 1}"
            self._ace_pill.update()

    def get_mapping(self) -> dict:
        return {"slicer": self._slot_idx, "ace": self._combo.currentData()}


# ─────────────────────────────────────────────
# Color Map + Options screen
# ─────────────────────────────────────────────
class ColorMapScreen(QWidget):
    confirmed      = pyqtSignal(dict)
    cancelled      = pyqtSignal()
    watch_requested = pyqtSignal()    # navega para workbench / acompanhar impressão

    def __init__(self, settings: dict, parent=None):
        super().__init__(parent)
        self._settings  = settings
        self._filepath  = None
        self._thumbnail = None
        self._meta      = {}
        self._map_rows: list[ColorMapRow] = []
        self._connected = False
        self._last_state = "OFFLINE"
        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Header ──
        hdr = QFrame()
        #hdr.setFixedHeight(50) #// removido para gerar mais espaço
        hdr.setStyleSheet("background:#080C0F; border-bottom:1px solid #1A2535;")
        hdr_l = QHBoxLayout(hdr)
        hdr_l.setContentsMargins(16, 0, 16, 0)
        lbl_title = QLabel("■  PRINT  SETUP")
        lbl_title.setFont(QFont("Courier New", 11, QFont.Weight.Bold))
        lbl_title.setStyleSheet("color:#00E5FF; letter-spacing:3px;")
        self._lbl_filename = QLabel("")
        self._lbl_filename.setFont(QFont("Courier New", 10))
        self._lbl_filename.setStyleSheet("color:#607080;")
        #hdr_l.addWidget(lbl_title) #// removido para gerar mais espaço
        #hdr_l.addSpacing(20)
        #hdr_l.addWidget(self._lbl_filename, 1) #// removido para gerar mais espaço
        root.addWidget(hdr)

        # ── Main content ──
        content = QHBoxLayout()
        content.setContentsMargins(16, 12, 16, 12)
        content.setSpacing(16)

        # ── LEFT: thumbnail + meta ──
        left = QVBoxLayout()
        left.setSpacing(10)

        self._thumb = QLabel()
        self._thumb.setFixedSize(200, 180)
        self._thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._thumb.setStyleSheet(
            "background:#0D0F11; border:1px solid #1E2D3D; border-radius:3px;"
        )
        self._thumb.setText("NO  PREVIEW")
        self._thumb.setFont(QFont("Courier New", 9))
        left.addWidget(self._thumb)

        grp_meta = QGroupBox("FILE  INFO")
        meta_l = QGridLayout(grp_meta)
        meta_l.setSpacing(6)
        meta_l.setContentsMargins(10, 5, 10, 5)

        def mr(label, attr):
            l = QLabel(label)
            l.setFont(QFont("Courier New", 10))
            l.setStyleSheet("color:#607080;")
            v = QLabel("--")
            v.setFont(QFont("Courier New", 10))
            v.setStyleSheet("color:#C8D0D8;")
            setattr(self, attr, v)
            return l, v

        for i, (lbl, attr) in enumerate([
            mr("TIME",     "_m_time"),
            mr("WEIGHT",   "_m_weight"),
            mr("LENGTH",   "_m_length"),
            mr("MATERIAL", "_m_material"),
            mr("LAYERS",   "_m_layers"),
        ]):
            meta_l.addWidget(lbl, i, 0)
            meta_l.addWidget(attr, i, 1)

        left.addWidget(grp_meta)
        left.addStretch()
        content.addLayout(left, 2)

        # ── CENTER: color mapping ──
        center = QVBoxLayout()
        center.setSpacing(8)

        map_hdr = QHBoxLayout()
        lbl_map = QLabel("COLOR  MAPPING")
        lbl_map.setFont(QFont("Courier New", 10, QFont.Weight.Bold))
        lbl_map.setStyleSheet("color:#607080; letter-spacing:2px;")
        btn_refresh = QPushButton("↺  Atualizar slots ACE")
        btn_refresh.setFont(QFont("Courier New", 8))
        btn_refresh.setFixedHeight(24)
        btn_refresh.setStyleSheet(
            "QPushButton{color:#2A4050;background:#0A0F14;border:1px solid #1A2535;"
            "padding:0 8px;border-radius:3px;}"
            "QPushButton:hover{color:#00E5FF;border-color:#00E5FF;}"
        )
        btn_refresh.clicked.connect(lambda: self._rebuild_map_rows(preserve_user_selection=False))
        map_hdr.addWidget(lbl_map)
        map_hdr.addStretch()
        map_hdr.addWidget(btn_refresh)
        center.addLayout(map_hdr)

        # ── Nome do arquivo a enviar ──
        name_row = QHBoxLayout()
        name_row.setSpacing(6)
        lbl_fname = QLabel("FILE  NAME")
        lbl_fname.setFont(QFont("Courier New", 9))
        lbl_fname.setStyleSheet("color:#607080; letter-spacing:1px;")
        lbl_fname.setFixedWidth(76)
        self._inp_filename = QLineEdit()
        self._inp_filename.setFont(QFont("Courier New", 10))
        self._inp_filename.setPlaceholderText("nome do arquivo...")
        self._inp_filename.setStyleSheet("""
            QLineEdit { background:#0D0F11; border:1px solid #1E2D3D; color:#C8D0D8;
                        font-family:'Courier New'; font-size:10px; padding:4px 8px;
                        border-radius:2px; }
            QLineEdit:focus { border-color:#00E5FF; }
        """)
        self._lbl_fname_ext = QLabel(".gcode.3mf")
        self._lbl_fname_ext.setFont(QFont("Courier New", 9))
        self._lbl_fname_ext.setStyleSheet("color:#3A5565;")
        name_row.addWidget(lbl_fname)
        name_row.addWidget(self._inp_filename, 1)
        name_row.addWidget(self._lbl_fname_ext)
        center.addLayout(name_row)

        lbl_hint = QLabel("Map each slicer slot to the matching ACE Pro slot.")
        lbl_hint.setFont(QFont("Courier New", 9))
        lbl_hint.setStyleSheet("color:#2A4050;")
        center.addWidget(lbl_hint)

        self._lbl_mismatch = QLabel("")
        self._lbl_mismatch.setFont(QFont("Courier New", 9))
        self._lbl_mismatch.setStyleSheet("color:#FFB300;")
        self._lbl_mismatch.setWordWrap(True)
        center.addWidget(self._lbl_mismatch)

        self._lbl_no_ace = QLabel(
            "⚠  ACE Pro desconectado — o arquivo será enviado sem configuração de cores/slots\n"
            "⚠  Certifique-se de que há filamento no sensor da toolhead antes de iniciar"
        )
        self._lbl_no_ace.setFont(QFont("Courier New", 9, QFont.Weight.Bold))
        self._lbl_no_ace.setStyleSheet(
            "color:#FF8C00; background:#1A0E00; border:1px solid #3A2200;"
            "padding:5px 10px; border-radius:3px;"
        )
        self._lbl_no_ace.setWordWrap(True)
        self._lbl_no_ace.setVisible(False)
        center.addWidget(self._lbl_no_ace)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("background:transparent;")
        self._map_container = QWidget()
        self._map_layout    = QVBoxLayout(self._map_container)
        self._map_layout.setSpacing(4)
        self._map_layout.setContentsMargins(0, 0, 0, 0)
        self._map_layout.addStretch()
        scroll.setWidget(self._map_container)
        scroll.setMinimumHeight(180)
        center.addWidget(scroll, 1)

        content.addLayout(center, 3)

        # ── RIGHT: options + printer + buttons ──
        right = QVBoxLayout()
        right.setSpacing(10)

        grp_printer = QGroupBox("PRINTER")
        pr_l = QVBoxLayout(grp_printer)
        pr_l.setContentsMargins(10, 0, 10, 0)
        self._combo_printer = QComboBox()
        self._combo_printer.setFont(QFont("Courier New", 11))
        ip   = self._settings.get("printer_ip", "")
        #name = f"Anycubic KS1  |  {ip}" if ip else "Anycubic KS1-C"
        #self._combo_printer.addItem(name)
        #self._lbl_pstatus = QLabel("● DISCONNECTED")
        #self._lbl_pstatus.setFont(QFont("Courier New", 10))
        #self._lbl_pstatus.setStyleSheet("color:#FF4444;")
        #pr_l.addWidget(self._combo_printer)
        #pr_l.addWidget(self._lbl_pstatus)
        #right.addWidget(grp_printer)

        grp_opts = QGroupBox("PRINT  OPTIONS")
        opts_g = QGridLayout(grp_opts)
        opts_g.setSpacing(8)
        opts_g.setContentsMargins(10, 20, 10, 10)

        last = self._settings.get("last_options", {})
        self._chk_leveling  = QCheckBox("Bed leveling")
        self._chk_resonance = QCheckBox("Resonance compensation")
        self._chk_timelapse = QCheckBox("Time-lapse")
        self._chk_flow      = QCheckBox("Flow calibration")
        self._chk_ai        = QCheckBox("AI detection  (cloud)")

        self._chk_leveling.setChecked(last.get("auto_leveling",    True))
        self._chk_resonance.setChecked(last.get("resonance",       False))
        self._chk_timelapse.setChecked(last.get("timelapse",       False))
        self._chk_flow.setChecked(last.get("flow_calibration",     False))
        self._chk_ai.setChecked(last.get("ai_detection",           False))
        self._chk_ai.setEnabled(False)

        for chk in [self._chk_leveling, self._chk_resonance,
                    self._chk_timelapse, self._chk_flow, self._chk_ai]:
            chk.setFont(QFont("Courier New", 10))
            chk.setStyleSheet("color:#C8D0D8; spacing:6px;")

        opts_g.addWidget(self._chk_leveling,  0, 0)
        opts_g.addWidget(self._chk_resonance, 0, 1)
        opts_g.addWidget(self._chk_timelapse, 1, 0)
        opts_g.addWidget(self._chk_flow,      1, 1)
        opts_g.addWidget(self._chk_ai,        2, 0, 1, 2)
        right.addWidget(grp_opts)

        grp_dry = QGroupBox("DRYING  OPTIONS")
        dry_l = QVBoxLayout(grp_dry)
        dry_l.setContentsMargins(10, 20, 10, 10)
        dry_l.setSpacing(8)

        # Row 1: mode selector
        dry_mode_row = QHBoxLayout()
        dry_mode_row.setSpacing(8)
        self._combo_dry = QComboBox()
        self._combo_dry.setFont(QFont("Courier New", 10))
        self._combo_dry.addItem("Not enabled",        0)
        self._combo_dry.addItem("Print While Drying", 1)
        self._combo_dry.addItem("Print After Drying", 2)
        dry_mode_row.addWidget(self._combo_dry, 1)
        dry_l.addLayout(dry_mode_row)

        # Row 2: temp + duration (hidden when mode=0)
        self._dry_params_row = QWidget()
        dry_params_l = QHBoxLayout(self._dry_params_row)
        dry_params_l.setContentsMargins(0, 0, 0, 0)
        dry_params_l.setSpacing(8)

        from PyQt6.QtWidgets import QSpinBox as _QSB
        lbl_temp = QLabel("Temp")
        lbl_temp.setFont(QFont("Courier New", 9))
        lbl_temp.setStyleSheet("color:#607080;")
        self._sp_dry_temp = _QSB()
        self._sp_dry_temp.setRange(30, 55)
        self._sp_dry_temp.setValue(35)
        self._sp_dry_temp.setSuffix(" °C")
        self._sp_dry_temp.setFont(QFont("Courier New", 10))
        self._sp_dry_temp.setMinimumWidth(80)

        lbl_dur = QLabel("Duration")
        lbl_dur.setFont(QFont("Courier New", 9))
        lbl_dur.setStyleSheet("color:#607080;")
        self._sp_dry_hours = _QSB()
        self._sp_dry_hours.setRange(1, 24)
        self._sp_dry_hours.setValue(12)
        self._sp_dry_hours.setSuffix(" h")
        self._sp_dry_hours.setFont(QFont("Courier New", 10))
        self._sp_dry_hours.setMinimumWidth(72)

        dry_params_l.addWidget(lbl_temp)
        dry_params_l.addWidget(self._sp_dry_temp)
        dry_params_l.addSpacing(12)
        dry_params_l.addWidget(lbl_dur)
        dry_params_l.addWidget(self._sp_dry_hours)
        dry_params_l.addStretch()
        dry_l.addWidget(self._dry_params_row)

        # Toggle visibility of params row based on mode
        def _on_dry_mode(idx):
            self._dry_params_row.setVisible(idx > 0)
        self._combo_dry.currentIndexChanged.connect(_on_dry_mode)
        self._dry_params_row.setVisible(False)  # default: not enabled

        # Restore from last_options if available
        saved_mode = last.get("dry_mode", 0)
        self._combo_dry.setCurrentIndex(saved_mode)
        self._dry_params_row.setVisible(saved_mode > 0)
        if last.get("dry_temp"):
            self._sp_dry_temp.setValue(last["dry_temp"])
        if last.get("dry_hours"):
            self._sp_dry_hours.setValue(last["dry_hours"])

        right.addWidget(grp_dry)

        right.addStretch()

        # ── Buttons ──
        btn_row = QHBoxLayout()

        btn_cancel = QPushButton("Cancel")
        btn_cancel.setFont(QFont("Courier New", 11))
        btn_cancel.setMinimumHeight(38)
        btn_cancel.setMinimumWidth(100)
        btn_cancel.clicked.connect(self.cancelled.emit)

        # Botão "Print Status" — navega para tela de workbench/acompanhar impressão
        btn_status = QPushButton("⫷⫣⫻ STATUS ⫻⫦⫸")
        btn_status.setFont(QFont("Courier New", 10))
        btn_status.setMinimumHeight(38)
        btn_status.setMinimumWidth(130)
        btn_status.setStyleSheet("""
            QPushButton {
                background:#0A1520; border:1px solid #00E5FF; color:#00E5FF;
                font-family:'Courier New'; font-size:10px; padding:0 12px; border-radius:2px;
            }
            QPushButton:hover { background:#0D2030; }
        """)
        btn_status.clicked.connect(self.watch_requested.emit)

        # ── Split button: ação principal + dropdown de alternativas ──────────
        # Ações disponíveis — (id, label)
        self._ACTIONS = [
            ("print",      "▶ PRINT"),
            ("save_3mf",   "💾 EXPORT"),
        ]
        self._current_action = "print"   # ação padrão

        # Container para o split button (botão principal + seta)
        split_container = QWidget()
        split_container.setEnabled(False)   # desabilitado até arquivo carregado
        split_lay = QHBoxLayout(split_container)
        split_lay.setContentsMargins(0, 0, 0, 0)
        split_lay.setSpacing(0)

        # Botão principal — executa a ação atual
        self._btn_start = QPushButton("▶ PRINT")
        self._btn_start.setFont(QFont("Courier New", 11, QFont.Weight.Bold))
        self._btn_start.setMinimumHeight(38)
        self._btn_start.setStyleSheet("""
            QPushButton {
                background:#003D52; border:1px solid #00E5FF; color:#00E5FF;
                font-family:'Courier New'; font-size:11px; font-weight:bold;
                letter-spacing:1px; border-right:none;
                border-radius:2px 0 0 2px; padding:0 14px;
            }
            QPushButton:hover  { background:#005070; }
            QPushButton:pressed{ background:#00E5FF; color:#000; }
            QPushButton:disabled{ background:#0D0F11; border-color:#1A2535;
                                   color:#2A3540; border-right:none; }
        """)
        self._btn_start.clicked.connect(self._on_start)

        # Botão seta — abre menu de opções
        from PyQt6.QtWidgets import QMenu
        self._btn_arrow = QPushButton("▾")
        self._btn_arrow.setFont(QFont("Courier New", 11, QFont.Weight.Bold))
        self._btn_arrow.setFixedWidth(26)
        self._btn_arrow.setMinimumHeight(38)
        self._btn_arrow.setStyleSheet("""
            QPushButton {
                background:#003D52; border:1px solid #00E5FF; color:#00E5FF;
                font-size:12px; border-radius:0 2px 2px 0; padding:0;
            }
            QPushButton:hover  { background:#005070; }
            QPushButton:pressed{ background:#00E5FF; color:#000; }
            QPushButton:disabled{ background:#0D0F11; border-color:#1A2535; color:#2A3540; }
        """)

        def _show_action_menu():
            menu = QMenu(self._btn_arrow)
            menu.setStyleSheet("""
                QMenu {
                    background:#111820; border:1px solid #00E5FF;
                    color:#C8D0D8; font-family:'Courier New'; font-size:11px;
                    padding:4px 0;
                }
                QMenu::item { padding:7px 24px 7px 14px; }
                QMenu::item:selected { background:#003D52; color:#00E5FF; }
                QMenu::item:checked  { color:#00E5FF; }
            """)
            for action_id, action_label in self._ACTIONS:
                act = menu.addAction(action_label)
                act.setCheckable(True)
                act.setChecked(action_id == self._current_action)
                act.setData(action_id)

            chosen = menu.exec(
                self._btn_arrow.mapToGlobal(
                    self._btn_arrow.rect().bottomLeft()
                )
            )
            if chosen and chosen.data():
                self._current_action = chosen.data()
                label = next(lbl for aid, lbl in self._ACTIONS
                             if aid == self._current_action)
                self._btn_start.setText(label)

        self._btn_arrow.clicked.connect(_show_action_menu)
        self._split_container = split_container

        split_lay.addWidget(self._btn_start)
        split_lay.addWidget(self._btn_arrow)

        # ── Layout dos botões em 2 linhas ──────────────────────────────────
        # Linha 1: Print Status (esquerda) | Split button (direita)
        # Linha 2: Cancel (largura total)
        from PyQt6.QtWidgets import QVBoxLayout as _QVB
        btn_area = _QVB()
        btn_area.setSpacing(6)
        btn_area.setContentsMargins(0, 0, 0, 0)

        btn_top = QHBoxLayout()
        btn_top.setSpacing(8)
        btn_top.addWidget(btn_status, 1)
        btn_top.addWidget(split_container, 1)

        btn_bottom = QHBoxLayout()
        btn_bottom.addWidget(btn_cancel)

        btn_area.addLayout(btn_top)
        btn_area.addLayout(btn_bottom)

        right.addLayout(btn_area)

        content.addLayout(right, 2)
        root.addLayout(content, 1)

    # ── Public API ───────────────────────────────────────────────────────────

    def load_file(self, filepath: str):
        self._filepath = filepath
        self._lbl_filename.setText(os.path.basename(filepath))

        # _extract_thumb_bytes suporta .gcode, .gcode.3mf, .3mf e ZIP sem extensão
        thumb = None
        img_data = _extract_thumb_bytes(filepath)
        if img_data:
            img = QImage.fromData(img_data)
            if not img.isNull():
                thumb = QPixmap.fromImage(img)

        self._thumbnail = thumb
        if thumb:
            self._thumb.setPixmap(
                thumb.scaled(198, 178,
                             Qt.AspectRatioMode.KeepAspectRatio,
                             Qt.TransformationMode.SmoothTransformation)
            )
            self._thumb.setText("")
            # Salva PNG para o workbench usar depois
            try:
                from core import job_state
                preview_dir = job_state.preview_dir()
                safe = "".join(c if c.isalnum() or c in "-_." else "_"
                               for c in os.path.splitext(os.path.basename(filepath))[0])
                png_path = os.path.join(preview_dir, safe + ".png")
                if thumb.save(png_path, "PNG"):
                    self._preview_png = png_path
                    job_state.save(
                        filepath=filepath,
                        task_name=os.path.basename(filepath),
                        preview_png=png_path,
                    )
                else:
                    self._preview_png = None
            except Exception:
                self._preview_png = None
        else:
            self._thumb.clear()
            self._thumb.setText("NO  PREVIEW")
            self._preview_png = None

        self._meta = parse_gcode_meta(filepath)
        self._m_time.setText(self._meta.get("estimated_time",  "--"))
        self._m_weight.setText(self._meta.get("filament_used_g", "--"))
        self._m_length.setText(self._meta.get("filament_used_m", "--"))
        self._m_material.setText(self._meta.get("material",      "--"))
        self._m_layers.setText(self._meta.get("layer_count",     "--"))

        self._rebuild_map_rows()

        # Preenche nome sugerido no campo FILE NAME
        base = os.path.splitext(os.path.basename(filepath))[0]
        for suf in (".gcode.3mf", "_se3d.gcode", "_se3d", ".gcode"):
            if base.endswith(suf):
                base = base[:-len(suf)]
                break
        self._inp_filename.setText(base)
        upload_mode = self._settings.get("upload_mode", "full")
        self._lbl_fname_ext.setText(".gcode" if upload_mode == "gcode_only" else ".gcode.3mf")

        connected = getattr(self, "_connected", False)
        self._refresh_print_btn()

        # ── Aviso ACE desconectado ───────────────────────────────────────────
        ace_connected = self._settings.get("ace_connected", False)
        if hasattr(self, "_lbl_no_ace"):
            self._lbl_no_ace.setVisible(not ace_connected)

        # ── Aviso: mais de 4 cores sem 2 ACE Pro ────────────────────────────
        colors = self._meta.get("filament_colors", [])
        if len(colors) > 4:
            self._check_multi_color_warning(len(colors))

    def _check_multi_color_warning(self, color_count: int):
        """Avisa o usuário quando o arquivo tem mais de 4 cores (limite de 1 ACE Pro)."""
        msg = QMessageBox(self)
        msg.setWindowTitle("Múltiplas cores detectadas")
        msg.setIcon(QMessageBox.Icon.Warning)
        msg.setText(
            f"Este arquivo usa <b>{color_count} cores</b>.<br><br>"
            "O ACE Pro suporta até <b>4 slots</b> por unidade.<br>"
            "Você tem <b>2 ACE Pro</b> conectados?"
        )
        btn_yes = msg.addButton("Sim, tenho 2 ACE Pro", QMessageBox.ButtonRole.YesRole)
        btn_no  = msg.addButton("Não, tenho apenas 1",  QMessageBox.ButtonRole.NoRole)
        msg.setDefaultButton(btn_no)
        msg.exec()

        if msg.clickedButton() == btn_no:
            msg2 = QMessageBox(self)
            msg2.setWindowTitle("Atenção — cores excedentes")
            msg2.setIcon(QMessageBox.Icon.Information)
            msg2.setText(
                f"Com apenas 1 ACE Pro, o arquivo de <b>{color_count} cores</b> pode gerar "
                "um erro na impressora ao iniciar.<br><br>"
                "<b>Recomendado:</b> abra o arquivo no fatiador, remova uma cor e "
                "fatie novamente antes de imprimir.<br><br>"
                "Deseja continuar mesmo assim?"
            )
            msg2.setStandardButtons(
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            msg2.setDefaultButton(QMessageBox.StandardButton.No)
            if msg2.exec() != QMessageBox.StandardButton.Yes:
                self._btn_start.setEnabled(False)
                self._lbl_mismatch.setText(
                    f"⚠  {color_count} cores detectadas — remova uma cor no fatiador "
                    "ou conecte um 2º ACE Pro antes de imprimir."
                )

    def _rebuild_map_rows(self, preserve_user_selection: bool = True):
        # Salva seleções atuais do usuário antes de reconstruir
        saved = {}
        if preserve_user_selection:
            for row in self._map_rows:
                saved[row._slot_idx] = row._combo.currentIndex()

        self._map_rows.clear()
        while self._map_layout.count() > 1:
            item = self._map_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        ace_slots = self._settings.get("slots", [
            {"paint_color": [255, 255, 255], "material_type": "PLA"},
            {"paint_color": [40,  40,  40 ], "material_type": "PLA"},
            {"paint_color": [255, 0,   0  ], "material_type": "PLA"},
            {"paint_color": [0,   0,   255], "material_type": "PLA"},
        ])
        ace_slots_show = [s for s in ace_slots if s.get("status", 5) != 0] or ace_slots

        slicer_colors = self._meta.get("filament_colors_rgb", [])
        slicer_types  = self._meta.get("filament_types",      [])

        used_slots = self._detect_used_slots()
        if not used_slots:
            used_slots = [0]

        mismatch = False
        for t_idx in used_slots:
            _c    = slicer_colors[t_idx] if t_idx < len(slicer_colors) else [200, 200, 200]
            color = [int(_c[0]), int(_c[1]), int(_c[2])] if len(_c) >= 3 else [200, 200, 200]
            mat   = slicer_types[t_idx]  if t_idx < len(slicer_types)  else "—"
            row   = ColorMapRow(t_idx, color, mat, ace_slots_show)

            # Restaura seleção do usuário se existir
            if preserve_user_selection and t_idx in saved:
                idx = saved[t_idx]
                if 0 <= idx < row._combo.count():
                    row._combo.setCurrentIndex(idx)
                    # Atualiza pill de cor ACE manualmente
                    if idx < len(ace_slots_show):
                        row._ace_pill.set_color(ace_slots_show[idx].get("paint_color", [255,255,255]))
                        row._ace_pill._label = f"S{idx + 1}"
                        row._ace_pill.update()

            self._map_layout.insertWidget(self._map_layout.count() - 1, row)
            self._map_rows.append(row)

            ace_idx = row.get_mapping()["ace"]
            if ace_idx < len(ace_slots):
                ace_color = ace_slots[ace_idx].get("paint_color", [255, 255, 255])
                if color != ace_color and color != [200, 200, 200]:
                    mismatch = True

        if mismatch:
            self._lbl_mismatch.setText("⚠  Color mismatch.")
        else:
            self._lbl_mismatch.setText("")

    def _detect_used_slots(self) -> list[int]:
        import re
        used = set()
        try:
            with open(self._filepath, "r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    m = re.match(r"^T(\d)", line.strip())
                    if m:
                        used.add(int(m.group(1)))
        except Exception:
            pass
        return sorted(used)

    

    def _refresh_print_btn(self):
        QMetaObject.invokeMethod(self, "_do_refresh_print_btn",
                                Qt.ConnectionType.QueuedConnection)

    @pyqtSlot()
    def _do_refresh_print_btn(self):
        connected   = getattr(self, "_connected", False)
        last_state  = getattr(self, "_last_state", "OFFLINE")
        is_idle     = last_state in ("IDLE", "")
        file_loaded = bool(getattr(self, "_filepath", None))
        can_print   = connected and is_idle and file_loaded
        if hasattr(self, "_split_container"):
            self._split_container.setEnabled(can_print)

    def update_connection_OLDOLD(self, connected: bool, ip: str = ""):
        self._connected = connected
        if connected:
            name = f"Anycubic KS1  |  {ip}" if ip else "Anycubic KS1-C"
            self._combo_printer.setItemText(0, name)
            self._chk_ai.setEnabled(False)
        else:
            self._chk_ai.setEnabled(False)

        file_loaded = bool(getattr(self, "_filepath", None))
        last_state  = getattr(self, "_last_state", "OFFLINE")
        is_idle     = last_state in ("IDLE", "")
        can_print   = connected and is_idle and file_loaded

        if hasattr(self, "_split_container"):
            self._split_container.setEnabled(can_print)

    def update_connection(self, connected: bool, ip: str = ""):
        self._connected = connected
        self._chk_ai.setEnabled(False)
        self._refresh_print_btn()


    def update_printer_state(self, state: str):
        self._last_state = state
        self._refresh_print_btn()

    def refresh_ace_slots(self):
        if hasattr(self, "_filepath") and self._filepath:
            self._rebuild_map_rows()

    def _on_start(self):
        if not self._filepath:
            return
        mapping = [r.get_mapping() for r in self._map_rows]
        dry_mode  = self._combo_dry.currentData()
        dry_temp  = self._sp_dry_temp.value()
        dry_hours = self._sp_dry_hours.value()
        opts = {
            "auto_leveling":    self._chk_leveling.isChecked(),
            "resonance":        self._chk_resonance.isChecked(),
            "timelapse":        self._chk_timelapse.isChecked(),
            "flow_calibration": self._chk_flow.isChecked(),
            "ai_detection":     self._chk_ai.isChecked(),
            "dry_mode":         dry_mode,
            "dry_temp":         dry_temp  if dry_mode > 0 else 0,
            "dry_hours":        dry_hours if dry_mode > 0 else 0,
        }
        # Nome digitado pelo usuário, ou fallback para nome do arquivo
        custom_name = self._inp_filename.text().strip()
        if not custom_name:
            custom_name = os.path.splitext(os.path.basename(self._filepath))[0]
            for suf in (".gcode.3mf", "_se3d.gcode", "_se3d", ".gcode"):
                if custom_name.endswith(suf):
                    custom_name = custom_name[:-len(suf)]
                    break

        job = {
            "filepath":      self._filepath,
            "task_name":     custom_name,
            "color_mapping": mapping,
            "thumbnail":     self._thumbnail,
            "preview_png":   getattr(self, "_preview_png", None),
            **opts,
        }

        action = getattr(self, "_current_action", "print")
        if action == "save_3mf":
            self._on_save_3mf(job)
        else:
            self.confirmed.emit(job)

    def _on_save_3mf(self, job: dict):
        """Exporta o arquivo: .gcode processado (modo gcode_only) ou .gcode.3mf (modo full)."""
        import threading
        from PyQt6.QtWidgets import QFileDialog, QMessageBox, QProgressDialog
        from PyQt6.QtCore import Qt

        filepath     = job["filepath"]
        fname_lower  = filepath.lower()
        is_3mf       = fname_lower.endswith(".3mf") and not fname_lower.endswith(".gcode.3mf")
        upload_mode  = self._settings.get("upload_mode", "full")

        configured_slots = self._settings.get("slots", [])
        # Para gcode_only: paint_info usa índices físicos ACE Pro (compatibilidade reimpressão)
        # Para full (3mf): pack() já recebe configured_slots e usa paint_index/index internamente
        pack_slots_map = []
        for m in job.get("color_mapping", []):
            slicer_idx = m["slicer"]
            ace_idx    = m["ace"]
            if ace_idx < len(configured_slots):
                s = configured_slots[ace_idx]
                pack_slots_map.append({
                    "paint_index":   slicer_idx,
                    "paint_color":   s.get("paint_color",   [200, 200, 200]),
                    "material_type": s.get("material_type", "PLA"),
                })

        prog_label = "Processando .gcode..." if upload_mode == "gcode_only" else "Gerando .gcode.3mf..."
        prog = QProgressDialog(prog_label, None, 0, 0, self)
        prog.setWindowTitle("Aguarde")
        prog.setWindowModality(Qt.WindowModality.WindowModal)
        prog.setMinimumWidth(320)
        prog.setCancelButton(None)
        prog.show()

        result_path = [None]
        error_msg   = [None]

        def _worker():
            try:
                from main import GCode3mfPacker

                if upload_mode == "gcode_only":
                    # Lê o gcode (de arquivo direto ou de dentro de um .gcode.3mf)
                    if fname_lower.endswith(".gcode.3mf"):
                        src = GCode3mfPacker.extract_gcode(filepath)
                    elif is_3mf:
                        src = filepath   # .3mf puro — extrai também
                        src = GCode3mfPacker.extract_gcode(filepath)
                    else:
                        src = filepath

                    for enc in ("utf-8", "utf-8-sig", "latin-1", "cp1252"):
                        try:
                            with open(src, "r", encoding=enc) as f:
                                gcode = f.read()
                            break
                        except UnicodeDecodeError:
                            continue
                    else:
                        with open(src, "rb") as f:
                            gcode = f.read().decode("utf-8", errors="replace")

                    # Aplica conversões (M486 → EXCLUDE_OBJECT, paint_info)
                    if "M486 S" in gcode and 'A"' in gcode:
                        gcode = GCode3mfPacker._convert_orca_to_klipper_objects(gcode)
                    if pack_slots_map:
                        gcode = GCode3mfPacker._inject_paint_info(gcode, pack_slots_map)

                    # Injeta topdown thumbnail no gcode
                    topdown_go = GCode3mfPacker._generate_topdown_thumb(gcode)
                    if topdown_go:
                        gcode = GCode3mfPacker._replace_topdown_in_gcode(gcode, topdown_go)

                    import tempfile as _tmp
                    base = os.path.splitext(os.path.basename(src))[0]
                    for suf in ("_se3d.gcode", "_se3d", ".gcode"):
                        if base.endswith(suf):
                            base = base[:-len(suf)]
                    result_path[0] = os.path.join(_tmp.gettempdir(), base + "_se3d.gcode")
                    with open(result_path[0], "w", encoding="utf-8") as f:
                        f.write(gcode)

                else:
                    # Modo full — empacota como .gcode.3mf
                    if is_3mf:
                        result_path[0] = filepath
                    else:
                        original = filepath
                        if fname_lower.endswith(".gcode.3mf"):
                            original = GCode3mfPacker.extract_gcode(filepath)
                        pack_slots = pack_slots_map if pack_slots_map else (
                            configured_slots if self._settings.get("ace_connected") else None
                        )
                        result_path[0] = GCode3mfPacker.pack(original, slots=pack_slots)

            except Exception as exc:
                error_msg[0] = str(exc)

        t = threading.Thread(target=_worker, daemon=True)
        t.start()

        from PyQt6.QtWidgets import QApplication
        while t.is_alive():
            QApplication.processEvents()
            t.join(timeout=0.05)

        prog.close()

        if error_msg[0]:
            QMessageBox.critical(self, "Erro ao gerar arquivo", error_msg[0])
            return

        generated = result_path[0]
        if not generated or not os.path.isfile(generated):
            QMessageBox.critical(self, "Erro", "Arquivo não foi gerado.")
            return

        # Nome sugerido — usa campo FILE NAME digitado pelo usuário
        user_custom = self._inp_filename.text().strip()
        base_name = user_custom if user_custom else os.path.splitext(os.path.basename(filepath))[0]
        for suf in (".gcode", "_se3d"):
            if base_name.endswith(suf):
                base_name = base_name[:-len(suf)]

        if upload_mode == "gcode_only":
            suggested    = base_name + "_se3d.gcode"
            file_filter  = "GCode Files (*.gcode);;Todos os arquivos (*)"
            dialog_title = "Salvar .gcode"
        else:
            suggested    = base_name + ".gcode.3mf"
            file_filter  = "3MF GCode (*.gcode.3mf);;Todos os arquivos (*)"
            dialog_title = "Salvar .gcode.3mf"

        save_path, _ = QFileDialog.getSaveFileName(
            self,
            dialog_title,
            os.path.join(os.path.expanduser("~"), "Desktop", suggested),
            file_filter
        )
        if not save_path:
            return

        import shutil
        try:
            shutil.copy2(generated, save_path)
            extra = "" if upload_mode == "gcode_only" else (
                "\n\nVocê pode inspecionar o conteúdo\n"
                "(renomeie para .zip e abra com qualquer descompactador)."
            )
            QMessageBox.information(
                self, "Arquivo salvo",
                f"Arquivo salvo em:\n{save_path}{extra}"
            )
        except Exception as exc:
            QMessageBox.critical(self, "Erro ao salvar", str(exc))


# ─────────────────────────────────────────────
# Printer Status Panel (used in SetupScreen right side)
# ─────────────────────────────────────────────
class PrinterStatusPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._mqtt = None
        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        hdr = QFrame()
        hdr.setFixedHeight(60)
        hdr.setStyleSheet("background:#080C0F; border-bottom:1px solid #1A2535;")
        hl = QHBoxLayout(hdr)
        hl.setContentsMargins(14, 0, 14, 0)
        lbl = QLabel("STATUS  DA  IMPRESSORA")
        lbl.setFont(QFont("Courier New", 10, QFont.Weight.Bold))
        lbl.setStyleSheet("color:#00E5FF; letter-spacing:3px;")
        self._lbl_conn = QLabel("● DESCONECTADA")
        self._lbl_conn.setFont(QFont("Courier New", 9))
        self._lbl_conn.setStyleSheet("color:#FF4444;")
        hl.addWidget(lbl)
        hl.addStretch()
        hl.addWidget(self._lbl_conn)
        root.addWidget(hdr)

        stats = QFrame()
        stats.setStyleSheet("background:#060A0D; border-bottom:1px solid #111820;")
        grid = QGridLayout(stats)
        grid.setContentsMargins(14, 10, 14, 10)
        grid.setHorizontalSpacing(18)
        grid.setVerticalSpacing(4)

        def _s(label, row, col):
            n = QLabel(label)
            n.setFont(QFont("Courier New", 8))
            n.setStyleSheet("color:#1E3550;")
            v = QLabel("--")
            v.setFont(QFont("Courier New", 11, QFont.Weight.Bold))
            v.setStyleSheet("color:#607080;")
            grid.addWidget(n, row * 2,     col)
            grid.addWidget(v, row * 2 + 1, col)
            return v

        self._v_state    = _s("ESTADO",    0, 0)
        self._v_progress = _s("PROGRESSO", 0, 1)
        self._v_layer    = _s("CAMADA",    0, 2)
        self._v_eta      = _s("ETA",       1, 0)
        self._v_bed      = _s("MESA",      1, 1)
        self._v_noz      = _s("BICO",      1, 2)
        root.addWidget(stats)

        log_hdr = QFrame()
        log_hdr.setFixedHeight(60)
        log_hdr.setStyleSheet("background:#080C0F; border-bottom:1px solid #111820;")
        lh = QHBoxLayout(log_hdr)
        lh.setContentsMargins(14, 0, 14, 0)
        lbl2 = QLabel("FEEDBACK  MQTT")
        lbl2.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        lbl2.setStyleSheet("color:#1E3550; letter-spacing:2px;")
        btn_clr = QPushButton("limpar")
        btn_clr.setFont(QFont("Courier New", 8))
        btn_clr.setStyleSheet(
            "QPushButton{color:#1E3550;background:transparent;border:none;}"
            "QPushButton:hover{color:#00E5FF;}"
        )
        btn_clr.clicked.connect(lambda: self._log.clear())
        lh.addWidget(lbl2)
        lh.addStretch()
        lh.addWidget(btn_clr)
        root.addWidget(log_hdr)

        self._log = QTextEdit()
        self._log.setReadOnly(True)
        self._log.setFont(QFont("Courier New", 8))
        self._log.setStyleSheet(
            "QTextEdit{background:#050810;color:#2A4560;border:none;padding:8px;}"
        )
        self._log.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        root.addWidget(self._log, 1)

    def set_connected(self, connected: bool, ip: str = ""):
        if connected:
            self._lbl_conn.setText(f"● {ip}" if ip else "● CONECTADA")
            self._lbl_conn.setStyleSheet("color:#00E5FF;")
        else:
            self._lbl_conn.setText("● DESCONECTADA")
            self._lbl_conn.setStyleSheet("color:#FF4444;")
            for v in (self._v_state, self._v_progress, self._v_layer,
                      self._v_eta, self._v_bed, self._v_noz):
                v.setText("--")
                v.setStyleSheet("color:#607080;")

    def set_mqtt(self, mqtt):
        if self._mqtt:
            try: self._mqtt.printer_info.disconnect(self._on_info)
            except Exception: pass
            try: self._mqtt.print_report.disconnect(self._on_report)
            except Exception: pass
        self._mqtt = mqtt
        if self._mqtt:
            self._mqtt.printer_info.connect(self._on_info)
            self._mqtt.print_report.connect(self._on_report)

    def _on_info(self, payload: dict):
        src  = payload.get("_source", "")
        data = payload.get("data", {}) or {}
        from datetime import datetime
        ts = datetime.now().strftime("%H:%M:%S")
        if src == "temp":
            bed   = data.get("bed_actual",  data.get("curr_hotbed_temp"))
            bed_t = data.get("bed_target",  data.get("target_hotbed_temp", 0))
            noz   = data.get("hotend0_actual", data.get("curr_nozzle_temp"))
            noz_t = data.get("hotend0_target", data.get("target_nozzle_temp", 0))
            if bed is not None:
                self._sv(self._v_bed, f"{bed}°/{bed_t}°",
                         "#FFB300" if bed_t else "#607080")
            if noz is not None:
                self._sv(self._v_noz, f"{noz}°/{noz_t}°",
                         "#FF6E40" if noz_t else "#607080")
            self._log_line(ts, f"temp  mesa={bed}°  bico={noz}°")
            return
        project = data.get("project", {})
        if project:
            state  = project.get("state") or ""
            pct    = project.get("progress", 0)
            layer  = project.get("curr_layer",    "--")
            layers = project.get("total_layers",  "--")
            eta    = project.get("remain_time",   0)
            fname  = project.get("filename",      "")
            colors = {
                "printing":     "#00E5FF",
                "auto_leveling":"#FFB300",
                "paused":       "#FF9800",
                "failed":       "#FF4444",
                "stoped":       "#607080",
            }
            self._sv(self._v_state,    state.upper() if state else "--", colors.get(state, "#607080"))
            self._sv(self._v_progress, f"{pct}%", "#00E5FF" if pct else "#607080")
            self._sv(self._v_layer,    f"{layer}/{layers}", "#8090A0")
            if eta:
                m, s = divmod(int(eta), 60)
                h, m = divmod(m, 60)
                self._sv(self._v_eta, f"{h:02d}:{m:02d}:{s:02d}", "#8090A0")
            if fname:
                self._log_line(ts, f"info  {state}  {pct}%  {fname[:32]}")

    def _on_report(self, payload: dict):
        action = payload.get("action", "")
        data   = payload.get("data", {}) or {}
        fname  = data.get("filename", "")
        from datetime import datetime
        ts = datetime.now().strftime("%H:%M:%S")
        if action:
            self._log_line(ts, f"print/{action}  {fname[:38]}")

    def _sv(self, lbl, text, color="#607080"):
        lbl.setText(text)
        lbl.setStyleSheet(f"color:{color}; font-weight:bold;")

    def _log_line(self, ts: str, text: str):
        line = (f'<span style="color:#1A3050">{ts}</span> '
                f'<span style="color:#3A6080">{text}</span>')
        self._log.append(line)
        if self._log.document().blockCount() > 300:
            cur = self._log.textCursor()
            cur.movePosition(cur.MoveOperation.Start)
            cur.select(cur.SelectionType.BlockUnderCursor)
            cur.removeSelectedText()
        self._log.verticalScrollBar().setValue(
            self._log.verticalScrollBar().maximum()
        )


# ─────────────────────────────────────────────
# Setup screen (initial drop / select)
# ─────────────────────────────────────────────
class PrintSetupScreen(QWidget):
    file_loaded     = pyqtSignal(str)
    watch_requested = pyqtSignal()

    def __init__(self, settings: dict, parent=None):
        super().__init__(parent)
        self._settings = settings
        self._filepath = None
        self._ace_data_received = False  # só True após receber dados do ACE ao conectar
        self._build_ui()

    def _build_ui(self):
        self.setAcceptDrops(True)

        main = QHBoxLayout(self)
        main.setContentsMargins(0, 0, 0, 0)
        main.setSpacing(0)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setStyleSheet("QSplitter::handle { background:#1A2535; width:2px; }")

        # Esquerda: drop zone
        left = QWidget()
        left_l = QVBoxLayout(left)
        left_l.setContentsMargins(40, 40, 40, 40)
        left_l.setSpacing(16)
        left_l.setAlignment(Qt.AlignmentFlag.AlignCenter)

        hdr = QFrame()
        hdr_l = QHBoxLayout(hdr)
        hdr_l.setContentsMargins(0, 0, 0, 0)
        lbl_title = QLabel("PRINT  SETUP")
        lbl_title.setFont(QFont("Courier New", 12, QFont.Weight.Bold))
        lbl_title.setStyleSheet("color:#00E5FF; letter-spacing:4px;")
        lbl_hint_hdr = QLabel("Selecione ou arraste um arquivo .gcode / .3mf")
        lbl_hint_hdr.setFont(QFont("Courier New", 9))
        lbl_hint_hdr.setStyleSheet("color:#2A4050;")
        #self._btn_watch = QPushButton("📊 STATUS")
        #self._btn_watch.setFont(QFont("Courier New", 9, QFont.Weight.Bold))
        #self._btn_watch.setMinimumWidth(100)
        #self._btn_watch.setFixedHeight(60)
        #self._btn_watch.setStyleSheet(
        #    "QPushButton{color:#00E5FF;background:#0A1520;border:1px solid #00E5FF;"
        #    "padding:0 12px;border-radius:3px;} QPushButton:hover{background:#0D2030;}"
        #)
        #self._btn_watch.setVisible(False)
        #self._btn_watch.clicked.connect(self.watch_requested)
        hdr_l.addWidget(lbl_title)
        hdr_l.addSpacing(16)
        hdr_l.addWidget(lbl_hint_hdr)
        hdr_l.addStretch()
        #hdr_l.addWidget(self._btn_watch)
        left_l.addWidget(hdr)

        # Drop zone
        self._drop_frame = QFrame()
        self._drop_frame.setMinimumSize(360, 220)
        self._drop_frame.setMaximumWidth(520)
        self._drop_frame.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._drop_frame.setStyleSheet("""
            QFrame { border:2px dashed #1E3550; border-radius:8px; background:#0A0D10; }
        """)
        self._drop_frame.setAcceptDrops(True)
        self._drop_frame.dragEnterEvent = self._on_drag_enter
        self._drop_frame.dropEvent      = self._on_drop

        drop_l = QVBoxLayout(self._drop_frame)
        drop_l.setAlignment(Qt.AlignmentFlag.AlignCenter)
        drop_l.setSpacing(10)

        lbl_icon = QLabel("⬇")
        lbl_icon.setFont(QFont("Courier New", 34))
        lbl_icon.setStyleSheet("color:#1A3D55; border:none;")
        lbl_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        drop_l.addWidget(lbl_icon)

        self._lbl_hint = QLabel("DRAG  .GCODE  FILE  HERE")
        self._lbl_hint.setFont(QFont("Courier New", 13, QFont.Weight.Bold))
        self._lbl_hint.setStyleSheet("color:#1E4060; letter-spacing:3px; border:none;")
        self._lbl_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        drop_l.addWidget(self._lbl_hint)

        lbl_ext = QLabel(".gcode  /  .bgcode  /  .gc")
        lbl_ext.setFont(QFont("Courier New", 8))
        lbl_ext.setStyleSheet("color:#162030; letter-spacing:2px; border:none;")
        lbl_ext.setAlignment(Qt.AlignmentFlag.AlignCenter)
        drop_l.addWidget(lbl_ext)
        drop_l.addSpacing(8)

        lbl_or = QLabel("─── ou ───")
        lbl_or.setFont(QFont("Courier New", 9))
        lbl_or.setStyleSheet("color:#1A2535; border:none;")
        lbl_or.setAlignment(Qt.AlignmentFlag.AlignCenter)
        drop_l.addWidget(lbl_or)

        btn_sel = QPushButton("SELECT  FILE")
        btn_sel.setFont(QFont("Courier New", 10, QFont.Weight.Bold))
        btn_sel.setObjectName("primary")
        btn_sel.setMinimumWidth(160)
        btn_sel.setFixedHeight(36)
        btn_sel.clicked.connect(self._on_select)
        drop_l.addWidget(btn_sel, alignment=Qt.AlignmentFlag.AlignCenter)

        drop_l.addSpacing(12)

        self._btn_status = QPushButton("📊 STATUS")
        self._btn_status.setFont(QFont("Courier New", 9, QFont.Weight.Bold))
        self._btn_status.setMinimumWidth(120)
        self._btn_status.setFixedHeight(32)
        self._btn_status.setStyleSheet("""
            QPushButton { background:#001A2A; border:1px solid #00E5FF;
                          color:#00E5FF; border-radius:4px; padding: 0 10px; }
            QPushButton:hover { background:#002A3A; }
        """)
        self._btn_status.clicked.connect(self._on_status_clicked)
        self._btn_status.setVisible(False)
        drop_l.addWidget(self._btn_status, alignment=Qt.AlignmentFlag.AlignCenter)

        left_l.addWidget(self._drop_frame)
        left_l.addStretch()
        splitter.addWidget(left)

        # Direita: painel de status
        self._status_panel = PrinterStatusPanel()
        splitter.addWidget(self._status_panel)
        splitter.setSizes([480, 520])
        main.addWidget(splitter)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        urls = event.mimeData().urls()
        if urls:
            path = urls[0].toLocalFile()
            if path.lower().endswith((".gcode", ".bgcode", ".gc", ".3mf")):
                self._load(path)

    def _on_drag_enter(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def _on_drop(self, event):
        urls = event.mimeData().urls()
        if urls:
            path = urls[0].toLocalFile()
            if path.lower().endswith((".gcode", ".bgcode", ".gc", ".3mf")):
                self._load(path)

    def _on_select(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select File", "",
            "Print Files (*.gcode *.bgcode *.gc *.3mf);;All Files (*)"
        )
        if path:
            self._load(path)

    def _load(self, path: str):
        self._filepath = path
        self._lbl_hint.setText(os.path.basename(path))
        self._lbl_hint.setStyleSheet("color:#00E5FF; letter-spacing:1px;")
        self._drop_frame.setStyleSheet(
            "QFrame { border:2px solid #00E5FF; border-radius:6px; background:#0D0F11; }"
        )
        self.file_loaded.emit(path)

    def _on_status_clicked(self):
        self.watch_requested.emit()

    def set_printing(self, active: bool):
        #if hasattr(self, "_btn_watch"):
        #    self._btn_watch.setVisible(active)
        if hasattr(self, "_btn_status"):
            self._btn_status.setVisible(active)

    def update_connection(self, connected: bool, ip: str = ""):
        if hasattr(self, "_status_panel"):
            self._status_panel.set_connected(connected, ip)
            

    def set_mqtt(self, mqtt_client):
        if hasattr(self, "_status_panel"):
            self._status_panel.set_mqtt(mqtt_client)

    def update_printer_state(self, state: str):
        self._last_printer_state = state
        is_idle    = state in ("IDLE", "")
        is_offline = state in ("OFFLINE",)
        is_busy    = not is_idle and not is_offline

        if hasattr(self, "_btn_status"):
            self._btn_status.setVisible(is_busy)

    def set_ace_ready(self):
        """Dados do ACE chegaram — apenas reavalia o estado atual."""
        self._ace_data_received = True
        last = getattr(self, "_last_printer_state", "")
        if last:
            self.update_printer_state(last)


# ─────────────────────────────────────────────
# Upload progress screen
# ─────────────────────────────────────────────
class _UploadProgressScreen(QWidget):
    cancel_requested = pyqtSignal()
    _sig_step  = pyqtSignal(str, int)
    _sig_indet = pyqtSignal(bool)
    _sig_error = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()
        self._sig_step.connect(self._do_step)
        self._sig_indet.connect(
            lambda on: self._bar.setRange(0, 0) if on else self._bar.setRange(0, 100)
        )
        self._sig_error.connect(self._do_error)

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.setSpacing(20)

        lbl = QLabel("PREPARANDO  IMPRESSÃO")
        lbl.setFont(QFont("Courier New", 13, QFont.Weight.Bold))
        lbl.setStyleSheet("color:#00E5FF; letter-spacing:4px;")
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._lbl_step = QLabel("Iniciando...")
        self._lbl_step.setFont(QFont("Courier New", 10))
        self._lbl_step.setStyleSheet("color:#8090A0;")
        self._lbl_step.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._bar = QProgressBar()
        self._bar.setRange(0, 100)
        self._bar.setValue(0)
        self._bar.setFixedHeight(6)
        self._bar.setFixedWidth(460)
        self._bar.setTextVisible(False)
        self._bar.setStyleSheet(
            "QProgressBar{background:#0D1820;border:none;border-radius:4px;}"
            "QProgressBar::chunk{background:#00E5FF;border-radius:4px;}"
        )

        self._lbl_err = QLabel("")
        self._lbl_err.setFont(QFont("Courier New", 9))
        self._lbl_err.setStyleSheet("color:#FF4444;")
        self._lbl_err.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self._lbl_err.setWordWrap(True)
        self._lbl_err.setMinimumHeight(200)
        self._lbl_err.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._lbl_err.setVisible(False)

        btn = QPushButton("CANCELAR")
        btn.setFont(QFont("Courier New", 9, QFont.Weight.Bold))
        btn.setFixedSize(140, 30)
        btn.clicked.connect(self.cancel_requested)

        root.addStretch()
        root.addWidget(lbl)
        root.addSpacing(10)
        root.addWidget(self._lbl_step, alignment=Qt.AlignmentFlag.AlignCenter)
        root.addWidget(self._bar,      alignment=Qt.AlignmentFlag.AlignCenter)
        root.addWidget(self._lbl_err,  alignment=Qt.AlignmentFlag.AlignCenter)
        root.addSpacing(12)
        root.addWidget(btn,            alignment=Qt.AlignmentFlag.AlignCenter)
        root.addStretch()

    def reset(self):
        self._bar.setRange(0, 100)
        self._bar.setValue(0)
        self._lbl_step.setText("Iniciando...")
        self._lbl_err.setVisible(False)

    def set_step(self, text: str, pct: int): self._sig_step.emit(text, pct)
    def set_indeterminate(self, on: bool):   self._sig_indet.emit(on)
    def set_done(self):                      self._sig_step.emit("Enviado com sucesso ✓", 100)
    def set_error(self, msg: str):           self._sig_error.emit(msg)

    def _do_step(self, text: str, pct: int):
        self._lbl_step.setText(text)
        self._bar.setRange(0, 100)
        self._bar.setValue(pct)

    def _do_error(self, msg: str):
        self._bar.setRange(0, 100)
        self._bar.setValue(0)
        self._lbl_step.setText("Erro durante o processo")
        self._lbl_err.setText(msg[:200])
        self._lbl_err.setVisible(True)


# ─────────────────────────────────────────────
# Workbench screen (durante a impressão)
# ─────────────────────────────────────────────
class WorkbenchScreen(QWidget):
    pause_requested  = pyqtSignal()
    stop_requested   = pyqtSignal()
    cancel_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self):
        main = QVBoxLayout(self)
        main.setContentsMargins(20, 16, 20, 16)
        main.setSpacing(12)

        top_row = QHBoxLayout()
        self._lbl_task  = QLabel("--")
        self._lbl_task.setFont(QFont("Courier New", 14, QFont.Weight.Bold))
        self._lbl_task.setStyleSheet("color:#C8D0D8;")
        self._lbl_phase = QLabel("IDLE")
        self._lbl_phase.setFont(QFont("Courier New", 12))
        self._lbl_phase.setStyleSheet("color:#00E5FF; letter-spacing:2px;")
        btn_back = QPushButton("NEW  PRINT")
        btn_back.setFont(QFont("Courier New", 11))
        btn_back.setMinimumWidth(110)
        btn_back.clicked.connect(self.cancel_requested.emit)
        top_row.addWidget(self._lbl_task)
        top_row.addStretch()
        top_row.addWidget(self._lbl_phase)
        top_row.addSpacing(20)
        top_row.addWidget(btn_back)
        main.addLayout(top_row)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color:#1A2535;")
        main.addWidget(sep)

        mid = QHBoxLayout()
        mid.setSpacing(20)

        thumb_frame = QFrame()
        thumb_frame.setFixedSize(160, 160)
        thumb_frame.setStyleSheet("background:#0D0F11; border:1px solid #1E2D3D; border-radius:3px;")
        thumb_l = QVBoxLayout(thumb_frame)
        thumb_l.setContentsMargins(4, 4, 4, 4)
        self._wb_thumb = QLabel()
        self._wb_thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._wb_thumb.setMinimumSize(150, 150)
        thumb_l.addWidget(self._wb_thumb)
        mid.addWidget(thumb_frame)

        prog_block = QVBoxLayout()
        prog_block.setSpacing(8)

        self._progress = QProgressBar()
        self._progress.setRange(0, 100)
        self._progress.setValue(0)
        self._progress.setTextVisible(False)
        self._progress.setFixedHeight(12)
        self._progress.setStyleSheet("""
            QProgressBar { background:#0D0F11; border:1px solid #1E2D3D; border-radius:2px; }
            QProgressBar::chunk {
                background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
                    stop:0 #005C7A, stop:1 #00E5FF);
                border-radius:2px;
            }
        """)

        pct_row = QHBoxLayout()
        self._lbl_pct = QLabel("0%")
        self._lbl_pct.setFont(QFont("Courier New", 22, QFont.Weight.Bold))
        self._lbl_pct.setStyleSheet("color:#00E5FF;")
        self._lbl_eta = QLabel("ETA  --")
        self._lbl_eta.setFont(QFont("Courier New", 12))
        self._lbl_eta.setStyleSheet("color:#607080;")
        pct_row.addWidget(self._lbl_pct)
        pct_row.addStretch()
        pct_row.addWidget(self._lbl_eta)

        info_grid = QGridLayout()
        info_grid.setSpacing(6)
        info_grid.setColumnStretch(1, 1)
        info_grid.setColumnStretch(3, 1)

        def ib(label, attr_lbl, attr_val):
            l = QLabel(label)
            l.setFont(QFont("Courier New", 10))
            l.setStyleSheet("color:#607080;")
            v = QLabel("--")
            v.setFont(QFont("Courier New", 11, QFont.Weight.Bold))
            v.setStyleSheet("color:#C8D0D8;")
            setattr(self, attr_lbl, l)
            setattr(self, attr_val, v)
            return l, v

        l1, v1 = ib("TIME ELAPSED", "_lbl_elapsed_l", "_lbl_elapsed")
        l2, v2 = ib("LAYER",        "_lbl_layer_l",   "_lbl_layer")
        l3, v3 = ib("BED",          "_lbl_bed_l",     "_lbl_bed_wb")
        l4, v4 = ib("NOZZLE",       "_lbl_noz_l",     "_lbl_noz_wb")

        info_grid.addWidget(l1, 0, 0); info_grid.addWidget(v1, 0, 1)
        info_grid.addWidget(l2, 0, 2); info_grid.addWidget(v2, 0, 3)
        info_grid.addWidget(l3, 1, 0); info_grid.addWidget(v3, 1, 1)
        info_grid.addWidget(l4, 1, 2); info_grid.addWidget(v4, 1, 3)

        prog_block.addLayout(pct_row)
        prog_block.addWidget(self._progress)
        prog_block.addSpacing(4)
        prog_block.addLayout(info_grid)
        prog_block.addStretch()
        mid.addLayout(prog_block, 1)
        main.addLayout(mid)

        sep2 = QFrame()
        sep2.setFrameShape(QFrame.Shape.HLine)
        sep2.setStyleSheet("color:#1A2535;")
        main.addWidget(sep2)

        bot = QHBoxLayout()
        bot.setSpacing(12)

        self._btn_pause = QPushButton("PAUSE")
        self._btn_pause.setFont(QFont("Courier New", 13, QFont.Weight.Bold))
        self._btn_pause.setMinimumSize(140, 44)
        self._btn_pause.clicked.connect(self._on_pause)

        self._btn_stop = QPushButton("STOP")
        self._btn_stop.setObjectName("danger")
        self._btn_stop.setFont(QFont("Courier New", 13, QFont.Weight.Bold))
        self._btn_stop.setMinimumSize(140, 44)
        self._btn_stop.clicked.connect(self._on_stop)

        self._lbl_options = QLabel("")
        self._lbl_options.setFont(QFont("Courier New", 10))
        self._lbl_options.setStyleSheet("color:#3A4550; letter-spacing:1px;")
        self._lbl_options.setWordWrap(True)

        bot.addWidget(self._btn_pause)
        bot.addWidget(self._btn_stop)
        bot.addSpacing(20)
        bot.addWidget(self._lbl_options, 1)
        main.addLayout(bot)

    def start_job(self, job: dict, thumbnail: QPixmap | None = None):
        self._lbl_task.setText(job.get("task_name", "--"))
        self._lbl_phase.setText("PRINTING")
        self._lbl_phase.setStyleSheet("color:#00FF88; letter-spacing:2px;")
        self._progress.setValue(0)
        self._lbl_pct.setText("0%")
        self._lbl_eta.setText("ETA  --")
        self._lbl_elapsed.setText("--")
        self._lbl_layer.setText("--")
        if thumbnail:
            self._wb_thumb.setPixmap(
                thumbnail.scaled(148, 148,
                                 Qt.AspectRatioMode.KeepAspectRatio,
                                 Qt.TransformationMode.SmoothTransformation)
            )
        else:
            self._wb_thumb.clear()
            self._wb_thumb.setText("NO  PREVIEW")
            self._wb_thumb.setStyleSheet("color:#2A3540; font-size:10px;")
        opts = []
        if job.get("auto_leveling"):    opts.append("LEVELING")
        if job.get("ai_detection"):     opts.append("AI")
        if job.get("flow_calibration"): opts.append("FLOW  CAL")
        if job.get("timelapse"):        opts.append("TIMELAPSE")
        if job.get("resonance"):        opts.append("RESONANCE")
        self._lbl_options.setText("  //  ".join(opts))

    def _apply_pending_thumb(self):
        """Chamado na main thread após extração de thumb em background."""
        thumb = getattr(self, "_pending_thumb", None)
        if thumb:
            self._wb_thumb.setStyleSheet("")
            self._wb_thumb.setText("")
            self._wb_thumb.setPixmap(
                thumb.scaled(148, 148,
                             Qt.AspectRatioMode.KeepAspectRatio,
                             Qt.TransformationMode.SmoothTransformation)
            )
            self._pending_thumb = None

    def _apply_pending_thumb_data(self):
        """Converte bytes → QPixmap na main thread e aplica no workbench."""
        data = getattr(self, "_pending_thumb_data", None)
        if data:
            img = QImage.fromData(data)
            if not img.isNull():
                px = QPixmap.fromImage(img)
                self._wb_thumb.setStyleSheet("")
                self._wb_thumb.setText("")
                self._wb_thumb.setPixmap(
                    px.scaled(148, 148,
                               Qt.AspectRatioMode.KeepAspectRatio,
                               Qt.TransformationMode.SmoothTransformation)
                )
            self._pending_thumb_data = None

    def update_progress(self, pct: int, eta: str = "--", elapsed: str = "--",
                        layer: str = "--", bed_temp: str = "--",
                        noz_temp: str = "--", phase: str = ""):
        # pct=-1 é sentinela "só atualizar temperatura, não mexer na barra"
        if pct >= 0:
            self._progress.setValue(pct)
            self._lbl_pct.setText(f"{pct}%")
        if eta not in ("--", ""):
            self._lbl_eta.setText(f"ETA  {eta}")
        if elapsed not in ("--", ""):
            self._lbl_elapsed.setText(elapsed)
        if layer not in ("--", "-/-", "0/0", "0/-", ""):
            self._lbl_layer.setText(layer)
        if bed_temp not in ("--", ""):
            self._lbl_bed_wb.setText(bed_temp)
        if noz_temp not in ("--", ""):
            self._lbl_noz_wb.setText(noz_temp)
        if phase and phase.upper() not in ("", "STOPED", "STOPPED", "STOP",
                                           "FINISH", "COMPLETE", "FINISHED"):
            self._lbl_phase.setText(phase.upper())

    def set_paused(self, paused: bool):
        self._btn_pause.setText("RESUME" if paused else "PAUSE")

    def _on_pause(self):
        paused = self._btn_pause.text() == "RESUME"
        self.set_paused(not paused)
        self.pause_requested.emit()

    def _on_stop(self):
        """Emite stop para a impressora E sinaliza cancelamento da tela."""
        self.stop_requested.emit()
        # Sempre volta para o setup após um delay para dar tempo ao MQTT processar
        QTimer.singleShot(800, self.cancel_requested.emit)


# ─────────────────────────────────────────────
# Main Print Widget  (stack: setup → colormap → workbench → upload)
# ─────────────────────────────────────────────
class PrintWidget(QWidget):
    command_ready     = pyqtSignal(str, object)
    enqueue_requested = pyqtSignal(str)
    _save_preview_sig = pyqtSignal(str)  # path do .gcode.3mf — salva PNG na main thread
    _go_workbench_sig = pyqtSignal()     # cross-thread: vai para workbench após print_start

    def __init__(self, settings: dict, parent=None):
        super().__init__(parent)
        self._settings      = settings
        self._current_job   = None
        self._current_thumb = None
        self._is_printing_cb = None
        self._pending_preview_thumb = None
        self._pending_preview_src   = None
        self._build_ui()
        self._save_preview_sig.connect(self._do_save_preview,
                                       Qt.ConnectionType.QueuedConnection)

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._stack = QStackedWidget()

        self._setup = PrintSetupScreen(self._settings)
        self._setup.file_loaded.connect(self._on_file_loaded)
        self._setup.watch_requested.connect(lambda: self._stack.setCurrentIndex(2))

        self._colormap = ColorMapScreen(self._settings)
        self._colormap.confirmed.connect(self._on_confirmed)
        self._colormap.cancelled.connect(lambda: self._stack.setCurrentIndex(0))
        self._colormap.watch_requested.connect(lambda: self._stack.setCurrentIndex(2))

        self._workbench = WorkbenchScreen()
        self._workbench.pause_requested.connect(lambda: self.command_ready.emit("print_pause", None))
        self._workbench.stop_requested.connect(lambda: self.command_ready.emit("print_stop", None))
        self._workbench.cancel_requested.connect(self._on_workbench_cancelled)

        self._upload_screen = _UploadProgressScreen()
        self._upload_screen.cancel_requested.connect(self._on_upload_cancelled)

        self._stack.addWidget(self._setup)           # 0
        self._stack.addWidget(self._colormap)        # 1
        self._stack.addWidget(self._workbench)       # 2
        self._stack.addWidget(self._upload_screen)   # 3
        self._go_workbench_sig.connect(self.switch_to_workbench)
        layout.addWidget(self._stack)

    def _on_file_loaded(self, path: str):
        # Se impressora ocupada, enfileira em vez de abrir colormap
        if callable(self._is_printing_cb) and self._is_printing_cb():
            self.enqueue_requested.emit(path)
            return
        self._colormap.load_file(path)
        self._stack.setCurrentIndex(1)

    def load_file_from_arg(self, path: str):
        self._on_file_loaded(path)

    # print_widget.py - substitua o método _on_confirmed inteiro

    def _on_confirmed(self, job: dict):
        import threading

        filepath = job["filepath"]

        self._settings["last_options"] = {
            "auto_leveling":    job.get("auto_leveling",    True),
            "resonance":        job.get("resonance",        False),
            "timelapse":        job.get("timelapse",        True),
            "flow_calibration": job.get("flow_calibration", False),
            "ai_detection":     job.get("ai_detection",     False),
            "dry_mode":         job.get("dry_mode",         0),
            "dry_temp":         job.get("dry_temp",         35),
            "dry_hours":        job.get("dry_hours",        12),
        }

        self._stack.setCurrentIndex(3)
        self._upload_screen.reset()

        def _worker():
            try:
                from main import GCode3mfPacker

                upload_mode = self._settings.get("upload_mode", "full")

                if upload_mode == "gcode_only":
                    self._upload_screen.set_step("Preparando arquivo...", 30)
                    # Lê o gcode e injeta topdown thumb
                    src = filepath
                    fname_lower = filepath.lower()
                    if fname_lower.endswith(".gcode.3mf") or fname_lower.endswith(".3mf"):
                        src = GCode3mfPacker.extract_gcode(filepath)
                    for enc in ("utf-8", "utf-8-sig", "latin-1", "cp1252"):
                        try:
                            with open(src, "r", encoding=enc) as _f:
                                gcode_raw = _f.read()
                            break
                        except UnicodeDecodeError:
                            continue
                    else:
                        with open(src, "rb") as _f:
                            gcode_raw = _f.read().decode("utf-8", errors="replace")
                    if "M486 S" in gcode_raw and 'A"' in gcode_raw:
                        gcode_raw = GCode3mfPacker._convert_orca_to_klipper_objects(gcode_raw)
                    # paint_info com índices físicos do ACE Pro — necessário para
                    # reimpressão pelo display (a impressora verifica compatibilidade
                    # comparando paint_index com os slots físicos carregados)
                    configured_slots_go = self._settings.get("slots", [])
                    pack_slots_map_go = []
                    for m in job.get("color_mapping", []):
                        slicer_idx = m["slicer"]
                        ace_idx    = m["ace"]
                        if ace_idx < len(configured_slots_go):
                            s = configured_slots_go[ace_idx]
                            phys_idx = s.get("index", s.get("paint_index", ace_idx))
                            pack_slots_map_go.append({
                                "paint_index":   int(phys_idx),
                                "paint_color":   s.get("paint_color",   [200, 200, 200]),
                                "material_type": s.get("material_type", "PLA"),
                            })
                    if pack_slots_map_go:
                        gcode_raw = GCode3mfPacker._inject_paint_info(gcode_raw, pack_slots_map_go)
                    self._upload_screen.set_step("Gerando thumbnail...", 55)
                    topdown = GCode3mfPacker._generate_topdown_thumb(gcode_raw)
                    if topdown:
                        gcode_raw = GCode3mfPacker._replace_topdown_in_gcode(gcode_raw, topdown)
                    # Salva em temp com nome do usuário
                    user_name_go = job.get("task_name", "").strip() or "print"
                    import tempfile as _tmp2
                    out_dir_go = os.path.join(
                        os.environ.get("LOCALAPPDATA", _tmp2.gettempdir()),
                        "AnyConnect", "SE3D_Hub", "Anycubic"
                    )
                    os.makedirs(out_dir_go, exist_ok=True)
                    import datetime as _dt2
                    ts_go = _dt2.datetime.now().strftime("%Y%m%d_%H%M%S")
                    final_filepath = os.path.join(out_dir_go, f"{user_name_go}_{ts_go}.gcode")
                    with open(final_filepath, "w", encoding="utf-8") as _f:
                        _f.write(gcode_raw)
                    job["filepath"]    = final_filepath
                    job["upload_mode"] = "gcode_only"
                    # NÃO sobrescreve task_name — usa o do usuário

                else:
                    # Modo full — inclui mapeamento de slots do ACE Pro
                    self._upload_screen.set_step("Empacotando em .gcode.3mf...", 40)
                    configured_slots = self._settings.get("slots", [])

                    pack_slots_map = []
                    for m in job.get("color_mapping", []):
                        slicer_idx = m["slicer"]
                        ace_idx    = m["ace"]
                        if ace_idx < len(configured_slots):
                            s = configured_slots[ace_idx]
                            pack_slots_map.append({
                                "paint_index":   slicer_idx,
                                "paint_color":   s.get("paint_color",   [200, 200, 200]),
                                "material_type": s.get("material_type", "PLA"),
                                "ace_index":     ace_idx,
                            })

                    ace_connected = self._settings.get("ace_connected", False)
                    if pack_slots_map:
                        pack_slots = pack_slots_map
                    elif ace_connected:
                        pack_slots = configured_slots
                    else:
                        pack_slots = None

                    gcode_3mf_path = GCode3mfPacker.pack(filepath, slots=pack_slots)
                    final_filepath = gcode_3mf_path

                # Usa o nome digitado pelo usuário; se vazio, usa basename do arquivo gerado
                user_task_name = job.get("task_name", "").strip()
                if not user_task_name:
                    user_task_name = os.path.splitext(os.path.basename(final_filepath))[0]

                job["filepath"]              = final_filepath
                job["task_name"]             = user_task_name
                job["file_id"]               = ""
                job["slots_config"]          = self._settings.get("slots", [])
                job["printer_ip"]            = self._settings.get("printer_ip", "")
                job["color_mapping_for_acm"] = job.get("color_mapping", [])
                job["ace_connected"]         = self._settings.get("ace_connected", False)

                self._current_job   = job
                self._current_thumb = job.get("thumbnail")

                self._upload_screen.set_step("Enviando para a impressora...", 75)
                self.command_ready.emit("print_start", job)
                self._go_workbench_sig.emit()

            except Exception as exc:
                self._upload_screen.set_error(f"{exc}")

        threading.Thread(target=_worker, daemon=True).start()

    def _on_confirmed_OLD(self, job: dict):
        import copy, threading

        filepath         = job["filepath"]
        is_3mf           = filepath.lower().endswith(".3mf")
        configured_slots = self._settings.get("slots", [])
        slots = copy.deepcopy(configured_slots)
        for m in job.get("color_mapping", []):
            ace_idx = m["ace"]
            if ace_idx < len(slots):
                slots[ace_idx]["paint_index"] = m["slicer"]

        self._settings["last_options"] = {
            "auto_leveling":    job.get("auto_leveling",    True),
            "resonance":        job.get("resonance",        False),
            "timelapse":        job.get("timelapse",        False),
            "flow_calibration": job.get("flow_calibration", False),
            "ai_detection":     job.get("ai_detection",     False),
            "dry_mode":         job.get("dry_mode",         0),
            "dry_temp":         job.get("dry_temp",         35),
            "dry_hours":        job.get("dry_hours",        12),
        }

        self._stack.setCurrentIndex(3)
        self._upload_screen.reset()

        def _worker():
            import datetime as _dt_log
            import os,sys
            #_log_path = os.path.join(os.path.expanduser("~"), "C:\\Users\\Roberto\\Desktop\\se3d_debug.log")
            desktop = os.path.join(os.path.expanduser("~"), "Desktop")
            _log_path = os.path.join(desktop, "se3d_debug.log")
            with open(_log_path, "w", encoding="utf-8") as _lf:
                _lf.write(f"[{_dt_log.datetime.now()}] worker iniciado\n")
                _lf.write(f"upload_mode: {self._settings.get('upload_mode')}\n")
                _lf.write(f"color_mapping: {job.get('color_mapping')}\n")
                _lf.write(f"slots: {self._settings.get('slots')}\n")
            try:
                if not is_3mf:
                    self._upload_screen.set_step("Lendo arquivo gcode...", 15)
                    from main import GCode3mfPacker
                    original = filepath
                    for suf in ("_se3d.gcode", "_se3d"):
                        if os.path.basename(original).endswith(suf):
                            candidate = original[:-len(suf)] + (".gcode" if suf == "_se3d" else "")
                            if os.path.exists(candidate):
                                original = candidate
                            break
                    self._upload_screen.set_step("Empacotando em .gcode.3mf...", 40)
                    ace_connected = self._settings.get("ace_connected", False)
                    pack_slots = slots if ace_connected else None
                    gcode_3mf_path = GCode3mfPacker.pack(original, slots=pack_slots)
                    self._upload_screen.set_step("Arquivo empacotado ✓", 60)
                    job["filepath"]  = gcode_3mf_path
                    job["task_name"] = os.path.basename(gcode_3mf_path)
                else:
                    self._upload_screen.set_step("Arquivo .3mf pronto ✓", 45)
                    job["task_name"] = os.path.basename(filepath)

                job["file_id"]               = ""
                job["slots_config"]          = configured_slots
                job["printer_ip"]            = self._settings.get("printer_ip", "")
                job["color_mapping_for_acm"] = job.get("color_mapping", [])
                job["ace_connected"]         = self._settings.get("ace_connected", False)
                self._current_job            = job
                self._current_thumb          = job.get("thumbnail")

                # Persiste filepath para restaurar thumb após reinício do app
                self._settings["last_job_filepath"] = job.get("filepath", "")
                self._settings["last_job_name"]     = job.get("task_name", "")
                try:
                    from core import settings as _sm
                    _sm.save(self._settings)
                except Exception:
                    pass

                self._upload_screen.set_step("Enviando para a impressora...", 75)
                self.command_ready.emit("print_start", job)

            except Exception as exc:
                self._upload_screen.set_error(f"{exc}")
            

        threading.Thread(target=_worker, daemon=True).start()

    def _on_upload_cancelled(self):
        """Cancel button on upload screen — always resets workbench state."""
        self._workbench_shown = False
        self._stack.setCurrentIndex(0)

    def _on_workbench_cancelled(self):
        self._workbench_shown = False
        self._stack.setCurrentIndex(0)
        # Se ainda está imprimindo (usuário clicou NEW PRINT ou STOP enquanto impressora
        # continuava), mantém os botões de status visíveis no setup
        still_printing = callable(self._is_printing_cb) and self._is_printing_cb()
        self._setup.set_printing(still_printing)

    def on_print_finished(self):
        """Chamado pelo MainWindow quando impressão termina via MQTT."""
        self._cleanup_job_files()
        self._workbench_shown = False

    def _cleanup_job_files(self):
        """Apaga PNG e job state quando impressão termina ou cancela."""
        try:
            from core import job_state
            job_state.clear()
        except Exception:
            pass
        # Limpa também do settings por compatibilidade
        self._settings.pop("last_job_filepath", None)
        self._settings.pop("last_job_name", None)
        self._settings.pop("last_preview_png", None)

    def _log(self, msg: str):
        """Log seguro — escreve no stdout original mesmo sem console."""
        try:
            import sys
            print(msg, file=sys.__stdout__, flush=True)
        except Exception:
            pass

    def _do_save_preview(self, gcode_3mf_path: str):
        """Salva PNG de preview na main thread (QPixmap não é thread-safe)."""
        thumb = self._pending_preview_thumb
        self._log(f"[PREVIEW] save chamado path={gcode_3mf_path}")
        self._log(f"[PREVIEW] thumb ok={thumb is not None and not thumb.isNull() if thumb else False}")
        if thumb and not thumb.isNull():
            png_path = os.path.splitext(gcode_3mf_path)[0] + ".preview.png"
            try:
                ok = thumb.save(png_path, "PNG")
                self._log(f"[PREVIEW] PNG salvo ok={ok} path={png_path}")
                self._settings["last_job_filepath"] = gcode_3mf_path
                self._settings["last_job_name"]     = os.path.basename(gcode_3mf_path)
                from core import settings as _sm
                _sm.save(self._settings)
                self._log(f"[PREVIEW] settings salvo")
            except Exception as e:
                self._log(f"[PREVIEW] ERRO: {e}")

    def switch_to_workbench(self):
        # Guard: only skip if workbench is already the active screen AND flag is set.
        # This allows switching FROM the upload screen (index 3) even if _workbench_shown
        # was somehow already True, fixing the "stuck on PREPARANDO IMPRESSÃO" issue.
        if self._stack.currentIndex() == 2 and getattr(self, "_workbench_shown", False):
            return
        self._workbench_shown = True

        self._upload_screen.set_done()
        self._setup.set_printing(True)

        # ── Resolve task_name ──────────────────────────────────────────
        task_name = ""
        gcode_3mf_path = ""
        gcode_path = ""

        # 1. job desta sessão tem prioridade no nome
        if self._current_job is not None:
            task_name = self._current_job.get("task_name", "")

        # 2. job_state (persistido entre sessões)
        try:
            from core import job_state as _js
            state = _js.load()
            if not task_name:
                task_name = state.get("task_name", "")
            gcode_3mf_path = state.get("filepath", "")
        except Exception:
            state = {}

        job = {"task_name": task_name or "--"}

        # ── Resolve thumbnail em cascata ───────────────────────────────
        # Fonte 1: thumb em memória desta sessão (acabou de enviar)
        thumb = self._current_thumb if self._current_thumb is not None else None

        # Fonte 2: PNG salvo no disco pelo load_file
        if thumb is None:
            png_path = state.get("preview_png", "")
            if png_path and os.path.isfile(png_path):
                px = QPixmap(png_path)
                if not px.isNull():
                    thumb = px

        # Inicia workbench já (com o que temos, ou sem thumb)
        self._workbench.start_job(job, thumb)
        self._stack.setCurrentIndex(2)

        # Fonte 3 (background): extrai thumbnail de dentro do .gcode.3mf / .gcode
        if thumb is None:
            # Escolhe o melhor arquivo disponível para extrair thumbnail
            src = gcode_3mf_path
            if not src and self._current_job:
                src = self._current_job.get("filepath", "")
            if src and os.path.isfile(src):
                import threading
                def _extract_thumb(src=src):
                    img_data = _extract_thumb_bytes(src)
                    if img_data:
                        self._workbench._pending_thumb_data = img_data
                        QTimer.singleShot(0, self._workbench._apply_pending_thumb_data)
                threading.Thread(target=_extract_thumb, daemon=True).start()

    def switch_to_workbench_OLD(self):
        self._upload_screen.set_done()
        self._setup.set_printing(True)
        QTimer.singleShot(700, lambda: (
            self._workbench.start_job(self._current_job, self._current_thumb),
            self._stack.setCurrentIndex(2)
        ))

    def update_progress(self, data: dict):
        self._workbench.update_progress(
            pct=data.get("progress", 0),
            eta=data.get("eta",      "--"),
            elapsed=data.get("elapsed", "--"),
            layer=data.get("layer",  "--"),
            bed_temp=data.get("bed_temp", "--"),
            noz_temp=data.get("noz_temp", "--"),
            phase=data.get("phase", ""),
        )

    def update_connection(self, connected: bool, ip: str = ""):
        self._setup.update_connection(connected, ip)
        self._colormap.update_connection(connected, ip)
        if hasattr(self._workbench, "_status_panel"):
            self._workbench._status_panel.set_connected(connected, ip)

    def set_mqtt(self, mqtt_client):
        if hasattr(self._setup, "set_mqtt"):
            self._setup.set_mqtt(mqtt_client)
        if hasattr(self._workbench, "set_mqtt"):
            self._workbench.set_mqtt(mqtt_client)

    def update_printer_state(self, state: str):
        is_idle    = state in ("IDLE", "")
        is_offline = state in ("OFFLINE",)
        is_busy    = not is_idle and not is_offline

        file_loaded = bool(getattr(self, "_filepath", None))
        can_print   = is_idle and file_loaded

        if hasattr(self, "_split_container"):
            self._split_container.setEnabled(can_print)

    def show_workbench(self):
        self._stack.setCurrentIndex(2)

    def show_setup(self):
        self._stack.setCurrentIndex(0)