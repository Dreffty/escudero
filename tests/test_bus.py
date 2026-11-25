# Tests del EventBus (Fase 2.3): suscripción, payloads y tolerancia a fallos.
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from escudero.events import EventBus  # noqa: E402


class TestBus(unittest.TestCase):
    def setUp(self):
        self.bus = EventBus()

    def test_emit_llega_a_listeners(self):
        vistos = []
        self.bus.on("app_blocked", lambda p: vistos.append(p.get("nombre")))
        self.bus.emit("app_blocked", {"nombre": "Steam"})
        self.assertEqual(vistos, ["Steam"])

    def test_payload_por_defecto_es_dict(self):
        vistos = []
        self.bus.on("x", vistos.append)
        self.bus.emit("x")
        self.assertEqual(vistos, [{}])

    def test_listener_que_explota_no_rompe_al_resto(self):
        vistos = []

        def malo(_p):
            raise RuntimeError("boom")

        self.bus.on("x", malo)
        self.bus.on("x", vistos.append)
        self.bus.emit("x", {"n": 1})          # no debe lanzar
        self.assertEqual(vistos, [{"n": 1}])

    def test_off_desuscribe(self):
        vistos = []
        listener = self.bus.on("x", vistos.append)
        self.bus.off("x", listener)
        self.bus.emit("x")
        self.assertEqual(vistos, [])

    def test_varios_listeners_en_orden(self):
        orden = []
        self.bus.on("x", lambda _p: orden.append("a"))
        self.bus.on("x", lambda _p: orden.append("b"))
        self.bus.emit("x")
        self.assertEqual(orden, ["a", "b"])


if __name__ == "__main__":
    unittest.main()
