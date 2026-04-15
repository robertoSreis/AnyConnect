# -*- coding: utf-8 -*-
"""Main window — screen flow + MQTT wiring"""

import os
import tempfile

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QStackedWidget, QStatusBar, QFrame,
    QTabWidget, QPushButton, QMessageBox, QDialog,
    QSystemTrayIcon, QMenu
)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QFont, QIcon, QAction

from ui.theme import STYLESHEET
from ui.printer_select import PrinterSelectWidget
from ui.login_widget import LoginWidget
from ui.control_widget import ControlWidget
from core import settings as settings_manager
from core.moonraker_client import MoonrakerClient
from core.mqtt_client import MqttClient
from ui.print_queue_widget import (
    PrintQueue, BedClearDialog, QueuedNoticeDialog, PrintQueueDialog
)


def build_client(mode: str, parent=None):
    """Factory — returns the right client for the connection mode."""
    if mode == "local":
        return MoonrakerClient(parent)
    return MqttClient(parent)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self._settings = settings_manager.load()
        self._mqtt = None  # criado em _restore_state para evitar wire duplo
        self._last_temps = {"bed": "--", "noz": "--"}
        self._printing_active = False
        self._queue_dialog_open = False
        self._printer_state_known = False
        self._workbench_shown = False
        self._ipc_processing = False
        self._reconnecting = False
        self._print_queue = PrintQueue(self)
        self._print_progress_reset = False
        self._reconnect_attempt    = 0      # contador de tentativas
        self._reconnect_countdown  = 5      # segundos até próxima tentativa
        self._auto_reconnect_stop  = False  # usuário parou manualmente
        self._print_queue.next_job_ready.connect(self._on_queue_next)
        self._print_queue.queue_changed.connect(self._on_queue_badge)
        self._print_queue.play_requested.connect(self._on_queue_next)
        self._setup_window()
        self._setup_tray()
        self._setup_ipc()
        self._build_ui()
        if hasattr(self._print, "print_started"):
            self._print.print_started.connect(self._on_print_started)
        QTimer.singleShot(0, self._restore_state)

    # ── Window ────────────────────────────────────────────────────────────────
    def _setup_window(self):
        self.setWindowTitle("SE3D  —  3D PRINTER CONTROLLER")
        self.setMinimumSize(900, 600)
        self.setStyleSheet(STYLESHEET)
        # Garante que a janela sempre abre maximizada
        self.setWindowState(Qt.WindowState.WindowMaximized)
        try:
            import os
            from PyQt6.QtGui import QIcon
            _base = os.path.dirname(os.path.abspath(__file__))
            for _c in [
                os.path.join(_base, "..", "icon.ico"),
                os.path.join(_base, "icon.ico"),
                os.path.join(os.getcwd(), "icon.ico"),
            ]:
                if os.path.exists(_c):
                    self.setWindowIcon(QIcon(_c))
                    break
        except Exception:
            pass

    # ── Tray Icon ─────────────────────────────────────────────────────────────
    def _setup_tray(self):
        self._tray = None
        self._tray_close = False
        try:
            _base = os.path.dirname(os.path.abspath(__file__))
            icon = None
            for _c in [
                os.path.join(_base, "..", "icon.ico"),
                os.path.join(_base, "icon.ico"),
                os.path.join(os.getcwd(), "icon.ico"),
            ]:
                if os.path.exists(_c):
                    icon = QIcon(_c)
                    break
            if icon is None:
                return
            self._tray = QSystemTrayIcon(icon, self)
            menu = QMenu()
            act_show = QAction("Abrir SE3D", self)
            act_show.triggered.connect(self._tray_show)
            act_quit = QAction("Sair", self)
            act_quit.triggered.connect(self._tray_quit)
            menu.addAction(act_show)
            menu.addSeparator()
            menu.addAction(act_quit)
            self._tray.setContextMenu(menu)
            self._tray.setToolTip("SE3D — 3D Printer Controller")
            self._tray.activated.connect(self._tray_activated)
            self._tray.show()
        except Exception:
            pass

    def _tray_show(self):
        self.showMaximized()
        self.activateWindow()
        self.raise_()

    def _tray_quit(self):
        self._tray_close = True
        from PyQt6.QtWidgets import QApplication
        QApplication.instance().quit()

    def _tray_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self._tray_show()

    def changeEvent(self, event):
        from PyQt6.QtCore import QEvent
        super().changeEvent(event)
        if event.type() == QEvent.Type.WindowStateChange:
            # Quando restaurar da barra de tarefas, garante que volta maximizado
            if not self.isMinimized() and not self.isMaximized() and self.isVisible():
                QTimer.singleShot(0, self.showMaximized)

    def closeEvent(self, event):
        if self._tray and self._tray.isVisible() and not self._tray_close:
            event.ignore()
            self.hide()
            self._tray.showMessage(
                "SE3D",
                "O app continua rodando na bandeja do sistema.",
                QSystemTrayIcon.MessageIcon.Information,
                1000,
            )
        else:
            self._ipc_clear()   # remove heartbeat — bridge saberá que o app fechou
            event.accept()

    # ── IPC — recebe filepath de nova instância via arquivo de handshake ─────────
    def _setup_ipc(self):
        """Cria e mantém o arquivo IPC atualizado (sinal de vida).
        Escreve "ALIVE:<timestamp>" a cada 500ms para que o bridge.py possa
        distinguir um app vivo de um arquivo orphan deixado por crash/fechamento.
        Nova instância do slicer escreve o filepath nesse arquivo.
        """
        self._ipc_file = os.path.join(tempfile.gettempdir(), "se3d_gestor_ipc.txt")
        self._ipc_write_alive()
        self._ipc_timer = QTimer(self)
        self._ipc_timer.setInterval(500)
        self._ipc_timer.timeout.connect(self._check_ipc)
        self._ipc_timer.start()

    def _ipc_write_alive(self):
        """Escreve o heartbeat de sinal de vida no arquivo IPC."""
        import time as _time
        try:
            with open(self._ipc_file, "w", encoding="utf-8") as f:
                f.write(f"ALIVE:{_time.time():.3f}")
        except Exception:
            pass

    def _ipc_clear(self):
        """Remove o arquivo IPC ao fechar — evita false-positive no bridge."""
        try:
            if os.path.exists(self._ipc_file):
                os.remove(self._ipc_file)
        except Exception:
            pass

    def _check_ipc(self):
        """Lê filepath se presente, depois escreve heartbeat ALIVE:<ts>."""
        import time as _time
        try:
            if not os.path.exists(self._ipc_file):
                self._ipc_write_alive()
                return
            with open(self._ipc_file, "r", encoding="utf-8") as f:
                content = f.read().strip()

            # Heartbeat próprio ou arquivo vazio — apenas renovar
            if not content or content.startswith("ALIVE:"):
                self._ipc_write_alive()
                return

            # Tem um filepath escrito pelo bridge — processar
            filepath = content
            # Reescreve heartbeat imediatamente (evita leitura dupla)
            self._ipc_write_alive()

            if filepath and os.path.isfile(filepath):
                if getattr(self, "_ipc_processing", False):
                    return
                self._ipc_processing = True
                self._tray_show()
                self._open_file(filepath)
                self._ipc_processing = False
        except Exception:
            self._ipc_processing = False
            self._ipc_write_alive()

    def _open_file(self, filepath: str):
        """Abre arquivo recebido via IPC ou argumento de linha de comando.
        Se a impressora estiver imprimindo, enfileira e avisa o usuário.
        """
        if not filepath or not os.path.isfile(filepath):
            return

        # Considera ocupado se: _printing_active OU upload em andamento
        upload_in_progress = False
        if hasattr(self, "_print") and hasattr(self._print, "_stack"):
            upload_in_progress = (self._print._stack.currentIndex() == 3)

        is_busy = getattr(self, "_printing_active", False) or upload_in_progress

        # Impressora ocupada → enfileira sem tocar no job_state do print atual.
        # O thumbnail é extraído pelo print_queue.enqueue() em background
        # e salvo como <filepath>.queue_thumb.png (isolado do workbench).
        if is_busy:
            job = {
                "filepath":  filepath,
                "task_name": os.path.splitext(os.path.basename(filepath))[0],
                "preview_png": "",
            }
            self._print_queue.enqueue(job)
            pos = self._print_queue.count()
            self._tray_show()
            dlg = QueuedNoticeDialog(job, pos, self)
            dlg.exec()
            return

        # Impressora livre: abre normalmente
        self._tray_show()
        if hasattr(self, "_tabs"):
            self._tabs.setCurrentIndex(0)
        if hasattr(self, "_print"):
            self._print.load_file_from_arg(filepath)

    def _on_queue_next(self, job: dict):
        """Chamado pela fila quando há job aguardando após fim de impressão."""
        if self._queue_dialog_open:
            return
        if getattr(self, "_printing_active", False):
            return

        self._queue_dialog_open = True
        self._tray_show()
        dlg = BedClearDialog(job, self)
        dlg.exec()
        action = dlg.get_action()
        self._queue_dialog_open = False

        if action == BedClearDialog.RESULT_OK:
            # Mesa confirmada — remove da fila e abre para impressão
            self._print_queue.dequeue()
            filepath = job.get("filepath", "")
            if filepath and os.path.isfile(filepath):
                if hasattr(self, "_tabs"):
                    self._tabs.setCurrentIndex(0)
                if hasattr(self, "_print"):
                    self._print.load_file_from_arg(filepath)
            if self._tray:
                self._tray.showMessage(
                    "SE3D — NEXT PRINT",
                    f"LOADING: {job.get('task_name', 'arquivo')}",
                    QSystemTrayIcon.MessageIcon.Information,
                    3000,
                )

        elif action == BedClearDialog.RESULT_SKIP:
            # Pular — move para o final e tenta o próximo (evita loop com 1 item)
            self._print_queue.dequeue()
            self._print_queue.enqueue(job)
            if not self._print_queue.is_empty():
                next_job = self._print_queue.peek()
                if next_job and next_job.get("filepath") != job.get("filepath"):
                    QTimer.singleShot(400, lambda j=next_job: self._on_queue_next(j))

        elif action == BedClearDialog.RESULT_CANCEL:
            # Remover permanentemente (usuário já confirmou no diálogo)
            self._print_queue.dequeue()
            if not self._print_queue.is_empty():
                QTimer.singleShot(500, self._print_queue.on_print_finished)

        # RESULT_WAIT ou fechar com X — não faz nada, job fica na fila
        # Próximo evento de print_finished vai disparar novamente

    def _on_queue_badge(self, count: int):
        """Atualiza o botão FILA com contador."""
        if hasattr(self, "_btn_queue"):
            if count > 0:
                self._btn_queue.setText(f"JOBS QUEUE [{count}]")
                self._btn_queue.setStyleSheet("""
                    QPushButton { background:transparent; border:none;
                                  color:#FFB300; font-family:'Courier New';
                                  font-size:11px; letter-spacing:1px; }
                    QPushButton:hover { color:#FFC830; }
                """)
            else:
                self._btn_queue.setText("JOBS QUEUE")
                self._btn_queue.setStyleSheet("""
                    QPushButton { background:transparent; border:none;
                                  color:#607080; font-family:'Courier New';
                                  font-size:11px; letter-spacing:1px; }
                    QPushButton:hover { color:#8090A0; }
                """)

    def _show_queue_dialog(self):
        """Abre o diálogo de visualização da fila."""
        dlg = PrintQueueDialog(self._print_queue, self,
                               is_printing=getattr(self, "_printing_active", False))
        dlg.exec()

    # ── UI ────────────────────────────────────────────────────────────────────
    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Top bar (mantido como atributo para não ser destruído pelo GC mesmo comentado)
        self._topbar = QFrame()
        self._topbar.setFixedHeight(48)
        self._topbar.setStyleSheet("background:#080C0F; border-bottom:1px solid #1A2535;")
        tl = QHBoxLayout(self._topbar)
        tl.setContentsMargins(20, 0, 20, 0)

        lbl_app = QLabel("■  3D  PRINT  CONTROLLER")
        lbl_app.setFont(QFont("Courier New", 12, QFont.Weight.Bold))
        lbl_app.setStyleSheet("color:#00E5FF; letter-spacing:4px;")

        self._lbl_printer = QLabel("")
        self._lbl_printer.setFont(QFont("Courier New", 10))
        self._lbl_printer.setStyleSheet("color:#607080; letter-spacing:2px;")

        self._lbl_conn = QLabel("○  DISCONNECTED")
        self._lbl_conn.setFont(QFont("Courier New", 10))
        self._lbl_conn.setStyleSheet("color:#FF4444; letter-spacing:2px;")

        tl.addWidget(lbl_app)
        tl.addStretch()
        tl.addWidget(self._lbl_printer)
        tl.addSpacing(20)
        tl.addWidget(self._lbl_conn)
        #root.addWidget(self._topbar)

        # Stack: 0=select  1=config  2=main
        self._stack = QStackedWidget()

        self._screen_select = PrinterSelectWidget()
        self._screen_select.brand_selected.connect(self._on_brand_selected)

        self._screen_login = LoginWidget(self._settings)
        self._screen_login.settings_saved.connect(self._on_settings_saved)
        self._screen_login.connect_requested.connect(self._on_connect_requested)
        self._screen_login.back_requested.connect(lambda: self._stack.setCurrentIndex(2))

        self._screen_main = self._build_main_tabs()

        self._stack.addWidget(self._screen_select)
        self._stack.addWidget(self._screen_login)
        self._stack.addWidget(self._screen_main)
        root.addWidget(self._stack)

        sb = QStatusBar()
        sb.setStyleSheet(
            "background:#080C0F; color:#3A4550; font-size:10px; border-top:1px solid #1A2535;"
        )
        sb.showMessage("READY  |  v0.1.0  |  SE3D GESTOR")
        self.setStatusBar(sb)

    def _build_main_tabs(self) -> QWidget:
        container = QWidget()
        cl = QVBoxLayout(container)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(0)

        # Sub-nav bar
        nav = QFrame()
        nav.setFixedHeight(36)
        nav.setStyleSheet("background:#080C0F; border-bottom:1px solid #1A2535;")
        nl = QHBoxLayout(nav)
        nl.setContentsMargins(16, 0, 16, 0)

        btn_cfg = QPushButton("CONFIG")
        btn_cfg.setMinimumWidth(90)
        btn_cfg.setFixedHeight(28)
        btn_cfg.setStyleSheet("""
            QPushButton { background:transparent; border:none; color:#607080;
                          font-family:'Courier New'; font-size:11px; letter-spacing:1px; }
            QPushButton:hover { color:#00E5FF; }
        """)
        btn_cfg.clicked.connect(lambda: self._stack.setCurrentIndex(1))
        # CONFIG aba
        self._tabs = QTabWidget()

        self._control = ControlWidget(self._settings)
        self._control.command_ready.connect(self._on_command)
        self._tabs.addTab(self._control, "CONTROL")
        # Nota: CONFIG é acessado via botão CONFIG → _stack index 1 (LoginWidget)
        # NÃO adicionar self._screen_login como aba aqui — ela está no _stack
        # e um QWidget só pode ter um pai por vez.

        self._btn_reconnect = QPushButton("CONNECT")
        self._btn_reconnect.setMinimumWidth(140)
        self._btn_reconnect.setFixedHeight(28)
        self._btn_reconnect.setStyleSheet("""
            QPushButton { background:#003D52; border:1px solid #00E5FF; color:#00E5FF;
                          font-family:'Courier New'; font-size:10px; letter-spacing:1px;
                          border-radius:2px; padding:0 10px; }
            QPushButton:hover { background:#005070; }
        """)
        self._btn_reconnect.clicked.connect(self._do_connect)

        from PyQt6.QtWidgets import QCheckBox as _QCB
        self._chk_auto_reconnect = _QCB("Auto")
        self._chk_auto_reconnect.setChecked(True)
        self._chk_auto_reconnect.setFont(QFont("Courier New", 9))
        self._chk_auto_reconnect.setStyleSheet("color:#607080;")
        self._chk_auto_reconnect.setToolTip("Reconexão automática")
        self._chk_auto_reconnect.toggled.connect(self._on_auto_reconnect_toggled)

        nl.addWidget(btn_cfg)
        nl.addStretch()

        self._btn_queue = QPushButton("JOBS QUEUE")
        self._btn_queue.setMinimumWidth(70)
        self._btn_queue.setFixedHeight(28)
        self._btn_queue.setStyleSheet("""
            QPushButton { background:transparent; border:none; color:#607080;
                          font-family:'Courier New'; font-size:11px; letter-spacing:1px; }
            QPushButton:hover { color:#8090A0; }
        """)
        self._btn_queue.clicked.connect(self._show_queue_dialog)
        nl.addWidget(self._btn_queue)
        nl.addSpacing(8)
        nl.addWidget(self._chk_auto_reconnect)
        nl.addSpacing(4)
        nl.addWidget(self._btn_reconnect)
        cl.addWidget(nav)

        

        # PrintWidget está embutido no ControlWidget — referência para callbacks
        self._print = self._control._print_widget
        # Injeta callback de status e conecta sinal de fila
        self._print._is_printing_cb = lambda: getattr(self, "_printing_active", False)
        self._print.enqueue_requested.connect(self._open_file)


        cl.addWidget(self._tabs)
        return container

    # ── MQTT wiring ───────────────────────────────────────────────────────────
    def _wire_mqtt(self):
        self._mqtt.connected.connect(self._on_mqtt_connected)
        self._mqtt.disconnected.connect(self._on_mqtt_disconnected)
        self._mqtt.connection_error.connect(self._on_mqtt_error)
        self._mqtt.printer_info.connect(self._on_printer_info)
        self._mqtt.print_report.connect(self._on_print_report)
        self._mqtt.device_id_found.connect(self._on_device_id_found)
        self._mqtt.motors_state.connect(self._on_motors_state)
        if hasattr(self._mqtt, "print_error"):
            self._mqtt.print_error.connect(self._on_print_error)

    def _do_connect(self):
        mode = self._settings.get("connection_mode", "cloud")
        ip   = self._settings.get("printer_ip", "").strip()

        if mode == "local":
            port = self._settings.get("moonraker_port", 7125)
            if not ip:
                QMessageBox.warning(self, "No IP", "Enter the printer IP in CONFIG first.")
                return
            self._set_status("connecting")
            self._mqtt.connect_to_printer(ip=ip, port=port)
        else:
            mqtt_user  = self._settings.get("mqtt_user", "").strip()
            mqtt_pass  = self._settings.get("mqtt_pass", "")
            did        = self._settings.get("device_id", "")
            region     = self._settings.get("cloud_region", "global")
            printer_ip = self._settings.get("printer_ip", "").strip()
            if not printer_ip:
                QMessageBox.warning(self, "IP não configurado",
                    "Configure o IP da impressora em CONFIG → Cloud.\n"
                    "Ex: 192.168.100.29")
                return
            self._set_status("connecting")
            self._mqtt.connect_to_printer(
                ip=printer_ip,
                mqtt_user=mqtt_user,
                mqtt_pass=mqtt_pass,
                device_id=did,
                region=region,
                slicer_token=self._settings.get("slicer_token", ""),
                device_cert=self._settings.get("device_cert", ""),
                device_key=self._settings.get("device_key",  ""),
                device_ca=self._settings.get("device_ca",   ""),
            )

    # ── MQTT callbacks ────────────────────────────────────────────────────────
    def _on_mqtt_connected(self):
        self._reconnecting = False
        if hasattr(self._print, "_current_job"):
            self._print._current_job   = None
            self._print._current_thumb = None

        mode = self._settings.get("connection_mode", "lan")
        via  = "Moonraker (Rinkhals)" if mode == "local" else "LAN (Mochi)"
        self._set_status("connected", f"✓ Connected via {via}")
        self._screen_login.append_log(f"✓ Connected via {via}")
        self.statusBar().showMessage("MQTT  CONNECTED  |  SE3D GESTOR")
        self._btn_reconnect.setText("DISCONNECT")
        self._btn_reconnect.clicked.disconnect()
        self._btn_reconnect.clicked.connect(self._do_disconnect)
        ip = self._settings.get("printer_ip", "")
        self._print.update_connection(connected=True, ip=ip)
        if hasattr(self._print, "set_mqtt"):
            self._print.set_mqtt(self._mqtt)
        if hasattr(self._print, "print_started"):
            try:
                self._print.print_started.disconnect(self._on_print_started)
            except Exception:
                pass
            self._print.print_started.connect(self._on_print_started)

        self._printer_state_known = False
        self._check_queue_attempts = 0

        # força IDLE no colormap ao conectar
        self._print._colormap._connected = True
        self._print._colormap._last_state = "IDLE"
        self._print._colormap._do_refresh_print_btn()
    def _on_mqtt_disconnected(self, reason: str):
        self._set_status("disconnected", reason)
        self.statusBar().showMessage(f"DISCONNECTED  |  {reason}")
        self._btn_reconnect.setText("CONNECT")
        self._btn_reconnect.clicked.disconnect()
        self._btn_reconnect.clicked.connect(self._do_connect)
        self._print.update_connection(connected=False)
        self._printing_active    = False
        self._printer_state_known = False
        self._workbench_shown    = False

        # Inicia reconexão automática se habilitada
        if self._chk_auto_reconnect.isChecked():
            self._auto_reconnect_stop = False
            self._reconnect_attempt   = 0
            self._reconnect_countdown = 5
            self._start_reconnect_display()

    def _on_mqtt_error(self, msg: str):
        self._set_status("error")
        if hasattr(self._screen_login, '_lbl_status'):
            self._screen_login._lbl_status.setText("● ERROR")
            self._screen_login._lbl_status.setStyleSheet(
                "color:#FF4444; font-size:11px; letter-spacing:1px;"
            )
        self._screen_login.append_log(f"ERROR: {msg.splitlines()[0]}")
        QMessageBox.critical(self, "Connection Error", msg)

    def _on_device_id_found(self, device_id: str):
        if device_id.startswith("__LOG__:"):
            msg = device_id[8:]
            self._screen_login.append_log(msg)
            self.statusBar().showMessage(msg.splitlines()[0][:80])
            return
        self._settings["device_id"] = device_id
        settings_manager.save(self._settings)
        if hasattr(self._screen_login, '_inp_device_id'):
            self._screen_login._inp_device_id.setText(device_id)
        self.statusBar().showMessage(f"DEVICE  ID  DISCOVERED:  {device_id}")
        self._screen_login.append_log(f"Device ID discovered: {device_id}")

    def _on_printer_info(self, payload: dict):
        source = payload.get("_source", "")

        if source == "temp":
            d = payload.get("data", {})
            self._control.update_temperatures(d)
            # Atualiza cache de temperaturas para injetar no progress_data
            bed = d.get("bed_actual", d.get("curr_hotbed_temp"))
            noz = d.get("hotend0_actual", d.get("curr_nozzle_temp"))
            if bed is not None:
                self._last_temps["bed"] = f"{bed} °C"
            if noz is not None:
                self._last_temps["noz"] = f"{noz} °C"
            return

        if source == "fan":
            if hasattr(self._control, "update_fans"):
                self._control.update_fans(payload.get("data", {}))
            return

        if source == "multicolor":
            data  = payload.get("data", {})
            boxes = data.get("multi_color_box", [])
            if not isinstance(boxes, list):
                return
            if not boxes:
                if hasattr(self._control, "set_ace_connected"):
                    self._control.set_ace_connected(False)
                self._settings["ace_connected"] = False
                if hasattr(self._print, "_colormap"):
                    cm = self._print._colormap
                    if hasattr(cm, "_lbl_no_ace"):
                        cm._lbl_no_ace.setVisible(True)
                return
            if hasattr(self._control, "set_ace_connected"):
                self._control.set_ace_connected(True)
            self._settings["ace_connected"] = True
            # Notifica SetupScreen que dados do ACE chegaram — libera botão STATUS
            if hasattr(self._print, "_setup") and hasattr(self._print._setup, "set_ace_ready"):
                self._print._setup.set_ace_ready()
            # Esconder aviso de ACE desconectado na tela de colormap
            if hasattr(self._print, "_colormap"):
                cm = self._print._colormap
                if hasattr(cm, "_lbl_no_ace"):
                    cm._lbl_no_ace.setVisible(False)
            box = boxes[0]
            if hasattr(self._control, "sync_ace_state"):
                self._control.sync_ace_state(box)

            slots_raw = box.get("slots", [])
            if slots_raw:
                current = {}
                for i, s in enumerate(self._settings.get("slots", [])):
                    key = s.get("index", s.get("paint_index", i))
                    current[key] = s
                active_slot_idx = -1
                for s in slots_raw:
                    slot_index = s.get("index", 0)
                    color      = s.get("color") or [255, 255, 255]
                    current[slot_index] = {
                        "index":               slot_index,
                        "material_type":       s.get("type", "PLA"),
                        "paint_color":         color[:3],
                        "consumables_percent": s.get("consumables_percent", 0),
                        "status":              s.get("status", 0),
                    }
                    if s.get("status") == 5:
                        active_slot_idx = slot_index
                parsed = [current[k] for k in sorted(current.keys())]
                self._control.refresh_slots(parsed)
                self._settings["slots"] = parsed
                if hasattr(self._print, "_colormap"):
                    self._print._colormap._settings["slots"] = parsed
                    if hasattr(self._print._colormap, "refresh_ace_slots"):
                        self._print._colormap.refresh_ace_slots()
                if active_slot_idx >= 0 and hasattr(self._control, "set_printing_slot"):
                    self._control.set_printing_slot(active_slot_idx)

            loaded = box.get("loaded_slot")
            if loaded is not None and hasattr(self._control, "set_printing_slot"):
                self._control.set_printing_slot(int(loaded))
            return

        if source == "video":
            stream_url = payload.get("stream_url", "")
            if stream_url and hasattr(self._control, "_cam_url"):
                self._control._cam_url = stream_url
                if hasattr(self._control, "_cam_url_label"):
                    self._control._cam_url_label.setText(stream_url)
                self._screen_login.append_log(f"  [CAMERA] stream_url: {stream_url}")
            return

        if source == "status":
            state = payload.get("status", "").lower()
            idle_states = {"idle", "free", "ready", "standby",
                           "stoped", "stopped", "stop", "stopping",
                           "finish", "complete", "finished"}
            if state in idle_states:
                self._printer_state_known = True
                was_printing = getattr(self, "_printing_active", False)
                self._printing_active = False
                display_state = "stopping" if state == "stopping" else "idle"
                self._control.update_printer_info({"status": display_state})
                self._set_status("idle")
                self._print.update_printer_state("IDLE")
                if hasattr(self._control, "set_printing_slot"):
                    self._control.set_printing_slot(-1)

                # "stopping" = impressora ainda está parando (resfriando, retraindo).
                # Não dispara a fila agora — agenda verificação após 4s para confirmar idle.
                # Se nesse intervalo chegar outro status "stopping" ou ocupado, o timer
                # é cancelado e remarcado, evitando disparo prematuro.
                if state == "stopping":
                    # Cancela timer anterior se existir
                    _t = getattr(self, "_idle_confirm_timer", None)
                    if _t is not None:
                        _t.stop()
                    self._idle_confirm_timer = QTimer(self)
                    self._idle_confirm_timer.setSingleShot(True)
                    self._idle_confirm_timer.timeout.connect(
                        lambda: self._check_idle_and_trigger_queue(was_printing)
                    )
                    self._idle_confirm_timer.start(4000)
                else:
                    # idle/finished/complete real — cancela qualquer timer pendente
                    _t = getattr(self, "_idle_confirm_timer", None)
                    if _t is not None:
                        _t.stop()
                        self._idle_confirm_timer = None
                    # Só dispara fila se estava imprimindo nesta sessão
                    if (not self._print_queue.is_empty()
                            and not self._queue_dialog_open
                            and was_printing):
                        QTimer.singleShot(1500, self._print_queue.on_print_finished)
            elif state:
                # Qualquer estado não-vazio = impressora ocupada
                # Cancela timer de confirmação de idle se estava pendente
                _t = getattr(self, "_idle_confirm_timer", None)
                if _t is not None:
                    _t.stop()
                    self._idle_confirm_timer = None
                self._printer_state_known = True
                self._printing_active = True
                self._control.update_printer_info({"status": state})
                self._set_status("busy")
                self._print.update_printer_state(state.upper())
            return

        if source == "light":
            status = payload.get("status", -1)
            if status != -1 and hasattr(self._control, "set_light_state"):
                self._control.set_light_state(int(status))
            return

        if "data" in payload:
            data = payload["data"]
            info = {
                "status":            data.get("state", ""),
                "firmware":          data.get("version", ""),
                "ip":                data.get("ip", self._settings.get("printer_ip", "")),
                "print_speed_mode":  data.get("print_speed_mode", 0),
                "fan_speed_pct":     data.get("fan_speed_pct", 0),
                "aux_fan_speed_pct": data.get("aux_fan_speed_pct", 0),
                "box_fan_level":     data.get("box_fan_level", 0),
            }
            temp = data.get("temp", {})
            if temp:
                info["bed_actual"]     = temp.get("curr_hotbed_temp",   0)
                info["hotend0_actual"] = temp.get("curr_nozzle_temp",   0)
                info["bed_target"]     = temp.get("target_hotbed_temp", 0)
                info["hotend0_target"] = temp.get("target_nozzle_temp", 0)
                # Atualiza cache com temperaturas do info/report
                self._last_temps["bed"] = f"{temp.get('curr_hotbed_temp', '--')} °C"
                self._last_temps["noz"] = f"{temp.get('curr_nozzle_temp', '--')} °C"

            project = data.get("project", {})
            if project:
                pstatus = project.get("print_status", 0)
                state_p = project.get("state", "")
                # print_status=2 significa job concluído (finished) — não sobrescreve o estado real
                # print_status=1 significa imprimindo — usa o state do projeto
                # Só usa state_p se impressora está ativamente imprimindo
                is_active_print = pstatus == 1 or state_p in ("printing", "paused", "busy")
                if is_active_print:
                    bed_str = f"{temp.get('curr_hotbed_temp', '--')} °C" if temp else self._last_temps["bed"]
                    noz_str = f"{temp.get('curr_nozzle_temp', '--')} °C" if temp else self._last_temps["noz"]
                    progress_data = {
                        "progress": int(project.get("progress", 0)),
                        "eta":      self._format_eta(project.get("remain_time", 0)),
                        "elapsed":  self._format_eta(project.get("print_time",  0)),
                        "layer":    f"{project.get('curr_layer','-')}/{project.get('total_layers','-')}",
                        "phase":    state_p,
                        "bed_temp": bed_str,
                        "noz_temp": noz_str,
                    }
                    self._print.update_progress(progress_data)
                    info["status"] = state_p  # só sobrescreve quando está imprimindo de fato
        else:
            info = payload

        self._control.update_printer_info(info)
        if any(info.get(k, 0) for k in ("bed_actual", "hotend0_actual")):
            self._control.update_temperatures(info)
        if hasattr(self._control, "update_fans"):
            self._control.update_fans(info)

        state = info.get("status", "").lower()
        idle_states = {"ready", "idle", "free", "standby",
                       "stoped", "stopped", "stop", "stopping",
                       "finish", "complete", "finished"}
        if state in idle_states:
            self._printing_active = False
            self._set_status("idle")
            self._print.update_printer_state("IDLE")
            if hasattr(self._control, "set_printing_slot"):
                self._control.set_printing_slot(-1)
        elif state:
            # Qualquer estado não-vazio e não-idle = ocupada
            self._printing_active = True
            self._set_status("busy")
            self._print.update_printer_state(state.upper())

    def _on_print_report(self, payload: dict):
        data   = payload.get("data", {})
        action = payload.get("action", "")

        # Vai para workbench apenas quando a impressão INICIA — não em cada update.
        # A impressora envia action="start" repetidamente durante a impressão;
        # usamos _printing_active para garantir que só trocamos de tela uma vez.
        if action == "start":
            self._printer_state_known = True   # impressora confirmada como imprimindo
            self._printing_active = True
            # Reseta progresso ao iniciar — evita barra inflada com valor residual
            if not getattr(self, "_workbench_shown", False):
                self._print_progress_reset = True
            if hasattr(self._print, "switch_to_workbench"):
                # Só troca de tela na primeira vez que detecta a impressão
                if not getattr(self, "_workbench_shown", False):
                    self._workbench_shown = True
                    self._print.switch_to_workbench()
        elif action in ("stop", "cancel", "finish", "complete", "stoped", "failed"):
            was_printing = getattr(self, "_printing_active", False)
            self._printing_active = False
            self._workbench_shown = False
            self._print_progress_reset = False

            # Limpa PNG de preview pois impressão terminou
            if hasattr(self._print, "on_print_finished"):
                self._print.on_print_finished()
            # Retorna para a tela de setup sempre que a impressão terminar/parar
            if hasattr(self._print, "_on_workbench_cancelled"):
                QTimer.singleShot(600, self._print._on_workbench_cancelled)
            # Safety: if stuck on upload screen (index 3), force back to setup
            if hasattr(self._print, "_stack") and self._print._stack.currentIndex() == 3:
                QTimer.singleShot(200, lambda: self._print._stack.setCurrentIndex(0))
            # Para "stop/stoped" não dispara fila aqui — aguarda confirmação via
            # source==status (idle real após stopping). Para finish/complete dispara.
            if was_printing and action in ("finish", "complete"):
                QTimer.singleShot(2000, self._print_queue.on_print_finished)

        if not data:
            return

        # Não atualizar progresso se a ação é de encerramento — evita apagar dados na tela
        if action in ("stop", "cancel", "finish", "complete", "stoped", "failed"):
            return

        # Temperaturas: atualiza cache se vieram no payload, senão usa o último valor conhecido
        if data.get("curr_hotbed_temp") is not None:
            self._last_temps["bed"] = f"{data['curr_hotbed_temp']} °C"
        if data.get("curr_nozzle_temp") is not None:
            self._last_temps["noz"] = f"{data['curr_nozzle_temp']} °C"

        # Só manda update_progress se tem dados reais de progresso
        progress = int(data.get("progress", 0))
        elapsed  = data.get("print_time", 0)
        layer    = data.get("curr_layer", 0)
        state_pr = data.get("state", "")

        # Fases de pré-impressão: progress é resíduo do job anterior — ignorar
        _pre_print_states = {"auto_leveling", "leveling", "homing", "warming_up",
                             "preheat", "preheating", "calibrating", "preparing"}
        is_pre_print = state_pr.lower() in _pre_print_states

        # Se recebemos action=start pela primeira vez, força reset da barra
        if getattr(self, "_print_progress_reset", False):
            self._print_progress_reset = False
            self._print.update_progress({
                "progress": 0, "eta": "--", "elapsed": "--",
                "layer": "--", "phase": state_pr,
                "bed_temp": self._last_temps["bed"],
                "noz_temp": self._last_temps["noz"],
            })
            if not is_pre_print:
                # Se já veio com progresso real junto do start, processa normalmente abaixo
                pass
            else:
                return  # aguarda fase de leveling terminar antes de mostrar progresso

        if is_pre_print:
            # Durante leveling/preheat só atualiza temperaturas e fase, não a barra
            self._print.update_progress({
                "progress": -1,  # sentinela: não mexer na barra
                "eta": "", "elapsed": "", "layer": "",
                "phase": state_pr,
                "bed_temp": self._last_temps["bed"],
                "noz_temp": self._last_temps["noz"],
            })
            return

        if progress > 0 or elapsed > 0 or layer > 0:
            progress_data = {
                "progress": progress,
                "eta":      self._format_eta(data.get("remain_time", 0)),
                "elapsed":  self._format_eta(elapsed),
                "layer":    f"{layer}/{data.get('total_layers', data.get('total_layer', '-'))}",
                "phase":    state_pr,
                "bed_temp": self._last_temps["bed"],
                "noz_temp": self._last_temps["noz"],
            }
            self._print.update_progress(progress_data)
            if hasattr(self._control, "update_print_progress"):
                self._control.update_print_progress(progress_data)
        else:
            # Só temperatura — atualiza apenas os campos de temperatura
            temp_only = {
                "progress": -1,  # sinal para não atualizar barra
                "eta":      "",
                "elapsed":  "",
                "layer":    "",
                "phase":    data.get("state", ""),
                "bed_temp": self._last_temps["bed"],
                "noz_temp": self._last_temps["noz"],
            }
            self._print.update_progress(temp_only)

        active_slot = data.get(
            "current_material_index",
            data.get("multi_color_index",
            data.get("current_slot",
            data.get("ace_slot", -1)))
        )
        if active_slot is not None and active_slot >= 0:
            if hasattr(self._control, "set_printing_slot"):
                self._control.set_printing_slot(int(active_slot))

    def _on_print_started(self):
        """Chamado imediatamente quando o usuário confirma envio para a impressora.
        Trava _printing_active antes de qualquer resposta MQTT, evitando que
        um segundo arquivo recebido via IPC seja aberto em vez de enfileirado."""
        self._printing_active = True

    def _check_idle_and_trigger_queue(self, was_printing: bool):
        """Chamado 4s após entrar em 'stopping'.
        Só dispara a fila se a impressora ainda está idle (não voltou a imprimir)
        e não há dialog de fila já aberto. Isso evita que um 'stopping' transitório
        acione a fila antes da impressora realmente parar."""
        self._idle_confirm_timer = None
        # Se voltou a imprimir entre o stopping e agora, ignora
        if getattr(self, "_printing_active", False):
            return
        if self._queue_dialog_open:
            return
        if not was_printing:
            return
        if self._print_queue.is_empty():
            return
        # Pede um status atualizado à impressora e aguarda mais 3s para confirmar
        if self._mqtt and self._mqtt.is_connected:
            try:
                self._mqtt.request_info()
            except Exception:
                pass
        # Timer final de confirmação — se após 3s ainda estiver idle, dispara
        self._idle_final_timer = QTimer(self)
        self._idle_final_timer.setSingleShot(True)
        self._idle_final_timer.timeout.connect(self._trigger_queue_if_still_idle)
        self._idle_final_timer.start(3000)

    def _trigger_queue_if_still_idle(self):
        """Disparo final da fila — só executa se impressora ainda estiver idle."""
        self._idle_final_timer = None
        if getattr(self, "_printing_active", False):
            return
        if self._queue_dialog_open:
            return
        if self._print_queue.is_empty():
            return
        self._print_queue.on_print_finished()

    # ── Command router ────────────────────────────────────────────────────────
    def _on_command(self, cmd: str, value):
        log = f"{cmd} = {value}"
        self.statusBar().showMessage(f"CMD  |  {log}")

        if not self._mqtt.is_connected:
            self.statusBar().showMessage(f"NOT CONNECTED  |  {log}")
            return

        # Se a impressora pode estar em standby, acorda e reenvia o comando após delay
        if self._mqtt.wake():
            QTimer.singleShot(800, lambda: self._dispatch_command(cmd, value))
            return

        self._dispatch_command(cmd, value)

    def _dispatch_command(self, cmd: str, value):
        # Log interno (ex: mensagens do ffmpeg da câmera)
        if cmd == "__log__":
            if isinstance(value, str):
                self._screen_login.append_log(value)
            return
        if cmd == "set_bed_temp":
            self._mqtt.set_temperature("hotbed", int(value))
        elif cmd in ("set_hotend0_temp", "set_hotend1_temp"):
            self._mqtt.set_temperature("nozzle", int(value))
        elif cmd in ("bed_off", "hotend0_off", "hotend1_off"):
            target = "hotbed" if cmd == "bed_off" else "nozzle"
            self._mqtt.set_temperature(target, 0)
        elif cmd == "fan_part":
            self._mqtt.set_fan("fan", int(value))
        elif cmd == "fan_aux":
            self._mqtt.set_fan("aux_fan", int(value))
        elif cmd == "fan_chamber":
            self._mqtt.set_fan("box_fan", int(value))
        elif cmd == "set_speed":
            self._mqtt.set_speed(int(value))
        elif cmd == "set_flow":
            self._mqtt.set_flow(int(value))
        elif cmd == "light":
            self._mqtt.set_light(bool(value))
        elif cmd == "motors_off":
            self._mqtt.motors_off()
        elif cmd == "jog":
            if isinstance(value, dict):
                self._mqtt.jog(value.get("axis", "X"), value.get("distance", 1.0))
        elif cmd == "home_all":
            self._mqtt.home("XYZ")
            # Habilita motores 10s após home — simples e direto, sem depender de axis/report
            QTimer.singleShot(10000, lambda: self._on_motors_state(True))
        elif cmd == "home_xy":
            self._mqtt.home("XY")
            QTimer.singleShot(10000, lambda: self._on_motors_state(True))
        elif cmd == "home_z":
            self._mqtt.home("Z")
        elif cmd == "emergency_stop":
            self._mqtt.stop_print()
        elif cmd == "print_start":
            if isinstance(value, dict):
                self._mqtt.start_print(
                    filename=value.get("task_name", "print.gcode"),
                    file_id=value.get("file_id", ""),
                    filepath=value.get("filepath", ""),
                    job=value,
                )
        elif cmd == "print_pause":
            self._mqtt.pause_print()
        elif cmd == "print_resume":
            self._mqtt.resume_print()
        elif cmd == "print_stop":
            self._mqtt.stop_print()
        elif cmd == "ace_auto_refill":
            self._mqtt.ace_auto_refill(bool(value))
        elif cmd == "ace_drying":
            if isinstance(value, dict):
                enabled = value.get("enabled", False)
                temp    = value.get("temp", 45)
                hours   = value.get("hours", 4)
                self._mqtt.ace_drying(enabled, target_temp=temp, duration=hours * 60)
            else:
                self._mqtt.ace_drying(bool(value))
        elif cmd == "ace_feed":
            slot = int(value) if value is not None else 0
            if hasattr(self._mqtt, 'ace_feed'):
                self._mqtt.ace_feed(slot)
        elif cmd == "ace_unfeed":
            slot = int(value) if value is not None else 0
            if hasattr(self._mqtt, 'ace_unfeed'):
                self._mqtt.ace_unfeed(slot)
        elif cmd == "ace_extrude":
            if isinstance(value, dict):
                slot = value.get("slot", 0)
                dist = value.get("distance", 10)
                if hasattr(self._mqtt, 'ace_extrude'):
                    self._mqtt.ace_extrude(slot, dist)
        elif cmd == "ace_retract":
            if isinstance(value, dict):
                slot = value.get("slot", 0)
                dist = value.get("distance", 10)
                if hasattr(self._mqtt, 'ace_retract'):
                    self._mqtt.ace_retract(slot, dist)
        elif cmd == "ace_set_slot":
            if hasattr(self._mqtt, 'ace_set_slot'):
                self._mqtt.ace_set_slot(int(value))
        elif cmd == "camera_start":
            self._mqtt.camera_start()
        elif cmd == "camera_stop":
            self._mqtt.camera_stop()
        elif cmd == "preheat":
            self._mqtt.set_temperature("hotbed", 60)
            self._mqtt.set_temperature("nozzle", 200)

    def _on_motors_state(self, enabled: bool):
        """Motores habilitados/desabilitados — atualiza UI de jog no ControlWidget."""
        if hasattr(self._control, "set_motors_enabled"):
            self._control.set_motors_enabled(enabled)

    def _on_print_error(self, code: int, msg: str):
        """Exibe popup de erro de impressão — uma única vez por código."""
        # Mensagens amigáveis para códigos conhecidos
        _known = {
            10107: (
                "⚠  FILAMENT NOT DETECTED",
                "The toolhead filament sensor did not detect any filament.\n\n"
                "Please check:\n"
                "  •  Filament is loaded and reaching the toolhead sensor\n"
                "  •  The ACE Pro is feeding correctly\n"
                "  •  There are no jams or tangles in the PTFE tube\n\n"
                "Load filament and try again."
            ),
            10133: (
                "⚠  MATERIAL / COLOR MISMATCH",
                "The printer rejected the print job due to a filament\n"
                "material or color mismatch with the ACE Pro slots.\n\n"
                "Please check:\n"
                "  •  The material type in each ACE Pro slot matches\n"
                "     what is configured in CONFIG → ACE Pro slots\n"
                "  •  The color mapping in the Print Setup screen\n"
                "     correctly maps each slicer slot to an ACE slot\n"
                "  •  Reconnect to the printer to refresh ACE slot data\n\n"
                "Update the slot configuration and try again."
            ),
        }
        title, detail = _known.get(code, (
            f"Print Error  (code {code})",
            f"The printer reported an error.\n\nCode: {code}\nMessage: {msg or '—'}"
        ))

        self._tray_show()
        dlg = QMessageBox(self)
        dlg.setWindowTitle(title)
        dlg.setIcon(QMessageBox.Icon.Warning)
        dlg.setText(f"<b style='font-family:Courier New'>{title}</b>")
        dlg.setInformativeText(detail)
        dlg.setStandardButtons(QMessageBox.StandardButton.Ok)
        dlg.setDefaultButton(QMessageBox.StandardButton.Ok)
        dlg.exec()

    def _do_disconnect(self):
        self._mqtt.disconnect_from_printer()

    # ── Navigation ─────────────────────────────────────────────────────────────
    def _on_brand_selected(self, brand_id: str):
        self._settings["printer_brand"] = brand_id
        settings_manager.save(self._settings)
        self._lbl_printer.setText(f"[  {brand_id.upper()}  ]")

        self._screen_login = LoginWidget(self._settings)
        self._screen_login.settings_saved.connect(self._on_settings_saved)
        self._screen_login.connect_requested.connect(self._on_connect_requested)
        self._screen_login.back_requested.connect(lambda: self._stack.setCurrentIndex(2))
        self._stack.removeWidget(self._stack.widget(1))
        self._stack.insertWidget(1, self._screen_login)

        ip = self._settings.get("printer_ip", "")
        self._stack.setCurrentIndex(2 if ip else 1)

    def _on_settings_saved(self, s: dict):
        self._settings = s
        settings_manager.save(s)
        # Atualiza URL da câmera no ControlWidget quando o IP mudar
        ip = s.get("printer_ip", "")
        if hasattr(self._control, "_cam_url"):
            self._control._cam_url = f"http://{ip}:18088/flv" if ip else ""
        if hasattr(self._control, "_cam_url_label"):
            self._control._cam_url_label.setText(
                self._control._cam_url or "— configure IP —"
            )

    def _on_connect_requested(self, s: dict):
        self._settings = s
        settings_manager.save(s)
        ip = s.get("printer_ip", "")
        if hasattr(self._control, "_cam_url"):
            self._control._cam_url = f"http://{ip}:18088/flv" if ip else ""
        if hasattr(self._control, "_cam_url_label"):
            self._control._cam_url_label.setText(
                self._control._cam_url or "— configure IP —"
            )
        self._stack.setCurrentIndex(2)
        self._do_connect()

    def _restore_state(self):
        ip   = self._settings.get("printer_ip", "")
        mode = self._settings.get("connection_mode", "cloud")

        self._mqtt = build_client(mode, self)
        self._wire_mqtt()

        if mode == "cloud" and self._settings.get("mqtt_user") and not self._settings.get("device_cert"):
            QTimer.singleShot(800, lambda: self._screen_login.append_log(
                "[AVISO] Certificado mTLS ausente. "
                "Vá em CONFIG → clique  [LOAD device_account.json]  para carregar o certificado."
            ))

        self._stack.setCurrentIndex(2)

        if ip:
            QTimer.singleShot(800, self._do_connect)

        # Timer de 1s para o display do botão de reconexão
        self._reconnect_display_timer = QTimer(self)
        self._reconnect_display_timer.setInterval(1000)
        self._reconnect_display_timer.timeout.connect(self._on_reconnect_tick)

        # Timer de 30s para refresh de status quando conectado
        self._status_refresh_timer = QTimer(self)
        self._status_refresh_timer.setInterval(30000)
        self._status_refresh_timer.timeout.connect(self._periodic_status_refresh)
        self._status_refresh_timer.start()



    def _periodic_status_refresh(self):
        if self._mqtt and self._mqtt.is_connected:
            try:
                self._mqtt.request_info()
            except Exception:
                pass

    def _start_reconnect_display(self):
        if not self._reconnect_display_timer.isActive():
            self._reconnect_countdown = 5
            self._reconnect_display_timer.start()
            self._update_reconnect_btn()
            # Desconecta handler atual e aponta para cancelar
            try:
                self._btn_reconnect.clicked.disconnect()
            except Exception:
                pass
            self._btn_reconnect.clicked.connect(self._cancel_auto_reconnect)

    def _stop_reconnect_display(self):
        self._reconnect_display_timer.stop()
        self._btn_reconnect.setText("CONNECT")
        self._btn_reconnect.setStyleSheet("""
            QPushButton { background:#003D52; border:1px solid #00E5FF; color:#00E5FF;
                          font-family:'Courier New'; font-size:10px; letter-spacing:1px;
                          border-radius:2px; padding:0 10px; }
            QPushButton:hover { background:#005070; }
        """)
        try:
            self._btn_reconnect.clicked.disconnect()
        except Exception:
            pass
        self._btn_reconnect.clicked.connect(self._do_connect)

    def _update_reconnect_btn(self):
        self._btn_reconnect.setText(f"RECONNECTING ({self._reconnect_countdown}s)")
        self._btn_reconnect.setStyleSheet("""
            QPushButton { background:#1A1000; border:1px solid #FFB300; color:#FFB300;
                          font-family:'Courier New'; font-size:10px; letter-spacing:1px;
                          border-radius:2px; padding:0 10px; }
            QPushButton:hover { background:#2A1800; }
        """)

    def _on_reconnect_tick(self):
        if self._auto_reconnect_stop or self._mqtt.is_connected:
            self._stop_reconnect_display()
            return

        self._reconnect_countdown -= 1
        self._update_reconnect_btn()

        if self._reconnect_countdown <= 0:
            # Tenta reconectar
            self._reconnect_attempt += 1
            ip = self._settings.get("printer_ip", "").strip()
            if ip:
                self._do_connect()

            # Mostra erro a cada 20 tentativas
            if self._reconnect_attempt % 20 == 0:
                self._on_mqtt_error(
                    f"Não foi possível reconectar após {self._reconnect_attempt} tentativas.\n\n"
                    f"IP: {ip}\nVerifique a impressora e a rede."
                )

            self._reconnect_countdown = 5

    def _cancel_auto_reconnect(self):
        self._auto_reconnect_stop = True
        self._chk_auto_reconnect.setChecked(False)
        self._stop_reconnect_display()

    def _on_auto_reconnect_toggled(self, checked: bool):
        if not checked:
            self._auto_reconnect_stop = True
            self._stop_reconnect_display()
        else:
            self._auto_reconnect_stop = False
            # Se já está desconectado, inicia imediatamente
            if self._mqtt and not self._mqtt.is_connected:
                self._reconnect_attempt   = 0
                self._reconnect_countdown = 5
                self._start_reconnect_display()


    # ── Helpers ────────────────────────────────────────────────────────────────
    def _set_status(self, state: str, log_msg: str = ""):
        styles = {
            "connecting":   ("● CONNECTING...", "#FFB300"),
            "connected":    ("● CONNECTED",     "#00FF88"),
            "idle":         ("● IDLE",          "#00FF88"),
            "busy":         ("● BUSY",          "#FFB300"),
            "error":        ("● ERROR",         "#FF4444"),
            "disconnected": ("○ DISCONNECTED",  "#FF4444"),
        }
        text, color = styles.get(state, ("○ DISCONNECTED", "#FF4444"))
        #self._lbl_conn.setText(text)
        #self._lbl_conn.setStyleSheet(
        #    f"color:{color}; font-family:'Courier New'; font-size:10px; letter-spacing:2px;"
        #)
        self._screen_login.set_connection_status(state, log_msg)

    @staticmethod
    def _format_eta(seconds: int) -> str:
        if not seconds:
            return "--"
        h, r = divmod(int(seconds), 3600)
        m, s = divmod(r, 60)
        if h:
            return f"{h}h {m:02d}m"
        return f"{m}h {s:02d}m"
