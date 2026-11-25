# Lector — el módulo "TextSniper" de Escudero: ⌃⌥T, eliges una zona de la
# pantalla (o una ventana, con la barra espaciadora) y su texto queda copiado.
# También lee la imagen que tengas copiada o un archivo: imágenes y PDF (si el
# PDF ya trae texto se saca tal cual; si es escaneado, se reconocen sus páginas).
# Todo local con Vision de Apple; el servidor Unlimited-OCR es opcional y, si no
# responde, se usa Vision en su lugar.

import base64
import json
import logging
import os
import subprocess
import tempfile
from pathlib import Path

log = logging.getLogger("escudero.lector")

try:
    from AppKit import NSPasteboard
except Exception:
    NSPasteboard = None

try:
    import Quartz
except Exception:
    Quartz = None

EXTENSIONES_IMAGEN = (".png", ".jpg", ".jpeg", ".tiff", ".tif", ".heic", ".webp",
                      ".gif", ".bmp")
MAX_PAGINAS_PDF = 20
AJUSTES_GRABACION = "x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture"

# ── Unlimited-OCR (Baidu, servidor SGLang local, opcional) ────────────────
UNLIMITED_OCR_URL = "http://127.0.0.1:10000/v1/chat/completions"
UNLIMITED_OCR_MODEL = "Unlimited-OCR"
UNLIMITED_OCR_PROMPT = "document parsing."
UNLIMITED_OCR_TIMEOUT = 120


# ── permiso de Grabación de pantalla ────────────────────────────────────
def permiso_pantalla():
    """Sin «Grabación de pantalla», macOS entrega capturas con solo el fondo de
    escritorio: el reconocimiento no encuentra nada y parece que falla."""
    if Quartz is None:
        return False
    try:
        return bool(Quartz.CGPreflightScreenCaptureAccess())
    except Exception:
        return True          # macOS sin esta API: no se puede saber, se intenta


def pedir_permiso_pantalla():
    """La primera vez macOS enseña su diálogo; después solo vale ir a Ajustes."""
    try:
        if Quartz is not None:
            Quartz.CGRequestScreenCaptureAccess()
    except Exception:
        pass
    subprocess.Popen(["open", AJUSTES_GRABACION],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


# ── de dónde sale la imagen ─────────────────────────────────────────────
def capturar_zona(timeout=180):
    """Deja elegir una zona de la pantalla. Devuelve (png, error);
    (None, None) si el usuario canceló con Esc."""
    fd, ruta = tempfile.mkstemp(prefix="escudero-lector-", suffix=".png")
    os.close(fd)
    os.unlink(ruta)            # screencapture no escribe nada si se cancela
    try:
        # -i: elegir zona (barra espaciadora: ventana) · -x: sin sonido · -o: sin sombra
        subprocess.run(["/usr/sbin/screencapture", "-i", "-x", "-o", ruta],
                       capture_output=True, timeout=timeout)
        if not os.path.exists(ruta) or os.path.getsize(ruta) == 0:
            return None, None
        return Path(ruta).read_bytes(), None
    except subprocess.TimeoutExpired:
        return None, "Tardaste demasiado en elegir la zona."
    except OSError as e:
        return None, f"No pude hacer la captura: {e}"
    finally:
        try:
            os.unlink(ruta)
        except OSError:
            pass


def imagen_portapapeles():
    """La imagen copiada (captura con ⌘⇧⌃4, «Copiar imagen»…) o un archivo de
    imagen copiado en el Finder. Devuelve (datos, error)."""
    if NSPasteboard is None:
        return None, "AppKit no disponible."
    pb = NSPasteboard.generalPasteboard()
    for tipo in ("public.png", "public.tiff", "public.jpeg"):
        datos = pb.dataForType_(tipo)
        if datos:
            return bytes(datos), None
    url = pb.stringForType_("public.file-url")
    if url:
        from urllib.parse import unquote, urlparse
        ruta = unquote(urlparse(str(url)).path)
        if ruta.lower().endswith(EXTENSIONES_IMAGEN + (".pdf",)):
            return ruta, None          # una ruta: leer_archivo sabe qué hacer
    return None, "No hay ninguna imagen copiada. Usa ⌃⌥T para elegir una zona de la pantalla."


# ── reconocer ───────────────────────────────────────────────────────────
def ocr_vision(datos):
    """Texto de unos bytes de imagen con Vision (es + en). Devuelve (texto, error)."""
    try:
        from Vision import VNImageRequestHandler, VNRecognizeTextRequest
    except Exception:
        return None, "Vision no disponible (falta pyobjc-framework-Vision)."
    try:
        handler = VNImageRequestHandler.alloc().initWithData_options_(datos, {})
        peticion = VNRecognizeTextRequest.alloc().init()
        peticion.setRecognitionLevel_(0)          # preciso, no rápido
        peticion.setUsesLanguageCorrection_(True)
        try:
            peticion.setRecognitionLanguages_(["es-ES", "en-US"])
        except Exception:
            pass
        ok = handler.performRequests_error_([peticion], None)
        if isinstance(ok, tuple):        # pyobjc devuelve (bool, NSError)
            ok = ok[0]
        if not ok:
            return None, "Vision no pudo procesar la imagen."
        lineas = []
        for obs in (peticion.results() or []):
            candidatos = obs.topCandidates_(1)
            if candidatos and len(candidatos):
                lineas.append(str(candidatos[0].string()))
        if not lineas:
            return None, "No he encontrado texto en la imagen."
        return "\n".join(lineas), None
    except Exception as e:
        log.exception("fallo en Vision")
        return None, f"El reconocimiento falló: {e}"


ocr_datos = ocr_vision        # nombre antiguo (lo usa la condición contenido_regex de Ordenar)


def ocr_unlimited(datos):
    """Texto con el servidor Unlimited-OCR local. Devuelve (texto, error)."""
    try:
        import urllib.request
        payload = {
            "model": UNLIMITED_OCR_MODEL,
            "messages": [{"role": "user", "content": [
                {"type": "text", "text": UNLIMITED_OCR_PROMPT},
                {"type": "image_url", "image_url": {
                    "url": "data:image/png;base64," + base64.b64encode(bytes(datos)).decode()}}]}],
            "temperature": 0,
            "stream": False,
        }
        req = urllib.request.Request(UNLIMITED_OCR_URL, data=json.dumps(payload).encode(),
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=UNLIMITED_OCR_TIMEOUT) as r:
            resultado = json.loads(r.read().decode("utf-8", "replace"))
        texto = resultado.get("choices", [{}])[0].get("message", {}).get("content", "")
        return (texto.strip(), None) if texto and texto.strip() else (None, "Unlimited-OCR no devolvió texto.")
    except Exception as e:
        return None, f"Unlimited-OCR no responde ({e.__class__.__name__})."


def reconocer(datos, motor="vision"):
    """Texto de una imagen con el motor elegido; si Unlimited-OCR no está, Vision."""
    if motor == "unlimited":
        texto, err = ocr_unlimited(datos)
        if texto:
            return texto, None
        log.info("Unlimited-OCR falló (%s); uso Vision", err)
    return ocr_vision(datos)


def _texto_pdf(ruta, motor):
    if Quartz is None:
        return None, "PDFKit no disponible."
    from Foundation import NSURL
    doc = Quartz.PDFDocument.alloc().initWithURL_(NSURL.fileURLWithPath_(str(ruta)))
    if doc is None:
        return None, "No pude abrir ese PDF."
    texto = str(doc.string() or "").strip()
    if len(texto) >= 20:                  # el PDF ya trae texto: tal cual, sin reconocer
        return texto, None
    partes = []
    for i in range(min(doc.pageCount(), MAX_PAGINAS_PDF)):
        pagina = doc.pageAtIndex_(i)
        caja = pagina.boundsForBox_(0)    # kPDFDisplayBoxMediaBox
        imagen = pagina.thumbnailOfSize_forBox_((caja.size.width * 2, caja.size.height * 2), 0)
        datos = imagen.TIFFRepresentation() if imagen is not None else None
        if datos:
            t, _err = reconocer(datos, motor)
            if t:
                partes.append(t)
    if not partes:
        return None, "No he encontrado texto en ese PDF."
    return "\n\n".join(partes), None


def leer_archivo(ruta, motor="vision"):
    """Texto de una imagen o un PDF del disco. Devuelve (texto, error)."""
    ruta = Path(str(ruta))
    if not ruta.is_file():
        return None, f"No encuentro «{ruta.name}»."
    ext = ruta.suffix.lower()
    try:
        if ext == ".pdf":
            return _texto_pdf(ruta, motor)
        if ext in EXTENSIONES_IMAGEN:
            return reconocer(ruta.read_bytes(), motor)
    except Exception as e:
        log.exception("fallo leyendo %s", ruta)
        return None, f"No pude leer «{ruta.name}»: {e}"
    return None, f"«{ruta.name}» no es una imagen ni un PDF."


def leer(origen, motor="vision"):
    """Texto de bytes de imagen o de una ruta (lo que devuelve imagen_portapapeles)."""
    if isinstance(origen, (str, os.PathLike)):
        return leer_archivo(origen, motor)
    return reconocer(origen, motor)


def elegir_archivo():
    """Panel nativo para elegir una imagen o un PDF. Solo desde el hilo principal."""
    from AppKit import NSOpenPanel
    panel = NSOpenPanel.openPanel()
    panel.setCanChooseFiles_(True)
    panel.setCanChooseDirectories_(False)
    panel.setAllowsMultipleSelection_(False)
    panel.setAllowedFileTypes_([e.lstrip(".") for e in EXTENSIONES_IMAGEN] + ["pdf"])
    panel.setTitle_("Leer texto de una imagen o un PDF")
    panel.setPrompt_("Leer texto")
    if panel.runModal() != 1:             # NSModalResponseOK
        return None
    urls = panel.URLs()
    return str(urls[0].path()) if urls else None
