# Escudero 🛡

Tu mayordomo de barra de menús. Varias apps de pago recreadas en una, **todo
local**: sin cuentas, sin suscripciones, sin que nada salga del Mac.

| Módulo | Inspirado en | Qué hace |
|---|---|---|
| 🗂 **Ordenar** | Hazel (~42 $) | Reglas sobre Descargas, en orden y la primera que casa gana: por **tipo** (imagen, documento…), nombre, **web de origen** (lo de Studium → Universidad), edad **desde que llegó** y tamaño, con **excepciones**. «Probar las reglas…» enseña qué haría y por qué; «Últimos movimientos» y **deshacer**. |
| 👁 **Vigía** | FavTray | Descansos visuales 20-20-20, solo si estás de verdad al teclado. |
| 📖 **Crónica** | Rize (18 $/mes) | El «Hoy» del menú: registra la app activa cada 5 s, la categoriza (tus reglas; si no, lo que la app dice ser: un juego cuenta como Ocio aunque no lo hayas apuntado), **detecta el proyecto** y genera un **informe HTML** del día. Al cambiar las reglas, el historial se reclasifica solo. |
| 📋 **Pergamino** | Maccy / Paste (~15 $/año) | Historial de portapapeles (los últimos 25: el más antiguo se borra solo; guardado en `pergamino.json` (en tu carpeta de datos) que solo tú puedes leer, o solo en memoria con `persistente: false`; nunca guarda lo que copian los gestores de contraseñas). **⌃⌥V desde cualquier app** abre un buscador estilo Spotlight: escribe para filtrar (sin importar tildes), ↑↓ y ⏎ **pega en tu app**, ⌘1–9 pega ese, ⌘⌫ lo olvida. En el menú, clic en un recorte → al portapapeles. |
| 📸 **Leer texto** | TextSniper (~10 $) | **⌃⌥T** desde cualquier app: eliges una zona de la pantalla (barra espaciadora: una ventana) y su texto queda copiado. También la imagen copiada o un archivo (imagen o PDF). Vision de Apple, en local. Necesita «Grabación de pantalla» y, si falta, te lo dice. |
| 🎯 **Foco** | One Thing | Tu única tarea del día escrita junto al escudo en la barra de menús. |
| 🪟 **Ventanas** | Rectangle/Magnet (~10 $) | Encaja la ventana frontal en la pantalla del puntero: ⌃⌥←→↑↓ mitades · ⌃⌥⏎ maximizar · ⌃⌥C centrar (también desde el menú). Sin permiso de Monitorización de Entrada. |
| 🧹 **Cortina** | Bartender (20 $) / Ice | Esconde los iconos de la barra de menús: ⌘-arrastra lo que no quieras ver a la izquierda del ❘ y la flecha ‹/› lo esconde/asoma (auto-recogida a los 15 s). |
| ⚔️ **Séquito** | — | Escudero levanta a sus apps compañeras al arrancar, con un interruptor por app en el menú. (Vacío de serie: añade las tuyas en la config.) |

El bloqueo de distracciones (la antigua Muralla) vive en FocusDesk.

## Instalar

```bash
git clone https://github.com/Dreffty/escudero.git
cd escudero
./instalar.sh
```

Necesitas macOS 13+ y Python 3.11 o más nuevo (`brew install python@3.12`).
El instalador empaqueta **Escudero.app** (lleva su propio Python dentro), la deja
en `/Applications` y la abre. Vive en la **barra de menús** (🛡), **no sale en el
Dock** y **se abre sola al iniciar sesión**; se quita en su menú → «Abrir al
iniciar sesión» (o en Ajustes → General → Ítems de inicio).

Para actualizar: `git pull && ./instalar.sh`. Para desinstalar: borra
`/Applications/Escudero.app` y, si quieres, `~/Library/Application Support/Escudero`.

**Permisos** (Ajustes → Privacidad y seguridad), para «Escudero»:
- **Accesibilidad** — Crónica ve *títulos* de ventana (YouTube frente a GitHub en
  el navegador), Ventanas mueve ventanas y ⏎ del buscador pega en tu app.
- **Grabación de pantalla** — solo para Leer texto (⌃⌥T). Sin él, macOS entrega
  capturas con el fondo de escritorio y no hay texto que leer.

> **Ordenar viene apagado.** Mira las reglas (menú → Ordenar → «Editar reglas…»),
> pulsa «Probar las reglas…» para ver qué haría sin mover nada y actívalo cuando
> te convenza.

## Configurar

Todo vive en `~/Library/Application Support/Escudero/config.yaml` (la primera vez
se copia de [config.ejemplo.yaml](config.ejemplo.yaml)), **validado con Pydantic** (mensajes de
error accionables; config inválida → la app sigue con la última buena).
Tras editar: menú 🛡 → **Recargar configuración**.
O valida desde terminal (tras `./instalar.sh`): `venv/bin/python escudero.py --validar-config`.

## Ordenar: cómo decide y qué no hace nunca

- Solo los archivos **sueltos**; las subcarpetas (tus proyectos) no se tocan.
- Reglas **en orden**, gana la primera que casa. En `si`, todas las condiciones;
  en una lista, basta una; `excepto` la descarta si se cumple cualquiera.
- Las edades cuentan **desde que el archivo llegó** a la carpeta (la «fecha de
  adición» del Finder): un zip viejo recién descomprimido no va al desván.
- Nunca borra ni sobrescribe: colisiones con sufijo « 2». Mueve también a otros discos.
- Ignora descargas a medias y lo que llegó o se modificó hace menos de 2 min.
- **Probar las reglas…** (menú) enseña qué haría con cada archivo y por qué,
  incluido «esperando a Comprimidos: lleva 2 de 7 días». No mueve nada.
- Historial en `ordenar.db` (carpeta de datos): **Últimos movimientos** (clic → en el Finder)
  y **deshacer** la última pasada.
- `contenido_regex` mira DENTRO (texto, o reconocimiento en imágenes y PDF) y
  recuerda lo leído; úsala en carpetas pequeñas.
- Las reglas por defecto no sacan nada de `~/Downloads`: solo lo ordenan en subcarpetas.

## Probar sin GUI

```bash
venv/bin/python escudero.py --probar-ordenar   # qué movería (en seco)
venv/bin/python escudero.py --informe          # genera el informe HTML
venv/bin/python escudero.py --validar-config   # valida config.yaml (errores explicados)
venv/bin/python -m unittest discover -s tests  # tests
```

## API local y ecosistema

Escudero escucha en `127.0.0.1:8764` para **VozLocal** (órdenes de voz) y
**ForgeDesk** (tiempo y foco). Contrato completo: [docs/API.md](docs/API.md);
mapa de integraciones: [docs/INTEGRACION.md](docs/INTEGRACION.md).
Token en `~/.config/escudero/api.token` (chmod 600, autogenerado).

Los datos (SQLite, logs, informes, estado) viven en
`~/Library/Application Support/Escudero/datos/` (menú → «Abrir carpeta de datos…»).
