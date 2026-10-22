# Spec 003 — Validación de los mercados derivados

**Nivel alcanzado (spec §5): Mínimo.**

- Modelo: Dixon-Coles sobre xG (E09 de la spec 001), ξ = 0.003, walk-forward con re-ajuste semanal; ninguna cuota entra al modelo.
- Test: temporada 2025-26 de las 5 ligas (1752 partidos), evaluado una sola vez (lock `HOLDOUT_003_USED.lock`).
- Validación: folds F1–F3 de la spec 001 (2022-23, 2023-24, 2024-25).
- Partidos europeos (Champions/Europa League): **pendientes** (ClubElo caído; T006 y una evaluación aparte con su propio lock).

## Cómo se asigna la confianza

Cada selección (por ejemplo, "Más de 2.5") es un evento sí/no. Se mide su calibración (ECE, 10 bins) y su sesgo relativo (probabilidad media / frecuencia real − 1). El grupo (mercado y línea) toma el nivel de su peor selección:

- **alta**: ECE < 0.02, |sesgo relativo| < 5 %, el grupo mejora a la línea base y ≥ 400 casos;
- **media**: el resto (incluye sesgo > 10 % no significativo: muestra insuficiente);
- **baja**: ECE ≥ 0.04, o sesgo relativo > 10 % significativo (|z| ≥ 2).

La comparación con la línea base (frecuencia histórica por liga) es por grupo, no por selección. El nivel publicado es el **peor entre validación y test**. Los mercados `baja` se muestran solo como información, sin consejos de valor.

Resultado publicado: **0 alta, 9 media, 9 baja** (en el test solo: 0 alta).

## Niveles por mercado

| Grupo | Validación | Test | Publicado | Mayor sesgo en test | ECE máx. test | Log loss test (base) |
|---|---|---|---|---|---|---|
| `h2h` | media | media | **media** | draw -8.3 % (z -2.2) | 0.034 | 0.5797 (0.6225) |
| `double_chance` (derivado de 1X2) | media | media | **media** | 12 +2.8 % (z +2.0) | 0.034 | 0.5797 (0.6225) |
| `draw_no_bet` | media | media | **media** | away +1.0 % (z +0.3) | 0.027 | 0.5759 (0.6750) |
| `totals:0.5` | media | media | **media** | under -11.8 % (z -1.5) | 0.008 | 0.2373 (0.2412) |
| `totals:1.5` | alta | baja | **baja** | under -12.4 % (z -3.3) | 0.031 | 0.5383 (0.5432) |
| `totals:2.5` | alta | baja | **baja** | under -8.2 % (z -3.5) | 0.041 | 0.6855 (0.6878) |
| `totals:3.5` | media | baja | **baja** | over +18.1 % (z +4.2) | 0.054 | 0.6037 (0.6026) |
| `totals:4.5` | baja | baja | **baja** | over +31.5 % (z +4.1) | 0.047 | 0.4084 (0.4077) |
| `btts` | alta | media | **media** | no -5.8 % (z -2.4) | 0.027 | 0.6864 (0.6907) |
| `team_totals:home:0.5` | alta | media | **media** | home_under -7.6 % (z -1.9) | 0.024 | 0.5026 (0.5362) |
| `team_totals:home:1.5` | media | media | **media** | home_over +6.0 % (z +2.2) | 0.030 | 0.6551 (0.6875) |
| `team_totals:home:2.5` | baja | media | **baja** | home_over +9.7 % (z +1.9) | 0.024 | 0.4893 (0.5189) |
| `team_totals:away:0.5` | alta | media | **media** | away_under -5.8 % (z -1.7) | 0.025 | 0.5838 (0.6098) |
| `team_totals:away:1.5` | alta | media | **media** | away_over +9.4 % (z +2.6) | 0.035 | 0.6194 (0.6434) |
| `team_totals:away:2.5` | media | baja | **baja** | away_over +21.7 % (z +2.9) | 0.030 | 0.3600 (0.3816) |
| `european_handicap:-1` | baja | baja | **baja** | home +10.9 % (z +2.2) | 0.025 | 0.5377 (0.5788) |
| `european_handicap:1` | media | baja | **baja** | away +17.0 % (z +2.3) | 0.025 | 0.4532 (0.4885) |
| `correct_score` | baja | baja | **baja** | top2 -13.9 % (z -2.4) | 0.016 | 0.3220 (0.3268) |

## Backtest de valor en Más/Menos 2.5

Probabilidad del modelo contra la cuota **pre-cierre** de cada escenario; umbral fijado en validación; una apuesta por partido; CLV contra el cierre de Pinnacle (solo para medir).

| Escenario | Umbral | Apuestas | % a "Más" | ROI (IC 95 %) | CLV medio (IC 95 %) | Placebo misma mezcla |
|---|---|---|---|---|---|---|
| b365 | 10% | 262 | 90% | -12.1 % (-25.1 %, -0.0 %) | -5.7 % (-6.4 %, -4.9 %) | -5.5 % |
| avg | 8% | 253 | 91% | -10.9 % (-23.5 %, +1.3 %) | -7.5 % (-8.3 %, -6.7 %) | -7.1 % |
| max | 10% | 303 | 89% | -10.1 % (-22.0 %, +2.5 %) | -4.3 % (-5.1 %, -3.6 %) | -4.2 % |

En validación (F1–F3), Bet365 dio CLV -4.8 % con 1098 apuestas (placebo misma mezcla -5.1 %).

## Conclusión

- **Probabilidades:** 9 de 18 grupos pueden generar consejos (alta/media); los `baja` solo como información.
- **Valor en Más/Menos 2.5:** la selección del modelo no le gana al cierre (CLV negativo): no hay valor demostrado. Los consejos de valor siguen **EXPERIMENTAL — solo papel** (principio XI).
- **Sesgo conocido:** el modelo espera más goles de los reales porque se ajusta sobre xG; los mercados de muchos goles salen sobreestimados (decisions.md). Recalibrarlo es un experimento futuro.
