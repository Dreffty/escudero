# Tests de Ordenar (el "Hazel"): reglas, edades por llegada, orígenes, tipos,
# excepciones, seguridad, deshacer y el informe de prueba.
import ctypes
import os
import plistlib
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ordenar as modulo  # noqa: E402
from ordenar import Ordenar  # noqa: E402

DIA = 86400


def config(base: Path, edad_minima=0, reglas=None):
    d = base / "descargas"
    return {"ordenar": {"activado": True, "edad_minima_seg": edad_minima, "carpetas": [{
        "ruta": str(d),
        "reglas": reglas if reglas is not None else [
            {"nombre": "Capturas", "si": {"patron": "captura*", "ext": ["png", "jpg"]},
             "hacer": {"mover": str(d / "Capturas")}},
            {"nombre": "Imágenes", "si": {"ext": ["png", "jpg"]},
             "hacer": {"mover": str(d / "Imágenes")}},
            {"nombre": "PDFs", "si": {"ext": ["pdf"]},
             "hacer": {"mover": str(d / "PDFs")}},
            {"nombre": "Zips viejos", "si": {"ext": ["zip"], "edad_dias": 7},
             "hacer": {"mover": str(d / "Comprimidos")}},
        ]}]}}


def toca(ruta: Path, modificado_hace_dias=0.0, contenido="x"):
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(contenido)
    if modificado_hace_dias:
        t = time.time() - modificado_hace_dias * DIA
        os.utime(ruta, (t, t))


def poner_origen(ruta: Path, *urls):
    """Lo que hace el navegador al descargar: la «procedencia» en un atributo."""
    libc = ctypes.CDLL(None)
    libc.setxattr.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_void_p,
                              ctypes.c_size_t, ctypes.c_uint32, ctypes.c_int]
    datos = plistlib.dumps(list(urls), fmt=plistlib.FMT_BINARY)
    assert libc.setxattr(os.fsencode(str(ruta)), b"com.apple.metadata:kMDItemWhereFroms",
                         datos, len(datos), 0, 0) == 0


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.base = Path(self._tmp.name)
        self.d = self.base / "descargas"
        self.d.mkdir()
        # Fecha de llegada controlada por el test (la de verdad no se puede fijar).
        self.llegadas = {}
        real = modulo.llegada
        p = patch.object(modulo, "llegada",
                         lambda ruta, st=None: self.llegadas.get(Path(ruta).name, real(ruta, st)))
        p.start()
        self.addCleanup(p.stop)

    def llego_hace(self, nombre, dias):
        self.llegadas[nombre] = time.time() - dias * DIA

    def ordenar(self, **kw):
        return Ordenar(config(self.base, **kw), self.base)

    def destinos(self, movidos):
        return {o.name: d.parent.name for o, d, _ in movidos}


class TestReglas(Base):
    def test_reglas_basicas_y_prioridad(self):
        toca(self.d / "foto.PNG")                       # ext en mayúsculas
        toca(self.d / "Captura 2026-06-07.png")         # casa Capturas ANTES que Imágenes
        toca(self.d / "doc.pdf")
        movidos = self.ordenar().pasada()
        self.assertEqual(self.destinos(movidos),
                         {"foto.PNG": "Imágenes", "Captura 2026-06-07.png": "Capturas", "doc.pdf": "PDFs"})
        self.assertTrue((self.d / "Imágenes" / "foto.PNG").exists())

    def test_tipo_nombre_sin_tildes_y_excepto(self):
        reglas = [
            {"nombre": "Capturas", "si": {"nombre": "captura de pantalla", "tipo": "imagen"},
             "excepto": {"nombre": "factura"}, "hacer": {"mover": str(self.d / "Capturas")}},
            {"nombre": "Documentos", "si": {"tipo": ["documento"]}, "hacer": {"mover": str(self.d / "Docs")}},
        ]
        toca(self.d / "Captura de Pantalla 2026-10-24 a las 9.00.png")
        toca(self.d / "Captura de pantalla factura.png")   # excepto: no es una captura de verdad
        toca(self.d / "trabajo.DOCX")
        toca(self.d / "datos.csv")
        o = Ordenar(config(self.base, reglas=reglas), self.base)
        self.assertEqual(self.destinos(o.pasada()), {
            "Captura de Pantalla 2026-10-24 a las 9.00.png": "Capturas",
            "trabajo.DOCX": "Docs", "datos.csv": "Docs"})
        self.assertTrue((self.d / "Captura de pantalla factura.png").exists())

    def test_origen_por_dominio(self):
        reglas = [{"nombre": "Universidad", "si": {"origen": ["usal.es"]},
                   "hacer": {"mover": str(self.d / "Universidad")}},
                  {"nombre": "PDFs", "si": {"tipo": "pdf"}, "hacer": {"mover": str(self.d / "PDFs")}}]
        toca(self.d / "tema6.pdf")
        poner_origen(self.d / "tema6.pdf", "https://studium26.usal.es/pluginfile.php/1/tema6.pdf",
                     "https://studium26.usal.es/course/view.php?id=9")
        toca(self.d / "factura.pdf")
        poner_origen(self.d / "factura.pdf", "https://outlook.live.com/mail/0/")
        toca(self.d / "otro.pdf")
        poner_origen(self.d / "otro.pdf", "https://malusal.es/x.pdf")   # no es usal.es
        o = Ordenar(config(self.base, reglas=reglas), self.base)
        self.assertEqual(self.destinos(o.pasada()),
                         {"tema6.pdf": "Universidad", "factura.pdf": "PDFs", "otro.pdf": "PDFs"})

    def test_tamano(self):
        reglas = [{"nombre": "Grandes", "si": {"mayor_mb": 1}, "hacer": {"mover": str(self.d / "Grandes")}},
                  {"nombre": "Pequeños", "si": {"menor_mb": 1}, "hacer": {"mover": str(self.d / "Peq")}}]
        toca(self.d / "grande.bin", contenido="x" * (2 * 1024 * 1024))
        toca(self.d / "chico.bin")
        o = Ordenar(config(self.base, reglas=reglas), self.base)
        self.assertEqual(self.destinos(o.pasada()), {"grande.bin": "Grandes", "chico.bin": "Peq"})

    def test_destino_con_fecha(self):
        reglas = [{"nombre": "Capturas", "si": {"ext": "png"},
                   "hacer": {"mover": str(self.d / "Capturas" / "{año}-{mes}")}}]
        toca(self.d / "a.png")
        self.llegadas["a.png"] = time.mktime((2026, 3, 9, 12, 0, 0, 0, 0, -1))
        o = Ordenar(config(self.base, reglas=reglas), self.base)
        self.assertEqual(self.destinos(o.pasada()), {"a.png": "2026-03"})


class TestEdades(Base):
    def test_edad_cuenta_desde_la_llegada(self):
        toca(self.d / "nuevo.zip")
        toca(self.d / "viejo.zip")
        self.llego_hace("nuevo.zip", 1)
        self.llego_hace("viejo.zip", 8)
        self.assertEqual([o.name for o, _, _ in self.ordenar().pasada()], ["viejo.zip"])

    def test_zip_antiguo_recien_descomprimido_no_va_al_desvan(self):
        # El fallo de antes: un archivo con fecha de modificación de hace un año
        # (así salen de un zip o de AirDrop) se iba al desván nada más llegar.
        reglas = [{"nombre": "Al desván", "si": {"sin_tocar_dias": 45},
                   "hacer": {"mover": str(self.d / "_Desván")}}]
        toca(self.d / "de-un-zip.txt", modificado_hace_dias=365)
        self.llego_hace("de-un-zip.txt", 0.01)
        toca(self.d / "olvidado.txt", modificado_hace_dias=200)
        self.llego_hace("olvidado.txt", 60)
        o = Ordenar(config(self.base, reglas=reglas), self.base)
        self.assertEqual([x.name for x, _, _ in o.pasada()], ["olvidado.txt"])

    def test_edad_minima_no_toca_lo_reciente(self):
        toca(self.d / "recien.png")
        self.assertEqual(self.ordenar(edad_minima=3600).pasada(), [])

    def test_lo_que_aun_se_escribe_espera(self):
        toca(self.d / "grabando.png")                   # recién modificado…
        self.llego_hace("grabando.png", 1)              # …aunque llegó ayer
        self.assertEqual(self.ordenar(edad_minima=600).pasada(), [])


class TestSeguridad(Base):
    def test_ignora_ocultos_carpetas_y_parciales(self):
        toca(self.d / ".oculto.png")
        (self.d / "una carpeta").mkdir()
        toca(self.d / "bajando.zip.crdownload")
        self.assertEqual(self.ordenar().pasada(), [])

    def test_colision_no_sobrescribe(self):
        toca(self.d / "PDFs" / "doc.pdf")
        toca(self.d / "doc.pdf")
        movidos = self.ordenar().pasada()
        self.assertEqual(movidos[0][1].name, "doc 2.pdf")
        self.assertTrue((self.d / "PDFs" / "doc.pdf").exists())

    def test_en_seco_no_mueve(self):
        toca(self.d / "foto.png")
        self.assertEqual(len(self.ordenar().pasada(en_seco=True)), 1)
        self.assertTrue((self.d / "foto.png").exists())

    def test_deshacer(self):
        toca(self.d / "foto.png")
        toca(self.d / "doc.pdf")
        o = self.ordenar()
        o.pasada()
        self.assertEqual(o.deshacer(), 2)
        self.assertTrue((self.d / "foto.png").exists())
        self.assertTrue((self.d / "doc.pdf").exists())
        self.assertEqual(o.movimientos_deshacer, [])

    def test_ya_en_su_sitio_no_se_mueve(self):
        toca(self.d / "Imágenes" / "foto.png")
        cfg = config(self.base)
        cfg["ordenar"]["carpetas"].append(
            {"ruta": str(self.d / "Imágenes"),
             "reglas": [{"nombre": "Imágenes", "si": {"ext": ["png"]},
                         "hacer": {"mover": str(self.d / "Imágenes")}}]})
        self.assertEqual(Ordenar(cfg, self.base).pasada(), [])

    def test_contenido_no_se_relee_en_cada_pasada(self):
        reglas = [{"nombre": "Facturas", "si": {"contenido_regex": "factura"},
                   "hacer": {"mover": str(self.d / "Facturas")}}]
        toca(self.d / "escaneo.png")
        o = Ordenar(config(self.base, reglas=reglas), self.base)
        with patch("lector.leer_archivo", return_value=("nada que ver", None)) as leer:
            o.pasada()
            o.pasada()
        self.assertEqual(leer.call_count, 1)


class TestExplicar(Base):
    def test_dice_por_que(self):
        toca(self.d / "foto.png")
        toca(self.d / "notas.xyz")
        toca(self.d / "bajando.crdownload")
        filas = {f["archivo"].name: f for f in self.ordenar().explicar()}
        self.assertEqual(filas["foto.png"]["regla"], "Imágenes")
        self.assertEqual(filas["notas.xyz"]["motivo"], "ninguna regla casa")
        self.assertEqual(filas["bajando.crdownload"]["motivo"], "descarga a medias")

    def test_dice_que_espera_por_la_edad(self):
        toca(self.d / "proyecto.zip")
        self.llego_hace("proyecto.zip", 2)
        fila = next(f for f in self.ordenar().explicar() if f["archivo"].name == "proyecto.zip")
        self.assertEqual(fila["motivo"], "esperando a «Zips viejos»: lleva 2 de 7 días")

    def test_informe_y_recientes(self):
        toca(self.d / "foto.png")
        toca(self.d / "notas.xyz")
        o = self.ordenar()
        html = o.informe_prueba().read_text(encoding="utf-8")
        self.assertIn("foto.png", html)
        self.assertIn("ninguna regla casa", html)
        self.assertTrue((self.d / "foto.png").exists(), "probar no mueve nada")
        o.pasada()
        recientes = o.recientes()
        self.assertEqual(len(recientes), 1)
        self.assertTrue(recientes[0][2].endswith("Imágenes/foto.png"))


if __name__ == "__main__":
    unittest.main()
