# Tests de Séquito: resolución de comandos y carpetas.
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sequito import Sequito  # noqa: E402


class TestSequito(unittest.TestCase):
    def test_resuelve_rutas_relativas_a_la_carpeta(self):
        s = Sequito({"sequito": [{
            "nombre": "VozLocal", "carpeta": "~/AI/wispr-local",
            "comando": ["venv/bin/python", "vozlocal.py"],
            "patron": "vozlocal.py", "autoarrancar": True,
        }]}, "/tmp", lambda *a, **k: None)
        self.assertEqual(len(s.entradas), 1)
        e = s.entradas[0]
        self.assertTrue(str(e["carpeta"]).endswith("AI/wispr-local"))
        self.assertTrue(e["cmd"][0].endswith("wispr-local/venv/bin/python"))
        self.assertTrue(e["cmd"][1].endswith("wispr-local/vozlocal.py"))
        self.assertTrue(e["auto"])

    def test_ignora_entradas_incompletas(self):
        s = Sequito({"sequito": [{"nombre": "rota", "comando": []},
                                 {"nombre": "sin patrón", "comando": ["x"]}]},
                     "/tmp", lambda *a, **k: None)
        self.assertEqual(s.entradas, [])

    def test_sin_config(self):
        s = Sequito({}, "/tmp", lambda *a, **k: None)
        self.assertEqual(s.entradas, [])


if __name__ == "__main__":
    unittest.main()
