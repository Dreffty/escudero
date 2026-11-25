# Ventanas — el módulo "Rectangle" de Escudero: encajar la ventana frontal
# (mitades, maximizar, centrar) con atajos globales ⌃⌥ o desde el menú.
# Los atajos son de Carbon (atajos.py): no piden Monitorización de Entrada.
# La pantalla objetivo es LA QUE TIENE EL PUNTERO. El movimiento va por la
# API de Accesibilidad directa (AXUIElement) — sin osascript ni permiso de
# Automatización: solo necesita Accesibilidad, el mismo que usa Crónica.

import logging
import os
import subprocess
import threading

log = logging.getLogger("escudero.ventanas")

try:
    from AppKit import NSEvent, NSScreen, NSWorkspace
    import Quartz
except Exception:
    NSEvent = NSScreen = NSWorkspace = Quartz = None

try:
    from ApplicationServices import (AXUIElementCopyAttributeValue,
                                     AXUIElementCreateApplication,
                                     AXUIElementSetAttributeValue, AXValueCreate,
                                     kAXValueCGPointType, kAXValueCGSizeType)
    _AX = True
except Exception:
    _AX = False

ACCIONES = ("izquierda", "derecha", "arriba", "abajo", "maximizar", "centrar")


# ── geometría pura (testeable) ───────────────────────────────────────────
def calcular_rect(accion, vis):
    """vis y resultado: (x, y, w, h) en coords Cocoa (origen abajo-izquierda)."""
    x, y, w, h = vis
    if accion == "izquierda":
        return (x, y, w / 2, h)
    if accion == "derecha":
        return (x + w / 2, y, w / 2, h)
    if accion == "arriba":
        return (x, y + h / 2, w, h / 2)
    if accion == "abajo":
        return (x, y, w, h / 2)
    if accion == "maximizar":
        return (x, y, w, h)
    if accion == "centrar":
        return (x + w * 0.15, y + h * 0.15, w * 0.7, h * 0.7)
    raise ValueError(f"acción desconocida: {accion}")


def a_coords_pantalla(rect_ns, alto_primario):
    """Cocoa (origen abajo-izq) → AX (origen arriba-izq global)."""
    x, y, w, h = rect_ns
    return (x, alto_primario - (y + h), w, h)


class Ventanas:
    def __init__(self, cfg, notificar):
        v = cfg.get("ventanas", {}) or {}
        self.atajos_on = bool(v.get("atajos", True))
        self.notificar = notificar
        self._atajos = []

    # ── elegir ventana y pantalla ────────────────────────────────────────
    def _pid_frontal(self):
        """PID de la app frontal, saltándose a Escudero mismo (sus diálogos
        y menú pueden hacerle figurar como frontal)."""
        fr = NSWorkspace.sharedWorkspace().frontmostApplication()
        pid = int(fr.processIdentifier()) if fr else 0
        if pid and pid != os.getpid():
            return pid
        ops = (Quartz.kCGWindowListOptionOnScreenOnly
               | Quartz.kCGWindowListExcludeDesktopElements)
        for info in Quartz.CGWindowListCopyWindowInfo(ops, Quartz.kCGNullWindowID) or []:
            if (info.get("kCGWindowLayer", 1) == 0
                    and int(info.get("kCGWindowOwnerPID", 0)) != os.getpid()):
                return int(info["kCGWindowOwnerPID"])
        return 0

    def _ventana_frontal(self):
        pid = self._pid_frontal()
        if not pid:
            return None
        app = AXUIElementCreateApplication(pid)
        err, win = AXUIElementCopyAttributeValue(app, "AXFocusedWindow", None)
        if err or win is None:
            err, wins = AXUIElementCopyAttributeValue(app, "AXWindows", None)
            win = wins[0] if (not err and wins and len(wins)) else None
        return win

    def _pantalla_del_raton(self):
        raton = NSEvent.mouseLocation()
        for p in NSScreen.screens():
            f = p.frame()
            if (f.origin.x <= raton.x <= f.origin.x + f.size.width and
                    f.origin.y <= raton.y <= f.origin.y + f.size.height):
                return p
        return NSScreen.mainScreen() or NSScreen.screens()[0]

    # ── la acción ────────────────────────────────────────────────────────
    def encajar(self, accion):
        """Mueve la ventana frontal a la posición `accion` en la pantalla del puntero."""
        if NSScreen is None or not _AX:
            log.warning("ventanas: AX/AppKit no disponibles")
            return False
        try:
            win = self._ventana_frontal()
            if win is None:
                self.notificar("🪟 Ventanas", "No encuentro la ventana frontal "
                               "(¿falta el permiso de Accesibilidad de «Escudero»?).")
                return False
            vis = self._pantalla_del_raton().visibleFrame()
            rect = calcular_rect(accion, (vis.origin.x, vis.origin.y,
                                          vis.size.width, vis.size.height))
            alto_prim = NSScreen.screens()[0].frame().size.height
            x, y, w, h = a_coords_pantalla(rect, alto_prim)
            pos = AXValueCreate(kAXValueCGPointType, Quartz.CGPoint(x=x, y=y))
            tam = AXValueCreate(kAXValueCGSizeType, Quartz.CGSize(width=w, height=h))
            e1 = AXUIElementSetAttributeValue(win, "AXPosition", pos)
            e2 = AXUIElementSetAttributeValue(win, "AXSize", tam)
            AXUIElementSetAttributeValue(win, "AXPosition", pos)  # 2º empujón (truco Rectangle)
            if e1 or e2:
                log.warning("ventanas [%s]: AXError pos=%s tam=%s", accion, e1, e2)
                self.notificar("🪟 Ventanas", "Sin permiso: activa «Escudero» en Ajustes → "
                               "Privacidad y seguridad → Accesibilidad, y reinícialo.")
                return False
            return True
        except Exception:
            log.exception("fallo encajando ventana")
            return False

    # ── atajos globales (Carbon: sin Monitorización de Entrada) ─────────
    ATAJOS = {"ctrl+opt+izquierda": "izquierda", "ctrl+opt+derecha": "derecha",
              "ctrl+opt+arriba": "arriba", "ctrl+opt+abajo": "abajo",
              "ctrl+opt+enter": "maximizar", "ctrl+opt+c": "centrar"}

    def arrancar_atajos(self):
        """⌃⌥ ←→↑↓ ⏎ C desde cualquier app. Antes iban con pynput, que necesita
        «Monitorización de Entrada» y, sin ella, se activaba sin hacer nada."""
        if not self.atajos_on:
            return
        try:
            from atajos import AtajoGlobal
        except Exception:
            log.warning("atajos globales no disponibles: ventanas solo desde el menú")
            return
        self._atajos = []
        fallidos = []
        for combinacion, accion in self.ATAJOS.items():
            atajo = AtajoGlobal(lambda a=accion: threading.Thread(
                target=self.encajar, args=(a,), daemon=True).start())
            ok, detalle = atajo.registrar(combinacion)
            if ok:
                self._atajos.append(atajo)
            else:
                fallidos.append(f"{combinacion} ({detalle})")
        log.info("atajos de ventanas activos: %d de %d%s", len(self._atajos), len(self.ATAJOS),
                 f" · no disponibles: {', '.join(fallidos)}" if fallidos else "")

    def parar(self):
        for atajo in getattr(self, "_atajos", []):
            atajo.quitar()
        self._atajos = []
