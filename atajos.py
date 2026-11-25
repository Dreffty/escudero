# Atajos de teclado globales para Escudero (⌃⌥V el buscador, ⌃⌥T el lector…).
# RegisterEventHotKey de Carbon, como Maccy o Raycast: no pide Monitorización de
# Entrada, y macOS se traga la pulsación (no llega a la app de delante).
#
# Varios atajos comparten la misma cola de eventos de la app: cada uno lleva su
# número y solo responde al suyo, devolviendo el resto a los demás manejadores.

import ctypes
import itertools
import logging

from pergamino import parsear_atajo

log = logging.getLogger("escudero.atajos")

try:
    from PyObjCTools import AppHelper
except Exception:          # tests sin PyObjC
    AppHelper = None


class _EventHotKeyID(ctypes.Structure):
    _fields_ = [("signature", ctypes.c_uint32), ("id", ctypes.c_uint32)]


class _EventTypeSpec(ctypes.Structure):
    _fields_ = [("eventClass", ctypes.c_uint32), ("eventKind", ctypes.c_uint32)]


_MANEJADOR = ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.c_void_p, ctypes.c_void_p,
                              ctypes.c_void_p)
_NO_ES_MIO = -9874          # eventNotHandledErr: que lo mire el siguiente manejador
_FIRMA = "ESCD"
_numeros = itertools.count(1)


def _cuatro(letras):
    return int.from_bytes(letras.encode("ascii"), "big")


_carbon = None


def _cargar_carbon():
    global _carbon
    if _carbon is None:
        c = ctypes.CDLL("/System/Library/Frameworks/Carbon.framework/Carbon")
        c.GetApplicationEventTarget.restype = ctypes.c_void_p
        c.InstallEventHandler.argtypes = [
            ctypes.c_void_p, _MANEJADOR, ctypes.c_ulong,
            ctypes.POINTER(_EventTypeSpec), ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_void_p)]
        c.InstallEventHandler.restype = ctypes.c_int32
        c.RegisterEventHotKey.argtypes = [
            ctypes.c_uint32, ctypes.c_uint32, _EventHotKeyID, ctypes.c_void_p,
            ctypes.c_uint32, ctypes.POINTER(ctypes.c_void_p)]
        c.RegisterEventHotKey.restype = ctypes.c_int32
        c.UnregisterEventHotKey.argtypes = [ctypes.c_void_p]
        c.UnregisterEventHotKey.restype = ctypes.c_int32
        c.GetEventParameter.argtypes = [
            ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p,
            ctypes.c_ulong, ctypes.c_void_p, ctypes.c_void_p]
        c.GetEventParameter.restype = ctypes.c_int32
        _carbon = c
    return _carbon


class AtajoGlobal:
    """Un atajo que funciona desde cualquier app y avisa en el hilo principal."""

    def __init__(self, accion):
        self.accion = accion
        self.etiqueta = ""
        self.numero = next(_numeros)
        self._cb = None
        self._ref = ctypes.c_void_p()
        self._manejador = ctypes.c_void_p()

    def registrar(self, texto_atajo):
        """Devuelve (ok, etiqueta o motivo del fallo)."""
        self.quitar()
        try:
            codigo, mascara, etiqueta = parsear_atajo(texto_atajo)
        except ValueError as e:
            return False, str(e)
        try:
            c = _cargar_carbon()
            destino = c.GetApplicationEventTarget()
            if self._cb is None:                       # el manejador, una sola vez
                cb = _MANEJADOR(self._al_pulsar)
                tipo = _EventTypeSpec(_cuatro("keyb"), 5)   # kEventHotKeyPressed
                err = c.InstallEventHandler(destino, cb, 1, ctypes.byref(tipo), None,
                                            ctypes.byref(self._manejador))
                if err:
                    return False, f"macOS no aceptó el manejador del atajo ({err})"
                self._cb = cb                          # que el GC no se lo lleve
            err = c.RegisterEventHotKey(codigo, mascara, _EventHotKeyID(_cuatro(_FIRMA), self.numero),
                                        destino, 0, ctypes.byref(self._ref))
            if err:
                self._ref = ctypes.c_void_p()
                return False, f"{etiqueta} ya lo usa otra app"
            self.etiqueta = etiqueta
            log.info("atajo %s registrado (n.º %s)", etiqueta, self.numero)
            return True, etiqueta
        except Exception as e:
            log.exception("no pude registrar el atajo")
            return False, str(e)

    def quitar(self):
        if self._ref.value and _carbon is not None:
            _carbon.UnregisterEventHotKey(self._ref)
        self._ref = ctypes.c_void_p()
        self.etiqueta = ""

    @staticmethod
    def _numero_pulsado(evento):
        """Qué atajo trae el evento (kEventParamDirectObject, typeEventHotKeyID)."""
        hk = _EventHotKeyID()
        err = _cargar_carbon().GetEventParameter(
            evento, _cuatro("----"), _cuatro("hkid"), None,
            ctypes.sizeof(hk), None, ctypes.byref(hk))
        if err or hk.signature != _cuatro(_FIRMA):
            return None
        return hk.id

    def _al_pulsar(self, _siguiente, evento, _datos):
        try:
            if self._numero_pulsado(evento) != self.numero:
                return _NO_ES_MIO
            if AppHelper is not None:
                AppHelper.callAfter(self.accion)
            else:
                self.accion()
        except Exception:
            log.exception("fallo atendiendo un atajo")
        return 0
