#!/usr/bin/env python3
# Escudero 🛡 — tu mayordomo de barra de menús, todo local. Tras la Fase 1 el
# core solo hace 4 cosas: cargar/validar config, timers, ensamblar el menú y
# persistir estado. La lógica vive en los módulos (ver escudero/core/module.py).
# CLI de pruebas (sin arrancar la barra):
#   venv/bin/python escudero.py --probar-ordenar   # qué movería (en seco)
#   venv/bin/python escudero.py --una-pasada       # una pasada real de Ordenar
#   venv/bin/python escudero.py --muestra          # una muestra de Crónica
#   venv/bin/python escudero.py --informe          # genera el informe HTML
#   venv/bin/python escudero.py --validar-config   # valida config.yaml y explica errores

import json
import logging
import logging.handlers
import os
import re
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

try:
    from Foundation import NSObject
except Exception:
    NSObject = None

if NSObject is not None:
    class _PuentePrincipal(NSObject):
        """Puente reutilizable para ejecutar código Python en el hilo principal."""
        def ejecutar_(self, _sender):
            try:
                self._caja["resultado"] = self._fn(*self._args)
            except BaseException as exc:  # se relanza en el hilo llamador
                self._caja["error"] = exc
            return None

RAIZ = Path(__file__).resolve().parent
# Tu config y tus datos viven fuera del código (y fuera de la app instalada):
# ~/Library/Application Support/Escudero/. ESCUDERO_HOME lo cambia (pruebas).
APOYO = Path(os.environ.get("ESCUDERO_HOME")
             or Path.home() / "Library" / "Application Support" / "Escudero")
DATOS = APOYO / "datos"
CONFIG = APOYO / "config.yaml"
CONFIG_EJEMPLO = RAIZ / "config.ejemplo.yaml"
EMPAQUETADO = bool(getattr(sys, "frozen", False))   # corriendo dentro de Escudero.app
if not EMPAQUETADO:
    sys.path.insert(0, str(RAIZ))
else:
    # En la app, este script vive en Resources/ junto a nada más: que no tape al
    # paquete `escudero/` (que va dentro de la app) por llamarse igual.
    sys.path[:] = [p for p in sys.path if Path(p).resolve() != RAIZ]
    sys.modules.pop("escudero", None)

from cortina import Cortina                                 # noqa: E402
from cronica import Cronica, fmt_dur                        # noqa: E402
from ordenar import Ordenar                                 # noqa: E402
import lector                                               # noqa: E402
from atajos import AtajoGlobal                              # noqa: E402
from pergamino import Pergamino                             # noqa: E402
from panel_pergamino import Buscador    # noqa: E402
from sequito import Sequito                                 # noqa: E402
from ventanas import ACCIONES, Ventanas                     # noqa: E402
from vigia import Vigia                                     # noqa: E402
import autoarranque                                         # noqa: E402
from api import EscuderoAPI                                 # noqa: E402
from escudero.config_schema import validar_config      # noqa: E402
from escudero.events import EventBus                   # noqa: E402

log = logging.getLogger("escudero")


def preparar_carpeta():
    """Primera vez: crea la carpeta de Escudero y copia la config de ejemplo
    (con Ordenar apagado: nada se mueve hasta que tú lo decidas)."""
    DATOS.mkdir(parents=True, exist_ok=True)
    if not CONFIG.exists() and CONFIG_EJEMPLO.exists():
        import shutil
        shutil.copyfile(CONFIG_EJEMPLO, CONFIG)


def preparar_logging():
    preparar_carpeta()
    h = logging.handlers.RotatingFileHandler(DATOS / "escudero.log",
                                             maxBytes=1_000_000, backupCount=2, encoding="utf-8")
    h.setFormatter(logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s"))
    logging.basicConfig(level=logging.INFO, handlers=[h])


def cargar_config():
    """Lee config.yaml SIN validar (compat CLI). Preferir cargar_config_validada()."""
    import yaml
    with open(CONFIG, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


# Fase 2.1: errores de la última validación (los enseña el menú y --validar-config)
ERRORES_CONFIG = []


def cargar_config_validada():
    """config.yaml validada con Pydantic. Devuelve (cfg, errores) donde `errores`
    es [] si todo está bien; si no, cfg = última config buena conocida (o los
    defaults) y la app sigue funcionando con aviso, sin explotar en runtime."""
    global ERRORES_CONFIG
    try:
        crudo = cargar_config()
    except Exception as e:
        ERRORES_CONFIG = [f"config.yaml no se pudo leer: {e}"]
        return _ultima_config_buena(), ERRORES_CONFIG
    ok, cfg, errores = validar_config(crudo)
    if ok:
        ERRORES_CONFIG = []
        _guardar_ultima_config_buena(cfg)
        return cfg, []
    ERRORES_CONFIG = errores
    log.error("config.yaml inválida (%d error(es)): %s", len(errores), " | ".join(errores))
    return _ultima_config_buena(), errores


RUTA_CONFIG_BUENA = DATOS / "config.ultima-buena.json"


def _guardar_ultima_config_buena(cfg):
    try:
        RUTA_CONFIG_BUENA.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


def _ultima_config_buena():
    try:
        return json.loads(RUTA_CONFIG_BUENA.read_text(encoding="utf-8"))
    except Exception:
        return {}


def notificar(titulo, texto, sonido=None):
    log.info("aviso: %s — %s", titulo, texto)

    def esc(s):
        return str(s).replace("\\", "\\\\").replace('"', '\\"')
    orden = f'display notification "{esc(texto)}" with title "{esc(titulo)}"'
    if sonido:
        orden += f' sound name "{esc(sonido)}"'
    subprocess.Popen(["osascript", "-e", orden],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


RUTA_ESTADO = DATOS / "estado.json"


# ── SF Symbols (iconos nativos monocromos, nada de emojis) ────────────────
def _simbolo(nombre):
    try:
        from AppKit import NSImage
        img = NSImage.imageWithSystemSymbolName_accessibilityDescription_(nombre, None)
        if img:
            img.setTemplate_(True)
        return img
    except Exception:
        return None


def _poner_icono(item, nombre_simbolo):
    """Pone un SF Symbol como imagen de un MenuItem de rumps."""
    try:
        img = _simbolo(nombre_simbolo)
        if img is not None:
            item._menuitem.setImage_(img)
    except Exception:
        pass


def cargar_estado():
    try:
        return json.loads(RUTA_ESTADO.read_text(encoding="utf-8"))
    except Exception:
        return {}


# ──────────────────────────────────────────────────────────────────────────
class Escudero:
    def __init__(self):
        import rumps
        self.rumps = rumps
        self.cfg, self.errores_config = cargar_config_validada()
        self._errores_config_avisados = False
        # Fase 2.3: bus de eventos entre módulos (Ordenar → estado, foco → integraciones)
        self.bus = EventBus()
        self.cronica = Cronica(self.cfg, DATOS)
        self.ordenar = Ordenar(self.cfg, DATOS)
        self.vigia = Vigia(self.cfg, notificar, self.cronica._idle)
        self.pergamino = Pergamino(self.cfg, ruta=DATOS / "pergamino.json")
        self.buscador = Buscador(self.pergamino, notificar, self._pegar_directo())
        self.atajo_lector = AtajoGlobal(self.leer_pantalla)
        self._leyendo = False
        self.ventanas = Ventanas(self.cfg, notificar)
        self.ventanas.arrancar_atajos()
        self.cortina = Cortina(self.cfg)
        self.sequito = Sequito(self.cfg, DATOS, notificar)
        self._ordenando = False
        self._lock_estado = threading.Lock()
        self._api = None

        est = cargar_estado()
        self.vigia.poner_ojos(est.get("ojos_on", self.vigia.ojos_on))
        self.cronica.pausada = bool(est.get("cronica_pausada", False))
        self.ordenar.activado = bool(est.get("ordenar_on", self.ordenar.activado))
        self.ordenar.movimientos_deshacer = est.get("deshacer", []) or self.ordenar.movimientos_deshacer
        self.foco = str(est.get("foco") or "")
        self._cortina_inicial = bool(est.get("cortina_oculta", True))
        self._conectar_eventos()

        self.app = rumps.App("Escudero", title="🛡", quit_button=None)
        self._construir_menu()
        self._activar_atajos()
        self._pintar()          # sin placeholders ni 15 s de espera al arrancar

        self.t1 = rumps.Timer(self.tick_pergamino, 1)
        self.t5 = rumps.Timer(self.tick_muestra, self.cronica.intervalo)
        self.t15 = rumps.Timer(self.tick_cuidados, 15)
        self.t60 = rumps.Timer(self.tick_ordenar, max(15, self.ordenar.intervalo))
        for t in (self.t1, self.t5, self.t15, self.t60):
            t.start()   # ojo: rumps.Timer dispara YA al arrancar

        self.sequito.arrancar_autos()
        self._arrancar_api()          # Fase 3.4: contrato de sinergia del ecosistema
        self._avisar_config_invalida()
        signal.signal(signal.SIGTERM, self._sigterm)
        log.info("Escudero en pie 🛡 (AX títulos: %s)", "sí" if self.cronica.ax_ok else "no")
        if not self.cronica.ax_ok:
            # sin Accesibilidad: pedir a macOS que muestre su diálogo y nos
            # añada a la lista de Ajustes (el usuario solo tiene que activar)
            try:
                from ApplicationServices import (AXIsProcessTrustedWithOptions,
                                                 kAXTrustedCheckOptionPrompt)
                AXIsProcessTrustedWithOptions({kAXTrustedCheckOptionPrompt: True})
            except Exception:
                pass

    # ── Fase 2.3: eventos entre módulos (sin acoplarlos entre sí) ──────────
    def _conectar_eventos(self):
        def al_ordenar(_payload):
            self._guardar_estado()

        self.bus.on("ordenar_movidos", al_ordenar)

    # ── Fase 3.4: API local ─────────────────────────────────────────────────
    def _arrancar_api(self):
        if not (self.cfg.get("api", {}) or {}).get("activada", True):
            log.info("API local desactivada en config.yaml")
            return
        try:
            self._api = EscuderoAPI(self, self.cfg)
            self._api.arrancar()
        except Exception:
            log.exception("no pude arrancar la API local")
            self._api = None

    def desde_hilo(self, fn, *args):
        """Ejecuta fn en el hilo principal y devuelve su resultado."""
        if threading.current_thread() is threading.main_thread():
            return fn(*args)
        if NSObject is None:
            with self._lock_estado:
                return fn(*args)

        caja = {}
        puente = _PuentePrincipal.alloc().init()
        puente._caja = caja
        puente._fn = fn
        puente._args = args
        try:
            puente.performSelectorOnMainThread_withObject_waitUntilDone_(
                "ejecutar:", None, True
            )
        except Exception:
            log.exception("puente al hilo principal falló; ejecuto en este hilo")
            with self._lock_estado:
                return fn(*args)
        if "error" in caja:
            raise caja["error"]
        return caja.get("resultado")

    def fijar_foco(self, texto):
        """Foco del día desde la API (POST /foco; lo usa ForgeDesk)."""
        texto = str(texto or "").strip()
        if texto == self.foco:
            return
        self.foco = texto
        self.bus.emit("foco_cambiado", {"texto": texto})
        self._guardar_estado()
        try:
            self._pintar()
        except Exception:
            log.exception("no pude repintar tras fijar foco")
        if texto:
            notificar("🎯 Foco", f"Foco del día: {texto}")

    def ejecutar_comando_voz(self, texto):
        """Comandos entrantes (Fase 4.2): «Escudero, …» desde VozLocal/ForgeDesk."""
        t = re.sub(r"^(escudero|oye escudero)[,\s]+", "", str(texto or "").strip().lower())

        m = re.match(r"^(?:mi )?foco (?:es |del día es )?(.+)$", t)
        if m:
            self.fijar_foco(m.group(1).strip())
            return {"ok": True, "accion": "foco", "foco": self.foco}

        if re.match(r"^ordena(?: las descargas| ahora| esto)?$", t):
            self.ordenar_ahora(None)
            return {"ok": True, "accion": "ordenar_ahora"}

        if re.match(r"^(deshaz|deshacer)(?: la última pasada)?$", t):
            n = self.ordenar.deshacer()
            self._guardar_estado()
            self._pintar()
            return {"ok": True, "accion": "deshacer", "n": n}

        if re.match(r"^(pausa|pausar)( crónica| cronica)?$", t):
            if not self.cronica.pausada:
                self.alternar_pausa(None)
            return {"ok": True, "accion": "cronica_pausada"}
        if re.match(r"^(reanuda|reanudar|sigue contando)$", t):
            if self.cronica.pausada:
                self.alternar_pausa(None)
            return {"ok": True, "accion": "cronica_reanudada"}
        if re.match(r"^silencio$", t):
            self.vigia.poner_ojos(False)
            self._guardar_estado()
            return {"ok": True, "accion": "ojos_apagados"}
        return {"ok": False, "error": f"comando no reconocido: «{texto}»",
                "comandos": ["mi foco es …", "ordena ahora", "deshacer",
                             "pausar crónica", "reanudar", "silencio"]}

    def _avisar_config_invalida(self):
        """Una sola notificación por arranque si config.yaml no valida."""
        if not self.errores_config or self._errores_config_avisados:
            return
        self._errores_config_avisados = True
        notificar("⚠️ Escudero", "config.yaml no es válido: sigo con la última buena. "
                  f"{len(self.errores_config)} error(es) — menú → Recargar configuración "
                  "para verlos.", "Basso")

    # ── menú ──────────────────────────────────────────────────────────────
    def _construir_menu(self):
        M = self.rumps.MenuItem
        # OJO: rumps usa el título como clave de menú → los slots dinámicos
        # nacen con títulos únicos (espacios) y se retitulan al pintar.
        self.i_cronica = M("Crónica — arrancando…", callback=self.abrir_informe)
        self.slots_cat = [M(" " * (i + 1)) for i in range(6)]
        self.slots_app = [M(" " * (i + 7)) for i in range(6)]
        self.i_pausar = M("Pausar Crónica", callback=self.alternar_pausa)
        self.i_informe = M("Informe de hoy…", callback=self.abrir_informe)

        self.i_ojos = M("Descanso 20-20-20", callback=self.alternar_ojos)

        self.i_foco = M("Foco del día…", callback=self.cambiar_foco)

        self.i_pergamino = M("Pergamino — vacío")
        self.i_perg_buscar = M("Buscar en el historial…", callback=self.abrir_buscador)
        # Los títulos iniciales distintos evitan colisiones en el dict de rumps;
        # _indice dice qué hueco es (los MenuItem vacíos son iguales entre sí
        # con ==, así que slots_perg.index(sender) siempre daba 0).
        self.slots_perg = [M(" " * (i + 1)) for i in range(12)]
        for i, slot in enumerate(self.slots_perg):
            slot._indice = i
        self.i_perg_vaciar = M("Vaciar historial", callback=self.vaciar_pergamino)
        
        # Lector (el "TextSniper"): el texto reconocido queda copiado
        self.i_ocr = M("Leer texto")
        self.i_ocr_pantalla = M("De una zona de la pantalla…", callback=self.leer_pantalla)
        self.i_ocr_portapapeles = M("De la imagen copiada", callback=self.leer_portapapeles)
        self.i_ocr_archivo = M("De una imagen o un PDF…", callback=self.leer_archivo)
        self.i_ocr.update([self.i_ocr_pantalla, self.i_ocr_portapapeles, self.i_ocr_archivo])

        self.i_ventanas = M("Ventanas")
        etiquetas = [("Mitad izquierda   ⌃⌥←", "izquierda"),
                     ("Mitad derecha   ⌃⌥→", "derecha"),
                     ("Mitad superior   ⌃⌥↑", "arriba"),
                     ("Mitad inferior   ⌃⌥↓", "abajo"),
                     ("Maximizar   ⌃⌥⏎", "maximizar"),
                     ("Centrar   ⌃⌥C", "centrar")]
        items_v = []
        for titulo, accion in etiquetas:
            it = M(titulo, callback=self._encajar_cb)
            it._accion = accion
            items_v.append(it)
        self.i_ventanas.update(items_v)

        self.i_sequito = M("Séquito")
        self.items_seq = []
        for ent in self.sequito.entradas:
            it = M(ent["nombre"], callback=self.alternar_companero)
            it._ent = ent
            self.items_seq.append(it)
        self.i_sequito.update(self.items_seq or
                              [M("(vacío — añade compañeros en config.yaml)")])

        self.i_cortina = M("Cortina")
        self.i_cortina_toggle = M("Ocultar iconos ahora", callback=self.alternar_cortina)
        self.i_cortina_ayuda = M("Cómo colocar los iconos…", callback=self.ayuda_cortina)
        self.i_cortina.update([self.i_cortina_toggle, self.i_cortina_ayuda])
        self.i_datos = M("Abrir carpeta de datos…", callback=self.abrir_datos)
        self.i_autoarranque = None
        if autoarranque.disponible():
            self.i_autoarranque = M("Abrir al iniciar sesión",
                                    callback=self.alternar_autoarranque)
            self.i_autoarranque.state = autoarranque.activado()

        self.i_ordenar = M("Ordenar", callback=None)
        self.i_ordenar_ya = M("Ordenar ahora", callback=self.ordenar_ahora)
        self.i_deshacer = M("Deshacer última pasada", callback=None)
        self.i_ordenar_on = M("Activado", callback=self.alternar_ordenar)
        self.i_probar = M("Probar las reglas…", callback=self.probar_reglas)
        self.i_recientes = M("Últimos movimientos")
        self.slots_mov = [M(" " * (i + 20)) for i in range(8)]
        for i, slot in enumerate(self.slots_mov):
            slot._indice = i
        self.i_recientes.update(self.slots_mov)
        self.i_reglas = M("Editar reglas…", callback=self.editar_reglas)
        self.i_recargar = M("Recargar configuración", callback=self.recargar)

        # un MenuItem es a la vez entrada y submenú: los hijos se le añaden con update()
        self.i_cronica.update([*self.slots_cat, None, *self.slots_app, None,
                               self.i_informe, self.i_pausar])
        self.i_ordenar.update([self.i_ordenar_ya, self.i_probar, None, self.i_recientes,
                               self.i_deshacer, None, self.i_ordenar_on, self.i_reglas,
                               self.i_recargar])
        self.i_pergamino.update([self.i_perg_buscar, None, *self.slots_perg, None,
                                 self.i_perg_vaciar])
        self.app.menu = [
            self.i_cronica,
            self.i_foco,
            None,
            self.i_pergamino,
            self.i_ocr,
            self.i_ventanas,
            None,
            self.i_ojos,
            None,
            self.i_ordenar,
            None,
            self.i_sequito,
            self.i_cortina,
            None,
            *([self.i_autoarranque] if self.i_autoarranque is not None else []),
            self.i_datos,
            M("Salir de Escudero", callback=self.salir),
        ]
        self._decorar_menu()

    def _decorar_menu(self):
        """Iconos nativos (SF Symbols template) en vez de emojis."""
        for item, simbolo in ((self.i_cronica, "clock"),
                              (self.i_foco, "target"),
                              (self.i_pergamino, "doc.on.clipboard"),
                              (self.i_perg_buscar, "magnifyingglass"),
                              (self.i_ocr, "text.viewfinder"),
                              (self.i_ventanas, "macwindow"),
                              (self.i_ojos, "eye"),
                              (self.i_ordenar, "folder.fill"),
                              (self.i_deshacer, "arrow.uturn.backward"),
                              (self.i_probar, "checklist"),
                              (self.i_recientes, "clock.arrow.circlepath"),
                              (self.i_sequito, "person.2.fill"),
                              (self.i_cortina, "menubar.rectangle"),
                              (self.i_informe, "chart.bar.doc.horizontal"),
                              (self.i_datos, "internaldrive")):
            _poner_icono(item, simbolo)

    def _vestir_barra(self):
        """El escudo de la barra: SF Symbol template en vez del emoji."""
        try:
            boton = self.app._nsapp.nsstatusitem.button()
            if boton is None:
                return False
            boton.setImagePosition_(2)  # NSImageLeft: imagen + texto (hora/foco)
            self._simbolo_barra = None
            self._actualizar_icono_barra()
            log.info("barra vestida con SF Symbols")
            return True
        except Exception:
            log.exception("no pude vestir la barra (me quedo con el emoji)")
            return False

    def _actualizar_icono_barra(self):
        """El escudo de la barra (SF Symbol template)."""
        deseado = "shield.lefthalf.filled"
        if deseado == getattr(self, "_simbolo_barra", None):
            return
        try:
            boton = self.app._nsapp.nsstatusitem.button()
            img = _simbolo(deseado) or _simbolo("shield.fill")
            if boton is not None and img is not None:
                boton.setImage_(img)
                self._simbolo_barra = deseado
        except Exception:
            pass

    def _rellenar(self, slots, textos):
        for i, slot in enumerate(slots):
            visible = i < len(textos)
            slot.title = textos[i] if visible else "—"
            try:
                slot.hidden = not visible
            except AttributeError:
                pass

    # ── ticks ──────────────────────────────────────────────────────────────
    def tick_muestra(self, _t=None):
        try:
            self.cronica.muestrear()
        except Exception:
            log.exception("fallo muestreando")

    def tick_pergamino(self, _t=None):
        try:
            if self.pergamino.vigilar():
                self._pintar_pergamino()
                self.buscador.refrescar()
        except Exception:
            log.exception("fallo en pergamino")

    def tick_cuidados(self, _t=None):
        try:
            if not getattr(self, "_barra_vestida", False):
                self._barra_vestida = self._vestir_barra()
            if self.cortina.activada and not self.cortina.montada:
                self.cortina.montar(self._cortina_inicial)   # tras existir el escudo
            self.cortina.tick()
            self.vigia.tick()
            self._pintar()
        except Exception:
            log.exception("fallo en tick de cuidados")

    def tick_ordenar(self, _t=None):
        if not self.ordenar.activado or self._ordenando:
            return
        threading.Thread(target=self._pasada_ordenar, args=(False,), daemon=True).start()

    def _pasada_ordenar(self, manual):
        self._ordenando = True
        try:
            movidos = self.ordenar.pasada()
            if movidos:
                self.bus.emit("ordenar_movidos",
                              {"n": len(movidos), "pasada_id": getattr(self.ordenar, "_pasada_deshacer", 0)})
                if self.ordenar.avisar or manual:
                    notificar("🗂 Escudero", f"He ordenado {len(movidos)} "
                              f"archivo{'s' if len(movidos) != 1 else ''}.")
            elif manual:
                notificar("🗂 Escudero", "Nada que ordenar: todo en su sitio.")
        except Exception:
            log.exception("fallo ordenando")
        finally:
            self._ordenando = False

    # ── pintado del menú ───────────────────────────────────────────────────
    def _pintar(self):
        r = self.cronica.resumen_hoy()
        top_cat = f" — {r['categorias'][0][0]} {fmt_dur(r['categorias'][0][1])}" if r["categorias"] else ""
        self.i_cronica.title = f"Hoy: {fmt_dur(r['total'])}{top_cat}"
        self._rellenar(self.slots_cat, [f"{c}: {fmt_dur(s)}" for c, s in r["categorias"][:6]])
        self._rellenar(self.slots_app, [f"· {a} — {fmt_dur(s)}" for a, s in r["apps"][:6]])

        cfg_barra = self.cfg.get("barra", {}) or {}
        partes = []
        if cfg_barra.get("mostrar_tiempo", True) and not self.cronica.pausada and r["total"]:
            h, m = int(r["total"]) // 3600, (int(r["total"]) % 3600) // 60
            partes.append(f"{h}:{m:02d}")
        if self.foco and cfg_barra.get("mostrar_foco", True):
            partes.append(self.foco[:22])
        texto_barra = " · ".join(partes)
        # con el símbolo puesto, el texto acompaña al icono; sin él, emoji de respaldo
        if getattr(self, "_barra_vestida", False):
            self.app.title = f" {texto_barra}" if texto_barra else ""
        else:
            self.app.title = f"🛡 {texto_barra}" if texto_barra else "🛡"
        self.i_foco.title = f"Foco: {self.foco}" if self.foco else "Foco del día…"
        self._pintar_pergamino()

        if getattr(self, "_barra_vestida", False):
            self._actualizar_icono_barra()
        self.i_ojos.state = self.vigia.ojos_on
        self.i_ordenar_on.state = self.ordenar.activado
        self.i_pausar.state = self.cronica.pausada
        if self.vigia.ojos_on:
            self.i_ojos.title = f"Descanso 20-20-20 — en {self.vigia.minutos_para_ojos()} min"
        else:
            self.i_ojos.title = "Descanso 20-20-20 — apagado"

        if self.ordenar.activado:
            ult = self.ordenar.ultima_pasada
            detalle = f" — última {ult[0]} ({ult[1]})" if ult else ""
            self.i_ordenar.title = f"Ordenar{detalle}"
        else:
            self.i_ordenar.title = "Ordenar — apagado"
        self.i_deshacer.set_callback(self.deshacer if self.ordenar.movimientos_deshacer else None)
        n = len(self.ordenar.movimientos_deshacer)
        self.i_deshacer.title = f"Deshacer última pasada ({n})" if n else "Deshacer última pasada"
        self._pintar_recientes()

        for it in self.items_seq:
            vivo = self.sequito.pid(it._ent) is not None
            it.title = f"{it._ent['nombre']} — {'activo' if vivo else 'parado'}"
            it.state = vivo
        if self.cortina.activada:
            self.i_cortina.title = "Cortina — recogida" if self.cortina.oculta else "Cortina — abierta"
            self.i_cortina_toggle.title = ("Mostrar iconos escondidos" if self.cortina.oculta
                                           else "Ocultar iconos ahora")

    def _pintar_recientes(self):
        """«Últimos movimientos»: qué movió Ordenar y adónde (clic → en el Finder)."""
        from pergamino import hace
        self._recientes = self.ordenar.recientes(len(self.slots_mov))
        for i, slot in enumerate(self.slots_mov):
            if i < len(self._recientes):
                ts, _origen, destino, _regla = self._recientes[i]
                d = Path(destino)
                slot.title = f"{d.name[:40]} → {d.parent.name} · {hace(ts)}"
                slot.set_callback(self.mostrar_movido)
            else:
                slot.title = "Nada movido todavía" if i == 0 else "—"
                slot.set_callback(None)
            try:
                slot.hidden = i >= max(1, len(self._recientes))
            except AttributeError:
                pass

    def _pintar_pergamino(self):
        n = len(self.pergamino.historial)
        self.i_pergamino.title = f"Pergamino — {n} recorte{'s' if n != 1 else ''}" if n else "Pergamino — vacío"
        textos = [t.replace("\n", " ⏎ ")[:48] for t in self.pergamino.historial[:len(self.slots_perg)]]
        for i, slot in enumerate(self.slots_perg):
            visible = i < len(textos)
            slot.title = textos[i] if visible else "—"
            slot.set_callback(self.clic_pergamino if visible else None)
            try:
                slot.hidden = not visible
            except AttributeError:
                pass

    # ── acciones del menú ──────────────────────────────────────────────────
    def cambiar_foco(self, _s):
        v = self.rumps.Window("Tu ÚNICA tarea de hoy (deja vacío para quitarla):",
                              title="Foco del día", default_text=self.foco,
                              ok="Guardar", cancel="Cancelar", dimensions=(340, 24)).run()
        if v.clicked:
            self.foco = str(v.text or "").strip()
            self._guardar_estado()
            self._pintar()

    def clic_pergamino(self, sender):
        i = getattr(sender, "_indice", None)
        historial = self.pergamino.historial
        if i is None or i >= len(historial):
            return
        # El menú de la barra no quita el foco a tu app: el ⌘V que pulses
        # ahora cae en el mismo campo donde estabas.
        if self.pergamino.restaurar(historial[i]):
            notificar("📋 Pergamino", "Copiado: pulsa ⌘V para pegarlo.")
        else:
            notificar("📋 Pergamino", "No pude dejarlo en el portapapeles.")

    def vaciar_pergamino(self, _s):
        self.pergamino.vaciar()
        self._pintar_pergamino()
        self.buscador.refrescar()

    def abrir_buscador(self, _s=None):
        self.buscador.mostrar()

    def _pegar_directo(self):
        return bool((self.cfg.get("pergamino", {}) or {}).get("pegar_directo", True))

    def _activar_atajos(self):
        """Registra los atajos globales (buscador ⌃⌥V, lector ⌃⌥T) y enseña la
        tecla en el menú; si otra app ya la usa, el menú sigue funcionando."""
        p = self.cfg.get("pergamino", {}) or {}
        for registrar, item, titulo, atajo in (
                (self.buscador.registrar_atajo, self.i_perg_buscar, "Buscar en el historial…",
                 p.get("atajo", "ctrl+opt+v")),
                (self.atajo_lector.registrar, self.i_ocr_pantalla, "De una zona de la pantalla…",
                 p.get("atajo_ocr", "ctrl+opt+t"))):
            ok, detalle = registrar(atajo)
            item.title = f"{titulo}   {detalle}" if ok else titulo
            if not ok:
                log.warning("atajo %s no disponible: %s", atajo, detalle)

    # ── Lector ────────────────────────────────────────────────────────────
    def _motor_ocr(self):
        return (self.cfg.get("pergamino", {}) or {}).get("motor_ocr", "vision")

    def leer_pantalla(self, _s=None):
        """⌃⌥T o el menú: eliges una zona y su texto queda copiado."""
        if self._leyendo:
            return
        if not lector.permiso_pantalla():
            lector.pedir_permiso_pantalla()
            notificar("📸 Leer texto",
                      "Falta el permiso «Grabación de pantalla»: actívalo para Escudero "
                      "(o para Terminal, si lo abres desde ahí) y vuelve a pulsar ⌃⌥T. "
                      "Sin él, macOS solo deja ver el fondo de escritorio.")
            return

        def tarea():
            datos, err = lector.capturar_zona()
            if datos is None and err is None:
                return                      # Esc: el usuario se arrepintió
            texto, err = (None, err) if err else lector.reconocer(datos, self._motor_ocr())
            self._entregar_texto(texto, err)
        self._en_segundo_plano(tarea)

    def leer_portapapeles(self, _s=None):
        def tarea():
            origen, err = lector.imagen_portapapeles()
            texto, err = (None, err) if err else lector.leer(origen, self._motor_ocr())
            self._entregar_texto(texto, err)
        self._en_segundo_plano(tarea)

    def leer_archivo(self, _s=None):
        ruta = lector.elegir_archivo()      # el panel, en el hilo principal (si no, no abre)
        if not ruta:
            return
        self._en_segundo_plano(lambda: self._entregar_texto(*lector.leer_archivo(ruta, self._motor_ocr())))

    def _en_segundo_plano(self, tarea):
        def envoltorio():
            self._leyendo = True
            try:
                tarea()
            except Exception:
                log.exception("fallo leyendo texto")
                self._entregar_texto(None, "Algo falló al leer el texto (mira el registro).")
            finally:
                self._leyendo = False
        threading.Thread(target=envoltorio, daemon=True).start()

    def _entregar_texto(self, texto, err):
        """Copia el texto reconocido (entra en el historial) y lo enseña; desde
        un hilo cualquiera, porque el portapapeles se toca en el principal."""
        def en_principal():
            if err or not texto:
                notificar("📸 Leer texto", err or "No he encontrado texto.")
                return
            if not self.pergamino.copiar(texto):
                notificar("📸 Leer texto", "Lo he leído, pero no pude copiarlo.")
                return
            lineas = texto.count("\n") + 1
            resumen = " ".join(texto.split())
            resumen = resumen[:80] + ("…" if len(resumen) > 80 else "")
            notificar("📸 Texto copiado" + (f" · {lineas} líneas" if lineas > 1 else ""), resumen, "Pop")
        try:
            from PyObjCTools import AppHelper
            AppHelper.callAfter(en_principal)
        except Exception:
            en_principal()

    def _encajar_cb(self, sender):
        threading.Thread(target=self.ventanas.encajar,
                         args=(sender._accion,), daemon=True).start()

    def alternar_cortina(self, _s):
        self.cortina.alternar()
        self._guardar_estado()
        self._pintar()

    def ayuda_cortina(self, _s):
        self.rumps.alert(
            "Cortina — cómo colocar los iconos",
            "En la barra hay dos símbolos nuevos: ❘ (separador) y ‹/› (flecha).\n\n"
            "1. Si no ves el ❘, pulsa la flecha › para ABRIR la cortina.\n"
            "2. Mantén ⌘ y ARRASTRA cada icono que quieras esconder "
            "(Ollama, Gemini…) a la IZQUIERDA del ❘.\n"
            "3. Deja a la derecha del ❘ lo que quieras ver siempre (🛡, reloj…).\n"
            "4. Pulsa ‹ para esconderlos. Si los asomas, se recogen solos a los 15 s.\n\n"
            "Los del sistema (Wi-Fi, batería…) se quitan en Ajustes → Centro de control.")

    def alternar_companero(self, sender):
        ent = sender._ent
        if self.sequito.pid(ent):
            self.sequito.parar(ent)
            notificar("⚔️ Séquito", f"{ent['nombre']} parado.")
        else:
            threading.Thread(target=lambda: (self.sequito.arrancar(ent),
                                             notificar("⚔️ Séquito", f"{ent['nombre']} en pie.")),
                             daemon=True).start()

    def alternar_ojos(self, _s):
        self.vigia.poner_ojos(not self.vigia.ojos_on)
        self.i_ojos.state = self.vigia.ojos_on
        self._guardar_estado()

    def alternar_pausa(self, _s):
        self.cronica.pausada = not self.cronica.pausada
        self.i_pausar.state = self.cronica.pausada
        self._guardar_estado()

    def alternar_ordenar(self, _s):
        self.ordenar.activado = not self.ordenar.activado
        self.i_ordenar_on.state = self.ordenar.activado
        self._guardar_estado()
        self._pintar()

    def ordenar_ahora(self, _s):
        if not self._ordenando:
            threading.Thread(target=self._pasada_ordenar, args=(True,), daemon=True).start()

    def deshacer(self, _s):
        n = self.ordenar.deshacer()
        self._guardar_estado()
        notificar("↩️ Escudero", f"{n} archivo{'s' if n != 1 else ''} de vuelta a su sitio.")
        self._pintar()

    def abrir_informe(self, _s):
        try:
            ruta = self.cronica.informe_html()
            subprocess.Popen(["open", str(ruta)])
        except Exception:
            log.exception("fallo generando informe")
            notificar("Escudero", "No pude generar el informe (mira escudero.log).")

    def editar_reglas(self, _s):
        subprocess.Popen(["open", "-t", str(CONFIG)])

    def probar_reglas(self, _s):
        """Qué haría Ordenar ahora con cada archivo suelto, y por qué (sin mover nada)."""
        try:
            subprocess.Popen(["open", str(self.ordenar.informe_prueba())])
        except Exception:
            log.exception("fallo probando las reglas")
            notificar("🗂 Ordenar", "No pude probar las reglas (mira el registro).")

    def mostrar_movido(self, sender):
        i = getattr(sender, "_indice", None)
        recientes = getattr(self, "_recientes", [])
        if i is None or i >= len(recientes):
            return
        destino = recientes[i][2]
        if Path(destino).exists():
            subprocess.Popen(["open", "-R", destino])
        else:
            notificar("🗂 Ordenar", f"«{Path(destino).name}» ya no está donde lo dejé.")

    def alternar_autoarranque(self, sender):
        sender.state = autoarranque.cambiar(not autoarranque.activado())

    def abrir_datos(self, _s):
        subprocess.Popen(["open", str(DATOS)])

    def recargar(self, _s):
        cfg, errores = cargar_config_validada()
        if errores:
            detalle = "\n".join(f"· {e}" for e in errores[:6])
            notificar("⚠️ Escudero", "config.yaml no es válido; sigo con la anterior.", "Basso")
            self.rumps.alert("config.yaml no es válido",
                             f"Sigo con la configuración anterior.\n\n{detalle}\n\n"
                             f"({len(errores)} error(es) · mira datos/escudero.log)")
            self.errores_config = errores
            return
        self.cfg = cfg
        self.errores_config = []
        self._errores_config_avisados = False
        self.cronica.actualizar_config(self.cfg)
        self.vigia.actualizar_config(self.cfg)
        nuevo = Ordenar(self.cfg, DATOS)
        nuevo.activado = self.ordenar.activado
        nuevo.ultima_pasada = self.ordenar.ultima_pasada
        nuevo.movimientos_deshacer = self.ordenar.movimientos_deshacer
        self.ordenar = nuevo
        self.pergamino.actualizar_config(self.cfg)
        self.buscador.pegar_directo = self._pegar_directo()
        self._activar_atajos()
        notificar("Escudero", "Configuración recargada ✅")
        self._pintar()

    def _guardar_estado(self):
        with self._lock_estado:
            try:
                RUTA_ESTADO.write_text(json.dumps({
                    "ojos_on": self.vigia.ojos_on,
                    "cronica_pausada": self.cronica.pausada,
                    "ordenar_on": self.ordenar.activado,
                    "deshacer": self.ordenar.movimientos_deshacer,
                    "foco": self.foco,
                    "cortina_oculta": self.cortina.oculta,
                }, ensure_ascii=False, indent=1), encoding="utf-8")
            except OSError:
                log.exception("no pude guardar estado.json")

    def _sigterm(self, *_):
        self.salir(None)

    def salir(self, _s):
        log.info("Escudero se retira. 🛡")
        self.cronica.volcar()
        self.ventanas.parar()
        self.buscador.parar()
        self.atajo_lector.quitar()
        self.cortina.parar()
        if self._api is not None:
            self._api.parar()
        self._guardar_estado()
        self.rumps.quit_application()

    def run(self):
        self.app.run()


# ── CLI de pruebas (sin GUI) ───────────────────────────────────────────────
def cli(args):
    cfg = cargar_config()
    if "--validar-config" in args:
        ok, normalizada, errores = validar_config(cfg if isinstance(cfg, dict) else {})
        if ok:
            print("config.yaml ✅ válida")
            print(f"  secciones: {', '.join(sorted(k for k in normalizada if k != 'x'))}")
            print(f"  ordenar: {len(normalizada.get('ordenar', {}).get('carpetas', []))} carpeta(s), "
                  f"{sum(len(c.get('reglas', [])) for c in normalizada.get('ordenar', {}).get('carpetas', []))} regla(s)")
            print(f"  API: puerto {normalizada.get('api', {}).get('puerto')}")
            print(f"  séquito: {len(normalizada.get('sequito', []))} compañero(s)")
        else:
            print(f"config.yaml ❌ {len(errores)} error(es):")
            for e in errores:
                print(f"  · {e}")
        return
    if "--probar-ordenar" in args or "--una-pasada" in args:
        o = Ordenar(cfg, DATOS)
        seco = "--probar-ordenar" in args
        movs = o.pasada(en_seco=seco)
        for origen, destino, regla in movs:
            print(f"{'PLAN  ' if seco else 'MOVIDO'}  {origen.name}  →  "
                  f"{Path(destino).parent.name}/  [{regla}]")
        print(f"\n{'Se moverían' if seco else 'Movidos'}: {len(movs)} archivos")
    elif "--muestra" in args:
        c = Cronica(cfg, DATOS)
        print("AX títulos:", "sí" if c.ax_ok else "no (solo apps)")
        print("muestra:", c.muestrear())
    elif "--informe" in args:
        c = Cronica(cfg, DATOS)
        print("informe:", c.informe_html())
    elif "--ventana" in args:
        i = args.index("--ventana")
        accion = args[i + 1] if len(args) > i + 1 and not args[i + 1].startswith("-") else "maximizar"
        v = Ventanas(cfg, lambda t, x, s=None: print(f"[aviso] {t}: {x}"))
        ok = v.encajar(accion)
        print(f"{accion} → {'✅ ok' if ok else '❌ falló'}   (acciones: {', '.join(ACCIONES)})")
    else:
        print(__doc__ or "flags: --probar-ordenar --una-pasada --muestra --informe")


_CANDADO = None


def hay_otro_escudero():
    """Guardia anti-instancias-dobles (start.command + launchd a la vez): un
    candado sobre datos/escudero.lock que el sistema suelta solo cuando el
    proceso muere. Buscar «escudero.py» con pgrep confundía con Escudero
    cualquier proceso que nombrara el archivo (un editor, una terminal)."""
    global _CANDADO
    import fcntl
    DATOS.mkdir(parents=True, exist_ok=True)
    _CANDADO = open(DATOS / "escudero.lock", "w")
    try:
        fcntl.flock(_CANDADO, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return False
    except OSError:
        return True


def main():
    preparar_logging()
    flags = {"--probar-ordenar", "--una-pasada", "--muestra", "--informe",
             "--ventana", "--validar-config"}
    if flags & set(sys.argv[1:]):
        cli(sys.argv[1:])
        return
    if hay_otro_escudero():
        log.warning("Ya hay otro Escudero corriendo — esta copia se retira.")
        notificar("🛡 Escudero", "Ya había un Escudero en marcha; esta copia se cierra sola.")
        return
    autoarranque.activar_la_primera_vez(APOYO)
    Escudero().run()


if __name__ == "__main__":
    main()
