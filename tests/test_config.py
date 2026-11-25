# Tests de la validación de config (Fase 2.1): errores accionables, defaults y
# saneado, y que la semántica de Ordenar no se rompa al normalizar.
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from escudero.config_schema import validar_config  # noqa: E402


class TestConfigValida(unittest.TestCase):
    def test_config_minima_ok_y_defaults(self):
        ok, cfg, errores = validar_config({})
        self.assertTrue(ok, errores)
        self.assertEqual(cfg["ordenar"]["intervalo_seg"], 60)
        self.assertEqual(cfg["pergamino"]["motor_ocr"], "vision")
        self.assertEqual(cfg["api"]["puerto"], 8764)
        self.assertNotIn("muralla", cfg)
        self.assertEqual(cfg["cronica"]["idle_seg"], 180)

    def test_ext_suelta_se_convierte_en_lista(self):
        ok, cfg, errores = validar_config({"ordenar": {"carpetas": [
            {"ruta": "~/Downloads", "reglas": [
                {"nombre": "PNGs", "si": {"ext": "png"}, "hacer": {"mover": "~/Downloads/Img"}}]}]}})
        self.assertTrue(ok, errores)
        self.assertEqual(cfg["ordenar"]["carpetas"][0]["reglas"][0]["si"]["ext"], ["png"])

    def test_contenido_regex_admitido(self):
        ok, _cfg, errores = validar_config({"ordenar": {"carpetas": [
            {"ruta": "~/Downloads", "reglas": [
                {"nombre": "Facturas", "si": {"contenido_regex": "factura"},
                 "hacer": {"mover": "~/Downloads/Facturas"}}]}]}})
        self.assertTrue(ok, errores)

    def test_una_seccion_muralla_vieja_no_rompe_nada(self):
        # Quien aún la tenga en su config.yaml no debe quedarse con la config inválida.
        ok, _cfg, errores = validar_config({"muralla": {"modo": "pomodoro"}})
        self.assertTrue(ok, errores)


class TestConfigErrores(unittest.TestCase):
    def _errores(self, cfg):
        ok, _, errores = validar_config(cfg)
        self.assertFalse(ok)
        return " | ".join(errores)

    def test_hacer_sin_accion(self):
        msg = self._errores({"ordenar": {"carpetas": [
            {"ruta": "~/D", "reglas": [{"nombre": "Capturas", "si": {"ext": ["png"]}, "hacer": {}}]}]}})
        self.assertIn("Capturas", msg)
        self.assertIn("'hacer' necesita 'mover'", msg)

    def test_mover_y_papelera_a_la_vez(self):
        msg = self._errores({"ordenar": {"carpetas": [
            {"ruta": "~/D", "reglas": [{"nombre": "X", "si": {"ext": ["png"]},
                                       "hacer": {"mover": "~/Y", "papelera": True}}]}]}})
        self.assertIn("no puede tener 'mover' y 'papelera'", msg)

    def test_condicion_desconocida(self):
        msg = self._errores({"ordenar": {"carpetas": [
            {"ruta": "~/D", "reglas": [{"nombre": "X", "si": {"extt": ["png"]},
                                       "hacer": {"mover": "~/Y"}}]}]}})
        self.assertIn("condiciones desconocidas", msg)

    def test_regex_no_compila(self):
        msg = self._errores({"ordenar": {"carpetas": [
            {"ruta": "~/D", "reglas": [{"nombre": "X", "si": {"regex": "([a-"},
                                       "hacer": {"mover": "~/Y"}}]}]}})
        self.assertIn("no compila", msg)

    def test_motor_ocr_invalido(self):
        msg = self._errores({"pergamino": {"motor_ocr": "tesseract"}})
        self.assertIn("vision", msg)

    def test_puerto_api_fuera_de_rango(self):
        msg = self._errores({"api": {"puerto": 80}})
        self.assertIn("1024", msg)

    def test_sequito_sin_patron(self):
        msg = self._errores({"sequito": [{"nombre": "VozLocal", "comando": ["VozLocal.app/x"]}]})
        self.assertIn("patron", msg)

    def test_intervalo_ordenar_demasiado_corto(self):
        msg = self._errores({"ordenar": {"intervalo_seg": 5}})
        self.assertIn("al menos 15", msg)


if __name__ == "__main__":
    unittest.main()
