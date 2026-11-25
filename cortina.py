# Cortina — el módulo "Bartender/Ice" de Escudero: esconde los iconos de la
# barra de menús que no quieres ver. El truco (el mismo de Hidden Bar/Dozer):
# ponemos un separador ❘ y una flecha ‹ en la barra; al ocultar, el separador
# se ensancha muchísimo y EMPUJA fuera de pantalla todo lo que esté a su
# izquierda. Colocación: ⌘-arrastra los iconos que quieras esconder a la
# IZQUIERDA del ❘. Cero permisos, API pública.

import logging
import time

log = logging.getLogger("escudero.cortina")

try:
    import objc
    from AppKit import NSStatusBar, NSVariableStatusItemLength
    from Foundation import NSObject

    class _Blanco(NSObject):
        """Receptor objc para el clic de la flecha."""
        def setCallback_(self, cb):
            self._cb = cb

        def pulsado_(self, _sender):
            cb = getattr(self, "_cb", None)
            if cb:
                cb()

    _APPKIT = True
except Exception:
    _APPKIT = False

ANCHO_OCULTAR = 10000.0
ANCHO_SEP = 10.0


class Cortina:
    def __init__(self, cfg):
        c = cfg.get("cortina", {}) or {}
        self.activada = bool(c.get("activada", True))
        self.auto_seg = int(c.get("auto_ocultar_seg", 15))
        self.oculta = True            # estado deseado; se aplica al montar
        self.mostrada_hasta = 0.0     # para el auto-ocultar
        self._sep = self._flecha = self._blanco = None

    @property
    def montada(self):
        return self._sep is not None

    def montar(self, oculta_inicial=True):
        """Crear los dos items en la barra. Llamar DESPUÉS de que exista el
        escudo de rumps, para que queden a su izquierda."""
        if not (self.activada and _APPKIT) or self._sep is not None:
            return
        try:
            barra = NSStatusBar.systemStatusBar()
            # flecha primero (queda pegada al escudo), separador después (más a la izquierda)
            self._flecha = barra.statusItemWithLength_(NSVariableStatusItemLength)
            self._blanco = _Blanco.alloc().init()
            self._blanco.setCallback_(self.alternar)
            boton = self._flecha.button()
            self._img_abrir, self._img_cerrar = self._simbolos_chevron()
            if self._img_cerrar is not None:
                boton.setImage_(self._img_cerrar)
            else:
                boton.setTitle_("‹")
            boton.setTarget_(self._blanco)
            boton.setAction_("pulsado:")
            self._flecha.setAutosaveName_("escudero-cortina-flecha")

            self._sep = barra.statusItemWithLength_(ANCHO_SEP)
            self._sep.button().setTitle_("❘")
            self._sep.setAutosaveName_("escudero-cortina-sep")

            self.poner(oculta_inicial)
            log.info("cortina montada (⌘-arrastra iconos a la izquierda del ❘)")
        except Exception:
            log.exception("no pude montar la cortina")
            self._sep = self._flecha = None

    @staticmethod
    def _simbolos_chevron():
        """(abrir ›, cerrar ‹) como SF Symbols template; None si no hay AppKit moderno."""
        try:
            from AppKit import NSImage
            imgs = []
            for nombre in ("chevron.right", "chevron.left"):
                img = NSImage.imageWithSystemSymbolName_accessibilityDescription_(nombre, None)
                if img is None:
                    return None, None
                img.setTemplate_(True)
                imgs.append(img)
            return imgs[0], imgs[1]
        except Exception:
            return None, None

    def _pinta_flecha(self, oculta):
        boton = self._flecha.button()
        img = self._img_abrir if oculta else self._img_cerrar
        if img is not None:
            boton.setImage_(img)
        else:
            boton.setTitle_("›" if oculta else "‹")

    def poner(self, oculta):
        """oculta=True → el separador se ensancha y esconde lo de su izquierda."""
        self.oculta = bool(oculta)
        if not self._sep:
            return
        try:
            self._sep.setLength_(ANCHO_OCULTAR if self.oculta else ANCHO_SEP)
            self._pinta_flecha(self.oculta)
            if not self.oculta:
                self.mostrada_hasta = time.time() + self.auto_seg if self.auto_seg else 0.0
        except Exception:
            log.exception("fallo poniendo la cortina")

    def alternar(self):
        self.poner(not self.oculta)

    def tick(self):
        """Auto-ocultar: si lleva mostrada más de auto_ocultar_seg, recoger."""
        if (self._sep and not self.oculta and self.auto_seg
                and self.mostrada_hasta and time.time() >= self.mostrada_hasta):
            self.poner(True)

    def parar(self):
        if not _APPKIT:
            return
        try:
            barra = NSStatusBar.systemStatusBar()
            for item in (self._sep, self._flecha):
                if item is not None:
                    barra.removeStatusItem_(item)
        except Exception:
            pass
        self._sep = self._flecha = None
