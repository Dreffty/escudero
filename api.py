# API local de Escudero (Fase 3.4 — EL CONTRATO DE SINERGIA del ecosistema).
#
# HTTP en 127.0.0.1 (puerto 8764 por defecto, configurable en config.yaml).
# Auth: token Bearer en ~/.config/escudero/api.token (chmod 600); se genera
# solo la primera vez. Sin dependencias externas (http.server de la stdlib).
#
# Endpoints (ver docs/API.md):
#   GET  /status                       → módulos, crónica de hoy, foco
#   POST /foco             {texto}
#   GET  /cronica/resumen?fecha=YYYY-MM-DD
#   POST /comando          {texto}     → comandos de voz entrantes (Fase 4.2)

import json
import logging
import secrets
import threading
from datetime import date, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

log = logging.getLogger("escudero.api")

RUTA_TOKEN = Path.home() / ".config" / "escudero" / "api.token"


def cargar_o_crear_token(configurado: str = "") -> str:
    """Token fijo de config si existe; si no, el del disco; si no, se crea (600)."""
    if configurado:
        return configurado
    try:
        return RUTA_TOKEN.read_text(encoding="utf-8").strip()
    except OSError:
        pass
    token = secrets.token_hex(24)
    try:
        RUTA_TOKEN.parent.mkdir(parents=True, exist_ok=True)
        RUTA_TOKEN.write_text(token, encoding="utf-8")
        RUTA_TOKEN.chmod(0o600)
        log.info("token de API nuevo en %s (chmod 600)", RUTA_TOKEN)
    except OSError as e:
        log.warning("No pude guardar el token de API: %s (vale para esta sesión)", e)
    return token


def _parse_fecha(texto):
    """'YYYY-MM-DD' → date; vacío → hoy. Lanza ValueError si no cuadra."""
    if not texto:
        return date.today()
    return datetime.strptime(texto.strip(), "%Y-%m-%d").date()


class EscuderoAPI:
    """Servidor HTTP local (hilo daemon). `app` es la instancia de Escudero;
    las mutaciones de GUI se reenvían al hilo principal con
    `app.desde_hilo(fn, *args)` (PyObjC performSelectorOnMainThread)."""

    def __init__(self, app, cfg):
        a = (cfg or {}).get("api", {}) or {}
        self.app = app
        self.puerto = int(a.get("puerto", 8764))
        self.token = cargar_o_crear_token(str(a.get("token", "") or ""))
        self._httpd = None

    # ── acciones (se ejecutan en el HILO PRINCIPAL vía app.desde_hilo) ──────
    def _estado(self):
        app = self.app
        modulos = [n for n in ("cronica", "ordenar", "pergamino", "ventanas",
                               "cortina", "sequito", "vigia")
                   if getattr(app, n, None) is not None]
        r = app.cronica.resumen_fecha()
        return 200, {
            "app": "escudero",
            "modulos": modulos,
            "foco": app.foco,
            "cronica_hoy": {
                "total_seg": r["total"],
                "categorias": {c: s for c, s in r["categorias"]},
                "proyectos": {p: s for p, s in r.get("proyectos", [])},
            },
            "ordenar": {"activado": app.ordenar.activado},
            "vigia": {"ojos": app.vigia.ojos_on},
        }

    def _fijar_foco(self, body):
        self.app.fijar_foco(str(body.get("texto", "") or "")[:200])
        return 200, {"ok": True, "foco": self.app.foco}

    def _resumen_cronica(self, query):
        try:
            dia = _parse_fecha((parse_qs(query).get("fecha") or [""])[0])
        except ValueError:
            return 400, {"error": "fecha debe ser YYYY-MM-DD"}
        r = self.app.cronica.resumen_fecha(dia)
        return 200, {
            "fecha": dia.isoformat(),
            "total_seg": r["total"],
            "categorias": {c: s for c, s in r["categorias"]},
            "apps": {a: s for a, s in r["apps"]},
            "proyectos": {p: s for p, s in r.get("proyectos", [])},
        }

    def _comando(self, body):
        texto = str(body.get("texto", "") or "").strip()[:300]
        if not texto:
            return 400, {"error": "falta 'texto'"}
        resultado = self.app.ejecutar_comando_voz(texto)
        return (200, resultado) if resultado.get("ok") else (400, resultado)

    # ── servidor ────────────────────────────────────────────────────────────
    def arrancar(self):
        api = self

        class Handler(BaseHTTPRequestHandler):
            server_version = "Escudero/2.0"

            def log_message(self, fmt, *args):
                log.debug("api: " + fmt, *args)

            def _auth_ok(self):
                return self.headers.get("Authorization", "") == f"Bearer {api.token}"

            def _json(self, codigo, obj):
                datos = json.dumps(obj, ensure_ascii=False).encode("utf-8")
                self.send_response(codigo)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(datos)))
                self.end_headers()
                self.wfile.write(datos)

            def _body(self):
                try:
                    n = int(self.headers.get("Content-Length", 0))
                except ValueError:
                    return None
                if n > 64 * 1024:
                    return None
                try:
                    return json.loads(self.rfile.read(n) or b"{}")
                except (ValueError, OSError):
                    return None

            def _accion(self, fn, *args):
                """Ejecuta fn en el hilo principal y responde su (codigo, payload)."""
                try:
                    codigo, payload = api.app.desde_hilo(fn, *args)
                except Exception as e:
                    log.exception("fallo atendiendo %s", self.path)
                    codigo, payload = 500, {"error": str(e)}
                self._json(codigo, payload)

            def do_GET(self):
                if not self._auth_ok():
                    return self._json(401, {"error": "falta token (Bearer ~/.config/escudero/api.token)"})
                ruta = urlparse(self.path)
                if ruta.path == "/status":
                    return self._accion(api._estado)
                if ruta.path == "/cronica/resumen":
                    return self._accion(api._resumen_cronica, ruta.query)
                self._json(404, {"error": "ruta desconocida",
                                 "rutas": ["/status", "/cronica/resumen", "/foco", "/comando"]})

            def do_POST(self):
                if not self._auth_ok():
                    return self._json(401, {"error": "falta token (Bearer ~/.config/escudero/api.token)"})
                body = self._body()
                if body is None:
                    return self._json(400, {"error": "cuerpo JSON inválido o demasiado grande"})
                ruta = urlparse(self.path).path
                if ruta == "/foco":
                    return self._accion(api._fijar_foco, body)
                if ruta == "/comando":
                    return self._accion(api._comando, body)
                self._json(404, {"error": "ruta desconocida"})

        try:
            self._httpd = ThreadingHTTPServer(("127.0.0.1", self.puerto), Handler)
        except OSError as e:
            log.warning("API local no pudo abrir 127.0.0.1:%s (%s)", self.puerto, e)
            self._httpd = None
            return False
        if self.puerto == 0:      # puerto efímero (tests): el SO elige uno libre
            self.puerto = self._httpd.server_address[1]
        threading.Thread(target=self._httpd.serve_forever, daemon=True,
                         name="escudero-api").start()
        log.info("API local en http://127.0.0.1:%s (token en %s)", self.puerto, RUTA_TOKEN)
        return True

    def parar(self):
        if self._httpd is not None:
            try:
                self._httpd.shutdown()
                self._httpd.server_close()
            except Exception:
                pass
            self._httpd = None

