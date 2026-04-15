# -*- coding: utf-8 -*-
"""
Config screen — connection mode selector, credentials, slots, print options.
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QLineEdit, QCheckBox, QFrame,
    QGroupBox, QSpinBox, QComboBox, QDialog, QTextEdit
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont

MATERIALS = ["PLA", "ABS", "PETG", "ASA", "TPU", "NYLON", "PC", "PLA+"]

BTN_MODE_SS = """
    QPushButton {
        background: #0D1B2A; border: 1px solid #1E2D3D; color: #607080;
        font-family: 'Courier New'; font-size: 11px; letter-spacing: 1px;
        padding: 6px 12px; border-radius: 2px;
    }
    QPushButton:checked  { background: #003D52; border-color: #00E5FF; color: #00E5FF; }
    QPushButton:hover:!checked { color: #00B8D4; }
"""
HELP_BTN_SS = """
    QPushButton {
        background: transparent; border: 1px solid #1E2D3D; color: #3A5565;
        font-family: 'Courier New'; font-size: 10px; padding: 4px 8px; border-radius: 2px;
    }
    QPushButton:hover { color: #00E5FF; border-color: #00E5FF; }
"""
FLBL = "font-family:'Courier New'; font-size:10px; color:#607080; letter-spacing:1px;"


# ── Color Button ──────────────────────────────────────────────────────────────
class ColorButton(QPushButton):
    color_changed = pyqtSignal(list)

    def __init__(self, initial_color: list, slot_label: str = "", parent=None):
        super().__init__(parent)
        self._color = list(initial_color)
        self._slot_label = slot_label
        self.setFixedSize(32, 32)
        self.setToolTip("Click to choose color")
        self.clicked.connect(self._open_picker)
        self._refresh()

    def _refresh(self):
        r, g, b = self._color
        self.setStyleSheet(
            f"QPushButton {{ background-color: rgb({r},{g},{b}); "
            f"border: 2px solid #1E2D3D; border-radius: 2px; }}"
            f"QPushButton:hover {{ border-color: #00E5FF; }}"
        )

    def _open_picker(self):
        from ui.color_picker import ColorPickerDialog
        dlg = ColorPickerDialog(tuple(self._color), self._slot_label, self)
        if dlg.exec():
            r, g, b = dlg.get_rgb()
            self._color = [r, g, b]
            self._refresh()
            self.color_changed.emit(self._color)

    def get_color(self): return list(self._color)
    def set_color(self, rgb): self._color = list(rgb); self._refresh()


# ── Slot Row ──────────────────────────────────────────────────────────────────
class SlotRow(QWidget):
    changed = pyqtSignal()

    def __init__(self, slot_index: int, slot_data: dict, parent=None):
        super().__init__(parent)
        self.slot_index = slot_index
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 2, 0, 2)
        lay.setSpacing(8)

        lbl = QLabel(f"SLOT  {slot_index + 1}", self)
        lbl.setFont(QFont("Courier New", 11, QFont.Weight.Bold))
        lbl.setStyleSheet("color:#607080; letter-spacing:2px;")
        lbl.setFixedWidth(64)

        self._btn_color = ColorButton(
            slot_data.get("paint_color", [255, 255, 255]),
            f"SLOT {slot_index + 1}", self
        )
        self._btn_color.color_changed.connect(lambda _: self.changed.emit())

        self._combo_mat = QComboBox(self)
        self._combo_mat.addItems(MATERIALS)
        self._combo_mat.setFont(QFont("Courier New", 11))
        mat = slot_data.get("material_type", "PLA")
        if mat in MATERIALS:
            self._combo_mat.setCurrentText(mat)
        self._combo_mat.currentTextChanged.connect(lambda _: self.changed.emit())

        lay.addWidget(lbl)
        lay.addWidget(self._btn_color)
        lay.addWidget(self._combo_mat, 1)

    def get_data(self):
        return {
            "paint_index":   self.slot_index,
            "paint_color":   self._btn_color.get_color(),
            "material_type": self._combo_mat.currentText(),
        }

    def set_data(self, d: dict):
        self._btn_color.set_color(d.get("paint_color", [255, 255, 255]))
        mat = d.get("material_type", "PLA")
        if mat in MATERIALS:
            self._combo_mat.setCurrentText(mat)


# ── Login Widget ──────────────────────────────────────────────────────────────
class LoginWidget(QWidget):
    settings_saved    = pyqtSignal(dict)
    connect_requested = pyqtSignal(dict)
    back_requested    = pyqtSignal()

    def __init__(self, settings: dict, parent=None):
        super().__init__(parent)
        self._settings = settings
        self._slicer_token = settings.get("slicer_token", "")   # token em memória
        self._build_ui()
        # Tenta auto-carregar o token silenciosamente ao abrir.
        # QTimer.singleShot(0) garante que os sinais já estão conectados
        # pelo main_window antes de emitirmos settings_saved.
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(0, lambda: self._auto_load_slicer_token(silent=True))

    # ── UI ────────────────────────────────────────────────────────────────────
    def _build_ui(self):
        s = self._settings
        slots    = s.get("slots", [{} for _ in range(4)])
        last     = s.get("last_options", {})

        root = QVBoxLayout(self)
        root.setContentsMargins(30, 20, 30, 0)
        root.setSpacing(0)

        # ── Header ────────────────────────────────────────
        header = QWidget(self)
        hl = QHBoxLayout(header)
        hl.setContentsMargins(0, 0, 0, 12)

        btn_back = QPushButton("< BACK", header)
        btn_back.setMinimumWidth(90)
        btn_back.clicked.connect(self.back_requested.emit)

        title = QLabel("ANYCUBIC  //  CONFIGURATION", header)
        title.setFont(QFont("Courier New", 13, QFont.Weight.Bold))
        title.setStyleSheet("color:#00E5FF; letter-spacing:3px;")

        hl.addWidget(btn_back)
        hl.addStretch()
        hl.addWidget(title)
        root.addWidget(header)

        sep = QFrame(self)
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color:#1A2535;")
        root.addWidget(sep)
        root.addSpacing(16)

        # ── Body (left | right) ────────────────────────────
        body = QWidget(self)
        body_lay = QHBoxLayout(body)
        body_lay.setContentsMargins(0, 0, 0, 0)
        body_lay.setSpacing(30)

        # ════════════════════════════════
        # LEFT COLUMN
        # ════════════════════════════════
        left_w = QWidget(body)
        left_lay = QVBoxLayout(left_w)
        left_lay.setContentsMargins(0, 0, 0, 0)
        left_lay.setSpacing(12)

        # ── Mode selector ────────────────────────────────────
        grp_mode = QGroupBox("CONNECTION  MODE", left_w)
        gm = QVBoxLayout(grp_mode)
        gm.setContentsMargins(12, 24, 12, 12)

        mode_row = QWidget(grp_mode)
        mode_lay = QHBoxLayout(mode_row)
        mode_lay.setContentsMargins(0, 0, 0, 0)
        mode_lay.setSpacing(8)

        self._btn_cloud = QPushButton("ANYCUBIC  CLOUD", mode_row)
        self._btn_cloud.setCheckable(True)
        self._btn_cloud.setStyleSheet(BTN_MODE_SS)

        self._btn_lan = QPushButton("LAN  (MOCHI)", mode_row)
        self._btn_lan.setCheckable(True)
        self._btn_lan.setStyleSheet(BTN_MODE_SS)
        self._btn_lan.setToolTip("Conecta diretamente ao broker Mochi da impressora\n"
                                 "via IP local (porta 9883 TLS)\n"
                                 "Requer: SSH FETCH para credenciais")

        self._btn_local = QPushButton("RINKHALS  /  LOCAL", mode_row)
        self._btn_local.setCheckable(True)
        self._btn_local.setStyleSheet(BTN_MODE_SS)
        self._btn_local.setToolTip("Moonraker / Klipper via WebSocket\n"
                                   "(somente se tiver Rinkhals instalado)")

        mode_lay.addWidget(self._btn_cloud)
        mode_lay.addWidget(self._btn_lan)
        mode_lay.addWidget(self._btn_local)
        gm.addWidget(mode_row)
        left_lay.addWidget(grp_mode)

        # ── Connection (IP / CN / Port) ───────────────────────
        self._grp_conn = QGroupBox("CONNECTION", left_w)
        gc = QVBoxLayout(self._grp_conn)
        gc.setContentsMargins(12, 24, 12, 12)
        gc.setSpacing(8)

        self._inp_ip = QLineEdit(self._grp_conn)
        self._inp_ip.setFont(QFont("Courier New", 12))
        self._inp_ip.setPlaceholderText("192.168.1.100")
        self._inp_ip.setText(s.get("printer_ip", ""))

        self._inp_cn = QLineEdit(self._grp_conn)
        self._inp_cn.setFont(QFont("Courier New", 12))
        self._inp_cn.setPlaceholderText("XXXX-XXXX-XXXX-XXXX")
        self._inp_cn.setText(s.get("printer_cn", ""))

        self._spin_port = QSpinBox(self._grp_conn)
        self._spin_port.setFont(QFont("Courier New", 12))
        self._spin_port.setRange(1, 65535)
        self._spin_port.setValue(s.get("moonraker_port", 7125))

        self._row_ip   = self._row("PRINTER  IP", self._inp_ip,    self._grp_conn)
        self._row_cn   = self._row("CN  CODE",    self._inp_cn,    self._grp_conn)
        self._row_port = self._row("API  PORT",   self._spin_port, self._grp_conn)
        gc.addWidget(self._row_ip)
        gc.addWidget(self._row_cn)
        gc.addWidget(self._row_port)

        self._lbl_status = QLabel("● NOT  CONNECTED", self._grp_conn)
        self._lbl_status.setFont(QFont("Courier New", 11))
        self._lbl_status.setObjectName("status_err")
        gc.addWidget(self._lbl_status)
        left_lay.addWidget(self._grp_conn)

        # ── Anycubic Cloud credentials ─────────────────────────
        self._grp_acc = QGroupBox("ANYCUBIC  CLOUD  CREDENTIALS", left_w)
        ga = QVBoxLayout(self._grp_acc)
        ga.setContentsMargins(12, 24, 12, 12)
        ga.setSpacing(4)

        # Two columns: login (left) | MQTT direct (right)
        two_cols = QWidget(self._grp_acc)
        two_lay  = QHBoxLayout(two_cols)
        two_lay.setContentsMargins(0, 0, 0, 0)
        two_lay.setSpacing(16)

        # -- Left: account login --
        col_l = QWidget(two_cols)
        cl    = QVBoxLayout(col_l)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(4)

        lbl_login = QLabel("ACCOUNT  LOGIN", col_l)
        lbl_login.setStyleSheet("color:#3A5565; " + FLBL)
        cl.addWidget(lbl_login)

        self._inp_email = QLineEdit(col_l)
        self._inp_email.setFont(QFont("Courier New", 11))
        self._inp_email.setPlaceholderText("email@example.com")
        self._inp_email.setText(s.get("anycubic_email", ""))
        lbl_e = QLabel("EMAIL", col_l); lbl_e.setStyleSheet(FLBL)
        cl.addWidget(lbl_e); cl.addWidget(self._inp_email)

        self._inp_pass = QLineEdit(col_l)
        self._inp_pass.setFont(QFont("Courier New", 11))
        self._inp_pass.setEchoMode(QLineEdit.EchoMode.Password)
        self._inp_pass.setPlaceholderText("password")
        self._inp_pass.setText(s.get("anycubic_pass", ""))
        lbl_p = QLabel("PASSWORD", col_l); lbl_p.setStyleSheet(FLBL)
        cl.addWidget(lbl_p); cl.addWidget(self._inp_pass)

        self._cmb_region = QComboBox(col_l)
        self._cmb_region.setFont(QFont("Courier New", 11))
        self._cmb_region.addItems(["GLOBAL", "CHINA"])
        self._cmb_region.setCurrentIndex(
            0 if s.get("cloud_region", "global") == "global" else 1)
        lbl_r = QLabel("REGION", col_l); lbl_r.setStyleSheet(FLBL)
        cl.addWidget(lbl_r); cl.addWidget(self._cmb_region)

        self._chk_remember = QCheckBox("REMEMBER  LOGIN", col_l)
        self._chk_remember.setFont(QFont("Courier New", 11))
        self._chk_remember.setChecked(s.get("remember_login", False))
        cl.addWidget(self._chk_remember)


        # ── Slicer Next auto-token ─────────────────────────────
        sep_slicer = QFrame(col_l)
        sep_slicer.setFrameShape(QFrame.Shape.HLine)
        sep_slicer.setStyleSheet("color:#1A2535; margin-top:4px; margin-bottom:2px;")
        cl.addWidget(sep_slicer)

        lbl_slicer_title = QLabel("ANYCUBIC  SLICER  NEXT  TOKEN", col_l)
        lbl_slicer_title.setStyleSheet("color:#3A5565; " + FLBL)
        cl.addWidget(lbl_slicer_title)

        # Botões lado a lado: [✓ TOKEN] [⟳ AUTO-LOAD]
        token_row = QWidget(col_l)
        token_row_lay = QHBoxLayout(token_row)
        token_row_lay.setContentsMargins(0, 0, 0, 0)
        token_row_lay.setSpacing(6)

        # Botão de status do token — clicável para ver detalhes
        self._btn_token_status = QPushButton("○  sem token", col_l)
        self._btn_token_status.setFont(QFont("Courier New", 10))
        self._btn_token_status.setStyleSheet("""
            QPushButton {
                background:transparent; border:1px solid #1A2535; color:#607080;
                font-family:'Courier New'; font-size:10px; padding:4px 8px;
                border-radius:2px; text-align:left;
            }
            QPushButton:hover { border-color:#00E5FF; color:#00E5FF; }
        """)
        self._btn_token_status.clicked.connect(self._show_token_details)

        # Botão auto-load
        btn_slicer = QPushButton("⟳", col_l)
        btn_slicer.setFixedWidth(28)
        btn_slicer.setFixedHeight(28)
        btn_slicer.setToolTip("Recarregar token do Anycubic Slicer Next")
        btn_slicer.setStyleSheet("""
            QPushButton {
                background:#0A1E14; border:1px solid #1A3528; color:#2A7050;
                font-size:14px; border-radius:2px;
            }
            QPushButton:hover { background:#0D2E1E; color:#00E5A0; border-color:#00E5A0; }
        """)
        btn_slicer.clicked.connect(lambda: self._auto_load_slicer_token(silent=False))

        token_row_lay.addWidget(self._btn_token_status, 1)
        token_row_lay.addWidget(btn_slicer)
        cl.addWidget(token_row)

        cl.addStretch()

        # -- Divider --
        vline = QFrame(two_cols)
        vline.setFrameShape(QFrame.Shape.VLine)
        vline.setStyleSheet("color:#1E2D3D;")

        # -- Right: MQTT direct --
        col_r = QWidget(two_cols)
        cr    = QVBoxLayout(col_r)
        cr.setContentsMargins(0, 0, 0, 0)
        cr.setSpacing(4)

        lbl_mqtt = QLabel("MQTT  DIRECT  (OPTIONAL)", col_r)
        lbl_mqtt.setStyleSheet("color:#3A5565; " + FLBL)
        cr.addWidget(lbl_mqtt)

        self._inp_mqtt_user = QLineEdit(col_r)
        self._inp_mqtt_user.setFont(QFont("Courier New", 11))
        self._inp_mqtt_user.setPlaceholderText("userXXXXXX  (auto-detected)")
        self._inp_mqtt_user.setText(s.get("mqtt_user", ""))
        lbl_mu = QLabel("USER", col_r); lbl_mu.setStyleSheet(FLBL)
        cr.addWidget(lbl_mu); cr.addWidget(self._inp_mqtt_user)

        self._inp_mqtt_pass = QLineEdit(col_r)
        self._inp_mqtt_pass.setFont(QFont("Courier New", 11))
        self._inp_mqtt_pass.setEchoMode(QLineEdit.EchoMode.Password)
        self._inp_mqtt_pass.setPlaceholderText("password")
        self._inp_mqtt_pass.setText(s.get("mqtt_pass", ""))
        lbl_mp = QLabel("PASSWORD", col_r); lbl_mp.setStyleSheet(FLBL)
        cr.addWidget(lbl_mp); cr.addWidget(self._inp_mqtt_pass)

        self._inp_device_id = QLineEdit(col_r)
        self._inp_device_id.setFont(QFont("Courier New", 11))
        self._inp_device_id.setPlaceholderText("auto-detected on first connect")
        self._inp_device_id.setText(s.get("device_id", ""))
        lbl_di = QLabel("DEVICE  ID", col_r); lbl_di.setStyleSheet(FLBL)
        cr.addWidget(lbl_di); cr.addWidget(self._inp_device_id)

        # Device certificate (mTLS) — stored in settings, NOT in QLineEdit
        # PEM content is multiline; QLineEdit truncates at first \n — cert must be kept in memory
        lbl_cert = QLabel("DEVICE  CERT  (mTLS)", col_r); lbl_cert.setStyleSheet(FLBL)
        self._lbl_cert_status = QLabel("○  sem certificado", col_r)
        self._lbl_cert_status.setFont(QFont("Courier New", 10))
        self._lbl_cert_status.setStyleSheet("color:#607080;")
        # Inicializa status visual com base no que está salvo
        if s.get("device_cert", ""):
            self._lbl_cert_status.setText("●  Certificado carregado")
            self._lbl_cert_status.setStyleSheet(
                "color:#00E5A0; font-family:'Courier New'; font-size:10px;")
        cr.addWidget(lbl_cert)
        cr.addWidget(self._lbl_cert_status)

        # Load from file / SSH buttons
        btn_row = QWidget(col_r)
        btn_row_lay = QHBoxLayout(btn_row)
        btn_row_lay.setContentsMargins(0, 0, 0, 0)
        btn_row_lay.setSpacing(6)

        btn_did = QPushButton("?  DEVICE  ID", col_r)
        btn_did.setStyleSheet(HELP_BTN_SS)
        btn_did.clicked.connect(self._show_deviceid_help)

        btn_load_cert = QPushButton("LOAD  .json", col_r)
        btn_load_cert.setStyleSheet(HELP_BTN_SS)
        btn_load_cert.clicked.connect(self._load_device_account)

        btn_ssh = QPushButton("⬇  SSH  FETCH", col_r)
        btn_ssh.setToolTip(
            "Busca device_account.json diretamente da impressora via SSH.\n"
            "Use o IP configurado no campo PRINTER IP.\n"
            "Senha SSH padrão: rockchip"
        )
        btn_ssh.setStyleSheet("""
            QPushButton {
                background:#0A1A2E; border:1px solid #1A3060; color:#3A70C0;
                font-family:'Courier New'; font-size:10px; padding:4px 6px; border-radius:2px;
            }
            QPushButton:hover { color:#60A0FF; border-color:#60A0FF; }
        """)
        btn_ssh.clicked.connect(self._fetch_device_account_ssh)

        btn_row_lay.addWidget(btn_did)
        btn_row_lay.addWidget(btn_load_cert)
        btn_row_lay.addWidget(btn_ssh)
        cr.addWidget(btn_row)
        cr.addStretch()

        two_lay.addWidget(col_l,  1)
        two_lay.addWidget(vline)
        two_lay.addWidget(col_r,  1)
        ga.addWidget(two_cols)
        left_lay.addWidget(self._grp_acc)

        left_lay.addStretch()

        # Wire mode buttons AFTER all widgets exist
        self._btn_cloud.clicked.connect(lambda: self._set_mode("cloud"))
        self._btn_lan.clicked.connect(lambda: self._set_mode("lan"))
        self._btn_local.clicked.connect(lambda: self._set_mode("local"))
        saved_mode = s.get("connection_mode", "lan")
        self._btn_cloud.setChecked(saved_mode == "cloud")
        self._btn_lan.setChecked(saved_mode == "lan")
        self._btn_local.setChecked(saved_mode == "local")
        self._set_mode(saved_mode)

        # ════════════════════════════════
        # RIGHT COLUMN
        # ════════════════════════════════
        right_w = QWidget(body)
        right_lay = QVBoxLayout(right_w)
        right_lay.setContentsMargins(0, 0, 0, 0)
        right_lay.setSpacing(12)

        # ── ACE Pro slots (2 × 2 grid) ───────────────────────
        grp_ace = QGroupBox("ACE  PRO  —  SLOT  CONFIGURATION", right_w)
        g4 = QVBoxLayout(grp_ace)
        g4.setContentsMargins(12, 24, 12, 12)
        g4.setSpacing(6)

        hint_ace = QLabel("Click the color swatch to choose filament color.", grp_ace)
        hint_ace.setFont(QFont("Courier New", 10))
        hint_ace.setStyleSheet("color:#3A4550;")
        g4.addWidget(hint_ace)

        self._slot_rows = []
        slots_grid = QWidget(grp_ace)
        sg_lay = QHBoxLayout(slots_grid)
        sg_lay.setContentsMargins(0, 0, 0, 0)
        sg_lay.setSpacing(12)

        col_sl = QWidget(slots_grid); csl = QVBoxLayout(col_sl)
        col_sr = QWidget(slots_grid); csr = QVBoxLayout(col_sr)
        csl.setContentsMargins(0, 0, 0, 0); csl.setSpacing(6)
        csr.setContentsMargins(0, 0, 0, 0); csr.setSpacing(6)

        for i in range(4):
            row = SlotRow(i, slots[i] if i < len(slots) else {}, grp_ace)
            self._slot_rows.append(row)
            (csl if i < 2 else csr).addWidget(row)

        sg_lay.addWidget(col_sl, 1)
        sg_lay.addWidget(col_sr, 1)
        g4.addWidget(slots_grid)
        right_lay.addWidget(grp_ace)

        # ── Default print options ─────────────────────────────
        grp_opts = QGroupBox("DEFAULT  PRINT  OPTIONS", right_w)
        g5 = QVBoxLayout(grp_opts)
        g5.setContentsMargins(12, 24, 12, 12)
        g5.setSpacing(8)

        self._chk_leveling  = QCheckBox("AUTO  BED  LEVELING",   grp_opts)
        self._chk_ai        = QCheckBox("AI  FAILURE  DETECTION", grp_opts)
        self._chk_timelapse = QCheckBox("TIME-LAPSE",             grp_opts)
        self._chk_flow      = QCheckBox("FLOW  CALIBRATION",      grp_opts)

        self._chk_leveling.setChecked(last.get("auto_leveling",    True))
        self._chk_ai.setChecked(      last.get("ai_detection",     False))
        self._chk_timelapse.setChecked(last.get("timelapse",       False))
        self._chk_flow.setChecked(    last.get("flow_calibration", False))

        for chk in [self._chk_leveling, self._chk_ai,
                    self._chk_timelapse, self._chk_flow]:
            chk.setFont(QFont("Courier New", 12))
            g5.addWidget(chk)
        right_lay.addWidget(grp_opts)

        # ── Upload mode selector ─────────────────────────────
        upload_row = QWidget(grp_opts)
        upload_lay = QHBoxLayout(upload_row)
        upload_lay.setContentsMargins(0, 8, 0, 0)
        upload_lay.setSpacing(12)

        lbl_upload = QLabel("UPLOAD  MODE", upload_row)
        lbl_upload.setFont(QFont("Courier New", 10))
        lbl_upload.setStyleSheet("color:#607080;")

        self._combo_upload = QComboBox(upload_row)
        self._combo_upload.setFont(QFont("Courier New", 10))
        self._combo_upload.addItem(".gcode.3mf", "full")
        self._combo_upload.addItem(".gcode (recommended)", "gcode_only")

        # Carregar valor salvo
        saved_mode = self._settings.get("upload_mode", "full")
        for i in range(self._combo_upload.count()):
            if self._combo_upload.itemData(i) == saved_mode:
                self._combo_upload.setCurrentIndex(i)
                break

        upload_lay.addWidget(lbl_upload)
        upload_lay.addWidget(self._combo_upload, 1)
        upload_lay.addStretch()
        g5.addWidget(upload_row)

        # ── Log panel ─────────────────────────────────────────
        grp_log = QGroupBox("CONNECTION  LOG", right_w)
        g6 = QVBoxLayout(grp_log)
        g6.setContentsMargins(12, 24, 12, 12)

        self._log = QTextEdit(grp_log)
        self._log.setReadOnly(True)
        self._log.setFont(QFont("Courier New", 10))
        self._log.setStyleSheet(
            "background:#060E14; color:#4A9070; border:1px solid #1A2535;")
        self._log.setMaximumHeight(140)
        g6.addWidget(self._log)
        right_lay.addWidget(grp_log)
        right_lay.addStretch()

        body_lay.addWidget(left_w,  1)
        body_lay.addWidget(right_w, 1)
        root.addWidget(body, 1)

        # ── Footer ────────────────────────────────────────────
        root.addSpacing(12)
        sep2 = QFrame(self)
        sep2.setFrameShape(QFrame.Shape.HLine)
        sep2.setStyleSheet("color:#1A2535;")
        root.addWidget(sep2)
        root.addSpacing(10)

        foot = QWidget(self)
        fl = QHBoxLayout(foot)
        fl.setContentsMargins(0, 0, 0, 10)
        fl.setSpacing(10)

        self._lbl_saved = QLabel("", foot)
        self._lbl_saved.setFont(QFont("Courier New", 11))
        self._lbl_saved.setObjectName("status_ok")

        btn_save = QPushButton("SAVE", foot)
        btn_save.setMinimumWidth(100)
        btn_save.clicked.connect(self._on_save)

        btn_connect = QPushButton("CONNECT  >", foot)
        btn_connect.setMinimumWidth(140)
        btn_connect.setStyleSheet("""
            QPushButton {
                background:#003D52; border:1px solid #00E5FF; color:#00E5FF;
                font-family:'Courier New'; font-size:12px; letter-spacing:2px;
                padding:8px 20px; border-radius:2px;
            }
            QPushButton:hover { background:#005070; }
        """)
        btn_connect.clicked.connect(self._on_connect)

        fl.addWidget(self._lbl_saved)
        fl.addStretch()
        fl.addWidget(btn_save)
        fl.addWidget(btn_connect)
        root.addWidget(foot)

    # ── Mode switching ────────────────────────────────────────────────────────
    def _set_mode(self, mode: str):
        is_cloud = (mode == "cloud")
        is_lan   = (mode == "lan")
        is_local = (mode == "local")

        self._btn_cloud.setChecked(is_cloud)
        self._btn_lan.setChecked(is_lan)
        self._btn_local.setChecked(is_local)

        # Cloud: mostrar credenciais cloud (email/pass/token)
        # LAN / Local: apenas IP + credenciais MQTT diretas
        self._grp_acc.setVisible(is_cloud)

        if is_cloud:
            self._grp_conn.setTitle("CONNECTION")
            self._row_cn.setVisible(True)
            self._row_port.setVisible(False)
        elif is_lan:
            self._grp_conn.setTitle("CONNECTION  (LAN  —  MOCHI  BROKER)")
            self._row_cn.setVisible(False)
            self._row_port.setVisible(False)
        else:  # local / Moonraker
            self._grp_conn.setTitle("CONNECTION  (RINKHALS  /  MOONRAKER)")
            self._row_cn.setVisible(False)
            self._row_port.setVisible(True)
            if self._spin_port.value() in (0, 8883, 9883):
                self._spin_port.setValue(7125)

    # ── Public API ────────────────────────────────────────────────────────────
    def set_connection_status(self, state: str, message: str = ""):
        """Called from main_window to update status in this config screen."""
        styles = {
            "connected":    ("● CONNECTED",      "color:#00FF88;"),
            "connecting":   ("● CONNECTING...",  "color:#FFB300;"),
            "disconnected": ("○ NOT  CONNECTED", "color:#FF4444;"),
            "error":        ("● ERROR",          "color:#FF4444;"),
            "idle":         ("● IDLE",           "color:#00FF88;"),
            "busy":         ("● BUSY",           "color:#FFB300;"),
        }
        text, style = styles.get(state, ("○ NOT  CONNECTED", "color:#FF4444;"))
        self._lbl_status.setText(text)
        self._lbl_status.setStyleSheet(
            style + " font-family:'Courier New'; font-size:11px;")
        if message:
            self.append_log(message)

    def append_log(self, text: str):
        """Append a line to the connection log panel."""
        self._log.append(text)

    # ── Helpers ───────────────────────────────────────────────────────────────
    @staticmethod
    def _row(label_text: str, widget: QWidget, parent: QWidget) -> QWidget:
        container = QWidget(parent)
        lay = QHBoxLayout(container)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)
        lbl = QLabel(label_text, container)
        lbl.setFont(QFont("Courier New", 12))
        lbl.setStyleSheet("color:#607080;")
        lbl.setFixedWidth(110)
        lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        lay.addWidget(lbl)
        lay.addWidget(widget, 1)
        return container

    def _collect(self) -> dict:
        d = dict(self._settings)
        mode = "cloud" if self._btn_cloud.isChecked() else "lan" if self._btn_lan.isChecked() else "local"
        d["connection_mode"]  = mode
        d["printer_ip"]       = self._inp_ip.text().strip()
        d["printer_cn"]       = self._inp_cn.text().strip()
        d["moonraker_port"]   = self._spin_port.value()
        d["anycubic_email"]   = self._inp_email.text().strip()
        d["anycubic_pass"]    = self._inp_pass.text()
        d["cloud_region"]     = "global" if self._cmb_region.currentIndex() == 0 else "cn"
        d["remember_login"]   = self._chk_remember.isChecked()
        d["mqtt_user"]        = self._inp_mqtt_user.text().strip()
        d["mqtt_pass"]        = self._inp_mqtt_pass.text()
        d["device_id"]        = self._inp_device_id.text().strip()
        d["device_cert"]      = self._settings.get("device_cert", "")   # PEM multiline
        d["device_key"]       = self._settings.get("device_key",  "")
        d["device_ca"]        = self._settings.get("device_ca",   "")
        # slicer_token carregado via auto-load do Anycubic Slicer Next
        d["slicer_token"]     = self._slicer_token
        d["slots"]            = [r.get_data() for r in self._slot_rows]
        d["last_options"]     = {
            "auto_leveling":    self._chk_leveling.isChecked(),
            "ai_detection":     self._chk_ai.isChecked(),
            "timelapse":        self._chk_timelapse.isChecked(),
            "flow_calibration": self._chk_flow.isChecked(),
        }
        d["upload_mode"] = self._combo_upload.currentData()
        return d

    def _on_save(self):
        self.settings_saved.emit(self._collect())
        self._lbl_saved.setText("✓  SAVED")

    def _on_connect(self):
        d = self._collect()
        self.settings_saved.emit(d)
        self.connect_requested.emit(d)
        self.set_connection_status("connecting")

    # ── Slicer Next Token ─────────────────────────────────────────────────────
    def _auto_load_slicer_token(self, silent: bool = False):
        """
        Tenta carregar o access_token do Anycubic Slicer Next automaticamente.

        silent=True  → sem caixas de diálogo, apenas atualiza o label.
        silent=False → mostra mensagem de sucesso ou erro detalhado.
        """
        from core.slicer_token import read_slicer_token
        from PyQt6.QtWidgets import QMessageBox

        result = read_slicer_token()

        if result.success:
            self._slicer_token = result.token
            info_parts = []
            if result.username:
                info_parts.append(result.username)
            if result.user_id:
                info_parts.append(f"ID: {result.user_id}")
            user_info = "  |  ".join(info_parts) if info_parts else ""

            self._btn_token_status.setText("✓  Token OK")
            self._btn_token_status.setStyleSheet("""
                QPushButton {
                    background:#0A1E14; border:1px solid #00E5A0; color:#00E5A0;
                    font-family:'Courier New'; font-size:10px; padding:4px 8px;
                    border-radius:2px; text-align:left;
                }
                QPushButton:hover { background:#0D2E1E; border-color:#00FFB8; color:#00FFB8; }
            """)
            self.append_log(
                f"[SLICER] Token carregado automaticamente"
                + (f" — {user_info}" if user_info else "")
            )
            self.settings_saved.emit(self._collect())

            if not silent:
                QMessageBox.information(
                    self, "Token Carregado",
                    f"Token do Anycubic Slicer Next carregado com sucesso!\n\n"
                    f"Token: {result.token_short}\n"
                    + (f"Usuário: {result.username}\n" if result.username else "")
                    + (f"User ID: {result.user_id}\n" if result.user_id else "")
                    + f"\nArquivo: {result.conf_path}\n\n"
                    "O token será usado automaticamente ao conectar via Anycubic Cloud."
                )
        else:
            self._slicer_token = ""
            self._btn_token_status.setText("○  sem token")
            self._btn_token_status.setStyleSheet("""
                QPushButton {
                    background:transparent; border:1px solid #1A2535; color:#607080;
                    font-family:'Courier New'; font-size:10px; padding:4px 8px;
                    border-radius:2px; text-align:left;
                }
                QPushButton:hover { border-color:#00E5FF; color:#00E5FF; }
            """)

            if not silent:
                # Diálogo de erro com instruções detalhadas
                dlg = QDialog(self)
                dlg.setWindowTitle("Anycubic Slicer Next — Não Encontrado")
                dlg.setMinimumWidth(540)
                dlg.setStyleSheet(self.styleSheet())
                lay = QVBoxLayout(dlg)

                txt = QTextEdit(dlg)
                txt.setReadOnly(True)
                txt.setFont(QFont("Courier New", 11))
                txt.setStyleSheet(
                    "background:#0D1B2A; color:#A0B8C8; border:1px solid #1E2D3D;")
                txt.setPlainText(
                    "ANYCUBIC SLICER NEXT — TOKEN NÃO ENCONTRADO\n"
                    + "=" * 46 + "\n\n"
                    f"Motivo: {result.error}\n\n"
                    + "=" * 46 + "\n\n"
                    "O QUE É NECESSÁRIO\n"
                    + "-" * 36 + "\n"
                    "O token de autenticação é obtido automaticamente\n"
                    "do Anycubic Slicer Next (software de fatiamento).\n\n"
                    "SEM O SLICER NEXT, VOCÊ AINDA PODE CONECTAR:\n"
                    + "-" * 36 + "\n"
                    "OPÇÃO 1 — Credenciais MQTT diretas\n"
                    "  Preencha os campos MQTT USER + MQTT PASS\n"
                    "  (obtidos via SSH na impressora)\n\n"
                    "  SSH: ssh root@<IP-da-impressora>\n"
                    "  Senha SSH: rockchip\n"
                    "  Arquivo: /userdata/app/gk/config/device_account.json\n\n"
                    "  Ou use o botão  [LOAD device_account.json]\n\n"
                    "OPÇÃO 2 — Modo local (recomendado)\n"
                    "  Mude para o modo  RINKHALS / LOCAL\n"
                    "  Conecta diretamente via IP sem necessidade\n"
                    "  de autenticação na nuvem.\n\n"
                    "OPÇÃO 3 — Instalar o Anycubic Slicer Next\n"
                    "  Download: https://www.anycubic.com/pages/anycubic-slicer\n"
                    "  Faça login com sua conta Anycubic\n"
                    "  Feche e reabra este programa — o token\n"
                    "  será carregado automaticamente."
                )
                lay.addWidget(txt)
                btn_ok = QPushButton("ENTENDIDO", dlg)
                btn_ok.clicked.connect(dlg.accept)
                lay.addWidget(btn_ok)
                dlg.exec()

    def _fetch_device_account_ssh(self):
        """Busca device_account.json via SSH diretamente da impressora."""
        from PyQt6.QtWidgets import QInputDialog, QMessageBox
        import subprocess, json as _json, shutil, os

        ip = self._inp_ip.text().strip()
        if not ip:
            QMessageBox.warning(self, "IP ausente",
                "Preencha o campo PRINTER IP antes de usar o SSH FETCH.")
            return

        ssh_pass, ok = QInputDialog.getText(
            self, "Senha SSH",
            f"Senha SSH para root@{ip}\n(padrão Rinkhals: rockchip)",
            QLineEdit.EchoMode.Password, "rockchip"
        )
        if not ok:
            return

        self.append_log(f"[SSH] Conectando em root@{ip}...")
        device_json = None
        error_msg   = ""
        method_used = ""
        REMOTE_FILE = "/userdata/app/gk/config/device_account.json"

        # 1: paramiko — sem ferramentas externas, aceita host key automaticamente
        try:
            import paramiko
            self.append_log("[SSH] Tentando paramiko...")
            client = paramiko.SSHClient()
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            client.connect(ip, port=22, username="root", password=ssh_pass,
                           timeout=10, allow_agent=False, look_for_keys=False)
            _, stdout, stderr = client.exec_command(f"cat {REMOTE_FILE}")
            out = stdout.read().decode("utf-8", errors="replace")
            err = stderr.read().decode("utf-8", errors="replace").strip()
            client.close()
            if out.strip():
                device_json = out
                method_used = "paramiko"
            else:
                error_msg = err or "saída vazia"
        except ImportError:
            self.append_log("[SSH] paramiko não instalado — tentando ssh.exe...")
        except Exception as e:
            self.append_log(f"[SSH] paramiko: {e}")
            error_msg = str(e)

        # 2: OpenSSH nativo do Windows
        if not device_json:
            ssh_bin = shutil.which("ssh")
            if ssh_bin:
                self.append_log("[SSH] Tentando OpenSSH (ssh.exe)...")
                try:
                    result = subprocess.run(
                        [ssh_bin,
                         "-o", "StrictHostKeyChecking=no",
                         "-o", "UserKnownHostsFile=NUL",
                         "-o", "ConnectTimeout=8",
                         "-o", "PubkeyAuthentication=no",
                         f"root@{ip}", f"cat {REMOTE_FILE}"],
                        input=ssh_pass + "\n",
                        capture_output=True, text=True, timeout=15
                    )
                    if result.returncode == 0 and result.stdout.strip():
                        device_json = result.stdout
                        method_used = "ssh.exe"
                    else:
                        error_msg = result.stderr or result.stdout
                except Exception as e:
                    error_msg = str(e)

        # 3: plink (PuTTY)
        if not device_json:
            plink = shutil.which("plink")
            if plink:
                self.append_log("[SSH] Tentando plink...")
                try:
                    result = subprocess.run(
                        [plink, "-ssh", f"root@{ip}", "-pw", ssh_pass,
                         "-batch", "-auto-store-sshkey", f"cat {REMOTE_FILE}"],
                        capture_output=True, text=True, timeout=15
                    )
                    if result.returncode == 0 and result.stdout.strip():
                        device_json = result.stdout
                        method_used = "plink"
                    else:
                        error_msg = result.stderr or result.stdout
                except Exception as e:
                    error_msg = str(e)

        if not device_json or not device_json.strip():
            self.append_log(f"[SSH] Falhou: {error_msg[:120]}")
            QMessageBox.critical(self, "SSH FETCH — Erro",
                f"Não foi possível conectar.\n\nIP: {ip}\nErro: {error_msg[:300]}\n\n"
                "Solução: instale paramiko:\n  pip install paramiko\n\n"
                "Manual: no SSH da impressora:\n"
                "  cat /userdata/app/gk/config/device_account.json\n"
                "Copie, salve como .json, use [LOAD .json]")
            return

        self.append_log(f"[SSH] Lido via {method_used} ({len(device_json)} chars)")

        try:
            s = device_json.find("{"); e2 = device_json.rfind("}")
            if s >= 0 and e2 > s:
                device_json = device_json[s:e2+1]
            data = _json.loads(device_json)
        except Exception as e:
            self.append_log(f"[SSH] JSON inválido: {e}")
            QMessageBox.critical(self, "SSH FETCH — JSON inválido",
                f"JSON inválido:\n{e}\n\n{device_json[:300]}")
            return

        # Salvar cópia local
        local_dir  = os.path.join(os.path.expanduser("~"), ".se3d")
        os.makedirs(local_dir, exist_ok=True)
        local_path = os.path.join(local_dir, f"device_account_{ip.replace('.','_')}.json")
        try:
            import json as _j2
            with open(local_path, "w", encoding="utf-8") as f:
                _j2.dump(data, f, indent=2, ensure_ascii=False)
            self.append_log(f"[SSH] Cópia salva: {local_path}")
        except Exception as ex:
            self.append_log(f"[SSH] Cópia local: {ex}")

        self._apply_device_account_with_debug(data, source=f"SSH:{ip}")

        # Também buscar os certs reais do cert3
        self._fetch_cert3_ssh(ip, ssh_pass, method_used)

    def _fetch_cert3_ssh(self, ip: str, ssh_pass: str, method_used: str):
        """Busca deviceCrt/devicePk/caCrt de /useremain/app/gk/cert3/ via SSH."""
        import os, configparser

        self.append_log("[CERT3] Buscando certs reais de /useremain/app/gk/cert3/...")

        # Também pegar deviceUnionid/deviceKey do device.ini
        files = {
            "deviceCrt": "/useremain/app/gk/cert3/deviceCrt",
            "devicePk":  "/useremain/app/gk/cert3/devicePk",
            "caCrt":     "/useremain/app/gk/cert3/caCrt",
            "device_ini":"/userdata/app/gk/config/device.ini",
        }
        results = {}

        for name, path in files.items():
            content = self._ssh_read_file(ip, ssh_pass, path, method_used)
            if content:
                results[name] = content
                self.append_log(f"[CERT3] {name}: {len(content)} chars")
            else:
                self.append_log(f"[CERT3] {name}: não encontrado")

        cert = results.get("deviceCrt", "")
        key  = results.get("devicePk",  "")
        ca   = results.get("caCrt",     "")

        if cert and key:
            self._settings["device_cert"] = cert
            self._settings["device_key"]  = key
            if ca:
                self._settings["device_ca"] = ca

            lines = [l for l in cert.splitlines() if l and not l.startswith("---")]
            self._lbl_cert_status.setText(f"●  cert3/deviceCrt carregado  ({sum(len(l) for l in lines)} bytes)")
            self._lbl_cert_status.setStyleSheet("color:#00E5A0; font-family:'Courier New'; font-size:10px;")
            self.append_log("[CERT3] ✓ Certs reais carregados de /useremain/app/gk/cert3/")

        # Extrair deviceUnionid/deviceKey do device.ini
        ini = results.get("device_ini", "")
        if ini:
            self._parse_device_ini(ini)

        self.settings_saved.emit(self._collect())

    def _parse_device_ini(self, ini_text: str):
        """Extrai deviceUnionid/deviceKey do device.ini — só usa se device_account não tiver user."""
        import re
        # Só sobrescreve se o campo estiver vazio (device_account.json tem prioridade)
        if self._inp_mqtt_user.text().strip():
            self.append_log("[CERT3] device.ini: user já preenchido pelo device_account.json — ignorando")
            return
        for section in ["cloud_global_prod", "cloud_prod"]:
            pat_uid = rf'\[{section}\].*?deviceUnionid\s*:\s*(\S+)'
            pat_key = rf'\[{section}\].*?deviceKey\s*:\s*(\S+)'
            m_uid = re.search(pat_uid, ini_text, re.DOTALL | re.IGNORECASE)
            m_key = re.search(pat_key, ini_text, re.DOTALL | re.IGNORECASE)
            if m_uid and m_key:
                uid = m_uid.group(1).strip()
                dkey = m_key.group(1).strip()
                if uid and dkey:
                    self._inp_mqtt_user.setText(uid)
                    self._inp_mqtt_pass.setText(dkey)
                    self._settings["mqtt_user"] = uid
                    self._settings["mqtt_pass"] = dkey
                    self.append_log(f"[CERT3] deviceUnionid → USER (fallback): {uid[:12]}...")
                    self.append_log(f"[CERT3] deviceKey → PASS (fallback): {dkey[:8]}...")
                    return

    def _ssh_read_file(self, ip: str, ssh_pass: str, remote_path: str, method: str) -> str:
        """Lê um arquivo remoto via SSH (reutiliza o método que funcionou)."""
        import subprocess, shutil
        try:
            if method == "paramiko":
                import paramiko
                client = paramiko.SSHClient()
                client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                client.connect(ip, port=22, username="root", password=ssh_pass,
                               timeout=10, allow_agent=False, look_for_keys=False)
                _, stdout, _ = client.exec_command(f"cat {remote_path}")
                out = stdout.read().decode("utf-8", errors="replace")
                client.close()
                return out.strip()
            elif method == "plink":
                plink = shutil.which("plink")
                result = subprocess.run(
                    [plink, "-ssh", f"root@{ip}", "-pw", ssh_pass,
                     "-batch", "-auto-store-sshkey", f"cat {remote_path}"],
                    capture_output=True, text=True, timeout=10)
                return result.stdout.strip()
            else:
                ssh_bin = shutil.which("ssh")
                result = subprocess.run(
                    [ssh_bin, "-o", "StrictHostKeyChecking=no",
                     "-o", "UserKnownHostsFile=NUL", f"root@{ip}",
                     f"cat {remote_path}"],
                    input=ssh_pass + "\n", capture_output=True, text=True, timeout=10)
                return result.stdout.strip()
        except Exception as e:
            self.append_log(f"[SSH] {remote_path}: {e}")
            return ""

    def _apply_device_account_with_debug(self, data: dict, source: str = ""):
        """Aplica device_account e faz diagnóstico detalhado no log."""
        cert_raw = data.get("devicecrt", "")
        key_raw  = data.get("devicepk",  "")
        self.append_log(f"[CERT] Fonte: {source} | devicecrt={len(cert_raw)} chars")
        if cert_raw:
            has_lit  = "\\n" in cert_raw
            has_real = "\n"  in cert_raw
            self.append_log(f"[CERT] \\n literais={has_lit} quebras reais={has_real}")
            cert  = cert_raw.replace("\\n", "\n")
            lines = cert.splitlines()
            dl    = [l for l in lines if l and not l.startswith("---")]
            self.append_log(f"[CERT] {len(lines)} linhas / {len(dl)} dados")
            try:
                import ssl, tempfile, os as _os
                ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
                ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE
                key = key_raw.replace("\\n", "\n")
                with tempfile.NamedTemporaryFile(delete=False, suffix=".crt", mode="w") as fc:
                    fc.write(cert); cp = fc.name
                with tempfile.NamedTemporaryFile(delete=False, suffix=".key", mode="w") as fk:
                    fk.write(key);  kp = fk.name
                try:
                    ctx.load_cert_chain(certfile=cp, keyfile=kp)
                    self.append_log("[CERT] ✓ PEM válido — load_cert_chain OK")
                finally:
                    _os.unlink(cp); _os.unlink(kp)
            except Exception as ex:
                self.append_log(f"[CERT] ✗ PEM: {ex}")
        else:
            self.append_log("[CERT] ✗ devicecrt ausente!")
        self._apply_device_account(data)


    def _apply_device_account(self, data: dict):
        """Aplica dados do device_account.json nos campos e settings."""
        from PyQt6.QtWidgets import QMessageBox

        user = data.get("username", "")
        pw   = data.get("password", "")
        did  = data.get("deviceId", "")
        cert = data.get("devicecrt", "")
        key  = data.get("devicepk", "")

        if cert: cert = cert.replace("\\n", "\n")
        if key:  key  = key.replace("\\n", "\n")

        if user:
            self._inp_mqtt_user.setText(user)
            self._settings["mqtt_user"] = user
        if pw:
            self._inp_mqtt_pass.setText(pw)
            self._settings["mqtt_pass"] = pw
        if did:
            self._inp_device_id.setText(did)
            self._settings["device_id"] = did

        self._settings["device_cert"] = cert
        self._settings["device_key"]  = key

        if cert:
            lines    = [l for l in cert.splitlines() if l and not l.startswith("---")]
            data_len = sum(len(l) for l in lines)
            self._lbl_cert_status.setText(f"●  Certificado carregado  ({data_len} bytes)")
            self._lbl_cert_status.setStyleSheet(
                "color:#00E5A0; font-family:'Courier New'; font-size:10px;")
        else:
            self._lbl_cert_status.setText("○  sem certificado")
            self._lbl_cert_status.setStyleSheet(
                "color:#FF4444; font-family:'Courier New'; font-size:10px;")

        self.settings_saved.emit(self._collect())

        loaded = [x for x, v in [
            ("MQTT USER", user), ("MQTT PASSWORD", pw),
            ("DEVICE ID", did), ("CERTIFICATE (mTLS)", cert), ("PRIVATE KEY (mTLS)", key)
        ] if v]
        QMessageBox.information(self, "Carregado",
            "Carregado com sucesso:\n\n• " + "\n• ".join(loaded))

    def _show_token_details(self):
        """Mostra popup com detalhes do token carregado (ou instrução se não há token)."""
        from PyQt6.QtWidgets import QMessageBox
        if self._slicer_token:
            short = self._slicer_token[:20] + "..." + self._slicer_token[-10:]
            QMessageBox.information(self, "Slicer Next Token",
                f"Token carregado com sucesso.\n\n"
                f"Valor: {short}\n"
                f"Tamanho: {len(self._slicer_token)} caracteres\n\n"
                "Este token é usado para autenticar na nuvem Anycubic\n"
                "e obter as credenciais MQTT automaticamente.")
        else:
            QMessageBox.warning(self, "Sem Token",
                "Nenhum token carregado.\n\n"
                "Clique em ⟳ para tentar carregar do Anycubic Slicer Next.")

    # ── Load device_account.json ──────────────────────────────────────────────
    def _load_device_account(self):
        """Load MQTT credentials and device cert from device_account.json."""
        from PyQt6.QtWidgets import QFileDialog, QMessageBox
        import json as _json

        path, _ = QFileDialog.getOpenFileName(
            self, "Open device_account.json", "", "JSON Files (*.json);;All Files (*)"
        )
        if not path:
            return
        try:
            with open(path, "rb") as f:
                raw_bytes = f.read()

            # Remover BOM (UTF-32, UTF-16, UTF-8)
            if raw_bytes.startswith(b'\xff\xfe\x00\x00') or raw_bytes.startswith(b'\x00\x00\xfe\xff'):
                raw_text = raw_bytes.decode("utf-32", errors="replace")
            elif raw_bytes.startswith(b'\xff\xfe') or raw_bytes.startswith(b'\xfe\xff'):
                raw_text = raw_bytes.decode("utf-16", errors="replace")
            elif raw_bytes.startswith(b'\xef\xbb\xbf'):
                raw_text = raw_bytes[3:].decode("utf-8", errors="replace")
            else:
                raw_text = raw_bytes.decode("utf-8", errors="replace")

            raw_text = raw_text.strip().lstrip('\x00\ufeff')
            data = _json.loads(raw_text)
            self._apply_device_account(data)
            self.append_log(f"[CERT] Carregado de arquivo: {path}")
        except Exception as e:
            QMessageBox.critical(self, "Load Error", f"Falha ao ler arquivo:\n{e}")

    def _show_deviceid_help(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("How to find your Device ID")
        dlg.setMinimumWidth(520)
        dlg.setStyleSheet(self.styleSheet())
        lay = QVBoxLayout(dlg)

        txt = QTextEdit(dlg)
        txt.setReadOnly(True)
        txt.setFont(QFont("Courier New", 11))
        txt.setStyleSheet("background:#0D1B2A; color:#A0B8C8; border:1px solid #1E2D3D;")
        txt.setPlainText(
            "HOW TO FIND YOUR DEVICE ID\n"
            + "=" * 42 + "\n\n"
            "OPTION 1 — AUTO-DETECT (easiest)\n"
            + "-" * 36 + "\n"
            "Leave the DEVICE ID field empty.\n"
            "Connect using your MQTT credentials.\n"
            "The device ID is discovered automatically\n"
            "from the first MQTT message and saved.\n\n"
            "OPTION 2 — Via Rinkhals SSH\n"
            + "-" * 36 + "\n"
            "1. SSH into your printer:\n"
            "   ssh root@<printer-ip>\n"
            "   (default password: rockchip)\n\n"
            "2. Run:\n"
            "   cat /userdata/app/gk/config/device_account.json\n\n"
            "3. Copy the 'deviceId' value\n\n"
            "   MQTT credentials are in the same file:\n"
            "     username  → 'username' field\n"
            "     password  → 'password' field\n\n"
            "OPTION 3 — Via Anycubic app\n"
            + "-" * 36 + "\n"
            "Open the Anycubic app > My Printer.\n"
            "The device ID appears in the printer details."
        )
        lay.addWidget(txt)
        btn = QPushButton("CLOSE", dlg)
        btn.clicked.connect(dlg.accept)
        lay.addWidget(btn)
        dlg.exec()
