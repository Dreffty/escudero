# Buscador de Pergamino — el panel estilo Spotlight/Maccy de Escudero.
#   ⌃⌥V (configurable) desde cualquier app abre un panel con el historial.
#   Escribe para filtrar · ↑↓ elegir · ⏎ o clic pegar · ⌘1–9 pegar ese
#   · ⌘⌫ olvidar el recorte · esc borra la búsqueda y, si ya está vacía, cierra.
#
# El panel NO activa Escudero: la app donde escribías sigue delante, así que al
# cerrarlo el ⌘V que mandamos cae en el mismo campo. El atajo es un hot key de
# Carbon (como Maccy o Raycast): no necesita Monitorización de Entrada. Pegar
# solo sí necesita Accesibilidad (la misma de Crónica); sin ella, copia y avisa.

import logging

from atajos import AtajoGlobal
from pergamino import hace

log = logging.getLogger("escudero.pergamino.buscador")

try:
    import objc
    import Quartz
    from AppKit import (NSApplication, NSBackingStoreBuffered, NSBox, NSBoxSeparator,
                        NSColor, NSEvent, NSFont, NSImage, NSImageSymbolConfiguration,
                        NSImageView, NSPanel, NSScreen, NSScrollView, NSTableCellView,
                        NSTableColumn, NSTableRowView, NSTableView, NSTextField,
                        NSView, NSVisualEffectView)
    from Foundation import NSMakeRect, NSObject, NSPointInRect
    from PyObjCTools import AppHelper
    _APPKIT = True
except Exception:          # tests y CLI sin AppKit
    _APPKIT = False

ANCHO, ALTO = 660, 460
ALTO_CABECERA = 58
ALTO_PIE = 32
ALTO_FILA = 34
TECLA_V = 9

# Constantes de AppKit por valor: cambian poco y así no dependemos de la versión
# exacta de PyObjC para importarlas.
_MASCARA_PANEL = 128 | (1 << 15)          # NonactivatingPanel | FullSizeContentView
_ESTILO_INSET = 2                          # NSTableViewStyleInset
_FONDO_RESALTADO = 1                       # NSBackgroundStyleEmphasized
_ANCHO_FLEX, _ALTO_FLEX, _MARGEN_IZQ = 2, 16, 1
_TODOS_LOS_ESCRITORIOS = 1 | 256           # CanJoinAllSpaces | FullScreenAuxiliary
_CMD = 1 << 20


# ── pegar en la app de delante ──────────────────────────────────────────
def accesibilidad_ok():
    try:
        from ApplicationServices import AXIsProcessTrusted
        return bool(AXIsProcessTrusted())
    except Exception:
        return False


def pegar_en_app_activa():
    """Pulsa ⌘V por ti en la app que tiene el foco."""
    fuente = Quartz.CGEventSourceCreate(Quartz.kCGEventSourceStateCombinedSessionState)
    for pulsada in (True, False):
        ev = Quartz.CGEventCreateKeyboardEvent(fuente, TECLA_V, pulsada)
        Quartz.CGEventSetFlags(ev, Quartz.kCGEventFlagMaskCommand)
        Quartz.CGEventPost(Quartz.kCGAnnotatedSessionEventTap, ev)


def _una_linea(texto, maximo=240):
    return " ".join(str(texto).split())[:maximo]


def _detalle(entrada):
    trozos = [entrada.get("app") or "", hace(entrada.get("ts"))]
    lineas = str(entrada["texto"]).count("\n") + 1
    if lineas > 1:
        trozos.append(f"{lineas} líneas")
    return " · ".join(t for t in trozos if t)


# ── el panel ────────────────────────────────────────────────────────────
if _APPKIT:

    class EscuderoPanelPergamino(NSPanel):
        """Panel sin bordes que recibe el teclado sin activar Escudero."""

        def canBecomeKeyWindow(self):
            return True

        def canBecomeMainWindow(self):
            return False

        def performKeyEquivalent_(self, evento):
            ctrl = self.delegate()
            try:
                if ctrl is not None and ctrl.tecla_con_comando(evento):
                    return True
            except Exception:
                log.exception("fallo con un atajo del buscador")
            return objc.super(EscuderoPanelPergamino, self).performKeyEquivalent_(evento)

    class EscuderoFilaPergamino(NSTableRowView):
        # Escudero nunca está «activa» (el foco es de tu app): sin esto, la
        # fila elegida se pintaría en gris apagado en vez del color de acento.
        def isEmphasized(self):
            return True

    class EscuderoCeldaPergamino(NSTableCellView):
        def setBackgroundStyle_(self, estilo):
            objc.super(EscuderoCeldaPergamino, self).setBackgroundStyle_(estilo)
            elegida = estilo == _FONDO_RESALTADO
            blanco = NSColor.alternateSelectedControlTextColor()
            self.texto.setTextColor_(blanco if elegida else NSColor.labelColor())
            self.detalle.setTextColor_(
                blanco.colorWithAlphaComponent_(0.8) if elegida
                else NSColor.secondaryLabelColor())
            self.atajo.setTextColor_(
                blanco.colorWithAlphaComponent_(0.8) if elegida
                else NSColor.tertiaryLabelColor())

    def _etiqueta(tamano, peso=0.0, alineacion=0):
        campo = NSTextField.labelWithString_("")
        campo.setFont_(NSFont.systemFontOfSize_weight_(tamano, peso))
        campo.setLineBreakMode_(4)                 # truncar al final con «…»
        campo.cell().setUsesSingleLineMode_(True)
        campo.setAlignment_(alineacion)
        return campo

    class EscuderoControladorPergamino(NSObject):
        """Datos, teclado y ratón del buscador (y delegado de todo)."""

        @objc.python_method
        def configurar(self, pergamino, avisar, pegar_directo):
            self.pergamino = pergamino
            self.avisar = avisar
            self.pegar_directo = pegar_directo
            self.resultados = []
            self.panel = None
            self._aviso_permiso_dado = False
            return self

        # ── construcción ────────────────────────────────────────────
        @objc.python_method
        def construir(self):
            panel = EscuderoPanelPergamino.alloc().initWithContentRect_styleMask_backing_defer_(
                NSMakeRect(0, 0, ANCHO, ALTO), _MASCARA_PANEL, NSBackingStoreBuffered, False)
            panel.setFloatingPanel_(True)
            panel.setLevel_(101)                       # por encima de menús y pantalla completa
            panel.setHidesOnDeactivate_(False)
            panel.setBecomesKeyOnlyIfNeeded_(False)
            panel.setCollectionBehavior_(_TODOS_LOS_ESCRITORIOS)
            panel.setOpaque_(False)
            panel.setBackgroundColor_(NSColor.clearColor())
            panel.setHasShadow_(True)
            panel.setTitlebarAppearsTransparent_(True)
            panel.setTitleVisibility_(1)               # sin título
            panel.setMovableByWindowBackground_(True)
            panel.setReleasedWhenClosed_(False)
            for boton in (0, 1, 2):                    # sin semáforo
                b = panel.standardWindowButton_(boton)
                if b is not None:
                    b.setHidden_(True)
            panel.setDelegate_(self)

            marco = NSMakeRect(0, 0, ANCHO, ALTO)
            contenido = NSView.alloc().initWithFrame_(marco)
            self._montar_cabecera(contenido)
            self._montar_lista(contenido)
            self._montar_pie(contenido)
            panel.setContentView_(self._fondo(marco, contenido))
            self.panel = panel

        @objc.python_method
        def _fondo(self, marco, contenido):
            """Liquid Glass en macOS 26; cristal esmerilado en versiones anteriores."""
            try:
                cristal = objc.lookUpClass("NSGlassEffectView").alloc().initWithFrame_(marco)
                cristal.setCornerRadius_(22)
                cristal.setContentView_(contenido)
                return cristal
            except Exception:
                fondo = NSVisualEffectView.alloc().initWithFrame_(marco)
                fondo.setMaterial_(6)                  # popover
                fondo.setBlendingMode_(0)
                fondo.setState_(1)
                fondo.setWantsLayer_(True)
                fondo.layer().setCornerRadius_(16)
                fondo.layer().setMasksToBounds_(True)
                contenido.setFrame_(marco)
                fondo.addSubview_(contenido)
                return fondo

        @objc.python_method
        def _montar_cabecera(self, vista):
            y = ALTO - ALTO_CABECERA
            lupa = NSImageView.alloc().initWithFrame_(NSMakeRect(22, y + 17, 24, 24))
            imagen = NSImage.imageWithSystemSymbolName_accessibilityDescription_(
                "magnifyingglass", "Buscar")
            if imagen is not None:
                conf = NSImageSymbolConfiguration.configurationWithPointSize_weight_(19, 0.0)
                lupa.setImage_(imagen.imageWithSymbolConfiguration_(conf))
                lupa.setContentTintColor_(NSColor.secondaryLabelColor())
            vista.addSubview_(lupa)

            campo = NSTextField.alloc().initWithFrame_(NSMakeRect(56, y + 14, ANCHO - 76, 30))
            campo.setBezeled_(False)
            campo.setDrawsBackground_(False)
            campo.setEditable_(True)
            campo.setSelectable_(True)
            campo.setFocusRingType_(1)                 # sin anillo azul
            campo.setFont_(NSFont.systemFontOfSize_weight_(22, -0.2))
            campo.setPlaceholderString_("Buscar en lo que has copiado")
            campo.cell().setUsesSingleLineMode_(True)
            campo.cell().setScrollable_(True)
            campo.setDelegate_(self)
            vista.addSubview_(campo)
            self.campo = campo

            raya = NSBox.alloc().initWithFrame_(NSMakeRect(0, y, ANCHO, 1))
            raya.setBoxType_(NSBoxSeparator)
            vista.addSubview_(raya)

        @objc.python_method
        def _montar_lista(self, vista):
            alto = ALTO - ALTO_CABECERA - ALTO_PIE - 2
            scroll = NSScrollView.alloc().initWithFrame_(NSMakeRect(0, ALTO_PIE + 1, ANCHO, alto))
            scroll.setDrawsBackground_(False)
            scroll.contentView().setDrawsBackground_(False)
            scroll.setHasVerticalScroller_(True)
            scroll.setAutohidesScrollers_(True)
            scroll.setBorderType_(0)

            tabla = NSTableView.alloc().initWithFrame_(scroll.bounds())
            columna = NSTableColumn.alloc().initWithIdentifier_("fila")
            columna.setWidth_(ANCHO - 24)
            tabla.addTableColumn_(columna)
            tabla.setHeaderView_(None)
            tabla.setStyle_(_ESTILO_INSET)
            tabla.setRowHeight_(ALTO_FILA)
            tabla.setBackgroundColor_(NSColor.clearColor())
            tabla.setRefusesFirstResponder_(True)      # el teclado, siempre en la búsqueda
            tabla.setDataSource_(self)
            tabla.setDelegate_(self)
            tabla.setTarget_(self)
            tabla.setAction_("clic:")
            scroll.setDocumentView_(tabla)
            tabla.sizeLastColumnToFit()
            vista.addSubview_(scroll)
            self.tabla = tabla

            vacio = _etiqueta(14, 0.0, 1)
            vacio.setFrame_(NSMakeRect(40, ALTO_PIE + alto / 2 - 10, ANCHO - 80, 22))
            vacio.setTextColor_(NSColor.secondaryLabelColor())
            vacio.setHidden_(True)
            vista.addSubview_(vacio)
            self.vacio = vacio

        @objc.python_method
        def _montar_pie(self, vista):
            raya = NSBox.alloc().initWithFrame_(NSMakeRect(0, ALTO_PIE, ANCHO, 1))
            raya.setBoxType_(NSBoxSeparator)
            vista.addSubview_(raya)
            self.ayuda = _etiqueta(11.5)
            self.ayuda.setFrame_(NSMakeRect(20, 9, ANCHO - 190, 15))
            self.ayuda.setTextColor_(NSColor.secondaryLabelColor())
            vista.addSubview_(self.ayuda)
            self.cuenta = _etiqueta(11.5, 0.0, 2)
            self.cuenta.setFrame_(NSMakeRect(ANCHO - 170, 9, 150, 15))
            self.cuenta.setTextColor_(NSColor.tertiaryLabelColor())
            vista.addSubview_(self.cuenta)

        # ── mostrar / ocultar ───────────────────────────────────────
        @objc.python_method
        def mostrar(self):
            if self.panel is None:
                self.construir()
            self.campo.setStringValue_("")
            self.filtrar(conservar=False)
            self._pintar_ayuda()
            self._colocar()
            self.panel.makeKeyAndOrderFront_(None)
            self.panel.makeFirstResponder_(self.campo)
            self.panel.invalidateShadow()

        @objc.python_method
        def ocultar(self):
            if self.panel is not None and self.panel.isVisible():
                self.panel.orderOut_(None)

        @objc.python_method
        def visible(self):
            return self.panel is not None and bool(self.panel.isVisible())

        @objc.python_method
        def _colocar(self):
            """En la pantalla del ratón, a un tercio de altura (como Spotlight)."""
            raton = NSEvent.mouseLocation()
            pantalla = next((p for p in NSScreen.screens() if NSPointInRect(raton, p.frame())),
                            NSScreen.mainScreen())
            zona = pantalla.visibleFrame()
            x = zona.origin.x + (zona.size.width - ANCHO) / 2
            y = zona.origin.y + zona.size.height * 0.80 - ALTO
            self.panel.setFrameOrigin_((round(x), round(max(zona.origin.y, y))))

        @objc.python_method
        def _pintar_ayuda(self):
            if self.pegar_directo and accesibilidad_ok():
                self.ayuda.setStringValue_("↩ pegar   ⌘1–9 pegar ese   ⌘⌫ olvidar   esc cerrar")
            elif self.pegar_directo:
                self.ayuda.setStringValue_(
                    "↩ copiar · para pegar solo, da Accesibilidad a Escudero")
            else:
                self.ayuda.setStringValue_("↩ copiar   ⌘1–9 copiar ese   ⌘⌫ olvidar   esc cerrar")

        # ── datos ───────────────────────────────────────────────────
        @objc.python_method
        def filtrar(self, conservar=True):
            elegido = self._elegido() if conservar else None
            consulta = str(self.campo.stringValue() or "")
            self.resultados = self.pergamino.buscar(consulta)
            self.tabla.reloadData()
            total = len(self.pergamino.historial)
            if not total:
                self.vacio.setStringValue_("Todavía no has copiado nada. Copia algo con ⌘C.")
            else:
                self.vacio.setStringValue_(f"Nada coincide con «{consulta.strip()}»")
            self.vacio.setHidden_(bool(self.resultados))
            if consulta.strip():
                self.cuenta.setStringValue_(f"{len(self.resultados)} de {total}")
            else:
                self.cuenta.setStringValue_(f"{total} recorte{'s' if total != 1 else ''}")
            fila = 0
            if elegido is not None:
                fila = next((i for i, e in enumerate(self.resultados)
                             if e["texto"] == elegido), 0)
            self._seleccionar(fila)

        @objc.python_method
        def refrescar(self):
            if self.visible():
                self.filtrar(conservar=True)

        @objc.python_method
        def _elegido(self):
            fila = self.tabla.selectedRow()
            if 0 <= fila < len(self.resultados):
                return self.resultados[fila]["texto"]
            return None

        @objc.python_method
        def _seleccionar(self, fila):
            if not self.resultados:
                self.tabla.deselectAll_(None)
                return
            fila = max(0, min(fila, len(self.resultados) - 1))
            from AppKit import NSIndexSet
            self.tabla.selectRowIndexes_byExtendingSelection_(
                NSIndexSet.indexSetWithIndex_(fila), False)
            self.tabla.scrollRowToVisible_(fila)

        # ── acciones ────────────────────────────────────────────────
        @objc.python_method
        def elegir(self, fila):
            if not 0 <= fila < len(self.resultados):
                return
            texto = self.resultados[fila]["texto"]
            ok = self.pergamino.restaurar(texto)
            self.ocultar()
            if not ok:
                self.avisar("📋 Pergamino", "No pude dejarlo en el portapapeles.")
                return
            if self.pegar_directo and accesibilidad_ok():
                # Un respiro para que macOS devuelva el foco a tu campo.
                AppHelper.callLater(0.06, pegar_en_app_activa)
            elif self.pegar_directo and not self._aviso_permiso_dado:
                self._aviso_permiso_dado = True
                self.avisar("📋 Pergamino",
                            "Copiado: pulsa ⌘V. Para que pegue solo, da Accesibilidad "
                            "a Escudero en Ajustes → Privacidad y seguridad.")
            else:
                self.avisar("📋 Pergamino", "Copiado: pulsa ⌘V para pegarlo.")

        @objc.python_method
        def olvidar_elegido(self):
            fila = self.tabla.selectedRow()
            elegido = self._elegido()
            if elegido is None:
                return
            self.pergamino.olvidar(elegido)
            self.filtrar(conservar=False)
            self._seleccionar(fila)                    # se queda donde estaba

        @objc.python_method
        def mover(self, salto):
            if self.resultados:
                self._seleccionar(self.tabla.selectedRow() + salto)

        @objc.python_method
        def tecla_con_comando(self, evento):
            if not evento.modifierFlags() & _CMD:
                return False
            tecla = str(evento.charactersIgnoringModifiers() or "").lower()
            if len(tecla) == 1 and tecla in "123456789":
                self.elegir(int(tecla) - 1)
                return True
            if tecla == "\x7f":                        # ⌘⌫
                self.olvidar_elegido()
                return True
            if tecla in ("w", "."):
                self.ocultar()
                return True
            # Escudero no tiene menú Edición: sin esto ⌘V/⌘A no irían en la búsqueda.
            edicion = {"a": "selectAll:", "c": "copy:", "v": "paste:", "x": "cut:",
                       "z": "undo:"}
            if tecla in edicion:
                NSApplication.sharedApplication().sendAction_to_from_(
                    edicion[tecla], None, self.panel)
                return True
            return False

        # ── delegado de la búsqueda ─────────────────────────────────
        def controlTextDidChange_(self, _aviso):
            self.filtrar(conservar=False)

        def control_textView_doCommandBySelector_(self, _control, _vista, orden):
            orden = orden.decode() if isinstance(orden, bytes) else str(orden)
            if orden == "moveUp:":
                self.mover(-1)
            elif orden == "moveDown:":
                self.mover(1)
            elif orden in ("scrollPageUp:", "pageUp:"):
                self.mover(-8)
            elif orden in ("scrollPageDown:", "pageDown:"):
                self.mover(8)
            elif orden in ("insertNewline:", "insertLineBreak:"):
                self.elegir(self.tabla.selectedRow())
            elif orden == "cancelOperation:":
                if str(self.campo.stringValue() or ""):
                    self.campo.setStringValue_("")
                    self.filtrar(conservar=False)
                else:
                    self.ocultar()
            elif orden in ("insertTab:", "insertBacktab:"):
                pass
            else:
                return False
            return True

        # ── tabla ───────────────────────────────────────────────────
        def numberOfRowsInTableView_(self, _tabla):
            return len(self.resultados)

        def tableView_rowViewForRow_(self, _tabla, _fila):
            return EscuderoFilaPergamino.alloc().init()

        def tableView_viewForTableColumn_row_(self, tabla, _columna, fila):
            celda = tabla.makeViewWithIdentifier_owner_("celda", self)
            if celda is None:
                celda = self._nueva_celda(tabla.bounds().size.width)
            entrada = self.resultados[fila]
            celda.texto.setStringValue_(_una_linea(entrada["texto"]))
            celda.detalle.setStringValue_(_detalle(entrada))
            celda.atajo.setStringValue_(f"⌘{fila + 1}" if fila < 9 else "")
            celda.setToolTip_(str(entrada["texto"])[:1500])
            return celda

        @objc.python_method
        def _nueva_celda(self, ancho):
            ancho = max(ancho - 20, 300)
            celda = EscuderoCeldaPergamino.alloc().initWithFrame_(
                NSMakeRect(0, 0, ancho, ALTO_FILA))
            celda.setIdentifier_("celda")
            y = (ALTO_FILA - 18) / 2
            ancho_detalle, ancho_atajo = 190, 30
            texto = _etiqueta(13.5)
            texto.setFrame_(NSMakeRect(8, y, ancho - ancho_detalle - ancho_atajo - 22, 18))
            texto.setAutoresizingMask_(_ANCHO_FLEX)
            detalle = _etiqueta(11.5, 0.0, 2)
            detalle.setFrame_(NSMakeRect(ancho - ancho_detalle - ancho_atajo - 8, y + 1,
                                         ancho_detalle, 16))
            detalle.setAutoresizingMask_(_MARGEN_IZQ)
            atajo = _etiqueta(11.5, 0.2, 2)
            atajo.setFrame_(NSMakeRect(ancho - ancho_atajo - 6, y + 1, ancho_atajo, 16))
            atajo.setAutoresizingMask_(_MARGEN_IZQ)
            for campo in (texto, detalle, atajo):
                celda.addSubview_(campo)
            celda.setTextField_(texto)
            celda.texto, celda.detalle, celda.atajo = texto, detalle, atajo
            celda.setBackgroundStyle_(0)
            return celda

        def clic_(self, _remitente):
            fila = self.tabla.clickedRow()
            if fila >= 0:
                self.elegir(fila)

        # ── ventana ─────────────────────────────────────────────────
        def windowDidResignKey_(self, _aviso):
            self.ocultar()                             # clic fuera = cerrar


class Buscador:
    """Lo que ve el resto de Escudero: abrir/cerrar, refrescar y el atajo."""

    def __init__(self, pergamino, avisar, pegar_directo=True):
        self.disponible = _APPKIT
        self._pergamino = pergamino
        self._avisar = avisar
        self.pegar_directo = pegar_directo
        self._ctrl = None
        self.atajo = AtajoGlobal(self.alternar)

    def _controlador(self):
        if self._ctrl is None:
            self._ctrl = EscuderoControladorPergamino.alloc().init().configurar(
                self._pergamino, self._avisar, self.pegar_directo)
        self._ctrl.pegar_directo = self.pegar_directo
        return self._ctrl

    def mostrar(self):
        if self.disponible:
            self._controlador().mostrar()

    def alternar(self):
        if not self.disponible:
            return
        ctrl = self._controlador()
        ctrl.ocultar() if ctrl.visible() else ctrl.mostrar()

    def visible(self):
        return self._ctrl is not None and self._ctrl.visible()

    def refrescar(self):
        if self._ctrl is not None:
            self._ctrl.refrescar()

    def registrar_atajo(self, texto):
        if not self.disponible:
            return False, "sin AppKit"
        return self.atajo.registrar(texto)

    def parar(self):
        self.atajo.quitar()
        if self._ctrl is not None:
            self._ctrl.ocultar()
