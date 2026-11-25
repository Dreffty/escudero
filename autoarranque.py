# Escudero 🛡 — abrir al iniciar sesión, como cualquier app de macOS.
# Usa SMAppService (macOS 13+): Escudero aparece en Ajustes → General → Ítems
# de inicio y se abre sola al encender el Mac, sin Terminal y sin icono en el
# Dock. Solo funciona con la app instalada (Escudero.app); desde el código
# fuente (`venv/bin/python escudero.py`) no hace nada.
import logging
import sys
from pathlib import Path

log = logging.getLogger("escudero.autoarranque")

_MARCA = ".autoarranque-configurado"


def _servicio():
    if not getattr(sys, "frozen", False):
        return None
    try:
        from ServiceManagement import SMAppService
        return SMAppService.mainAppService()
    except Exception:
        log.exception("ServiceManagement no disponible")
        return None


def disponible():
    return _servicio() is not None


def activado():
    s = _servicio()
    # SMAppServiceStatusEnabled == 1
    return s is not None and int(s.status()) == 1


def cambiar(encender):
    """Enciende o apaga el autoarranque y devuelve cómo ha quedado de verdad."""
    s = _servicio()
    if s is None:
        return False
    if encender:
        ok, err = s.registerAndReturnError_(None)
    else:
        ok, err = s.unregisterAndReturnError_(None)
    if not ok:
        log.warning("no pude %s el autoarranque: %s",
                    "activar" if encender else "quitar", err)
    return activado()


def activar_la_primera_vez(carpeta):
    """La primera vez que se abre la app instalada, se apunta sola a los ítems
    de inicio. Si luego lo quitas desde el menú, se respeta."""
    if not disponible():
        return
    marca = Path(carpeta) / _MARCA
    if marca.exists():
        return
    cambiar(True)
    try:
        marca.parent.mkdir(parents=True, exist_ok=True)
        marca.touch()
    except OSError:
        log.exception("no pude guardar la marca de autoarranque")
