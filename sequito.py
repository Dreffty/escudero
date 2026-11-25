# Séquito — los compañeros de Escudero: otras apps tuyas (VozLocal…) que
# arrancan solas cuando arranca el escudo y se controlan desde su menú.
# Un solo botón levanta todo el campamento.

import json
import logging
import os
import subprocess
import threading
import time
import urllib.request
from pathlib import Path

log = logging.getLogger("escudero.sequito")

# Fase 4.1: si la compañera es VozLocal y su API local responde, el menú muestra
# el estado real (idle/grabando/transcribiendo) en vez de solo vivo/muerto.
_API_VOZLOCAL = ("vozlocal", "wispr")


def _token_vozlocal():
    try:
        return (Path.home() / ".config" / "vozlocal" / "api.token").read_text().strip()
    except OSError:
        return ""


class Sequito:
    def __init__(self, cfg, raiz_datos, notificar):
        self.raiz = Path(raiz_datos)
        self.notificar = notificar
        self.entradas = []
        for e in (cfg.get("sequito") or []):
            carpeta = Path(os.path.expanduser(str(e.get("carpeta", "~")))).resolve()
            cmd = []
            for parte in (e.get("comando") or []):
                parte = os.path.expanduser(str(parte))
                cmd.append(parte if os.path.isabs(parte) else str(carpeta / parte))
            if not cmd or not e.get("patron"):
                log.warning("entrada de séquito sin comando/patrón: %s", e)
                continue
            self.entradas.append({"nombre": str(e.get("nombre", "?")),
                                  "carpeta": carpeta, "cmd": cmd,
                                  "patron": str(e["patron"]),
                                  "auto": bool(e.get("autoarrancar", False))})

    def pid(self, ent):
        try:
            r = subprocess.run(["pgrep", "-f", ent["patron"]],
                               capture_output=True, text=True)
            pids = [p for p in r.stdout.split() if p.strip()]
            return int(pids[0]) if pids else None
        except Exception:
            return None

    def estado_api(self, ent, timeout=1.0):
        """Estado real de la compañera si expone API tipo VozLocal (GET /status).
        Devuelve el dict de estado o None si no responde/no aplica."""
        nombre = (ent.get("nombre") or "").lower()
        if not any(k in nombre for k in _API_VOZLOCAL):
            return None
        token = _token_vozlocal()
        try:
            req = urllib.request.Request("http://127.0.0.1:8765/status")
            if token:
                req.add_header("Authorization", f"Bearer {token}")
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8", "replace"))
        except Exception:
            return None

    def arrancar(self, ent):
        if self.pid(ent):
            return True
        try:
            nombre_log = "".join(c for c in ent["nombre"] if c.isalnum()) or "companero"
            salida = open(self.raiz / f"sequito-{nombre_log}.log", "ab")
            subprocess.Popen(ent["cmd"], cwd=ent["carpeta"],
                             stdout=salida, stderr=salida,
                             start_new_session=True)
            log.info("séquito: arrancado %s", ent["nombre"])
            return True
        except Exception:
            log.exception("séquito: no pude arrancar %s", ent["nombre"])
            return False

    def parar(self, ent):
        try:
            subprocess.run(["pkill", "-f", ent["patron"]])
            log.info("séquito: parado %s", ent["nombre"])
        except Exception:
            log.exception("séquito: no pude parar %s", ent["nombre"])

    def arrancar_autos(self):
        """Llamar al arrancar Escudero: levanta a los compañeros marcados
        con autoarrancar (con un respiro para no pelearnos por el arranque)."""
        pendientes = [e for e in self.entradas if e["auto"] and not self.pid(e)]
        if not pendientes:
            return

        def tarea():
            time.sleep(3)
            for ent in pendientes:
                if self.arrancar(ent):
                    self.notificar("⚔️ Séquito", f"{ent['nombre']} en pie.")
        threading.Thread(target=tarea, daemon=True).start()
