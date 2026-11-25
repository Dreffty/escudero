# EventBus interno de Escudero (Fase 2.3): comunicación entre módulos sin
# acoplarlos. Sincrónico y tolerante a fallos: un listener que explota se
# registra en el log y NO rompe al emisor ni al resto de listeners.
#
# Eventos definidos hoy (payloads dict):
#   "ordenar_movidos"  Ordenar → {n, pasada_id}           core: guarda el estado
#   "foco_cambiado"    Foco    → {texto}

import logging

log = logging.getLogger("escudero.bus")


class EventBus:
    def __init__(self):
        self._listeners = {}

    def on(self, evento, listener):
        """Suscribe listener(payload) al evento. Devuelve el propio listener."""
        self._listeners.setdefault(evento, []).append(listener)
        return listener

    def off(self, evento, listener):
        try:
            self._listeners.get(evento, []).remove(listener)
        except ValueError:
            pass

    def emit(self, evento, payload=None):
        """Emite un evento. Nunca lanza: errores de listeners solo al log."""
        for listener in list(self._listeners.get(evento, [])):
            try:
                listener(payload or {})
            except Exception:
                log.exception("listener de %r falló", evento)
