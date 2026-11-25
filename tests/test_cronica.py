# Tests de Crónica: categorizador y resumen/informe sobre SQLite.
# (El muestreo real necesita pyobjc; aquí probamos la lógica pura.)
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from cronica import Cronica, categorizar, fmt_dur  # noqa: E402

CATS = {
    "Código": {"apps": ["Code", "Terminal", "Xcode"], "titulos": ["github", "claude code"]},
    "Ocio": {"apps": ["TV", "Steam"], "titulos": ["youtube"]},
}


class TestCategorizar(unittest.TestCase):
    def test_titulo_manda_sobre_app(self):
        self.assertEqual(categorizar(CATS, "Safari", "Mi vídeo — YouTube", "com.apple.Safari"), "Ocio")
        self.assertEqual(categorizar(CATS, "Terminal", "claude code — valorforge", ""), "Código")

    def test_app_y_bundle(self):
        self.assertEqual(categorizar(CATS, "Visual Studio Code", "", ""), "Código")
        self.assertEqual(categorizar(CATS, "Xcode", "", "com.apple.dt.Xcode"), "Código")

    def test_nombres_cortos_exactos(self):
        self.assertEqual(categorizar(CATS, "TV", "", "com.apple.TV"), "Ocio")
        # "tv" NO debe casar por subcadena con otras apps
        self.assertEqual(categorizar(CATS, "Notatv", "", ""), "Otros")

    def test_navegador_y_otros(self):
        self.assertEqual(categorizar(CATS, "Safari", "", "com.apple.Safari"), "Navegación")
        self.assertEqual(categorizar(CATS, "Calculadora", "", "com.apple.calculator"), "Otros")


class TestCronicaDB(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.c = Cronica({"cronica": {"categorias": CATS}}, self._tmp.name)

    def tearDown(self):
        try:
            self.c._db and self.c._db.close()
        finally:
            self._tmp.cleanup()

    def test_resumen_e_informe(self):
        ahora = int(time.time())
        self.c._buffer = [
            (ahora - 20, "Code", "com.msft.code", "app.js — valorforge", "Código", 5),
            (ahora - 15, "Code", "com.msft.code", "app.js — valorforge", "Código", 5),
            (ahora - 10, "Safari", "com.apple.Safari", "YouTube", "Ocio", 5),
        ]
        self.c.volcar()
        self.assertEqual(self.c._buffer, [])
        r = self.c.resumen_hoy()
        self.assertEqual(r["total"], 15)
        self.assertEqual(r["categorias"][0], ("Código", 10))
        self.assertEqual(r["apps"][0], ("Code", 10))

        ruta = self.c.informe_html()
        html = Path(ruta).read_text(encoding="utf-8")
        self.assertIn("Crónica", html)
        self.assertIn("Código", html)

    def test_fmt_dur(self):
        self.assertEqual(fmt_dur(45), "45s")
        self.assertEqual(fmt_dur(300), "5m")
        self.assertEqual(fmt_dur(3720), "1h 02m")


if __name__ == "__main__":
    unittest.main()
