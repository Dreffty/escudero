# Crónica — el módulo "Rize" de Escudero: cada 5 s apunta qué app tienes
# delante (y el título de ventana, si le diste permiso de Accesibilidad),
# lo categoriza y lo guarda en SQLite. Con idle de más de 3 minutos o pantalla
# bloqueada no cuenta nada. Todo se queda en tu disco.
#
# Cómo se categoriza, en este orden:
#   1. tus reglas por título de ventana (Brave con «Disney+» → Ocio)
#   2. tus reglas por nombre de app
#   3. navegador sin pista en el título → «Navegación»
#   4. lo que la propia app dice que es (su Info.plist: juego, herramienta de
#      desarrollo, red social…): así una app nueva no cae en «Otros»
#   5. «Otros»
# Si cambian las reglas, el historial se reclasifica solo (una vez).

import hashlib
import json
import logging
import re
import sqlite3
import subprocess
import time
from datetime import date, datetime, timedelta
from pathlib import Path

log = logging.getLogger("escudero.cronica")

try:
    from AppKit import NSWorkspace
    from Foundation import NSBundle
except Exception:
    NSWorkspace = NSBundle = None

try:
    import Quartz
except Exception:
    Quartz = None

try:
    from ApplicationServices import (AXIsProcessTrusted, AXUIElementCopyAttributeValue,
                                     AXUIElementCreateApplication)
    _AX = True
except Exception:
    _AX = False

NAVEGADORES = ("com.apple.safari", "com.google.chrome", "org.mozilla.firefox",
               "company.thebrowser.browser", "com.brave.browser", "com.microsoft.edgemac",
               "com.vivaldi.vivaldi")

COLORES = {"Código": "#4f8ef7", "Diseño": "#b06ef7", "IA": "#f7a04f", "Comunicación": "#4fd0a7",
           "Docs": "#e8c94f", "Estudio": "#7c8cf8", "Negocio": "#3fb8c9", "Ocio": "#f76e8e",
           "Navegación": "#8fa3b8", "Otros": "#6b7684"}

# Lo que declara cada app en su Info.plist (LSApplicationCategoryType), sin el
# prefijo «public.app-category.». Los «*-games» cuentan como «games».
CATEGORIA_DECLARADA = {
    "games": "Ocio", "entertainment": "Ocio", "music": "Ocio", "sports": "Ocio",
    "developer-tools": "Código",
    "social-networking": "Comunicación",
    "graphics-design": "Diseño", "photography": "Diseño", "video": "Diseño",
    "education": "Estudio",
    "productivity": "Docs", "business": "Docs", "reference": "Docs", "finance": "Docs",
}
# Diálogos del sistema que salen un momento (contraseña, avisos): no son tiempo de nada.
SISTEMA_SIN_CONTAR = ("com.apple.loginwindow", "com.apple.SecurityAgent",
                      "com.apple.UserNotificationCenter", "com.apple.CoreServicesUIAgent",
                      "com.apple.notificationcenterui", "com.apple.controlcenter",
                      "com.apple.universalaccessAuthWarn", "com.apple.TCC")
# Sube cuando cambia CÓMO se categoriza, para reclasificar el historial.
_VERSION_CATEGORIAS = 2
_declaradas = {}


def categoria_declarada(bundle):
    """La categoría que la propia app dice ser, ya traducida («Ocio», «Código»…)."""
    if not bundle or NSWorkspace is None:
        return ""
    if bundle in _declaradas:
        return _declaradas[bundle]
    cat = ""
    try:
        url = NSWorkspace.sharedWorkspace().URLForApplicationWithBundleIdentifier_(bundle)
        info = NSBundle.bundleWithURL_(url).infoDictionary() if url is not None else None
        tipo = str((info or {}).get("LSApplicationCategoryType") or "")
        tipo = tipo.replace("public.app-category.", "").lower()
        if tipo.endswith("-games"):
            tipo = "games"
        cat = CATEGORIA_DECLARADA.get(tipo, "")
    except Exception:
        cat = ""
    _declaradas[bundle] = cat
    return cat


def fmt_dur(seg):
    seg = int(seg or 0)
    h, m = seg // 3600, (seg % 3600) // 60
    if h:
        return f"{h}h {m:02d}m"
    if m:
        return f"{m}m"
    return f"{seg}s"


def categorizar(categorias, app, titulo, bundle="", declarada=""):
    """Tus reglas (título, luego app); navegador sin pista → «Navegación»; si
    no, lo que la app declara ser (`declarada`); lo demás → «Otros»."""
    app_l = (app or "").lower()
    tit_l = (titulo or "").lower()
    bun_l = (bundle or "").lower()
    if tit_l:
        for cat, reglas in categorias.items():
            for palabra in (reglas or {}).get("titulos", []) or []:
                if str(palabra).lower() in tit_l:
                    return cat
    for cat, reglas in categorias.items():
        for nombre in (reglas or {}).get("apps", []) or []:
            n = str(nombre).lower()
            if not n:
                continue
            if len(n) <= 3:                    # nombres cortos («TV»): solo igualdad exacta
                if app_l == n:
                    return cat
            elif n in app_l or n in bun_l:
                return cat
    if any(b in bun_l for b in NAVEGADORES):
        return "Navegación"
    return declarada or "Otros"


# ── detección de proyecto (Fase 3.1: prepara la integración con ForgeDesk) ──
_APPS_CODIGO = ("code", "cursor", "xcode", "terminal", "iterm", "ghostty", "warp",
                "sublime", "zed", "nova", "simulator")


def _raiz_git(directorio: Path) -> str:
    """Nombre de la carpeta que contiene .git subiendo desde `directorio` ('' si ninguna)."""
    try:
        d = Path(directorio).resolve()
    except OSError:
        return ""
    for _ in range(10):
        if (d / ".git").exists():
            return d.name
        if d.parent == d:
            break
        d = d.parent
    return ""


def _proyecto_por_git(pid) -> str:
    """Repo Git del directorio de trabajo de la app frontal (editores/terminales)."""
    if not pid:
        return ""
    try:
        r = subprocess.run(["lsof", "-a", "-p", str(int(pid)), "-d", "cwd", "-Fn"],
                           capture_output=True, text=True, timeout=1.5)
    except Exception:
        return ""
    for linea in r.stdout.splitlines():
        if linea.startswith("n") and linea[1:].startswith("/"):
            nombre = _raiz_git(Path(linea[1:]))
            if nombre:
                return nombre
    return ""


_SEPARADORES_TITULO = (" — ", " – ", " —— ", " • ", " · ")


def detectar_proyecto(app: str, titulo: str, bundle: str = "", pid: int = 0) -> str:
    """Proyecto activo: «main.py — valorforge» → «valorforge»; si no, el repo Git
    del cwd de la app frontal (terminales/editores). '' cuando no hay pista."""
    app_l = (app or "").lower()
    if not any(a in app_l or a in (bundle or "").lower() for a in _APPS_CODIGO):
        return ""
    for parte in re.split("|".join(re.escape(s) for s in _SEPARADORES_TITULO), titulo or ""):
        p = parte.strip()
        if 2 <= len(p) <= 60 and "." not in p and " " not in p \
                and not p.startswith(("http", "~/", "/")):
            return p
    return _proyecto_por_git(pid)


class Cronica:
    def __init__(self, cfg, raiz_datos):
        self.pausada = False
        self._buffer = []
        self._db = None
        self.raiz = Path(raiz_datos)
        self.db_path = self.raiz / "cronica.db"
        self.ax_ok = False
        if _AX:
            try:
                self.ax_ok = bool(AXIsProcessTrusted())
            except Exception:
                self.ax_ok = False
        self.actualizar_config(cfg)

    def actualizar_config(self, cfg):
        c = cfg.get("cronica", {}) or {}
        self.intervalo = int(c.get("intervalo_seg", 5))
        self.idle_max = int(c.get("idle_seg", 180))
        self.categorias = c.get("categorias", {}) or {}
        try:
            self.recategorizar_si_cambio()
        except Exception:
            log.exception("no pude reclasificar el historial")

    # ── reclasificar el historial cuando cambian las reglas ───────────────
    def _firma_reglas(self):
        texto = json.dumps({"v": _VERSION_CATEGORIAS, "c": self.categorias},
                           sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(texto.encode()).hexdigest()

    def recategorizar_si_cambio(self):
        """Vuelve a categorizar todo lo guardado si las reglas no son las de la
        última vez: «Hoy» y los informes siempre cuentan con las reglas de ahora."""
        db = self._con()
        db.execute("CREATE TABLE IF NOT EXISTS meta (clave TEXT PRIMARY KEY, valor TEXT)")
        firma = self._firma_reglas()
        fila = db.execute("SELECT valor FROM meta WHERE clave='reglas'").fetchone()
        if fila and fila[0] == firma:
            return 0
        self.volcar()
        cambios, memo = {}, {}
        for rowid, app, bundle, titulo, cat in db.execute(
                "SELECT rowid, app, bundle, titulo, cat FROM muestras"):
            clave = (app, bundle, titulo)
            if clave not in memo:
                memo[clave] = categorizar(self.categorias, app, titulo, bundle,
                                          categoria_declarada(bundle))
            if memo[clave] != cat:
                cambios.setdefault(memo[clave], []).append(rowid)
        for cat, filas in cambios.items():
            db.executemany("UPDATE muestras SET cat=? WHERE rowid=?", [(cat, r) for r in filas])
        db.execute("INSERT OR REPLACE INTO meta (clave, valor) VALUES ('reglas', ?)", (firma,))
        db.commit()
        n = sum(len(v) for v in cambios.values())
        if n:
            log.info("crónica: %d muestras reclasificadas con las reglas nuevas", n)
        return n

    # ── infraestructura ────────────────────────────────────────────────────
    def _con(self):
        if self._db is None:
            self.raiz.mkdir(parents=True, exist_ok=True)
            self._db = sqlite3.connect(self.db_path, check_same_thread=False)
            self._db.execute("PRAGMA journal_mode=WAL")
            self._db.execute("""CREATE TABLE IF NOT EXISTS muestras (
                ts INTEGER, app TEXT, bundle TEXT, titulo TEXT, cat TEXT, dur INTEGER)""")
            self._db.execute("CREATE INDEX IF NOT EXISTS idx_ts ON muestras(ts)")
            self._migrar_proyecto()
            self._db.commit()
        return self._db

    def _migrar_proyecto(self):
        """Fase 3.1: columna `proyecto` añadida a posteriori (ALTER suave)."""
        cols = [f[1] for f in self._db.execute("PRAGMA table_info(muestras)")]
        if "proyecto" not in cols:
            self._db.execute("ALTER TABLE muestras ADD COLUMN proyecto TEXT DEFAULT ''")

    def _idle(self):
        if not Quartz:
            return 0.0
        try:
            return float(Quartz.CGEventSourceSecondsSinceLastEventType(
                Quartz.kCGEventSourceStateHIDSystemState, int(Quartz.kCGAnyInputEventType)))
        except Exception:
            return 0.0

    def _bloqueada(self):
        if not Quartz:
            return False
        try:
            d = Quartz.CGSessionCopyCurrentDictionary()
            return bool(d and d.get("CGSSessionScreenIsLocked", 0))
        except Exception:
            return False

    def _titulo(self, pid):
        if not self.ax_ok:
            return ""
        try:
            app = AXUIElementCreateApplication(pid)
            err, ventana = AXUIElementCopyAttributeValue(app, "AXFocusedWindow", None)
            if err or ventana is None:
                return ""
            err, titulo = AXUIElementCopyAttributeValue(ventana, "AXTitle", None)
            return str(titulo) if (not err and titulo) else ""
        except Exception:
            return ""

    # ── muestreo ───────────────────────────────────────────────────────────
    def muestrear(self):
        """Una muestra de 5 s. Llamar desde un timer; barato (~1 ms)."""
        if self.pausada or NSWorkspace is None:
            return None
        if self._bloqueada() or self._idle() >= self.idle_max:
            return None
        fr = NSWorkspace.sharedWorkspace().frontmostApplication()
        if fr is None:
            return None
        app = str(fr.localizedName() or "")
        bundle = str(fr.bundleIdentifier() or "")
        if not app or bundle in SISTEMA_SIN_CONTAR:
            return None
        pid = fr.processIdentifier()
        titulo = self._titulo(pid)
        cat = categorizar(self.categorias, app, titulo, bundle, categoria_declarada(bundle))
        try:
            proyecto = detectar_proyecto(app, titulo, bundle, pid)
        except Exception:
            proyecto = ""
        fila = (int(time.time()), app, bundle, titulo[:200], cat, self.intervalo, proyecto)
        self._buffer.append(fila)
        if len(self._buffer) >= 12:            # ~1 vez por minuto
            self.volcar()
        return fila

    def volcar(self):
        if not self._buffer:
            return
        try:
            db = self._con()
            if len(self._buffer[0]) == 6:      # buffer antiguo sin proyecto (tests)
                self._buffer = [f + ("",) for f in self._buffer]
            db.executemany("INSERT INTO muestras VALUES (?,?,?,?,?,?,?)", self._buffer)
            db.commit()
            self._buffer = []
        except sqlite3.Error as e:
            log.warning("No pude volcar muestras: %s", e)

    # ── consultas ──────────────────────────────────────────────────────────
    def _medianoche(self, dia=None):
        return int(datetime.combine(dia or date.today(), datetime.min.time()).timestamp())

    def resumen_hoy(self):
        return self.resumen_fecha()

    def resumen_fecha(self, dia=None):
        """Resumen de un día (date o None=hoy): total, categorías, apps y proyectos.
        Este dict es el contrato del endpoint GET /cronica/resumen de la API."""
        self.volcar()
        m = self._medianoche(dia)
        fin = m + 86400
        db = self._con()
        cats = db.execute("SELECT cat, SUM(dur) FROM muestras WHERE ts>=? AND ts<? "
                          "GROUP BY cat ORDER BY 2 DESC", (m, fin)).fetchall()
        apps = db.execute("SELECT app, SUM(dur) FROM muestras WHERE ts>=? AND ts<? "
                          "GROUP BY app ORDER BY 2 DESC LIMIT 12", (m, fin)).fetchall()
        proyectos = db.execute("SELECT proyecto, SUM(dur) FROM muestras "
                               "WHERE ts>=? AND ts<? AND proyecto != '' "
                               "GROUP BY proyecto ORDER BY 2 DESC", (m, fin)).fetchall()
        return {"total": sum(s for _, s in cats), "categorias": cats, "apps": apps,
                "proyectos": proyectos}

    # ── informe HTML ───────────────────────────────────────────────────────
    def informe_html(self):
        """Genera datos/informe-AAAAMMDD.html (autocontenido) y devuelve la ruta."""
        self.volcar()
        db = self._con()
        hoy = date.today()
        m = self._medianoche(hoy)

        r = self.resumen_hoy()
        horas = dict(db.execute(
            "SELECT CAST(strftime('%H', ts, 'unixepoch', 'localtime') AS INTEGER), SUM(dur) "
            "FROM muestras WHERE ts>=? GROUP BY 1", (m,)).fetchall())
        top = db.execute(
            "SELECT app, titulo, cat, SUM(dur) d FROM muestras WHERE ts>=? "
            "GROUP BY app, titulo ORDER BY d DESC LIMIT 15", (m,)).fetchall()
        hace7 = self._medianoche(hoy - timedelta(days=6))
        semana = db.execute(
            "SELECT date(ts,'unixepoch','localtime') dia, SUM(dur) FROM muestras "
            "WHERE ts>=? GROUP BY dia ORDER BY dia", (hace7,)).fetchall()

        def color(cat):
            return COLORES.get(cat, COLORES["Otros"])

        filas_cat = "".join(
            f"<div class='fila'><span class='eti'>{c}</span>"
            f"<div class='pista'><div class='barra' style='width:{(s / r['total'] * 100) if r['total'] else 0:.1f}%;"
            f"background:{color(c)}'></div></div><span class='dur'>{fmt_dur(s)}</span></div>"
            for c, s in r["categorias"])

        max_h = max(list(horas.values()) or [1])
        barras_horas = "".join(
            f"<div class='hcol'><div class='hbar' style='height:{horas.get(h, 0) / max_h * 100:.0f}%'"
            f" title='{h:02d}h — {fmt_dur(horas.get(h, 0))}'></div><span>{h:02d}</span></div>"
            for h in range(24))

        filas_top = "".join(
            f"<tr><td><span class='punto' style='background:{color(c)}'></span>{a}</td>"
            f"<td class='tit'>{(t or '—')[:70]}</td><td class='dur'>{fmt_dur(d)}</td></tr>"
            for a, t, c, d in top)

        filas_semana = "".join(
            f"<tr><td>{dia}</td><td class='dur'>{fmt_dur(s)}</td></tr>" for dia, s in semana)

        filas_proy = "".join(
            f"<div class='fila'><span class='eti'>{p}</span>"
            f"<div class='pista'><div class='barra' style='width:{(s / r['total'] * 100) if r['total'] else 0:.1f}%;"
            f"background:#4f8ef7'></div></div><span class='dur'>{fmt_dur(s)}</span></div>"
            for p, s in r.get("proyectos", []))

        html = f"""<!doctype html><html lang="es"><head><meta charset="utf-8">
<title>Crónica — {hoy.strftime('%d/%m/%Y')}</title>
<style>
:root {{ --fondo:#fff; --tinta:#1c2733; --suave:#5b6b7b; --linea:#e5eaf0; --pista:#eef2f6; }}
@media (prefers-color-scheme: dark) {{
  :root {{ --fondo:#14181d; --tinta:#e8edf2; --suave:#93a1b0; --linea:#2a323b; --pista:#1f262e; }} }}
body {{ font: 15px/1.5 -apple-system, sans-serif; background:var(--fondo); color:var(--tinta);
       max-width:720px; margin:2rem auto; padding:0 1.2rem; }}
h1 {{ font-size:1.4rem; }} h2 {{ font-size:1.05rem; margin-top:2rem; color:var(--suave); }}
.total {{ font-size:2.2rem; font-weight:700; }}
.fila {{ display:flex; align-items:center; gap:.7rem; margin:.45rem 0; }}
.eti {{ width:8.5rem; }} .dur {{ color:var(--suave); font-variant-numeric:tabular-nums; }}
.pista {{ flex:1; background:var(--pista); border-radius:6px; height:14px; overflow:hidden; }}
.barra {{ height:100%; border-radius:6px; }}
.horas {{ display:flex; gap:3px; align-items:flex-end; height:90px; margin-top:.8rem; }}
.hcol {{ flex:1; display:flex; flex-direction:column; justify-content:flex-end; height:100%;
        text-align:center; font-size:9px; color:var(--suave); gap:2px; }}
.hbar {{ background:#4f8ef7; border-radius:3px 3px 0 0; min-height:1px; }}
table {{ width:100%; border-collapse:collapse; margin-top:.6rem; }}
td {{ padding:.35rem .4rem; border-bottom:1px solid var(--linea); }}
.tit {{ color:var(--suave); font-size:.85rem; }}
.punto {{ display:inline-block; width:9px; height:9px; border-radius:50%; margin-right:.5rem; }}
td.dur {{ text-align:right; white-space:nowrap; }}
</style></head><body>
<h1>📖 Crónica del {hoy.strftime('%d/%m/%Y')}</h1>
<div class="total">{fmt_dur(r['total'])}</div>
<div style="color:var(--suave)">de actividad real frente al Mac{'' if self.ax_ok else ' · (sin permiso de Accesibilidad: solo apps, sin títulos)'}</div>
<h2>Por categoría</h2>{filas_cat or '<p>Sin datos todavía.</p>'}
{('<h2>Por proyecto</h2>' + filas_proy) if filas_proy else ''}
<h2>Por horas</h2><div class="horas">{barras_horas}</div>
<h2>Top 15 (app · ventana)</h2><table>{filas_top}</table>
<h2>Últimos 7 días</h2><table>{filas_semana}</table>
<p style="color:var(--suave);font-size:.8rem;margin-top:2rem">Generado por Escudero 🛡 — todo local, nada sale de tu Mac.</p>
</body></html>"""
        ruta = self.raiz / f"informe-{hoy.strftime('%Y%m%d')}.html"
        ruta.write_text(html, encoding="utf-8")
        return ruta
