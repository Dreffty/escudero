# Ordenar — el módulo "Hazel" de Escudero: reglas declarativas sobre carpetas.
# Filosofía: conservador. Mover, nunca borrar (la papelera existe pero no viene
# activada en ninguna regla por defecto); colisiones con sufijo « 2»; lo recién
# llegado, lo que se sigue escribiendo y las descargas a medias no se tocan.
# Cada pasada real se puede deshacer desde el menú.
#
# Cómo se decide (lo mismo que enseña «Probar las reglas…»):
#   · Solo los archivos sueltos de la carpeta (las subcarpetas no se tocan).
#   · Las reglas se miran EN ORDEN y gana la primera que casa.
#   · Dentro de `si`, se tienen que cumplir TODAS las condiciones; dentro de una
#     lista (tipos, extensiones, nombres, orígenes) basta con UNA.
#   · `excepto` descarta la regla si se cumple CUALQUIERA de sus condiciones.
#   · Las edades cuentan desde que el archivo LLEGÓ a la carpeta (la «fecha de
#     adición» del Finder), no desde su fecha de modificación: un zip antiguo
#     recién descomprimido no se va al desván nada más llegar.
#
# Historial en SQLite (datos/ordenar.db, tabla movimientos): deshacer por
# pasada, «Últimos movimientos» del menú y estadísticas.

import ctypes
import fnmatch
import html
import logging
import os
import plistlib
import re
import shutil
import sqlite3
import struct
import time
import unicodedata
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

log = logging.getLogger("escudero.ordenar")

# Extensiones de descargas a medio hacer: jamás se tocan
PARCIALES = (".crdownload", ".download", ".part", ".partial", ".aria2", ".tmp",
             ".opdownload", ".!qb")

# `tipo:` en una regla: nombres fáciles en vez de listas de extensiones.
TIPOS = {
    "imagen": ["png", "jpg", "jpeg", "gif", "webp", "heic", "heif", "svg", "tiff", "tif",
               "bmp", "avif", "ico", "raw", "cr2", "nef", "dng"],
    "video": ["mp4", "mov", "m4v", "webm", "mkv", "avi", "wmv", "flv", "3gp", "mts"],
    "audio": ["mp3", "m4a", "wav", "aac", "flac", "ogg", "aiff", "aif", "opus", "caf"],
    "pdf": ["pdf"],
    "documento": ["pdf", "doc", "docx", "odt", "rtf", "txt", "md", "pages", "xls", "xlsx",
                  "csv", "numbers", "ods", "ppt", "pptx", "key", "odp", "epub", "tex"],
    "comprimido": ["zip", "rar", "7z", "gz", "tgz", "tar", "bz2", "xz", "zst"],
    "instalador": ["dmg", "pkg", "mpkg", "iso", "app"],
    "codigo": ["py", "js", "ts", "jsx", "tsx", "json", "html", "css", "swift", "c", "cpp",
               "h", "java", "kt", "go", "rs", "rb", "php", "sh", "ipynb", "sql", "yaml", "yml"],
    "fuente": ["ttf", "otf", "woff", "woff2"],
}
CONDICIONES = ("tipo", "ext", "nombre", "patron", "regex", "origen", "edad_dias",
               "sin_tocar_dias", "mayor_mb", "menor_mb", "contenido_regex")
PLANTILLAS_DESTINO = ("año", "mes", "dia")

# Tipos en los que la condición `contenido_regex` sabe mirar:
# imágenes/PDF → reconocimiento local (lector); texto plano → lectura.
_CONTENIDO_OCR = (".png", ".jpg", ".jpeg", ".tiff", ".heic", ".webp", ".bmp", ".gif", ".pdf")
_CONTENIDO_TEXTO = (".txt", ".md", ".csv", ".json", ".log", ".xml", ".html")


def _normal(texto):
    """Minúsculas y sin tildes, para comparar nombres como los escribe una persona."""
    t = unicodedata.normalize("NFKD", str(texto or ""))
    return "".join(c for c in t if not unicodedata.combining(c)).casefold()


def _lista(valor):
    if valor is None:
        return []
    return [valor] if isinstance(valor, (str, int, float)) else list(valor)


def extensiones_de(si):
    """Extensiones que admite la regla por `tipo` y `ext` juntas ([] = cualquiera)."""
    exts = [str(e).lower().lstrip(".") for e in _lista(si.get("ext"))]
    for t in _lista(si.get("tipo")):
        exts += TIPOS.get(_normal(t), [])
    return exts


# ── metadatos del Finder (sin Spotlight y sin subprocesos) ─────────────────
_libc = ctypes.CDLL(None, use_errno=True)
_libc.getxattr.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_void_p,
                           ctypes.c_size_t, ctypes.c_uint32, ctypes.c_int]
_libc.getxattr.restype = ctypes.c_ssize_t


def _xattr(ruta, nombre):
    r, n = os.fsencode(str(ruta)), nombre.encode()
    tam = _libc.getxattr(r, n, None, 0, 0, 0)
    if tam <= 0:
        return None
    buf = ctypes.create_string_buffer(tam)
    leido = _libc.getxattr(r, n, buf, tam, 0, 0)
    return buf.raw[:leido] if leido > 0 else None


def origenes(ruta):
    """Direcciones desde las que se descargó (lo que el Finder llama «De dónde»)."""
    crudo = _xattr(ruta, "com.apple.metadata:kMDItemWhereFroms")
    if not crudo:
        return []
    try:
        valor = plistlib.loads(crudo)
    except Exception:
        return []
    return [str(u) for u in _lista(valor) if u]


def _ultimo_uso(ruta):
    """Última vez que se abrió (com.apple.lastuseddate#PS: segundos + nanosegundos)."""
    crudo = _xattr(ruta, "com.apple.lastuseddate#PS")
    if not crudo or len(crudo) < 8:
        return 0.0
    try:
        return float(struct.unpack("<q", crudo[:8])[0])
    except struct.error:
        return 0.0


def llegada(ruta, st=None):
    """Cuándo llegó el archivo a esta carpeta: la «fecha de adición» del Finder.
    Sin ella, la de creación; nunca la de modificación, que un zip conserva."""
    try:
        from Foundation import NSURL, NSURLAddedToDirectoryDateKey
        ok, valor, _err = NSURL.fileURLWithPath_(str(ruta)).getResourceValue_forKey_error_(
            None, NSURLAddedToDirectoryDateKey, None)
        if ok and valor is not None:
            return float(valor.timeIntervalSince1970())
    except Exception:
        pass
    st = st or os.stat(ruta)
    return float(getattr(st, "st_birthtime", st.st_ctime))


class Ordenar:
    def __init__(self, cfg, raiz_datos):
        o = cfg.get("ordenar", {}) or {}
        self.activado = bool(o.get("activado", True))
        self.intervalo = int(o.get("intervalo_seg", 60))
        self.edad_minima = int(o.get("edad_minima_seg", 120))
        self.avisar = bool(o.get("avisar", True))
        self.carpetas = o.get("carpetas", []) or []
        self.ultima_pasada = None        # (hora "HH:MM", nº movimientos)
        self.raiz = Path(raiz_datos)
        self.db_path = self.raiz / "ordenar.db"
        self._db = None
        self._pasada_deshacer = 0
        self._cache_contenido = {}
        self._migrar_log_texto()         # importa datos/ordenar.log si existe
        self.movimientos_deshacer = self._cargar_deshacer()

    # ── persistencia SQLite ────────────────────────────────────────────────
    @property
    def registro(self):
        """Compat con versiones anteriores (el menú «Ver registro…»)."""
        return self.db_path

    def _con(self):
        if self._db is None:
            self.raiz.mkdir(parents=True, exist_ok=True)
            self._db = sqlite3.connect(self.db_path, check_same_thread=False)
            self._db.execute("PRAGMA journal_mode=WAL")
            self._db.execute("""CREATE TABLE IF NOT EXISTS movimientos (
                id INTEGER PRIMARY KEY,
                ts INTEGER NOT NULL,
                origen TEXT NOT NULL,
                destino TEXT NOT NULL,
                regla TEXT NOT NULL,
                pasada_id INTEGER NOT NULL,
                deshecho INTEGER DEFAULT 0)""")
            self._db.execute("CREATE INDEX IF NOT EXISTS idx_pasada ON movimientos(pasada_id)")
            self._db.commit()
        return self._db

    def _migrar_log_texto(self):
        """Importa el histórico de datos/ordenar.log (formato viejo) a SQLite.
        Se ejecuta una sola vez: el log queda renombrado a ordenar.log.importado."""
        viejo = self.raiz / "ordenar.log"
        if not viejo.exists() or self.db_path.exists():
            return
        patron = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})  (.+?)  →  (.+?)  \(regla: (.+)\)\s*$")
        try:
            lineas = viejo.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            return
        importados = 0
        try:
            db = self._con()
            for linea in lineas:
                m = patron.match(linea)
                if not m:
                    continue                # líneas «↩️ deshechos…» no se importan
                ts = int(time.mktime(time.strptime(m.group(1), "%Y-%m-%d %H:%M:%S")))
                db.execute("INSERT INTO movimientos (ts, origen, destino, regla, pasada_id, deshecho)"
                           " VALUES (?,?,?,?,?,1)", (ts, m.group(2), m.group(3), m.group(4), ts))
                importados += 1
            db.commit()
        except sqlite3.Error as e:
            log.warning("No pude importar ordenar.log: %s", e)
            return
        try:
            viejo.rename(self.raiz / "ordenar.log.importado")
        except OSError:
            pass
        if importados:
            log.info("ordenar.log histórico importado a SQLite: %d movimientos", importados)

    def _cargar_deshacer(self):
        """Movimientos deshacibles: los de la ÚLTIMA pasada no deshecha."""
        try:
            db = self._con()
            fila = db.execute("SELECT MAX(pasada_id) FROM movimientos WHERE deshecho=0").fetchone()
            if not fila or fila[0] is None:
                return []
            self._pasada_deshacer = fila[0]
            return [(d, o) for o, d in db.execute(
                "SELECT origen, destino FROM movimientos WHERE pasada_id=? AND deshecho=0",
                (fila[0],))]
        except sqlite3.Error:
            return []

    def registrar_pasada(self, movidos):
        """Inserta una pasada real en SQLite. Devuelve el pasada_id (0 si no hubo)."""
        if not movidos:
            return 0
        pasada_id = int(time.time())
        try:
            db = self._con()
            for origen, destino, regla in movidos:
                db.execute("INSERT INTO movimientos (ts, origen, destino, regla, pasada_id)"
                           " VALUES (?,?,?,?,?)",
                           (int(time.time()), str(origen), str(destino), str(regla), pasada_id))
            db.commit()
        except sqlite3.Error as e:
            log.warning("No pude registrar la pasada: %s", e)
        self._pasada_deshacer = pasada_id
        return pasada_id

    def historial(self, limite=50):
        """Últimos movimientos (historial queryable y estadísticas)."""
        try:
            return self._con().execute(
                "SELECT ts, origen, destino, regla, pasada_id, deshecho "
                "FROM movimientos ORDER BY id DESC LIMIT ?", (limite,)).fetchall()
        except sqlite3.Error:
            return []

    # ── condiciones ────────────────────────────────────────────────────────
    def _texto_contenido(self, ruta: Path) -> str:
        """Contenido textual del archivo: lectura directa para texto plano,
        reconocimiento local para imágenes y PDFs. '' si no aplica. Se guarda por
        (ruta, tamaño, fecha) para no repetir el reconocimiento en cada pasada."""
        ext = ruta.suffix.lower()
        try:
            st = ruta.stat()
            clave = (str(ruta), st.st_size, st.st_mtime)
            if clave in self._cache_contenido:
                return self._cache_contenido[clave]
            texto = ""
            if ext in _CONTENIDO_TEXTO:
                if st.st_size <= 512 * 1024:          # no leer tochos en una pasada
                    texto = ruta.read_text(encoding="utf-8", errors="replace")
            elif ext in _CONTENIDO_OCR:
                from lector import leer_archivo        # import perezoso: solo si la regla lo usa
                texto, err = leer_archivo(ruta)
                if err:
                    log.info("no pude leer el texto de %s: %s", ruta.name, err)
                texto = texto or ""
            if len(self._cache_contenido) > 500:
                self._cache_contenido.clear()
            self._cache_contenido[clave] = texto
            return texto
        except Exception as e:
            log.info("No pude leer contenido de %s: %s", ruta.name, e)
        return ""

    def _condicion(self, clave, valor, ruta: Path, ahora: float, info: dict) -> bool:
        """Una condición sobre un archivo. `info` guarda lo ya calculado."""
        nombre = ruta.name
        if clave in ("ext", "tipo"):
            exts = extensiones_de({clave: valor})
            return ruta.suffix.lower().lstrip(".") in exts
        if clave == "nombre":
            n = _normal(nombre)
            return any(_normal(v) in n for v in _lista(valor))
        if clave == "patron":
            return any(fnmatch.fnmatch(nombre.lower(), str(v).lower()) for v in _lista(valor))
        if clave == "regex":
            return re.search(str(valor), nombre, re.IGNORECASE) is not None
        if clave == "origen":
            if "origenes" not in info:
                info["origenes"] = [(urlparse(u).hostname or "").lower() for u in origenes(ruta)]
            dominios = [str(d).lower().lstrip(".") for d in _lista(valor)]
            return any(h == d or h.endswith("." + d) for h in info["origenes"] for d in dominios if h)
        if clave == "edad_dias":
            return (ahora - info["llegada"]) >= float(valor) * 86400
        if clave == "sin_tocar_dias":
            ultimo = max(info["llegada"], info["st"].st_mtime, _ultimo_uso(ruta))
            return (ahora - ultimo) >= float(valor) * 86400
        if clave == "mayor_mb":
            return info["st"].st_size >= float(valor) * 1024 * 1024
        if clave == "menor_mb":
            return info["st"].st_size < float(valor) * 1024 * 1024
        if clave == "contenido_regex":
            texto = self._texto_contenido(ruta)
            return bool(texto) and re.search(str(valor), texto, re.IGNORECASE) is not None
        return False

    def _cumple(self, ruta: Path, si: dict, ahora: float, info: dict = None, excepto: dict = None) -> bool:
        """`si`: todas sus condiciones (AND). `excepto`: ninguna de las suyas (OR)."""
        if info is None:
            st = ruta.stat()
            info = {"st": st, "llegada": llegada(ruta, st)}
        # las baratas primero: el reconocimiento de texto, solo si todo lo demás casa
        orden = sorted(si, key=lambda k: k == "contenido_regex")
        if not all(self._condicion(k, si[k], ruta, ahora, info) for k in orden):
            return False
        if excepto and any(self._condicion(k, v, ruta, ahora, info) for k, v in excepto.items()):
            return False
        return True

    def _destino_libre(self, carpeta: Path, nombre: str) -> Path:
        """Nombre libre en `carpeta`: si existe, prueba «nombre 2.ext», «nombre 3.ext»…"""
        destino = carpeta / nombre
        base, ext = os.path.splitext(nombre)
        n = 2
        while destino.exists():
            destino = carpeta / f"{base} {n}{ext}"
            n += 1
        return destino

    @staticmethod
    def _carpeta_destino(plantilla, cuando: float) -> Path:
        """«~/Downloads/Capturas/{año}-{mes}» con la fecha de llegada del archivo."""
        f = datetime.fromtimestamp(cuando)
        texto = str(plantilla).format_map({"año": f"{f.year}", "mes": f"{f.month:02d}",
                                           "dia": f"{f.day:02d}"})
        return Path(os.path.expanduser(texto))

    # ── la pasada ──────────────────────────────────────────────────────────
    def explicar(self):
        """Qué pasaría con cada archivo suelto, y por qué. Es la verdad que usa
        la pasada real y lo que enseña «Probar las reglas…»:
        [{carpeta, archivo, regla, destino, motivo}] (regla/destino None si no se mueve)."""
        ahora = time.time()
        filas = []
        for c in self.carpetas:
            raiz = Path(os.path.expanduser(str(c.get("ruta", "")))).resolve()
            if not raiz.is_dir():
                filas.append({"carpeta": str(raiz), "archivo": None, "regla": None,
                              "destino": None, "motivo": "la carpeta no existe"})
                continue
            reglas = c.get("reglas", []) or []
            try:
                entradas = sorted(raiz.iterdir(), key=lambda e: e.name.lower())
            except OSError as e:
                log.warning("No puedo listar %s: %s", raiz, e)
                continue
            for entrada in entradas:
                fila = {"carpeta": str(raiz), "archivo": entrada, "regla": None,
                        "destino": None, "motivo": ""}
                try:
                    if entrada.name.startswith("."):
                        continue                         # ocultos: ni se enseñan
                    if entrada.is_symlink() or not entrada.is_file():
                        continue                         # carpetas y enlaces: nunca se tocan
                    if entrada.suffix.lower() in PARCIALES:
                        fila["motivo"] = "descarga a medias"
                        filas.append(fila)
                        continue
                    st = entrada.stat()
                    info = {"st": st, "llegada": llegada(entrada, st)}
                    reciente = min(ahora - st.st_mtime, ahora - info["llegada"])
                    if reciente < self.edad_minima:
                        fila["motivo"] = f"recién llegado o aún se escribe (espera {self.edad_minima} s)"
                        filas.append(fila)
                        continue
                    for regla in reglas:
                        si = regla.get("si", {}) or {}
                        if not self._cumple(entrada, si, ahora, info, regla.get("excepto") or {}):
                            continue
                        hacer = regla.get("hacer", {}) or {}
                        fila["regla"] = str(regla.get("nombre", "?"))
                        if hacer.get("papelera"):
                            fila["destino"] = Path.home() / ".Trash"
                            fila["motivo"] = "a la papelera"
                        else:
                            destino = self._carpeta_destino(hacer["mover"], info["llegada"])
                            if entrada.parent.resolve() == destino.resolve():
                                fila["regla"], fila["motivo"] = None, "ya está en su sitio"
                            else:
                                fila["destino"] = destino
                                fila["motivo"] = "se mueve"
                        break                            # la primera regla que casa, gana
                    else:
                        fila["motivo"] = self._espera(entrada, reglas, ahora, info) or "ninguna regla casa"
                except OSError as e:
                    fila["motivo"] = f"no se puede leer ({e.strerror or e})"
                filas.append(fila)
        return filas

    def _espera(self, ruta, reglas, ahora, info):
        """Si una regla casaría salvo por la edad, lo dice: «esperando a …»."""
        for regla in reglas:
            si = regla.get("si", {}) or {}
            edades = {k: si[k] for k in ("edad_dias", "sin_tocar_dias") if k in si}
            resto = {k: v for k, v in si.items() if k not in edades}
            if not edades or not self._cumple(ruta, resto, ahora, info, regla.get("excepto") or {}):
                continue
            clave, dias = next(iter(edades.items()))
            if clave == "edad_dias":
                lleva = (ahora - info["llegada"]) / 86400
            else:
                lleva = (ahora - max(info["llegada"], info["st"].st_mtime, _ultimo_uso(ruta))) / 86400
            return f"esperando a «{regla.get('nombre', '?')}»: lleva {int(lleva)} de {int(float(dias))} días"
        return ""

    def _plan(self):
        """[(origen, carpeta_destino, regla)] de lo que se movería ahora mismo."""
        return [(f["archivo"], f["destino"], f["regla"] + (" → papelera" if f["motivo"] == "a la papelera" else ""))
                for f in self.explicar() if f["destino"] is not None]

    def pasada(self, en_seco=False):
        """Ejecuta (o simula, con en_seco=True) una pasada.
        Devuelve [(origen, destino_final, regla), ...]."""
        plan = self._plan()
        if en_seco:
            return [(o, d / o.name, r) for o, d, r in plan]

        movidos, deshacer = [], []
        for origen, carpeta_destino, regla in plan:
            try:
                carpeta_destino.mkdir(parents=True, exist_ok=True)
                destino = self._destino_libre(carpeta_destino, origen.name)
                # shutil.move: también entre discos (os.rename falla con EXDEV)
                shutil.move(str(origen), str(destino))
            except OSError as e:
                log.warning("No pude mover %s: %s", origen, e)
                continue
            movidos.append((origen, destino, regla))
            deshacer.append((str(destino), str(origen)))

        if movidos:
            self.movimientos_deshacer = deshacer
            self.registrar_pasada(movidos)   # historial queryable en SQLite
        self.ultima_pasada = (time.strftime("%H:%M"), len(movidos))
        return movidos

    def recientes(self, n=8):
        """Últimos movimientos que siguen en pie: [(ts, origen, destino, regla)]."""
        try:
            return self._con().execute(
                "SELECT ts, origen, destino, regla FROM movimientos WHERE deshecho=0 "
                "ORDER BY id DESC LIMIT ?", (n,)).fetchall()
        except sqlite3.Error:
            return []

    def informe_prueba(self):
        """datos/ordenar-prueba.html: cada archivo suelto, qué le pasaría y por qué."""
        filas = self.explicar()
        home = str(Path.home())

        def corto(ruta):
            r = str(ruta)
            return "~" + r[len(home):] if r.startswith(home) else r

        cuerpo = []
        for carpeta in dict.fromkeys(f["carpeta"] for f in filas):
            propias = [f for f in filas if f["carpeta"] == carpeta]
            cuerpo.append(f"<h2>{html.escape(corto(carpeta))}</h2>")
            sin_archivo = [f for f in propias if f["archivo"] is None]
            if sin_archivo:
                cuerpo.append(f"<p class='aviso'>{html.escape(sin_archivo[0]['motivo'])}</p>")
                continue
            if not propias:
                cuerpo.append("<p class='suave'>No hay archivos sueltos. Todo en su sitio.</p>")
                continue
            cuerpo.append("<table><tr><th>Archivo</th><th>Qué haría</th><th>Regla</th></tr>")
            for f in propias:
                if f["destino"] is not None:
                    accion = ("a la papelera" if f["motivo"] == "a la papelera"
                              else "→ " + html.escape(corto(f["destino"])))
                    clase = "mueve"
                else:
                    accion, clase = html.escape(f["motivo"]), "queda"
                cuerpo.append(f"<tr class='{clase}'><td>{html.escape(f['archivo'].name)}</td>"
                              f"<td>{accion}</td><td>{html.escape(f['regla'] or '—')}</td></tr>")
            cuerpo.append("</table>")
        n_mueve = sum(1 for f in filas if f["destino"] is not None)
        pagina = f"""<!doctype html><html lang="es"><head><meta charset="utf-8">
<title>Ordenar — prueba de reglas</title>
<style>
:root {{ --fondo:#fff; --tinta:#1c2733; --suave:#5b6b7b; --linea:#e5eaf0; --verde:#1f8a5b; --aviso:#b45309; }}
@media (prefers-color-scheme: dark) {{
  :root {{ --fondo:#14181d; --tinta:#e8edf2; --suave:#93a1b0; --linea:#2a323b; --verde:#4fd0a7; --aviso:#f5a524; }} }}
body {{ font: 15px/1.5 -apple-system, sans-serif; background:var(--fondo); color:var(--tinta);
       max-width:860px; margin:2rem auto; padding:0 1.2rem; }}
h1 {{ font-size:1.4rem; }} h2 {{ font-size:1.05rem; margin-top:2rem; color:var(--suave); }}
table {{ width:100%; border-collapse:collapse; }} th {{ text-align:left; color:var(--suave); font-weight:500; }}
td, th {{ padding:.4rem .5rem; border-bottom:1px solid var(--linea); vertical-align:top; }}
tr.mueve td:nth-child(2) {{ color:var(--verde); }} tr.queda td:nth-child(2) {{ color:var(--suave); }}
.suave {{ color:var(--suave); }} .aviso {{ color:var(--aviso); }}
</style></head><body>
<h1>Ordenar — qué haría ahora</h1>
<p class="suave">Ahora mismo se moverían {n_mueve} archivo{'s' if n_mueve != 1 else ''}. Las reglas se miran en orden
y gana la primera que casa; las edades cuentan desde que el archivo llegó a la carpeta.
Nada se ha movido todavía. Cambia las reglas en config.yaml y vuelve a probar.</p>
{''.join(cuerpo)}
</body></html>"""
        ruta = self.raiz / "ordenar-prueba.html"
        ruta.write_text(pagina, encoding="utf-8")
        return ruta

    def deshacer(self):
        """Devuelve a su sitio los archivos de la última pasada. Retorna cuántos volvieron."""
        n = 0
        for destino, origen in self.movimientos_deshacer:
            d, o = Path(destino), Path(origen)
            if not d.exists():
                continue
            try:
                o.parent.mkdir(parents=True, exist_ok=True)
                objetivo = self._destino_libre(o.parent, o.name)
                os.rename(d, objetivo)
                n += 1
            except OSError as e:
                log.warning("No pude deshacer %s: %s", destino, e)
        self.movimientos_deshacer = []
        if self._pasada_deshacer:
            try:
                self._con().execute("UPDATE movimientos SET deshecho=1 WHERE pasada_id=?",
                                    (self._pasada_deshacer,))
                self._con().commit()
            except sqlite3.Error as e:
                log.warning("No pude marcar la pasada como deshecha: %s", e)
            self._pasada_deshacer = 0
        return n
