# Tests del Lector (el "TextSniper"): imagen, PDF con texto, PDF escaneado, el
# respaldo de Vision, y los atajos globales (cada uno responde solo al suyo).
import ctypes
import time
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import lector  # noqa: E402

from AppKit import (NSApplication, NSBitmapImageFileTypePNG, NSBitmapImageRep, NSColor,  # noqa: E402
                    NSFont, NSFontAttributeName, NSForegroundColorAttributeName, NSImage,
                    NSMakeRect, NSRectFill, NSString)
from Foundation import NSMakePoint, NSMakeSize, NSURL  # noqa: E402
import Quartz  # noqa: E402

FRASE = "Práctica 2: sockets TCP, entrega el viernes"


def imagen_con_texto(texto=FRASE):
    img = NSImage.alloc().initWithSize_(NSMakeSize(760, 160))
    img.lockFocus()
    NSColor.whiteColor().set()
    NSRectFill(NSMakeRect(0, 0, 760, 160))
    NSString.stringWithString_(texto).drawAtPoint_withAttributes_(
        NSMakePoint(20, 64), {NSFontAttributeName: NSFont.systemFontOfSize_(30),
                              NSForegroundColorAttributeName: NSColor.blackColor()})
    img.unlockFocus()
    return img


def png(img):
    rep = NSBitmapImageRep.imageRepWithData_(img.TIFFRepresentation())
    return bytes(rep.representationUsingType_properties_(NSBitmapImageFileTypePNG, None))


class TestLector(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.carpeta = Path(self.dir.name)

    def test_lee_una_imagen(self):
        texto, err = lector.reconocer(png(imagen_con_texto()))
        self.assertIsNone(err)
        self.assertIn("sockets TCP", texto)
        self.assertIn("Práctica", texto, "las tildes tienen que salir bien")

    def test_imagen_sin_texto_lo_dice(self):
        vacia = NSImage.alloc().initWithSize_(NSMakeSize(200, 100))
        vacia.lockFocus()
        NSColor.whiteColor().set()
        NSRectFill(NSMakeRect(0, 0, 200, 100))
        vacia.unlockFocus()
        texto, err = lector.reconocer(png(vacia))
        self.assertIsNone(texto)
        self.assertIn("No he encontrado texto", err)

    def test_si_unlimited_no_responde_usa_vision(self):
        texto, err = lector.reconocer(png(imagen_con_texto()), motor="unlimited")
        self.assertIsNone(err)
        self.assertIn("sockets TCP", texto)

    def test_archivo_de_imagen(self):
        ruta = self.carpeta / "captura.png"
        ruta.write_bytes(png(imagen_con_texto()))
        texto, err = lector.leer_archivo(ruta)
        self.assertIsNone(err)
        self.assertIn("sockets TCP", texto)

    def test_pdf_con_texto_se_saca_tal_cual(self):
        ruta = self.carpeta / "apuntes.pdf"
        contexto = Quartz.CGPDFContextCreateWithURL(NSURL.fileURLWithPath_(str(ruta)),
                                                    Quartz.CGRectMake(0, 0, 595, 842), None)
        Quartz.CGContextBeginPage(contexto, None)
        from AppKit import NSGraphicsContext
        NSGraphicsContext.saveGraphicsState()
        NSGraphicsContext.setCurrentContext_(
            NSGraphicsContext.graphicsContextWithCGContext_flipped_(contexto, False))
        NSString.stringWithString_("Tema 6: árboles binarios de búsqueda").drawAtPoint_withAttributes_(
            NSMakePoint(50, 700), {NSFontAttributeName: NSFont.systemFontOfSize_(18)})
        NSGraphicsContext.restoreGraphicsState()
        Quartz.CGContextEndPage(contexto)
        Quartz.CGPDFContextClose(contexto)
        del contexto
        texto, err = lector.leer_archivo(ruta)
        self.assertIsNone(err)
        self.assertIn("árboles binarios", texto)

    def test_pdf_escaneado_se_reconoce(self):
        ruta = self.carpeta / "escaneado.pdf"
        pagina = Quartz.PDFPage.alloc().initWithImage_(imagen_con_texto())
        doc = Quartz.PDFDocument.alloc().init()
        doc.insertPage_atIndex_(pagina, 0)
        self.assertTrue(doc.writeToFile_(str(ruta)))
        self.assertLess(len(str(Quartz.PDFDocument.alloc().initWithURL_(
            NSURL.fileURLWithPath_(str(ruta))).string() or "").strip()), 20, "el PDF no debe traer texto")
        texto, err = lector.leer_archivo(ruta)
        self.assertIsNone(err)
        self.assertIn("sockets TCP", texto)

    def test_archivo_que_no_es_imagen(self):
        ruta = self.carpeta / "notas.txt"
        ruta.write_text("hola")
        texto, err = lector.leer_archivo(ruta)
        self.assertIsNone(texto)
        self.assertIn("no es una imagen ni un PDF", err)

    def test_archivo_que_no_existe(self):
        texto, err = lector.leer_archivo(self.carpeta / "nada.png")
        self.assertIsNone(texto)
        self.assertIn("No encuentro", err)


class TestAtajos(unittest.TestCase):
    """Dos atajos en la misma app: cada pulsación llega solo a su dueño."""

    def test_cada_atajo_responde_solo_al_suyo(self):
        import atajos
        from PyObjCTools import AppHelper
        NSApplication.sharedApplication().setActivationPolicy_(1)
        pulsados = []
        uno = atajos.AtajoGlobal(lambda: pulsados.append("uno"))
        dos = atajos.AtajoGlobal(lambda: pulsados.append("dos"))
        self.addCleanup(uno.quitar)
        self.addCleanup(dos.quitar)
        self.assertTrue(uno.registrar("ctrl+opt+shift+cmd+8")[0])
        self.assertTrue(dos.registrar("ctrl+opt+shift+cmd+9")[0])

        c = atajos._cargar_carbon()
        c.CreateEvent.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_double,
                                  ctypes.c_uint32, ctypes.POINTER(ctypes.c_void_p)]
        c.SetEventParameter.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32,
                                        ctypes.c_ulong, ctypes.c_void_p]
        c.SendEventToEventTarget.argtypes = [ctypes.c_void_p, ctypes.c_void_p]

        def pulsar(numero):
            ev = ctypes.c_void_p()
            c.CreateEvent(None, atajos._cuatro("keyb"), 5, 0.0, 0, ctypes.byref(ev))
            hk = atajos._EventHotKeyID(atajos._cuatro(atajos._FIRMA), numero)
            c.SetEventParameter(ev, atajos._cuatro("----"), atajos._cuatro("hkid"),
                                ctypes.sizeof(hk), ctypes.byref(hk))
            c.SendEventToEventTarget(ev, c.GetApplicationEventTarget())

        pulsar(uno.numero)
        pulsar(dos.numero)
        pulsar(dos.numero)
        AppHelper.callLater(0.3, AppHelper.stopEventLoop)
        AppHelper.runConsoleEventLoop()
        self.assertEqual(sorted(pulsados), ["dos", "dos", "uno"])


if __name__ == "__main__":
    unittest.main()


class TestLectorEnEscudero(unittest.TestCase):
    """El recorrido entero de ⌃⌥T en el código real de Escudero, con la captura
    simulada: permiso → captura → reconocer → portapapeles (entra en el historial)."""

    @classmethod
    def setUpClass(cls):
        import importlib.util
        cls.app = sys.modules.get("_escudero_core")
        if cls.app is None:
            spec = importlib.util.spec_from_file_location(
                "_escudero_core", Path(__file__).resolve().parents[1] / "escudero.py")
            cls.app = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(cls.app)
            sys.modules["_escudero_core"] = cls.app

    def falso(self):
        from types import SimpleNamespace
        from pergamino import Pergamino

        class PB:
            contenido = ""

            def clearContents(self):
                pass

            def setString_forType_(self, s, t):
                PB.contenido = s
                return True

        Escudero = self.app.Escudero
        yo = SimpleNamespace(cfg={"pergamino": {"motor_ocr": "vision"}}, _leyendo=False)
        yo.pergamino = Pergamino({"pergamino": {}})
        yo.pergamino._pb = PB()
        for nombre in ("_motor_ocr", "_en_segundo_plano", "_entregar_texto", "leer_pantalla"):
            setattr(yo, nombre, getattr(Escudero, nombre).__get__(yo))
        return yo, PB

    def esperar(self, condicion, segundos=8):
        from PyObjCTools import AppHelper
        fin = time.time() + segundos
        while time.time() < fin and not condicion():
            AppHelper.callLater(0.1, AppHelper.stopEventLoop)
            AppHelper.runConsoleEventLoop()

    def test_sin_permiso_lo_dice_y_no_captura(self):
        from unittest.mock import patch
        yo, PB = self.falso()
        with patch.object(lector, "permiso_pantalla", return_value=False), \
                patch.object(lector, "pedir_permiso_pantalla") as pedir, \
                patch.object(lector, "capturar_zona") as capturar, \
                patch.object(self.app, "notificar") as aviso:
            yo.leer_pantalla()
        pedir.assert_called_once()
        capturar.assert_not_called()
        self.assertIn("Grabación de pantalla", aviso.call_args[0][1])

    def test_zona_elegida_queda_copiada(self):
        from unittest.mock import patch
        yo, PB = self.falso()
        with patch.object(lector, "permiso_pantalla", return_value=True), \
                patch.object(lector, "capturar_zona", return_value=(png(imagen_con_texto()), None)), \
                patch.object(self.app, "notificar") as aviso:
            yo.leer_pantalla()
            self.esperar(lambda: aviso.called)
        self.assertIn("sockets TCP", PB.contenido)
        self.assertTrue(aviso.call_args[0][0].startswith("📸 Texto copiado"))
        self.assertFalse(yo._leyendo)

    def test_esc_no_hace_nada(self):
        from unittest.mock import patch
        yo, PB = self.falso()
        with patch.object(lector, "permiso_pantalla", return_value=True), \
                patch.object(lector, "capturar_zona", return_value=(None, None)), \
                patch.object(self.app, "notificar") as aviso:
            yo.leer_pantalla()
            self.esperar(lambda: not yo._leyendo, 3)
        aviso.assert_not_called()
        self.assertEqual(PB.contenido, "")
