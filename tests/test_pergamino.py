# Tests de Pergamino (el "Maccy"): historial, disco, búsqueda y el menú.
import importlib.util
import json
import os
import stat
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))
from pergamino import Pergamino, hace, normalizar, parsear_atajo  # noqa: E402


class PBFake:
    """NSPasteboard de mentira: changeCount solo sube al escribir."""
    def __init__(self, cc=100):
        self.cc = cc
        self.contenido = ""
        self.tipos = ["public.utf8-plain-text"]

    def clearContents(self):
        pass

    def setString_forType_(self, s, t):
        self.contenido = str(s)
        self.cc += 1
        return True

    def changeCount(self):
        return self.cc

    def types(self):
        return self.tipos

    def stringForType_(self, t):
        return self.contenido

    def copiar(self, texto):
        """Lo que pasa cuando el usuario pulsa ⌘C en otra app."""
        self.contenido = texto
        self.cc += 1


class TestHistorial(unittest.TestCase):
    def setUp(self):
        self.p = Pergamino({"pergamino": {"maximo": 3}})

    def test_agrega_al_principio(self):
        self.p.agregar("uno")
        self.p.agregar("dos")
        self.assertEqual(self.p.historial, ["dos", "uno"])

    def test_duplicado_sube_al_principio_y_renueva_su_origen(self):
        self.p.agregar("uno", app="Notas", ts=10)
        self.p.agregar("dos", ts=20)
        self.p.agregar("uno", app="Brave Browser", ts=30)
        self.assertEqual(self.p.historial, ["uno", "dos"])
        self.assertEqual(self.p.entradas[0]["app"], "Brave Browser")
        self.assertEqual(self.p.entradas[0]["ts"], 30)

    def test_respeta_maximo(self):
        for t in ("a", "b", "c", "d"):
            self.p.agregar(t)
        self.assertEqual(self.p.historial, ["d", "c", "b"])

    def test_rechaza_vacios_y_gigantes(self):
        self.assertFalse(self.p.agregar("   "))
        self.assertFalse(self.p.agregar(""))
        self.assertFalse(self.p.agregar(None))
        self.assertFalse(self.p.agregar("x" * 100_001))
        self.assertEqual(self.p.historial, [])

    def test_vaciar(self):
        self.p.agregar("algo")
        self.p.vaciar()
        self.assertEqual(self.p.historial, [])

    def test_olvidar_quita_solo_ese(self):
        for t in ("a", "b", "c"):
            self.p.agregar(t)
        self.assertTrue(self.p.olvidar("b"))
        self.assertFalse(self.p.olvidar("no existe"))
        self.assertEqual(self.p.historial, ["c", "a"])


class TestPortapapeles(unittest.TestCase):
    def test_vigilar_captura_lo_que_copias(self):
        p = Pergamino({"pergamino": {"maximo": 5}})
        p._pb = PBFake()
        p._pb.copiar("hola")
        self.assertTrue(p.vigilar())
        self.assertFalse(p.vigilar())          # sin cambios, no relee
        self.assertEqual(p.historial, ["hola"])

    def test_vigilar_ignora_gestores_de_contrasenas(self):
        p = Pergamino({"pergamino": {"maximo": 5}})
        p._pb = PBFake()
        p._pb.tipos = ["public.utf8-plain-text", "org.nspasteboard.ConcealedType"]
        p._pb.copiar("contraseña-secreta")
        self.assertFalse(p.vigilar())
        self.assertEqual(p.historial, [])

    def test_restaurar_sin_appkit_devuelve_false(self):
        p = Pergamino({"pergamino": {"maximo": 3}})
        p._pb = None
        self.assertFalse(p.restaurar("hola"))

    def test_restaurar_none_devuelve_false(self):
        p = Pergamino({"pergamino": {"maximo": 3}})
        p._pb = PBFake()
        self.assertFalse(p.restaurar(None))
        self.assertFalse(p.restaurar(""))

    def test_restaurar_deja_el_texto_y_no_lo_recaptura(self):
        p = Pergamino({"pergamino": {"maximo": 3}})
        p.agregar("recorte restaurado")
        p.agregar("otra cosa")
        p._pb = PBFake()
        p._ultimo_cambio = 100
        self.assertTrue(p.restaurar("recorte restaurado"))
        self.assertEqual(p._pb.contenido, "recorte restaurado")
        self.assertEqual(p._cambio_restaurado, 101)
        # El siguiente vigilar() absorbe nuestro propio cambio sin reordenar.
        self.assertFalse(p.vigilar())
        self.assertEqual(p.historial, ["otra cosa", "recorte restaurado"])
        self.assertIsNone(p._cambio_restaurado)

    def test_restaurar_no_declara_exito_si_macos_rechaza(self):
        p = Pergamino({"pergamino": {"maximo": 3}})
        pb = PBFake()
        pb.setString_forType_ = lambda s, t: False
        p._pb = pb
        self.assertFalse(p.restaurar("texto"))
        self.assertIsNone(p._cambio_restaurado)


class TestDisco(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.ruta = Path(self.dir.name) / "pergamino.json"
        self.cfg = {"pergamino": {"maximo": 50, "persistente": True}}

    def test_sobrevive_a_reiniciar(self):
        p = Pergamino(self.cfg, ruta=self.ruta)
        p.agregar("primero", app="Notas")
        p.agregar("segundo ñandú", app="Brave Browser")
        otro = Pergamino(self.cfg, ruta=self.ruta)
        self.assertEqual(otro.historial, ["segundo ñandú", "primero"])
        self.assertEqual(otro.entradas[0]["app"], "Brave Browser")

    def test_archivo_solo_legible_por_ti(self):
        Pergamino(self.cfg, ruta=self.ruta).agregar("privado")
        modo = stat.S_IMODE(os.stat(self.ruta).st_mode)
        self.assertEqual(modo, 0o600)

    def test_vaciar_y_olvidar_llegan_al_disco(self):
        p = Pergamino(self.cfg, ruta=self.ruta)
        p.agregar("a")
        p.agregar("b")
        p.olvidar("a")
        self.assertEqual(Pergamino(self.cfg, ruta=self.ruta).historial, ["b"])
        p.vaciar()
        self.assertEqual(Pergamino(self.cfg, ruta=self.ruta).historial, [])

    def test_archivo_roto_se_aparta_y_no_tumba_nada(self):
        self.ruta.write_text("{esto no es json", encoding="utf-8")
        p = Pergamino(self.cfg, ruta=self.ruta)
        self.assertEqual(p.historial, [])
        self.assertTrue(self.ruta.with_suffix(".corrupto.json").exists())

    def test_sin_persistencia_no_escribe_y_borra_lo_viejo(self):
        Pergamino(self.cfg, ruta=self.ruta).agregar("viejo")
        self.assertTrue(self.ruta.exists())
        p = Pergamino({"pergamino": {"persistente": False}}, ruta=self.ruta)
        self.assertFalse(self.ruta.exists())
        p.agregar("nuevo")
        self.assertFalse(self.ruta.exists())
        self.assertEqual(p.historial, ["nuevo"])

    def test_recargar_config_recorta_y_apaga_el_disco(self):
        p = Pergamino(self.cfg, ruta=self.ruta)
        for t in ("a", "b", "c"):
            p.agregar(t)
        p.actualizar_config({"pergamino": {"maximo": 2, "persistente": True}})
        self.assertEqual(Pergamino(self.cfg, ruta=self.ruta).historial, ["c", "b"])
        p.actualizar_config({"pergamino": {"maximo": 2, "persistente": False}})
        self.assertFalse(self.ruta.exists())

    def test_ignora_entradas_raras_del_archivo(self):
        self.ruta.write_text(json.dumps({"version": 1, "entradas": [
            {"texto": "bueno", "ts": 5, "app": "Notas"},
            {"texto": "   "}, {"nada": 1}, None, {"texto": "bueno"}]}), encoding="utf-8")
        self.assertEqual(Pergamino(self.cfg, ruta=self.ruta).historial, ["bueno"])


class TestBusqueda(unittest.TestCase):
    def setUp(self):
        self.p = Pergamino({"pergamino": {"maximo": 50}})
        for t in ("git push origin main", "Canción de la práctica 2",
                  "correo de la USAL", "práctica de redes: sockets"):
            self.p.agregar(t)

    def textos(self, consulta):
        return [e["texto"] for e in self.p.buscar(consulta)]

    def test_sin_consulta_devuelve_todo_en_orden(self):
        self.assertEqual(self.textos(""), self.p.historial)

    def test_ignora_tildes_y_mayusculas(self):
        self.assertEqual(self.textos("cancion"), ["Canción de la práctica 2"])
        self.assertEqual(self.textos("usal"), ["correo de la USAL"])

    def test_todas_las_palabras_en_cualquier_orden(self):
        self.assertEqual(self.textos("sockets practica"), ["práctica de redes: sockets"])
        self.assertEqual(self.textos("practica"),
                         ["práctica de redes: sockets", "Canción de la práctica 2"])

    def test_sin_resultados(self):
        self.assertEqual(self.textos("xyz"), [])

    def test_limite(self):
        self.assertEqual(len(self.p.buscar("", limite=2)), 2)


class TestUtilidades(unittest.TestCase):
    def test_normalizar(self):
        self.assertEqual(normalizar("Ñandú CANCIÓN"), "nandu cancion")

    def test_hace(self):
        ahora = time.mktime((2026, 10, 24, 12, 0, 0, 0, 0, -1))
        self.assertEqual(hace(ahora - 20, ahora), "ahora")
        self.assertEqual(hace(ahora - 600, ahora), "hace 10 min")
        self.assertEqual(hace(ahora - 3 * 3600, ahora), "hace 3 h")
        self.assertEqual(hace(ahora - 20 * 3600, ahora), "ayer")
        self.assertEqual(hace(ahora - 4 * 86400, ahora), "hace 4 días")
        self.assertEqual(hace(ahora - 30 * 86400, ahora), "24 sep")
        self.assertEqual(hace(0, ahora), "")

    def test_parsear_atajo(self):
        self.assertEqual(parsear_atajo("ctrl+opt+v"), (9, 0x1800, "⌃⌥V"))
        self.assertEqual(parsear_atajo("Cmd + Shift + Espacio")[2], "⇧⌘Espacio")
        for malo in ("v", "shift+v", "ctrl+opt", "ctrl+ñ", "ctrl+a+b", ""):
            with self.assertRaises(ValueError):
                parsear_atajo(malo)


class TestMenu(unittest.TestCase):
    """El fallo de verdad: pulsar cualquier recorte copiaba siempre el primero."""

    @classmethod
    def setUpClass(cls):
        # Mismo nombre y caché que test_comandos_voz: escudero.py no se puede
        # cargar dos veces (define una clase de Objective-C).
        cls.app = sys.modules.get("_escudero_core")
        if cls.app is None:
            spec = importlib.util.spec_from_file_location("_escudero_core",
                                                          RAIZ / "escudero.py")
            cls.app = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(cls.app)
            sys.modules["_escudero_core"] = cls.app

    def test_cada_hueco_copia_su_recorte(self):
        import rumps

        class Falso:
            pass

        yo = Falso()
        yo.pergamino = Pergamino({"pergamino": {"maximo": 20}})
        yo.pergamino._pb = PBFake()
        for i in range(12):
            yo.pergamino.agregar(f"recorte {i}")
        yo.slots_perg = [rumps.MenuItem(" " * (i + 1)) for i in range(12)]
        for i, slot in enumerate(yo.slots_perg):
            slot._indice = i
        # Los MenuItem de rumps sin hijos son iguales entre sí con ==:
        # precisamente por eso .index() no sirve para saber cuál se pulsó.
        self.assertEqual(yo.slots_perg[5], yo.slots_perg[0])

        with patch.object(self.app, "notificar"):
            for i in (0, 5, 11):
                self.app.Escudero.clic_pergamino(yo, yo.slots_perg[i])
                self.assertEqual(yo.pergamino._pb.contenido, yo.pergamino.historial[i])

    def test_hueco_vacio_no_hace_nada(self):
        import rumps

        class Falso:
            pass

        yo = Falso()
        yo.pergamino = Pergamino({"pergamino": {"maximo": 20}})
        yo.pergamino._pb = PBFake()
        yo.pergamino.agregar("solo uno")
        hueco = rumps.MenuItem("   ")
        hueco._indice = 4
        with patch.object(self.app, "notificar") as aviso:
            self.app.Escudero.clic_pergamino(yo, hueco)
        aviso.assert_not_called()
        self.assertEqual(yo.pergamino._pb.contenido, "")


if __name__ == "__main__":
    unittest.main()
