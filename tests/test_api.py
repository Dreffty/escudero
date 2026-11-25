# Tests de la API local (Fase 3.4 — contrato de sinergia con VozLocal/ForgeDesk).
# Usa una app de mentira: comprobamos auth, rutas, validaciones y formas JSON.
import json
import sys
import unittest
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from api import EscuderoAPI  # noqa: E402

TOKEN = "token-de-prueba"


class CronicaFalsa:
    def resumen_fecha(self, dia=None):
        return {"total": 3600,
                "categorias": [("Código", 3000), ("Ocio", 600)],
                "apps": [("Code", 3000)],
                "proyectos": [("valorforge", 2400)]}


class AppFalsa:
    """Imita la superficie de escudero.Escudero que usa la API."""

    def __init__(self):
        self.cronica = CronicaFalsa()
        self.foco = ""
        self.ordenar = type("O", (), {"activado": True})()
        self.vigia = type("V", (), {"ojos_on": True})()
        self.llamadas = []

    # la API siempre pasa por aquí; sin GUI ejecutamos en el hilo actual
    def desde_hilo(self, fn, *args):
        return fn(*args)

    def fijar_foco(self, texto):
        self.foco = texto

    def ejecutar_comando_voz(self, texto):
        self.llamadas.append(texto)
        return {"ok": True, "accion": "foco", "foco": texto}


def peticion(puerto, ruta, metodo="GET", cuerpo=None, token=TOKEN):
    datos = json.dumps(cuerpo).encode() if cuerpo is not None else None
    req = urllib.request.Request(f"http://127.0.0.1:{puerto}{ruta}", data=datos, method=metodo)
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    if datos is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=3) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8"))


class TestAPI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = AppFalsa()
        # puerto 0 = efímero (nunca choca con un Escudero de verdad corriendo)
        cls.api = EscuderoAPI(cls.app, {"api": {"puerto": 0, "token": TOKEN}})
        assert cls.api.arrancar(), "no pude levantar la API de prueba"
        cls.puerto = cls.api.puerto

    @classmethod
    def tearDownClass(cls):
        cls.api.parar()

    def setUp(self):
        self.app.foco = ""

    # ── auth ────────────────────────────────────────────────────────────────
    def test_sin_token_da_401(self):
        codigo, cuerpo = peticion(self.puerto, "/status", token="")
        self.assertEqual(codigo, 401)
        self.assertIn("token", cuerpo["error"])

    def test_token_erroneo_da_401(self):
        codigo, _ = peticion(self.puerto, "/status", token="otro")
        self.assertEqual(codigo, 401)

    # ── GET ────────────────────────────────────────────────────────────────
    def test_status(self):
        codigo, cuerpo = peticion(self.puerto, "/status")
        self.assertEqual(codigo, 200)
        self.assertEqual(cuerpo["app"], "escudero")
        self.assertNotIn("muralla", cuerpo)
        self.assertIn("cronica_hoy", cuerpo)
        self.assertEqual(cuerpo["cronica_hoy"]["categorias"]["Código"], 3000)
        self.assertEqual(cuerpo["cronica_hoy"]["proyectos"]["valorforge"], 2400)
        self.assertEqual(cuerpo["vigia"], {"ojos": True})

    def test_resumen_por_fecha(self):
        codigo, cuerpo = peticion(self.puerto, "/cronica/resumen?fecha=2026-07-11")
        self.assertEqual(codigo, 200)
        self.assertEqual(cuerpo["fecha"], "2026-07-11")
        self.assertEqual(cuerpo["apps"]["Code"], 3000)

    def test_resumen_fecha_mal_formada(self):
        codigo, cuerpo = peticion(self.puerto, "/cronica/resumen?fecha=11/07/2026")
        self.assertEqual(codigo, 400)
        self.assertIn("YYYY-MM-DD", cuerpo["error"])

    def test_ruta_desconocida(self):
        codigo, _ = peticion(self.puerto, "/nada")
        self.assertEqual(codigo, 404)

    def test_rutas_de_la_muralla_ya_no_existen(self):
        codigo, _ = peticion(self.puerto, "/muralla/iniciar", "POST", {"horas": 1})
        self.assertEqual(codigo, 404)

    # ── POST foco / comando ───────────────────────────────────────────────
    def test_fijar_foco(self):
        codigo, cuerpo = peticion(self.puerto, "/foco", "POST", {"texto": "terminar la API"})
        self.assertEqual(codigo, 200)
        self.assertEqual(cuerpo["foco"], "terminar la API")
        self.assertEqual(self.app.foco, "terminar la API")

    def test_comando_de_voz(self):
        codigo, cuerpo = peticion(self.puerto, "/comando", "POST", {"texto": "Escudero, foco"})
        self.assertEqual(codigo, 200)
        self.assertTrue(cuerpo["ok"])
        self.assertEqual(self.app.llamadas[-1], "Escudero, foco")

    def test_comando_vacio(self):
        codigo, _ = peticion(self.puerto, "/comando", "POST", {"texto": "  "})
        self.assertEqual(codigo, 400)

    def test_cuerpo_json_invalido(self):
        req = urllib.request.Request(f"http://127.0.0.1:{self.puerto}/foco",
                                     data=b"{no json", method="POST")
        req.add_header("Authorization", f"Bearer {TOKEN}")
        try:
            urllib.request.urlopen(req, timeout=3)
            self.fail("debería haber dado 400")
        except urllib.error.HTTPError as e:
            self.assertEqual(e.code, 400)


if __name__ == "__main__":
    unittest.main()
