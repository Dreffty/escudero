# Tests de Ventanas (el "Rectangle"): la geometría pura.
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ventanas import a_coords_pantalla, calcular_rect  # noqa: E402

# Pantalla de 1920×1080 con barra de menús de 25 px y sin dock:
VIS = (0.0, 0.0, 1920.0, 1055.0)
ALTO = 1080.0


class TestGeometria(unittest.TestCase):
    def test_mitades(self):
        self.assertEqual(calcular_rect("izquierda", VIS), (0, 0, 960, 1055))
        self.assertEqual(calcular_rect("derecha", VIS), (960, 0, 960, 1055))
        self.assertEqual(calcular_rect("abajo", VIS), (0, 0, 1920, 527.5))
        self.assertEqual(calcular_rect("arriba", VIS), (0, 527.5, 1920, 527.5))

    def test_maximizar_y_centrar(self):
        self.assertEqual(calcular_rect("maximizar", VIS), VIS)
        x, y, w, h = calcular_rect("centrar", VIS)
        self.assertAlmostEqual(w, 1920 * 0.7)
        self.assertAlmostEqual(x, 1920 * 0.15)

    def test_accion_desconocida(self):
        with self.assertRaises(ValueError):
            calcular_rect("diagonal", VIS)

    def test_conversion_a_coords_de_pantalla(self):
        # maximizada: en Cocoa y=0 abajo → arriba-izquierda queda bajo la barra (25 px)
        self.assertEqual(a_coords_pantalla((0, 0, 1920, 1055), ALTO), (0, 25, 1920, 1055))
        # mitad superior: pegada a la barra de menús
        self.assertEqual(a_coords_pantalla((0, 527.5, 1920, 527.5), ALTO), (0, 25.0, 1920, 527.5))
        # mitad inferior: empieza a mitad de pantalla
        self.assertEqual(a_coords_pantalla((0, 0, 1920, 527.5), ALTO), (0, 552.5, 1920, 527.5))


if __name__ == "__main__":
    unittest.main()
