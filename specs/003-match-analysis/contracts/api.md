# Contrato de la API — extensión de la spec 003

Se suma a los contratos de las specs 001 y 002. Mismo formato de errores. Escrituras con `X-API-Key`.

## GET `/api/v1/teams/search?q=madr`

```json
[ { "name": "Real Madrid", "league": "SP1", "clubelo": 1985.4 },
  { "name": "Atlético Madrid", "league": "SP1", "clubelo": 1890.1 } ]
```

## GET `/api/v1/analysis/fixture?home=Real Madrid&away=RB Leipzig`

Busca el próximo partido entre los dos equipos (ligas, Champions, Europa League).

```json
{ "found": true, "match_id": "UCL-2026-10-22-real-madrid-rb-leipzig", "competition": "UCL", "kickoff": "2026-10-22T19:00:00Z" }
```
Si no hay partido próximo: `found: false`. El análisis se puede pedir igual con `date` y `competition` (partido hipotético, sin cuotas).

## GET `/api/v1/analysis`

Query: `home`, `away` (obligatorios), `match_id` o (`date` + `competition`), `min_edge` (default de settings).

```json
{
  "match": {
    "match_id": "UCL-2026-10-22-real-madrid-rb-leipzig",
    "competition": "UCL",
    "kickoff": "2026-10-22T19:00:00Z",
    "home_team": "Real Madrid",
    "away_team": "RB Leipzig",
    "cross_league": true,
    "ratings": { "home": 1985.4, "away": 1812.7, "source": "clubelo", "date": "2026-10-21" },
    "expected_goals": { "home": 2.05, "away": 1.12 },
    "odds_snapshot_at": "2026-10-21T15:00:00Z",
    "warnings": ["Partido entre ligas: la fuerza se ajusta con ClubElo, hay más incertidumbre.", "Sin xG para partidos europeos."]
  },
  "best_options": [
    {
      "market": "team_totals", "selection": "home_over", "line": 1.5,
      "label": "Real Madrid más de 1.5 goles",
      "probability": 0.6420, "fair_odds": 1.56, "best_odds": 1.95, "bookmaker": "betsson",
      "ev": 0.2519, "verdict": "valor", "confidence": "media", "experimental": true,
      "reasons": [
        { "stance": "for", "text": "El modelo espera 2.1 goles de Real Madrid en este partido.", "evidence": { "lambda_home": 2.05 } },
        { "stance": "for", "text": "Real Madrid marcó 2 o más en 5 de sus últimos 6 partidos de local.", "evidence": { "scored_2plus": 5, "n": 6, "venue": "home" } },
        { "stance": "context", "text": "Partido entre ligas: la fuerza se ajusta con ClubElo, hay más incertidumbre.", "evidence": { "cross_league": true } }
      ]
    }
  ],
  "most_likely": [
    {
      "label": "Real Madrid o empate", "market": "double_chance", "selection": "1X",
      "probability": 0.8210, "fair_odds": 1.22, "best_odds": 1.15, "ev": -0.0559, "verdict": "evitar",
      "price_comment": "Muy probable (82 %), pero la cuota 1.15 paga menos de lo justo (1.22): EV −5.6 %. No conviene."
    }
  ],
  "no_value_message": null,
  "markets": [
    {
      "market": "totals", "name": "Más/Menos goles", "confidence": "alta", "experimental": true,
      "selections": [
        { "selection": "over", "line": 2.5, "label": "Más de 2.5", "probability": 0.6110, "fair_odds": 1.64, "best_odds": 1.70, "bookmaker": "1xbet", "ev": 0.0387, "verdict": "valor" },
        { "selection": "under", "line": 2.5, "label": "Menos de 2.5", "probability": 0.3890, "fair_odds": 2.57, "best_odds": 2.25, "bookmaker": "betsson", "ev": -0.1248, "verdict": "evitar" }
      ]
    }
  ],
  "form": {
    "home": {
      "last6": [ { "date": "2026-10-18", "opponent": "Getafe", "competition": "SP1", "venue": "home", "goals_for": 3, "goals_against": 1, "xg_for": 2.4, "xg_against": 0.7, "result": "W" } ],
      "summary": { "goals_for_avg": 2.3, "goals_against_avg": 0.8, "xg_for_avg": 2.1, "xg_against_avg": 0.9, "over25_pct": 0.67, "btts_pct": 0.50, "scored_2plus": 5, "streak": "WWDWWW" },
      "summary_venue": { "venue": "home", "n": 6, "goals_for_avg": 2.4 }
    },
    "away": { "...": "..." },
    "h2h": { "matches": [], "note": "Los enfrentamientos directos tienen poco poder predictivo." }
  }
}
```

- `verdict`: `valor` | `justo` | `evitar` | `sin_cuota`.
- `confidence`: `alta` | `media` | `baja` (de `reports/market_calibration.json`).
- `experimental`: `true` hasta que el mercado cumpla la condición de US6.
- `no_value_message`: texto cuando `best_options` está vacío.
- Errores: `404 TEAM_NOT_FOUND`; `422 SAME_TEAM`; `503 RATINGS_UNAVAILABLE` (partido entre ligas sin ClubElo).

## POST `/api/v1/analysis/{match_id}/odds/refresh`

Descarga los mercados adicionales del evento. `X-API-Key`.

```json
{ "markets": ["h2h","totals","btts","team_totals","double_chance","draw_no_bet"], "credits_used": 6, "credits_remaining": 478 }
```
`429 ODDS_BUDGET_LOW` igual que la spec 002.

### GET `/api/v1/analysis/{match_id}/odds/estimate`
Costo estimado antes de refrescar: `{ "markets": 6, "regions": 1, "estimated_credits": 6, "credits_remaining": 484 }`.

## Registro de apuestas (cambio en spec 002)

`POST /api/v1/bets` acepta además `market`, `selection` y `line` (opcionales; por defecto `h2h`). Liquidación según el mercado; CLV solo si hay cuota de cierre de referencia.

## GET `/api/v1/markets/calibration`
Devuelve `reports/market_calibration.json`.
