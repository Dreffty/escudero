# API local de Escudero — contrato de sinergia del ecosistema

Escudero escucha en **`127.0.0.1:8764`** (configurable; nunca escucha en la red).
Solo la hablan apps del propio Mac: **VozLocal** (`localhost:8765`) la usa para
mandar órdenes de voz, y **ForgeDesk** (`localhost:8763`) para leer tiempo y
fijar el foco del día.

> Puerto asignados en el ecosistema (ver también las fichas de VozLocal y ForgeDesk):
> ForgeDesk `8763` · Escudero `8764` · VozLocal `8765`.

## Autenticación

Header en TODAS las peticiones:

```
Authorization: Bearer <token>
```

El token vive en **`~/.config/escudero/api.token`** (chmod `600`, se genera solo
la primera vez que arranca la app). También se puede fijar en `config.yaml`:

```yaml
api:
  activada: true
  puerto: 8764
  # token: "..."   # vacío = se autogenera en ~/.config/escudero/api.token
```

Sin token o con token erróneo → `401 {"error": "falta token …"}`.
Cuerpo JSON inválido o > 64 KB → `400`.

## Endpoints

### `GET /status` — «¿cómo vas, escudero?»

```json
{
  "app": "escudero",
  "modulos": ["cronica", "ordenar", "pergamino", "ventanas", "cortina", "sequito", "vigia"],
  "foco": "terminar la API",
  "cronica_hoy": {"total_seg": 12540,
                  "categorias": {"Código": 9000, "Ocio": 600},
                  "proyectos": {"valorforge": 7200}},
  "ordenar": {"activado": true},
  "vigia": {"ojos": true}
}
```

### `POST /foco` — fijar el foco del día (lo usa ForgeDesk)

```jsonc
{ "texto": "terminar la API" }               // vacío = quitar el foco
// 200 {"ok": true, "foco": "terminar la API"}
```

### `GET /cronica/resumen?fecha=YYYY-MM-DD` — tiempo para los handoffs de ForgeDesk

Sin `fecha` → hoy. Forma:

```json
{
  "fecha": "2026-09-18",
  "total_seg": 12540,
  "categorias": {"Código": 9000, "Ocio": 600, "Ocio bloqueado": 120},
  "apps": {"Code": 8200, "Terminal": 800},
  "proyectos": {"valorforge": 7200}
}
// 400 {"error": "fecha debe ser YYYY-MM-DD"}
```

### `POST /comando` — órdenes de voz («Escudero, …») desde VozLocal

```jsonc
{ "texto": "Escudero, mi foco es terminar la API" }
// 200 {"ok": true, "accion": "foco", "foco": "terminar la API"}
// 400 {"ok": false, "error": "comando no reconocido: …", "comandos": [...]}
```

Comandos reconocidos hoy:

| Dices | Acción |
|---|---|
| `mi foco es …` | fija el foco del día |
| `ordena ahora` | pasada manual de Ordenar |
| `deshacer` | devuelve la última pasada |
| `pausar crónica` / `reanudar` | pausa/reanuda Crónica |
| `silencio` | apaga los avisos 20-20-20 |

## Probarla a mano

```bash
TOKEN=$(cat ~/.config/escudero/api.token)
curl -s -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8764/status | python3 -m json.tool
curl -s -H "Authorization: Bearer $TOKEN" \
     "http://127.0.0.1:8764/cronica/resumen?fecha=2026-09-18" | python3 -m json.tool
curl -s -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
     -d '{"texto":"concéntrame 25 min"}' http://127.0.0.1:8764/comando
```

## Notas de diseño

- **Solo localhost**: el bind es literalmente `127.0.0.1`; nada sale del Mac.
- **Thread-safe**: el servidor (`ThreadingHTTPServer`) corre en un hilo daemon;
  las mutaciones se reenvían al hilo principal de rumps vía `desde_hilo()`.
- **Token en disco (600)**: legible solo por tu usuario. Para rotarlo, borra el
  archivo y reinicia Escudero.

> La Muralla (y `/muralla/iniciar`, `/muralla/levantar`, «concéntrame…») se quitó el
> 2026-10-24: el bloqueo de distracciones vive en FocusDesk.
