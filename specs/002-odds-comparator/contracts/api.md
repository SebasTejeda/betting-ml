# Contrato de la API — v1, extensión de la spec 002

Se suma a `specs/001-prediction-model/contracts/api.md`. Mismo formato de errores, mismos códigos HTTP. Los endpoints que escriben datos (`POST`, `PATCH`, `DELETE`) requieren el header `X-API-Key` (clave en `.env`, variable `APP_API_KEY`).

---

## Cuotas

### POST `/api/v1/odds/refresh`
Descarga un snapshot nuevo de The Odds API para las ligas configuradas.

Query: `league` (opcional, por defecto todas).

`202`:
```json
{ "snapshot_id": 412, "leagues": ["E0","SP1"], "events": 18, "credits_used": 4, "credits_remaining": 431, "unmapped_teams": [] }
```
`429` si los créditos restantes están bajo el mínimo configurado:
```json
{ "error": { "code": "ODDS_BUDGET_LOW", "message": "Quedan 42 créditos (mínimo 50). Refresco bloqueado hasta el próximo ciclo." } }
```
Antes de responder `429` se consulta `GET /v4/sports` (gratis) para detectar si el proveedor ya renovó los créditos del mes. Si una liga falla a mitad del refresco, lo ya descargado (y pagado) se guarda igual y se responde `502 ODDS_API_ERROR`. Los partidos ya empezados no se guardan.

### GET `/api/v1/odds/budget`
```json
{ "credits_remaining": 431, "credits_used_month": 69, "min_reserve": 50, "last_refresh": "2026-09-27T13:02:00Z" }
```

### GET `/api/v1/bookmakers`
```json
[ { "key": "pinnacle", "name": "Pinnacle", "role": "reference", "accessible": false },
  { "key": "betsson", "name": "Betsson", "role": "soft", "accessible": true },
  { "key": "teapuesto", "name": "Te Apuesto", "role": "soft", "accessible": true, "source": "manual" } ]
```

---

## Comparador

### GET `/api/v1/comparator`
Partidos de una fecha con la mejor cuota por resultado (producto principal) y, aparte, la señal experimental.

Query: `date` (default hoy en `America/Lima`), `league`, `only_value` (bool), `min_edge` (default `0.02`), `accessible_only` (default `true`).

```json
{
  "date": "2026-09-27",
  "snapshot_at": "2026-09-27T13:02:00Z",
  "reference": "pinnacle",
  "count": 1,
  "matches": [
    {
      "match_id": "E0-2026-09-27-arsenal-chelsea",
      "league": "E0",
      "kickoff": "2026-09-27T14:00:00Z",
      "home_team": "Arsenal",
      "away_team": "Chelsea",
      "fair": {
        "source": "pinnacle",
        "probabilities": { "home": 0.5140, "draw": 0.2560, "away": 0.2300 },
        "odds": { "home": 1.95, "draw": 3.91, "away": 4.35 }
      },
      "model": { "probabilities": { "home": 0.5123, "draw": 0.2544, "away": 0.2333 }, "version": "E12-..." },
      "best": {
        "home": { "bookmaker": "betsson", "odds": 1.98, "ev": 0.0177 },
        "draw": { "bookmaker": "1xbet",   "odds": 3.95, "ev": 0.0112 },
        "away": { "bookmaker": "betsson", "odds": 4.60, "ev": 0.0580 }
      },
      "margins": { "best_combined": 0.0035, "average": 0.0480, "best_vs_average_uplift": 0.041 },
      "experimental_signal": {
        "label": "EXPERIMENTAL — solo papel",
        "bets": [
          { "outcome": "away", "bookmaker": "betsson", "odds": 4.60, "ev": 0.0580, "model_agrees": true, "suggested_stake": 2.01 }
        ]
      }
    }
  ]
}
```

- `ev = p_justa × cuota − 1`.
- `model_agrees = p_modelo ≥ p_justa` para ese resultado.
- `suggested_stake` en la moneda del bankroll (Kelly 25 % sobre `p_justa`, con tope).
- `margins.best_combined` = margen de la combinación de mejores cuotas accesibles; `average` = margen de la cuota promedio; `best_vs_average_uplift` = cuánto más paga la mejor cuota que el promedio (media de los 3 resultados).
- La señal de valor va **solo** dentro de `experimental_signal` y nunca se llama "recomendación" (reorientación 2026-09-27).
- Sin referencia disponible para un partido: `fair: null`, `experimental_signal: null`, y `warning: "Sin cuota de referencia"`.

### GET `/api/v1/comparator/{match_id}`
Detalle: todas las casas × resultados, margen de cada casa, mejor cuota resaltada y serie temporal de la cuota de referencia.

```json
{
  "match_id": "...",
  "bookmakers": [ { "key": "betsson", "accessible": true, "odds": { "home": 1.98, "draw": 3.40, "away": 4.60 }, "margin": 0.0166, "updated_at": "..." } ],
  "reference_history": [ { "at": "2026-09-26T20:00:00Z", "odds": { "home": 1.97, "draw": 3.90, "away": 4.30 } } ]
}
```

### POST `/api/v1/calculator`
Evalúa una cuota ingresada a mano (US4). También guarda la cuota como snapshot `manual`. Solo acepta casas de ingreso manual (`source: manual` en el catálogo): una casa que llega por la API (p. ej. `pinnacle`) responde `422 BOOKMAKER_NOT_MANUAL`. Las cuotas manuales nunca se usan como referencia, ni para el CLV ni para la señal.

Request:
```json
{ "match_id": "E0-2026-09-27-arsenal-chelsea", "outcome": "away", "bookmaker": "teapuesto", "odds": 4.40 }
```
Response:
```json
{ "fair_probability": 0.2300, "fair_odds": 4.35, "ev": 0.0120, "verdict": "justo", "experimental": true, "suggested_stake": 0.0, "model_probability": 0.2333, "model_agrees": true, "best_available": { "bookmaker": "betsson", "odds": 4.60 } }
```
Veredicto: `valor` si `ev ≥ min_edge`; `justo` si `0 ≤ ev < min_edge`; `evitar` si `ev < 0`.

---

## Diario de apuestas

### POST `/api/v1/bets`
```json
{ "match_id": "...", "outcome": "away", "bookmaker": "teapuesto", "odds": 4.40, "stake": 10.0, "kind": "paper", "from_experimental_signal": false, "note": "opcional" }
```
`201` con la apuesta creada. `kind`: `real` | `paper`. `from_experimental_signal` (default `false`) marca las apuestas que vienen de la señal experimental.

Señal experimental sin evidencia: si `kind = real`, `from_experimental_signal = true` y aún no hay 100 apuestas en papel de la señal con CLV medio > 0, sin `"confirm": true` responde `409` con `code: "EXPERIMENTAL_SIGNAL_UNPROVEN"` y el mensaje "Esta señal aún no tiene evidencia (X/100 apuestas en papel, CLV actual Y). ¿Apostar dinero real igual?". Con `confirm: true` se registra (con la marca).

Si viola un límite (US6):
- Advertencia (stake alto o se acerca al límite mensual): `201` con `"warnings": ["..."]` **solo si** el request trae `"confirm": true`; si no, `409` con `code: "LIMIT_WARNING"` y el detalle. El "peor caso" suma la pérdida del mes + el stake de las apuestas reales pendientes + el stake nuevo.
- Presupuesto mensual superado y `kind = real`: `403` con `code: "MONTHLY_LIMIT_REACHED"`. Para el bloqueo, las apuestas reales pendientes de partidos que empezaron hace más de 3 h cuentan como perdidas hasta que se liquidan.
- Apuesta `real` sobre un partido sin cuotas de la API (hora de inicio desconocida): `422` con `code: "MATCH_WITHOUT_ODDS"`. En papel se acepta; sin hora de inicio conocida, se usa el inicio del día del `match_id` para liquidar o borrar.
- Una apuesta registrada después del inicio del partido se acepta pero lleva un aviso en `warnings`, y su probabilidad justa usa solo cuotas anteriores al inicio.

### GET `/api/v1/bets`
Query: `status`, `kind`, `league`, `from`, `to`. Lista paginada (`page`, `size`).

### PATCH `/api/v1/bets/{id}`
Editar nota (siempre) o liquidar manualmente (`status`). La liquidación manual solo vale para apuestas `pendiente` (si no, `409 BET_NOT_PENDING`) y después del inicio del partido (si no, `409 MATCH_NOT_STARTED`). Una apuesta liquidada no se puede volver a liquidar a mano ni volver a `pendiente`. Cada apuesta lleva `result_source` (`manual` | `official` | `null`): una apuesta real liquidada a mano como `ganada` o `nula` cuenta como perdida para el límite mensual hasta que `settle` la confirma con el resultado oficial.

### DELETE `/api/v1/bets/{id}`
Solo apuestas `pendiente` (si no, `409 BET_NOT_PENDING`) y antes del inicio del partido (si no, `409 MATCH_ALREADY_STARTED`): así borrar una apuesta no puede esconder una pérdida del mes.

### POST `/api/v1/bets/settle`
Liquida las pendientes con los resultados disponibles y calcula el CLV. Además revisa las apuestas liquidadas a mano en los últimos 30 días: si no coinciden con el resultado oficial, se corrigen (el resultado oficial manda).
```json
{ "settled": 3, "clv_computed": 3, "still_pending": 1, "corrected": 0 }
```

### GET `/api/v1/bets/summary`
Query: `kind` (`real` por defecto, `paper` o `all`), `from`, `to`.
```json
{
  "bets": 57, "settled": 52, "staked": 520.0, "profit": -8.4, "roi": -0.0162,
  "clv_mean": 0.021, "clv_positive_rate": 0.61,
  "bankroll": { "initial": 500.0, "current": 491.6, "series": [ { "date": "2026-10-01", "value": 500.0 } ] },
  "by_league": [ { "league": "E0", "bets": 14, "roi": 0.05, "clv_mean": 0.03 } ],
  "by_bookmaker": [ { "bookmaker": "betsson", "bets": 20, "roi": -0.02, "clv_mean": 0.018 } ],
  "month": { "loss_limit": 100.0, "current_loss": 8.4, "remaining": 91.6 },
  "experimental_signal": { "paper_bets": 23, "target": 100, "clv_mean": 0.012, "evidence_met": false },
  "best_odds_uplift_mean": 0.038,
  "note": "Con menos de 300 apuestas el ROI es mayormente ruido; mira el CLV."
}
```

---

## Configuración personal

### GET / PUT `/api/v1/settings`
```json
{ "bankroll_initial": 500.0, "currency": "PEN", "monthly_loss_limit": 100.0, "max_stake_pct": 0.02, "kelly_fraction": 0.25, "min_edge": 0.02 }
```
`PUT` requiere `X-API-Key`. Bajar límites aplica de inmediato; subir `monthly_loss_limit` aplica recién desde el mes siguiente.

---

## Backtest

### GET `/api/v1/backtest/pinnacle`
Devuelve `reports/backtest_002.json` (resultados de US1) para mostrarlos en el frontend, con `margins` (contenido de `reports/margins_002.json`: margen medio por escenario y cuánto más paga la mejor cuota que el promedio) si existe. `404 BACKTEST_NOT_FOUND` si aún no se corrió el backtest final.
