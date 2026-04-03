# -*- coding: utf-8 -*-
"""Base interface — both clients must implement these methods/signals."""
from PyQt6.QtCore import QObject, pyqtSignal

class PrinterClientBase(QObject):
    connected        = pyqtSignal()
    disconnected     = pyqtSignal(str)
    connection_error = pyqtSignal(str)
    printer_info     = pyqtSignal(dict)
    print_report     = pyqtSignal(dict)
    device_id_found  = pyqtSignal(str)
    camera_stream    = pyqtSignal(str)   # emite URL do stream quando pronto
    motors_state     = pyqtSignal(bool)  # True = motores habilitados, False = desabilitados (precisa home)

    def connect_to_printer(self, **kwargs): raise NotImplementedError
    def disconnect_from_printer(self):      raise NotImplementedError
    def set_temperature(self, target, value): raise NotImplementedError
    def set_fan(self, fan, value):           raise NotImplementedError
    def set_speed(self, mode):               raise NotImplementedError
    def set_light(self, on):                 raise NotImplementedError
    def jog(self, axis, distance):           raise NotImplementedError
    def home(self, axes="XYZ"):              raise NotImplementedError
    def emergency_stop(self):                raise NotImplementedError
    def print_start(self, filename, **kw):   raise NotImplementedError
    def print_pause(self):                   raise NotImplementedError
    def print_resume(self):                  raise NotImplementedError
    def print_stop(self):                    raise NotImplementedError
    def request_info(self):                  raise NotImplementedError

    @property
    def is_connected(self) -> bool: return False
    @property
    def device_id(self) -> str:     return ""
