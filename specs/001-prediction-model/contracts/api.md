# Contrato de la API — v1

- Base URL local: `http://localhost:8000`
- Formato: JSON, UTF-8. Fechas en ISO 8601. Probabilidades entre 0 y 1 con 4 decimales.
- Documentación automática: `/docs` (Swagger) y `/openapi.json`.
- Errores con formato único:

```json
{ "error": { "code": "TEAM_NOT_FOUND", "message": "Equipo 'Man Utd FC' no reconocido en E0", "details": {} } }
```

| Código HTTP | Uso |
|---|---|
| 200 | OK (incluye listas vacías) |
| 404 | Recurso no encontrado (liga o equipo) |
| 422 | Validación de entrada (FastAPI/Pydantic) |
| 503 | Modelo no entrenado o datos no disponibles |

---

## GET `/health`

```json
{ "status": "ok", "model_loaded": true, "model_version": "E08-xgb-2026-09-27", "data_last_update": "2026-09-27T10:00:00Z" }
```

## GET `/api/v1/leagues`

```json
[ { "code": "E0", "name": "Premier League", "country": "England", "teams": 20 } ]
```

## GET `/api/v1/leagues/{code}/teams`

```json
[ { "name": "Arsenal", "elo": 1874.2 } ]
```

## GET `/api/v1/matches`

Partidos de una fecha con predicción.

Query params:

| Param | Tipo | Default | Descripción |
|---|---|---|---|
| `date` | `YYYY-MM-DD` | hoy en `America/Lima` | Fecha a consultar |
| `league` | string | todas | Filtrar por código de liga |
| `only_value` | bool | `false` | Solo partidos con al menos una value bet |
| `min_edge` | float | `0.05` | Umbral de valor esperado |

Respuesta:

```json
{
  "date": "2026-09-27",
  "model_version": "E08-xgb-2026-09-27",
  "count": 1,
  "message": null,
  "matches": [
    {
      "match_id": "E0-2026-09-27-arsenal-chelsea",
      "league": "E0",
      "kickoff": "2026-09-27T14:00:00Z",
      "home_team": "Arsenal",
      "away_team": "Chelsea",
      "probabilities": { "home": 0.5123, "draw": 0.2544, "away": 0.2333 },
      "fair_odds":     { "home": 1.95,   "draw": 3.93,   "away": 4.29 },
      "market": {
        "source": "football-data fixtures.csv",
        "average_odds": { "home": 1.90, "draw": 3.70, "away": 4.20 },
        "best_odds":    { "home": 1.98, "draw": 3.90, "away": 4.50 },
        "implied_probabilities": { "home": 0.5087, "draw": 0.2612, "away": 0.2301 }
      },
      "value_bets": [
        { "outcome": "away", "odds": 4.50, "model_probability": 0.2333, "expected_value": 0.0499, "kelly_fraction": 0.0036 }
      ],
      "over_under_2_5": null
    }
  ]
}
```

- `expected_value = p_modelo × cuota − 1`.
- `kelly_fraction` = Kelly fraccional al 25 %, con tope del 2 % del bankroll.
- `over_under_2_5` solo se llena si el campeón es un modelo de goles (US7).
- Si no hay partidos: `count: 0`, `matches: []`, `message: "No hay partidos de las ligas soportadas para 2026-09-27 en la fuente"`.

## POST `/api/v1/predictions`

Predicción de un partido cualquiera.

Request:

```json
{
  "league": "E0",
  "home_team": "Arsenal",
  "away_team": "Chelsea",
  "match_date": "2026-09-27",
  "odds": { "home": 1.98, "draw": 3.90, "away": 4.50 }
}
```

`match_date` y `odds` son opcionales. Sin `odds`, la respuesta no incluye `value_bets` ni `market`. Si el campeón usa cuotas como feature y no se envían, se usa la variante del modelo sin cuotas y se indica en `model_variant`.

Response: igual a un elemento de `matches`, más `"model_variant": "with_odds" | "without_odds"`.

## GET `/api/v1/model`

```json
{
  "version": "E08-xgb-2026-09-27",
  "experiment_id": "E08",
  "trained_on": "2014-15..2024-25",
  "features": ["elo_diff", "xg_for_home_last6", "..."],
  "validation_metrics": { "log_loss": 0.9721, "brier": 0.5781, "ece": 0.012 },
  "holdout_metrics":    { "log_loss": 0.9750, "brier": 0.5802, "ece": 0.015 },
  "success_level": "Bueno"
}
```

## GET `/api/v1/experiments`

Devuelve el contenido de `reports/experiments.csv` como lista de objetos, ordenado por `val_log_loss`.

## GET `/api/v1/tracking/summary` (US6)

```json
{ "predictions": 124, "graded": 98, "log_loss": 0.981, "accuracy": 0.52, "value_bets": 17, "roi": 0.034 }
```

## POST `/api/v1/admin/refresh`

Vuelve a descargar `fixtures.csv` y los datos de la temporada en curso. Protegido con header `X-API-Key` (valor en `.env`). Responde `202` con un resumen.

---

## Colección de Postman

`postman/betting-ml.postman_collection.json` con:
- Variable `{{baseUrl}}` = `http://localhost:8000`.
- Una request por endpoint, con ejemplos válidos e inválidos (equipo inexistente, fecha mal formada).
- Tests básicos en cada request (`pm.response.to.have.status(...)`, suma de probabilidades ≈ 1).
