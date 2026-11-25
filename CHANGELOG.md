# Escudero — registro de cambios

Formato: fases de la ficha de proyecto (P0/P1/P2).

## [2.3] — 2026-11-25 — App de verdad, lista para compartir

### Cambiado
- **Escudero.app de verdad** (py2app): lleva su propio Python, vive en
  `/Applications`, sin icono en el Dock y sin abrir Terminal. `./instalar.sh`
  la empaqueta, la firma (ad-hoc) y la instala.
- **Abrir al iniciar sesión** con SMAppService (ítem de inicio normal de macOS),
  activado la primera vez y con interruptor en el menú. Sustituye al LaunchAgent
  que abría `start.command` en Terminal (el instalador lo retira).
- La config y los datos pasan a `~/Library/Application Support/Escudero/`
  (el instalador copia los de la versión anterior). En el repo solo queda
  `config.ejemplo.yaml`, neutra y con **Ordenar apagado** de serie.

### Quitado
- `start.command`, `autoarranque.sh` y el lanzador `Escudero.app` en zsh.

## [2.2] — 2026-10-24 — Revisión: menos módulos, y los que quedan funcionan

### Quitado
- **Muralla** (el bloqueo de apps vive en FocusDesk), **Mantener despierto** y
  el **contador de tokens de Claude**: módulos, menú, API (`/muralla/*`),
  comandos de voz («concéntrame…»), config y tests. `muralla:` en un config
  viejo se ignora sin invalidarlo.
- VozLocal del Séquito: su código ya no existe en el Mac y fallaba al arrancar.
- `pynput`: ya no lo usa nadie.

### Leer texto (antes «Lector»), reescrito en lector.py
- No funcionaba por tres razones: «Desde archivo» abría el panel desde un hilo
  secundario (macOS no lo permite), «Desde ventana» capturaba sin permiso de
  Grabación de pantalla (macOS entrega solo el fondo de escritorio, así que
  «no hay texto»), y «Desde portapapeles» exigía capturar antes con ⌘⇧⌃4.
- Ahora: **⌃⌥T** → eliges zona (o ventana con espacio) → texto copiado y en el
  historial. Comprueba el permiso antes y, si falta, abre Ajustes y lo explica.
  Lee también la imagen copiada y archivos: imágenes y PDF (texto directo o, si
  es escaneado, reconociendo sus páginas). Unlimited-OCR cae a Vision si no está.

### Ordenar: reglas mejor definidas
- Las edades cuentan **desde que el archivo llegó** (fecha de adición), no
  desde su modificación: un zip viejo recién descomprimido ya no va al desván.
- Condiciones nuevas: `tipo` (imagen, documento…), `nombre` (contiene, sin
  tildes), `origen` (web de descarga: lo de usal.es → Universidad),
  `sin_tocar_dias`, `menor_mb`, y `excepto`. Destino con `{año}-{mes}`.
- Validación estricta: una regla sin condiciones, un tipo inventado o una ruta
  relativa dan un error claro en vez de hacer cosas raras.
- «Probar las reglas…» enseña qué haría con cada archivo y por qué (incluido
  «esperando a Comprimidos: lleva 1 de 7 días»); «Últimos movimientos» (clic →
  en el Finder) sustituye a «Ver registro…», que abría la base de datos binaria.
- Mueve entre discos (shutil.move) y no repite el reconocimiento de
  `contenido_regex` en cada pasada.
- Reglas por defecto nuevas: Universidad (por origen) y Documentos.

### Crónica (el «Hoy» del menú)
- 23 de 33 horas de la semana salían como «Otros» (21 h eran League of Legends).
  Ahora, si ninguna regla casa, cuenta lo que la app declara ser (juego → Ocio,
  herramienta de desarrollo → Código…), con reglas por defecto más completas y
  dos categorías nuevas, Estudio y Negocio. Sobre la semana real: «Otros» 0,5 h.
- Al cambiar las reglas, el historial se reclasifica solo (una vez).
- Los diálogos del sistema (contraseña, avisos) ya no cuentan como tiempo.

### Autoarranque
- Apuntaba a `~/AI/escudero`, que ya no existe, y además no podía funcionar desde
  Descargas: macOS no deja que un LaunchAgent arranque programas de esa carpeta
  (EX_CONFIG, 78) y, fuera de Terminal, Python no tiene permiso para leerla. Ahora
  el agente abre `start.command` en Terminal en segundo plano, que sí lo tiene.
- El script mataba el Escudero abierto y arrancaba el nuevo sin esperar: el nuevo
  encontraba el candado cogido y se retiraba. Ahora espera.

### Otros arreglos
- Atajos globales en atajos.py: con varios (⌃⌥V, ⌃⌥T, Ventanas) cada uno
  responde solo al suyo. Ventanas pasa de pynput (pedía Monitorización de
  Entrada y, sin ella, no hacía nada) a estos atajos.
- Las marcas ✓ de Descanso, Pausar Crónica y Ordenar activado no se
  actualizaban (iban detrás de un return).
- «Ya hay otro Escudero» buscaba el texto «escudero.py» en cualquier proceso
  (un editor con el archivo abierto bastaba para que no arrancase): ahora es un
  candado de archivo.

## [2.1] — 2026-10-24 — Pergamino que funciona, con memoria y buscador

### Arreglado
- **Elegir un recorte del menú siempre copiaba el primero.** Los `MenuItem` de
  rumps heredan de `OrderedDict` y dos sin hijos son iguales con `==`, así que
  `slots_perg.index(sender)` devolvía 0 pulsaras el que pulsaras: se volvía a
  copiar lo que ya estaba en el portapapeles y parecía que no hacía nada. Cada
  hueco lleva ahora su `_indice` (test de regresión con `MenuItem` reales).
- Fuera los parches del intento del 24-25/09, que perseguían un fallo que no
  existía: verificar cada copia con `pbpaste`/`pbcopy` (además fallaba con
  tildes si Escudero arrancaba sin `LANG`, y bloqueaba el hilo principal) y
  consultar por Accesibilidad la app de delante cada segundo para devolverle
  el foco (el menú de la barra nunca se lo quita). Se conserva su arreglo bueno:
  el puente al hilo principal ya no redefine una clase de Objective-C en cada
  llamada (`_Puente is overriding existing Objective-C class`).

### Nuevo
- **Historial persistente**: `datos/pergamino.json`, escritura atómica con
  permisos 0600, los últimos 25 recortes (el más antiguo se borra solo); un archivo roto se aparta como
  `.corrupto.json` en vez de tumbar nada. `persistente: false` vuelve a solo
  memoria y borra el archivo.
- **Buscador ⌃⌥V** (`panel_pergamino.py`): panel flotante con Liquid Glass que
  no activa Escudero, así que ⏎ pega en el mismo campo donde escribías.
  Búsqueda sin tildes ni mayúsculas y con todas las palabras en cualquier
  orden; cada fila dice de qué app vino y cuándo. El atajo es un hot key de
  Carbon (no pide Monitorización de Entrada); pegar usa Accesibilidad y, sin
  ella, copia y avisa.
- Config nueva en `pergamino`: `persistente`, `atajo`, `pegar_directo`
  (validadas: un atajo imposible da un error legible).

## [2.0] — 2026-09-18 — Fases 1, 2, 3 y 4

### Fase 1 — Contrato de módulos (P0)
- Nuevo paquete `escudero/`: `module.py` (`EscuderoModule`: `menu_items/tick/`
  `export_state/load_state/actualizar_config/shutdown`), `events.py`
  (EventBus síncrono tolerante a fallos), `config_schema.py`.
- El core (`escudero.py`) queda en su rol: config + timers + menú + estado.
- Las 8 reglas intangibles (§6 de la ficha) siguen intactas.

### Fase 2 — Calidad de datos (P0)
- **Config validada con Pydantic** (`pydantic>=2.0` en requirements):
  errores accionables en vez de excepciones en runtime
  («regla “Capturas”: 'hacer' necesita 'mover' o 'papelera»').
  Config inválida → la app sigue con la última buena
  (`datos/config.ultima-buena.json`) y el menú/CLI lo explican
  (`--validar-config`, «Recargar configuración» muestra el detalle).
- **Ordenar → SQLite** (`datos/ordenar.db`, tabla `movimientos` con `pasada_id`):
  deshacer la última pasada, `historial()` queryable, `deshecho` por pasada.
  Migración automática del `ordenar.log` histórico (167 movimientos importados
  en la instalación de referencia; queda como `ordenar.log.importado`).
- **EventBus**: `app_blocked` (Muralla → Crónica lo cuenta como categoría
  «Ocio bloqueado»), `ordenar_movidos`, `muralla_iniciada/levantada`, `foco_cambiado`.

### Fase 3 — Producto (P1)
- **Crónica con detección de proyecto**: del título de ventana
  («main.py — valorforge») o del repo Git del cwd de la app frontal (lsof).
  Columna `proyecto` (migración ALTER suave), sección «Por proyecto» en el
  informe HTML, y `resumen_fecha(dia)` (contrato de la API y de ForgeDesk).
- **Muralla pomodoro**: `modo: pomodoro` con `trabajo_min/descanso_min/ciclos`;
  bloquea solo en tramos de trabajo; la fase se muestra en el menú
  («24m 10s trabajo 1/4 · total 1h 29m»). La sesión persiste entre reinicios.
  Toggles de apps persistidos por **patrón** (`muralla_activos`), no por índice.
- **Ordenar `contenido_regex`**: condición que mira DENTRO del archivo
  (texto plano por lectura directa; imágenes/PDF por OCR local de Vision
  reusando `pergamino.ocr_datos`). OJO: lento — solo carpetas pequeñas.
- **API local en 127.0.0.1:8764** (`api.py`, stdlib sin dependencias):
  `GET /status`, `POST /muralla/iniciar|levantar`, `POST /foco`,
  `GET /cronica/resumen?fecha=`, `POST /comando`. Token Bearer en
  `~/.config/escudero/api.token` (600, autogenerado). Documentada en `docs/API.md`.

### Fase 4 — Sinergia (P2)
- **Cliente de VozLocal** (`sequito.estado_api`): si `localhost:8765/status`
  responde, el menú muestra el estado real (idle/grabando/transcribiendo);
  si no, fallback a vivo/muerto por pgrep (timeout 1 s).
- **`POST /comando`**: órdenes «Escudero, …» (concéntrame N min/h, levanta la
  muralla <frase>, mi foco es …, ordena ahora, deshacer, pausar/reanudar crónica).
- `docs/INTEGRACION.md`: mapa de flujos y contratos con VozLocal y ForgeDesk.

### Tests
- 42 → **99 tests** (`python -m unittest discover -s tests`): nuevos
  `test_config`, `test_bus`, `test_ordenar_db`, `test_api` (servidor real con
  app falsa, puerto efímero), `test_muralla_pomodoro`, `test_comandos_voz`
  (lógica del core sin GUI vía carga desligada de escudero.py).
