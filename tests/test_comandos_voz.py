# Tests de los comandos de voz del core (Fase 4.2: «Escudero, …»).
# La lógica se prueba como FUNCIÓN DESLIGADA de escudero.py (sin rumps/GUI)
# con un stub que imita la superficie que usan los comandos.
#
# NOTA: importar escudero.py ejecuta sus imports de módulos (todos puros,
# sin GUI: rumps solo se importa dentro de Escudero.__init__).
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import importlib.util as _ilu
_spec = _ilu.spec_from_file_location(
    "_escudero_core", str(Path(__file__).resolve().parents[1] / "escudero.py"))
# Cargado una sola vez para toda la suite: escudero.py define una clase de
# Objective-C y cargarlo dos veces la «redefiniría» (objc.error).
_core = sys.modules.get("_escudero_core")
if _core is None:
    _core = _ilu.module_from_spec(_spec)
    _spec.loader.exec_module(_core)  # noqa: E402
    sys.modules["_escudero_core"] = _core


class TestComandosVoz(unittest.TestCase):
    def stub(self):
        st = SimpleNamespace()
        st.foco = ""
        st.cronica = SimpleNamespace(pausada=False)
        st.vigia = SimpleNamespace(ojos_on=True,
                                   poner_ojos=lambda on: setattr(st.vigia, "ojos_on", on))
        st.ordenar = SimpleNamespace(deshacer=lambda: 0)
        st.avisos = []
        st._guardar_estado = lambda: None
        st._pintar = lambda: None
        st.fijar_foco = lambda t: setattr(st, "foco", t)
        st.ordenar_ahora = lambda _s: st.avisos.append("ordenar")
        st.alternar_pausa = lambda _s: setattr(st.cronica, "pausada", not st.cronica.pausada)
        return st

    def cmd(self, st, texto):
        return _core.Escudero.ejecutar_comando_voz(st, texto)

    def test_concentrarme_ya_no_existe(self):
        # La Muralla se quitó: FocusDesk es quien bloquea. Escudero lo dice en vez de fingir.
        r = self.cmd(self.stub(), "Escudero, concéntrame 2 horas")
        self.assertFalse(r.get("ok"))
        self.assertNotIn("concéntrame N horas/min", r.get("comandos", []))

    def test_silencio_apaga_los_descansos(self):
        st = self.stub()
        self.assertEqual(self.cmd(st, "silencio").get("accion"), "ojos_apagados")
        self.assertFalse(st.vigia.ojos_on)

    def test_fijar_foco(self):
        st = self.stub()
        r = self.cmd(st, "mi foco es terminar el informe")
        self.assertTrue(r.get("ok") and r.get("foco") == "terminar el informe")
        self.assertEqual(st.foco, "terminar el informe")

    def test_ordenar_y_deshacer(self):
        st = self.stub()
        self.assertTrue(self.cmd(st, "ordena ahora").get("ok"))
        self.assertEqual(st.avisos, ["ordenar"])
        r = self.cmd(st, "deshacer")
        self.assertTrue(r.get("ok") and r.get("n") == 0)

    def test_pausar_y_reanudar_cronica(self):
        st = self.stub()
        self.assertEqual(self.cmd(st, "pausar crónica").get("accion"), "cronica_pausada")
        self.assertTrue(st.cronica.pausada)
        self.assertEqual(self.cmd(st, "reanudar").get("accion"), "cronica_reanudada")
        self.assertFalse(st.cronica.pausada)

    def test_comando_desconocido_devuelve_ayuda(self):
        st = self.stub()
        r = self.cmd(st, "hazme un café")
        self.assertFalse(r.get("ok"))
        self.assertIn("comandos", r)


if __name__ == "__main__":
    unittest.main()
