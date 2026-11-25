# Integración del ecosistema: VozLocal ↔ Escudero ↔ ForgeDesk

Documento vivo de los puntos de contacto entre las tres apps. Todas son
**locales por diseño** (bind `127.0.0.1`, tokens en `~/.config/<app>/api.token`
con chmod 600). Puertos asignados: **ForgeDesk `8763` · Escudero `8764` · VozLocal `8765`**.

## Mapa de flujos

```
┌──────────┐  «Escudero, concéntrame…»   ┌──────────┐
│ VozLocal │ ──POST :8764/comando──────▶ │ Escudero │
│  :8765   │ ◀──GET :8765/status──────── │  :8764   │
└──────────┘   (estado real en Séquito)  └────┬─────┘
                                              │ GET :8764/cronica/resumen
                                              │ POST :8764/foco
                                         ┌────▼─────┐
                                         │ForgeDesk │
                                         │  :8763   │
                                         └──────────┘
```

## Puntos de contacto (hoy implementados)

| # | Dirección | Mecanismo | Estado |
|---|---|---|---|
| 1 | VozLocal → Escudero: órdenes de voz | `POST localhost:8764/comando` `{"texto": "Escudero, concéntrame 25 min"}` | ✅ implementado (comandos en `docs/API.md`) |
| 2 | Escudero → VozLocal: estado real del compañero | Séquito consulta `GET localhost:8765/status` (timeout 1 s, Bearer voxlocal token). Si no responde: fallback a «vivo/muerto» por `pgrep` | ✅ implementado (`sequito.estado_api`) — el menú muestra idle/grabando/transcribiendo cuando VozLocal expone su API |
| 3 | Escudero → ForgeDesk: tiempo por categoría/proyecto | `GET localhost:8764/cronica/resumen?fecha=YYYY-MM-DD` → ForgeDesk lo incrusta en sus handoffs («Tiempo invertido») | ✅ implementado (incluye `proyectos`, detectados por título de ventana o repo Git) |
| 4 | ForgeDesk → Escudero: foco del día | `POST localhost:8764/foco` `{"texto": "…"}` → aparece junto al escudo en la barra | ✅ implementado |
| 5 | Escudero → Escudero: eventos internos | `EventBus` (`escudero/events.py`): `ordenar_movidos`, `foco_cambiado` | ✅ implementado (la Muralla y sus eventos se quitaron el 2026-10-24) |

## Contratos pendientes (fase de sinergia)

| # | Qué falta | Quién lo tiene que hacer |
|---|---|---|
| 6 | Webhook configurable de VozLocal («Captura: …» → ForgeDesk) | VozLocal (su ficha, Fase 4) |
| 7 | Importar `GET :8764/cronica/resumen` en los handoffs de ForgeDesk (degradación silenciosa si Escudero no corre) | ForgeDesk (su ficha, Fase 4 §169) |
| 8 | Vocabulario de proyectos de ForgeDesk → Whisper de VozLocal | VozLocal + ForgeDesk |
| 9 | Arquitectura de plugins de VozLocal/ForgeDesk (cada ficha la pide por su lado) | cada proyecto |

## Reglas de juego (no negociar)

1. **Sin cuentas, sin nube**: todo el tráfico es `127.0.0.1`. Cualquier
   dependencia con red queda vetada (igual que analytics/crash-reporting).
2. **Degradación silenciosa**: si la otra app no corre, la funcionalidad se
   esconde o usa fallback (pgrep, última config buena). Nunca bloquear el arranque.
3. **Timeouts cortos** (≤ 1 s) en las llamadas entre apps: una compañera colgada
   no puede congelar el menú.
4. **Los tokens son por usuario**, no por app: `~/.config/<app>/api.token`, 600.
