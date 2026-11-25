# Interfaz común de módulos de Escudero (Fase 1 — arquitectura de plugins).
#
# Criterio de aceptación: añadir un módulo nuevo = crear una clase que herede
# de EscuderoModule y registrarla en MODULES de core/registry.py. CERO cambios
# en el core (escudero.py).
#
# El core garantiza:
#   · tick() se llama cada `tick_interval` segundos (puede ser 0 → sin timer).
#   · export_state()/load_state() alimentan datos/estado.json (guardado atómico).
#   · actualizar_config() se llama al arrancar y en «Recargar configuración».
#   · menu_items() se re-consulta tras cada refresco; el módulo es responsable
#     de actualizar los títulos de SUS items (los crea una vez en menu_items
#     y los retitula; rumps usa el título como clave, ver escudero.py).

from abc import ABC


class EscuderoModule(ABC):
    """Contrato de un módulo de Escudero.

    Los métodos tienen implementación por defecto (no-op) para que un módulo
    simple solo implemente lo que necesita. `ctx` es un objeto ModuleContext
    con: notificar(titulo, texto, sonido), bus (EventBus), cfg, datos (Path),
    rumps (el módulo, None en modo CLI) y servicios compartidos (idle_fn...).
    """

    name = "modulo"
    icon = "puzzlepiece"          # SF Symbol para decorar el menú
    tick_interval = 0.0           # segundos entre ticks; 0 → el core no crea timer

    def __init__(self, cfg, ctx):
        self.cfg = cfg
        self.ctx = ctx

    # ── menú ────────────────────────────────────────────────────────────────
    def menu_items(self):
        """Lista de MenuItem de rumps que aporta (con separadores None).
        Se llama UNA vez al construir el menú; el módulo guarda referencias
        y retitula en sus ticks. Por defecto: sin presencia en el menú."""
        return []

    # ── ciclo de vida ───────────────────────────────────────────────────────
    def tick(self):
        """Llamado por el timer principal (si tick_interval > 0)."""

    def actualizar_config(self, cfg):
        """Nueva config validada (ya pasó por Pydantic). Por defecto: guardar."""
        self.cfg = cfg

    def shutdown(self):
        """Al salir de la app: soltar procesos, items de barra, etc."""

    # ── persistencia (el core vuelca todo a estado.json) ────────────────────
    def export_state(self):
        """Dict JSON-serializable → estado.json (bajo la clave self.name)."""
        return {}

    def load_state(self, state):
        """Recibe SU sección de estado.json ({} si no había nada)."""
