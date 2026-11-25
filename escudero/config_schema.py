# Validación de config.yaml con Pydantic (Fase 2.1).
#
# Objetivo: que un YAML mal formado o una regla inválida NO explote en
# runtime, sino que produzca un mensaje ACCIONABLE, p. ej.:
#   ordenar → carpetas[0] → regla #2: 'hacer' necesita 'mover' o 'papelera'
#
# Uso:
#   ok, datos, errores = validar_config(diccionario_yaml)
#   ok=False → errores es una lista de strings legibles (la app sigue con la
#   última config buena y el menú muestra el error).

from __future__ import annotations

from typing import Optional

try:
    from pydantic import BaseModel, ConfigDict, ValidationError, field_validator, model_validator
except ImportError:  # guarda defensiva (pydantic es dependencia desde Fase 2)
    BaseModel = None


if BaseModel is not None:

    class _Base(BaseModel):
        model_config = ConfigDict(extra="allow")   # claves futuras no rompen

    class BarraCfg(_Base):
        mostrar_tiempo: bool = True
        mostrar_foco: bool = True

    class PergaminoCfg(_Base):
        maximo: int = 25
        motor_ocr: str = "vision"
        persistente: bool = True
        atajo: str = "ctrl+opt+v"
        atajo_ocr: str = "ctrl+opt+t"
        pegar_directo: bool = True

        @field_validator("atajo", "atajo_ocr")
        @classmethod
        def _atajo_valido(cls, v):
            from pergamino import parsear_atajo
            parsear_atajo(v)          # ValueError con mensaje legible si no vale
            return str(v)

        @field_validator("maximo")
        @classmethod
        def _maximo_positivo(cls, v):
            if v < 1:
                raise ValueError("'maximo' debe ser al menos 1")
            return v

        @field_validator("motor_ocr")
        @classmethod
        def _motor_valido(cls, v):
            v = str(v).strip().lower()
            if v not in ("vision", "unlimited"):
                raise ValueError("'motor_ocr' debe ser \"vision\" o \"unlimited\"")
            return v

    class VentanasCfg(_Base):
        atajos: bool = True

    class SequitoEntrada(_Base):
        nombre: str
        carpeta: str = "~"
        comando: list = []
        patron: str = ""
        autoarrancar: bool = False

        @model_validator(mode="after")
        def _completo(self):
            if not isinstance(self.comando, list) or not self.comando \
                    or not all(isinstance(p, str) for p in self.comando):
                raise ValueError(f"séquito «{self.nombre}»: 'comando' debe ser una lista de textos no vacía")
            if not str(self.patron).strip():
                raise ValueError(f"séquito «{self.nombre}»: falta 'patron' (lo que busca pgrep)")
            return self

    class CortinaCfg(_Base):
        activada: bool = True
        auto_ocultar_seg: int = 15

        @field_validator("auto_ocultar_seg")
        @classmethod
        def _auto_no_negativo(cls, v):
            if int(v) < 0:
                raise ValueError("'auto_ocultar_seg' no puede ser negativo (0 = nunca)")
            return v


    class OrdenarRegla(_Base):
        nombre: str = "sin nombre"
        si: dict = {}
        excepto: dict = {}
        hacer: dict = {}

        @staticmethod
        def _condiciones(nombre, donde, conds):
            """Comprueba y sanea un bloque de condiciones (`si` o `excepto`)."""
            import re
            from ordenar import CONDICIONES, TIPOS, _normal
            if not isinstance(conds, dict):
                raise ValueError(f"regla «{nombre}»: '{donde}' debe ser un mapa de condiciones")
            desconocidas = set(conds) - set(CONDICIONES)
            if desconocidas:
                raise ValueError(
                    f"regla «{nombre}»: condiciones desconocidas en '{donde}': "
                    f"{', '.join(sorted(desconocidas))} (válidas: {', '.join(CONDICIONES)})")
            for clave in ("ext", "tipo", "nombre", "patron", "origen"):
                if clave in conds:
                    valor = conds[clave]
                    if isinstance(valor, str):
                        conds[clave] = valor = [valor]
                    if not isinstance(valor, list) or not all(isinstance(v, str) and v.strip() for v in valor):
                        raise ValueError(f"regla «{nombre}»: '{clave}' debe ser un texto o una lista de textos")
            for t in conds.get("tipo", []):
                if _normal(t) not in TIPOS:
                    raise ValueError(f"regla «{nombre}»: tipo «{t}» desconocido "
                                     f"(válidos: {', '.join(TIPOS)})")
            for clave in ("edad_dias", "sin_tocar_dias", "mayor_mb", "menor_mb"):
                if clave in conds:
                    try:
                        if float(conds[clave]) < 0:
                            raise ValueError
                    except (TypeError, ValueError):
                        raise ValueError(f"regla «{nombre}»: '{clave}' debe ser un número ≥ 0")
            for clave in ("regex", "contenido_regex"):
                if clave in conds:
                    try:
                        re.compile(str(conds[clave]))
                    except re.error as e:
                        raise ValueError(f"regla «{nombre}»: '{clave}' no compila: {e}")
            return conds

        @model_validator(mode="after")
        def _regla_coherente(self):
            import string
            from ordenar import PLANTILLAS_DESTINO
            self.si = self._condiciones(self.nombre, "si", self.si)
            self.excepto = self._condiciones(self.nombre, "excepto", self.excepto)
            if not self.si:
                raise ValueError(f"regla «{self.nombre}»: 'si' necesita al menos una condición "
                                 "(una regla sin condiciones movería todo)")
            if not isinstance(self.hacer, dict) or not ("mover" in self.hacer or self.hacer.get("papelera")):
                raise ValueError(
                    f"regla «{self.nombre}»: 'hacer' necesita 'mover' (ruta destino) "
                    "o 'papelera: true'")
            if "mover" in self.hacer and self.hacer.get("papelera"):
                raise ValueError(
                    f"regla «{self.nombre}»: 'hacer' no puede tener 'mover' y 'papelera' a la vez")
            if "mover" in self.hacer:
                destino = str(self.hacer["mover"] or "").strip()
                if not destino.startswith(("~", "/")):
                    raise ValueError(f"regla «{self.nombre}»: 'mover' debe ser una ruta completa "
                                     "(que empiece por ~ o /)")
                campos = {c for _, c, _, _ in string.Formatter().parse(destino) if c}
                raras = campos - set(PLANTILLAS_DESTINO)
                if raras:
                    raise ValueError(f"regla «{self.nombre}»: en 'mover' solo valen "
                                     f"{{año}}, {{mes}} y {{dia}} (no {', '.join(sorted(raras))})")
            return self

    class OrdenarCarpeta(_Base):
        ruta: str
        reglas: list = []

        @field_validator("reglas")
        @classmethod
        def _reglas_validas(cls, v):
            out = []
            for i, r in enumerate(v or []):
                if not isinstance(r, dict):
                    raise ValueError(f"regla #{i + 1} debe ser un mapa {{nombre, si, hacer}}")
                out.append(OrdenarRegla(**r).model_dump())
            return out

    class OrdenarCfg(_Base):
        activado: bool = True
        intervalo_seg: int = 60
        edad_minima_seg: int = 120
        avisar: bool = True
        carpetas: list = []

        @field_validator("intervalo_seg")
        @classmethod
        def _intervalo_minimo(cls, v):
            if int(v) < 15:
                raise ValueError("'intervalo_seg' debe ser al menos 15 (las pasadas pisan disco)")
            return v

        @field_validator("carpetas")
        @classmethod
        def _carpetas_validas(cls, v):
            out = []
            for i, c in enumerate(v or []):
                if not isinstance(c, dict) or "ruta" not in c:
                    raise ValueError(f"carpetas[{i}] necesita al menos 'ruta'")
                out.append(OrdenarCarpeta(**c).model_dump())
            return out

    class VigiaOjosCfg(_Base):
        activado: bool = True
        intervalo_min: int = 20
        sonido: Optional[str] = "Glass"

        @field_validator("intervalo_min")
        @classmethod
        def _intervalo_positivo(cls, v):
            if int(v) < 1:
                raise ValueError("'intervalo_min' debe ser al menos 1")
            return v

    class VigiaCfg(_Base):
        ojos: VigiaOjosCfg = VigiaOjosCfg()

    class CategoriaCfg(_Base):
        apps: list = []
        titulos: list = []

    class CronicaCfg(_Base):
        intervalo_seg: int = 5
        idle_seg: int = 180
        categorias: dict = {}

        @field_validator("intervalo_seg", "idle_seg")
        @classmethod
        def _positivo(cls, v):
            if int(v) < 1:
                raise ValueError("debe ser al menos 1 segundo")
            return v

        @field_validator("categorias")
        @classmethod
        def _categorias_validas(cls, v):
            out = {}
            for nombre, reglas in (v or {}).items():
                if not isinstance(reglas, dict):
                    raise ValueError(f"categoría «{nombre}» debe ser un mapa {{apps, titulos}}")
                out[nombre] = CategoriaCfg(**reglas).model_dump()
            return out

    class ApiCfg(_Base):
        activada: bool = True
        puerto: int = 8764
        token: str = ""        # vacío → se genera solo y se guarda en ~/.config/escudero

        @field_validator("puerto")
        @classmethod
        def _puerto_valido(cls, v):
            if int(v) == 0:                  # 0 = puerto efímero (solo tests)
                return v
            if not (1024 <= int(v) <= 65535):
                raise ValueError("'puerto' debe estar entre 1024 y 65535")
            return v

    class EscuderoCfg(_Base):
        barra: BarraCfg = BarraCfg()
        pergamino: PergaminoCfg = PergaminoCfg()
        ventanas: VentanasCfg = VentanasCfg()
        sequito: list = []
        cortina: CortinaCfg = CortinaCfg()
        ordenar: OrdenarCfg = OrdenarCfg()
        vigia: VigiaCfg = VigiaCfg()
        cronica: CronicaCfg = CronicaCfg()
        api: ApiCfg = ApiCfg()

        @field_validator("sequito")
        @classmethod
        def _sequito_valido(cls, v):
            out = []
            for i, e in enumerate(v or []):
                if not isinstance(e, dict):
                    raise ValueError(f"sequito[{i}] debe ser un mapa {{nombre, carpeta, comando, patron}}")
                out.append(SequitoEntrada(**e).model_dump())
            return out

    def _fmt_ruta(loc) -> str:
        """('ordenar','carpetas',0,'reglas',2,'hacer') → 'ordenar → carpetas[0] → regla #3 → hacer'"""
        partes = []
        for parte in loc:
            if isinstance(parte, int):
                cont = partes[-1] if partes else ""
                singular = {"carpetas": "carpeta", "reglas": "regla", "apps": "app",
                            "sequito": "entrada", "titulos": "título"}.get(cont, cont)
                partes[-1:] = [f"{cont}[{parte}] «{singular} #{parte + 1}»"]
            else:
                partes.append(str(parte))
        return " → ".join(partes)


def validar_config(cfg: dict):
    """Valida el dict de config.yaml. Devuelve (ok, cfg_normalizada, errores).

    - ok=True: cfg_normalizada es la config con defaults aplicados y valores
      saneados (p. ej. 'ext: png' → ['png']). Segura para usar.
    - ok=False: errores = lista de strings legibles y accionables;
      cfg_normalizada es el dict ORIGINAL (la app debe seguir con su última
      config buena, no con esta).
    """
    if BaseModel is None:
        return True, cfg, ["pydantic no está instalado: config sin validar"]
    if not isinstance(cfg, dict):
        return False, cfg, ["config.yaml debe ser un mapa YAML (sección: valores)"]
    try:
        modelo = EscuderoCfg(**cfg)
    except ValidationError as e:
        errores = []
        for err in e.errors():
            ruta = _fmt_ruta(err.get("loc", ()))
            msg = str(err.get("msg", ""))
            if msg.startswith("Value error, "):
                msg = msg[len("Value error, "):]
            errores.append(f"{ruta}: {msg}" if ruta else msg)
        return False, cfg, errores
    # model_dump con defaults: las secciones ausentes quedan completas
    return True, modelo.model_dump(), []

