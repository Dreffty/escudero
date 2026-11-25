# Tests del historial SQLite de Ordenar (Fase 2.2): pasada, deshacer por pasada,
# migración del ordenar.log de texto y consultas del historial.
import os
import sqlite3
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ordenar import Ordenar  # noqa: E402


def config(base: Path):
    d = base / "descargas"
    return {"ordenar": {"activado": True, "edad_minima_seg": 0, "carpetas": [{
        "ruta": str(d),
        "reglas": [
            {"nombre": "Imágenes", "si": {"ext": ["png", "jpg"]},
             "hacer": {"mover": str(d / "Imágenes")}},
            {"nombre": "PDFs", "si": {"ext": ["pdf"]},
             "hacer": {"mover": str(d / "PDFs")}},
        ]}]}}


def toca(ruta: Path, contenido="x"):
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(contenido)


class TestOrdenarSQLite(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base = Path(self._tmp.name)
        self.d = self.base / "descargas"
        self.d.mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def test_pasada_registra_movimientos(self):
        toca(self.d / "foto.png")
        toca(self.d / "doc.pdf")
        o = Ordenar(config(self.base), self.base)
        movidos = o.pasada()
        self.assertEqual(len(movidos), 2)
        filas = o.historial()
        self.assertEqual(len(filas), 2)
        reglas = {f[3] for f in filas}
        self.assertEqual(reglas, {"Imágenes", "PDFs"})
        self.assertTrue((self.base / "ordenar.db").exists())

    def test_deshacer_marca_la_pasada(self):
        toca(self.d / "foto.png")
        o = Ordenar(config(self.base), self.base)
        o.pasada()
        self.assertEqual(o.deshacer(), 1)
        self.assertTrue((self.d / "foto.png").exists())
        con = sqlite3.connect(self.base / "ordenar.db")
        deshechos = con.execute("SELECT COUNT(*) FROM movimientos WHERE deshecho=1").fetchone()[0]
        con.close()
        self.assertEqual(deshechos, 1)

    def test_deshacer_solo_la_ultima_pasada(self):
        toca(self.d / "uno.png")
        o = Ordenar(config(self.base), self.base)
        o.pasada()
        toca(self.d / "dos.pdf")
        o.pasada()
        self.assertEqual(len(o.movimientos_deshacer), 1)   # solo la pasada nueva
        self.assertEqual(o.deshacer(), 1)
        self.assertTrue((self.d / "dos.pdf").exists())

    def test_persistencia_entre_instancias(self):
        toca(self.d / "foto.png")
        Ordenar(config(self.base), self.base).pasada()
        otra = Ordenar(config(self.base), self.base)       # arranque nuevo
        self.assertEqual(len(otra.movimientos_deshacer), 1)
        self.assertEqual(otra.deshacer(), 1)
        self.assertTrue((self.d / "foto.png").exists())

    def test_migracion_del_log_de_texto(self):
        log = self.base / "ordenar.log"
        log.write_text(
            "2026-07-11 17:04:53  /Users/x/a.pdf  →  /Users/x/PDFs/a.pdf  (regla: PDFs)\n"
            "2026-07-11 17:04:53  /Users/x/b.png  →  /Users/x/Imágenes/b.png  (regla: Imágenes)\n"
            "2026-07-11 17:05:00  ↩️ deshechos 2 movimientos\n", encoding="utf-8")
        o = Ordenar(config(self.base), self.base)
        self.assertEqual(len(o.historial()), 2)            # solo las 2 parseables
        self.assertFalse(log.exists())                     # renombrado
        self.assertTrue((self.base / "ordenar.log.importado").exists())
        con = sqlite3.connect(self.base / "ordenar.db")
        viejos = con.execute("SELECT COUNT(*) FROM movimientos WHERE deshecho=1").fetchone()[0]
        con.close()
        self.assertEqual(viejos, 2)                        # histórico = ya deshecho

    def test_migracion_no_pisa_una_base_existente(self):
        toca(self.d / "foto.png")
        Ordenar(config(self.base), self.base).pasada()
        (self.base / "ordenar.log").write_text("basura\n", encoding="utf-8")
        o = Ordenar(config(self.base), self.base)          # no debe re-importar
        self.assertEqual(len(o.historial()), 1)
        self.assertTrue((self.base / "ordenar.log").exists())

    def test_condicion_contenido_regex_en_texto(self):
        cfg = config(self.base)
        cfg["ordenar"]["carpetas"][0]["reglas"].insert(0, {
            "nombre": "Facturas", "si": {"contenido_regex": "factura"},
            "hacer": {"mover": str(self.d / "Facturas")}})
        cfg["ordenar"]["carpetas"][0]["reglas"].append({
            "nombre": "Textos", "si": {"ext": ["txt"]}, "hacer": {"mover": str(self.d / "Textos")}})
        toca(self.d / "factura-2026.txt", "Factura total 120 €")
        toca(self.d / "notas.txt", "comprar leche")
        movidos = Ordenar(cfg, self.base).pasada()
        destinos = {o.name: d.parent.name for o, d, _ in movidos}
        self.assertEqual(destinos["factura-2026.txt"], "Facturas")
        self.assertEqual(destinos["notas.txt"], "Textos")

    def test_contenido_regex_no_casa_no_mueve(self):
        cfg = config(self.base)
        cfg["ordenar"]["carpetas"][0]["reglas"] = [{
            "nombre": "Facturas", "si": {"contenido_regex": "factura"},
            "hacer": {"mover": str(self.d / "Facturas")}}]
        toca(self.d / "otra.txt", "hola mundo")
        self.assertEqual(Ordenar(cfg, self.base).pasada(), [])

    def test_registro_apunta_a_la_base_sqlite(self):
        o = Ordenar(config(self.base), self.base)
        self.assertEqual(o.registro.name, "ordenar.db")


if __name__ == "__main__":
    unittest.main()