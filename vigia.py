# Vigía — el módulo "FavTray" de Escudero: descansos visuales 20-20-20 (cada
# N minutos, mira algo lejano 20 segundos), solo si estás de verdad al teclado.

import logging
import time

log = logging.getLogger("escudero.vigia")


class Vigia:
    def __init__(self, cfg, notificar, idle_fn):
        self.notificar = notificar
        self.idle_fn = idle_fn      # función que devuelve segundos de inactividad
        self.ojos_on = True
        self.actualizar_config(cfg)
        self.proximo_ojos = time.time() + self.intervalo_ojos

    def actualizar_config(self, cfg):
        v = cfg.get("vigia", {}) or {}
        ojos = v.get("ojos", {}) or {}
        self.intervalo_ojos = max(1, int(ojos.get("intervalo_min", 20))) * 60
        self.sonido = ojos.get("sonido")  # None → sin sonido
        if not hasattr(self, "_config_inicial"):
            self.ojos_on = bool(ojos.get("activado", True))
            self._config_inicial = True

    # ── tick periódico (cada ~15 s, desde el timer principal) ──────────────
    def tick(self):
        ahora = time.time()
        if self.ojos_on and ahora >= self.proximo_ojos:
            if self.idle_fn() < 120:      # solo si estás de verdad al teclado
                self.notificar("👁️ Descanso 20-20-20",
                               "Mira algo a 6 metros durante 20 segundos. Tus ojos te lo pagan.",
                               self.sonido)
                self.proximo_ojos = ahora + self.intervalo_ojos
            else:                          # ya estás descansando: reintenta en 5 min
                self.proximo_ojos = ahora + 300

    def minutos_para_ojos(self):
        return max(0, int((self.proximo_ojos - time.time()) / 60))

    def poner_ojos(self, on):
        self.ojos_on = bool(on)
        if on:
            self.proximo_ojos = time.time() + self.intervalo_ojos
