# Spec 003 — Partidos entre ligas (Champions/Europa League)

- Test: Champions 2025-26, clubes de países del catálogo (evaluado una sola vez): 113 partidos elegibles de 189 (lock `HOLDOUT_003_EUROPE_USED.lock`).
- Rating: Elo propio entre ligas sobre openfootball (ClubElo caído); fuerza = nivel del club en su liga + desplazamiento de la liga estimado con partidos europeos.
- Elegibles: clubes de países del catálogo con ≥ 10 partidos con rating en el último año y un partido de liga en los 60 días previos.

## Modelos

| Modelo | Log loss 1X2 validación (media 2018-25) | Log loss 1X2 test | Log loss Más/Menos 2.5 test | Goles esperados / reales (test) |
|---|---|---|---|---|
| Frecuencias | 1.0587 | 1.0306 | 0.6736 | 2.93 / 3.41 |
| Elo crudo | 1.0094 | 0.9439 | 0.6707 | 2.93 / 3.41 |
| Elo + desplazamiento por liga | 0.9880 | 0.9298 | 0.6782 | 2.94 / 3.41 |

## Niveles de confianza

| Mercado | Validación | Test | Publicado |
|---|---|---|---|
| `h2h` | baja | baja | **baja** |
| `totals:2.5` | media | baja | **baja** |

## Cómo leerlo

- Los niveles valen para partidos entre clubes de países del catálogo; para el resto la API no da análisis (`503 RATINGS_UNAVAILABLE`).
- `alta` exige ≥ 400 casos positivos: con el test europeo no se puede alcanzar.
- 1X2: el ajuste por liga es el mejor modelo también en el test (0.9298 frente a 0.9439 del Elo crudo), pero queda `baja`: en validación por una ECE apenas por encima del umbral con sesgo ≈ 0, y en el test (113 partidos) la ECE de 10 bins es ruido (sesgos no significativos, |z| ≤ 1.2).
- Más/Menos 2.5: en validación era `media` (calibrado pero distingue poco); en la Champions 2025-26 hubo muchos más goles de lo habitual (3.41 por partido frente a 2.94 esperados) y el modelo no mejora a la línea base (log loss 0.6782 frente a 0.6754). Publicado: `baja`.
- _Esta sección se corrigió a mano tras la evaluación (el texto generado describía la validación); las cifras salen de `market_calibration_europe.json`._
- Los partidos entre ligas siempre llevan el aviso de más incertidumbre.
