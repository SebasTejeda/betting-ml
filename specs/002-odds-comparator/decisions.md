# Registro de decisiones — Spec 002

Formato:

```
## AAAA-MM-DD — Título corto
- Contexto:
- Decisión:
- Motivo:
- Impacto:
```

## 2026-09-27 — Pinnacle como referencia vía The Odds API
- Contexto: la API pública de Pinnacle cerró en julio de 2025.
- Decisión: usar la cuota de Pinnacle que publica The Odds API (región `eu`) y Betfair Exchange como respaldo.
- Motivo: es la forma gratuita y legal disponible; el plan gratis alcanza para uso personal.
- Impacto: la cuota puede tener retraso; se muestra la hora de la última actualización.

## 2026-09-27 — Casas peruanas por ingreso manual
- Contexto: ninguna API de cuotas revisada cubre las casas con licencia de MINCETUR.
- Decisión: ingreso manual en la calculadora; sin scraping.
- Motivo: términos de uso y fragilidad del scraping.
- Impacto: un paso manual por apuesta, pero con evaluación instantánea.

## 2026-09-27 — Reutilizar 2025-26 como test del backtest
- Contexto: 2025-26 ya se usó como holdout del modelo en la spec 001.
- Decisión: usarlo también como test de la estrategia de referencia, con su propio lock.
- Motivo: la estrategia no aprende parámetros del modelo; su único hiperparámetro (umbral) se fija en F1–F3.
- Impacto: la variante con filtro del modelo sí hereda que el campeón se eligió sin ver 2025-26, así que sigue siendo válida.

## 2026-09-27 — `/matches` vacío del sábado 26/09/2026 no era un bug (T002)
- Contexto: spec §7 pedía verificar si el filtro de fecha de `/matches` fallaba.
- Hallazgo: el `fixtures.csv` real descargado ese día (`data/raw/fixtures/fixtures_20260927T003301.csv`) solo contiene E2, E3, EC, SC1 y SP2. Las 5 ligas soportadas jugaron por última vez el 20/09 y el calendario de Understat (descargado el 26/09) no tiene partidos suyos entre el 25 y el 28/09 (parón entre jornadas). El parseo `dd/mm/yyyy`, la conversión hora UK → UTC y el filtro por fecha en `America/Lima` son correctos.
- Decisión: no se cambia la lógica; se agrega un test de regresión con un extracto del CSV real (`tests/unit/test_fixtures_20260926.py`).
- Impacto: la lógica de fechas de fixtures se puede reutilizar en la spec 002.

## 2026-09-27 — Backtest en validación: regla del umbral y advertencia sobre `max_odds` (T005)
- Regla del umbral (no fijada en la spec): para cada escenario × variante, el umbral de {0.01, 0.02, 0.03, 0.05} con **mayor CLV medio** en F1–F3 agrupados entre los que tienen **≥ 300 apuestas**; si hay empate o ninguno llega a 300, el menor (más apuestas). Se usa el CLV y no el ROI porque el ROI con cientos de apuestas es mayormente ruido y la puerta T008 se define por CLV.
- Variantes con filtro del modelo: usan las predicciones out-of-fold de F1–F3 guardadas por los experimentos de la spec 001 (E12 y E06, campeones de `models/champion.json`).
- Advertencia: en el escenario `max`, el CLV positivo (+5.7 %) viene casi todo de apuestas a longshots (cuota mediana 6.7) donde la mejor cuota del mercado supera a Pinnacle en un 17 % de media (hasta +83 %). Son precios atípicos o desactualizados de alguna casa, a menudo inaccesibles o con límites bajos, y `Max*` de football-data puede incluir casas o exchanges que no se pueden usar desde Perú. El ROI del mismo escenario es −13 % (IC [−35 %, +14 %]). Se trata `max` como escenario optimista y dudoso; la referencia realista es `b365`.
- Control: el escenario `avg` da CLV medio negativo (−11.7 % con apenas 10 apuestas), como se esperaba: sin precios por encima del mercado promedio no hay valor.

## 2026-09-27 — Estrategia principal y reglas del test final, fijadas antes de verlo (T006/T007)
- Estrategia principal del backtest: **Bet365 sin filtro del modelo** (`b365|none`). Es el escenario realista de "una casa blanda" (spec §6) y no depende del modelo. Decide el nivel de la spec §5 y la conclusión. Los demás escenarios se reportan igual.
- Conclusión: **seguir** si la principal alcanza el nivel Bueno en el test (CLV > 0 y límite inferior del IC del ROI > −3 %); **seguir con cambios** si no, pero algún escenario que no sea el control `avg` tiene CLV > 0 en el test; **no seguir** en otro caso.
- El test final usa los umbrales fijados en validación, las predicciones del holdout de la spec 001 (modelos entrenados sin ver 2025-26) y su propio lock (`reports/HOLDOUT_002_USED.lock`, reclamado antes de leer datos). Las apuestas del test se guardan en `reports/holdout_artifacts/backtest_002_test_bets.parquet`.
- Solo hay cuotas de Pinnacle en ~55 % de 2025-26: en el resto no hay referencia y no se apuesta. Se reporta la cobertura.

## 2026-09-27 — Reglas del test final revisadas tras el checkpoint T006 (antes de ver el test)
- Contexto: `ml-reviewer` bloqueó el diseño del test final (sin fuga). Con las reglas anteriores la conclusión estaba casi decidida: el CLV de `max` es positivo por construcción (sigue al EV casi 1:1 porque mide que el precio máximo supera a Pinnacle, no que se pueda apostar a él), y cualquier escenario con CLV puntual > 0 bastaba para "seguir con cambios".
- Decisiones (fijadas antes de ejecutar T007):
  - `max` y `avg` son **solo informativos**. La evidencia sale de **Bet365**, una casa blanda real.
  - **Seguir:** la estrategia principal `b365|none` alcanza el nivel Bueno en el test (CLV > 0 y límite inferior del IC 95 % del ROI > −3 %).
  - **Seguir con cambios:** si no, pero alguna variante Bet365 (sin filtro o con filtro de modelo) tiene, sumando validación y test con sus umbrales fijos, **≥ 50 apuestas con CLV y límite inferior del IC 95 % del CLV > 0**.
  - **No seguir:** en otro caso.
  - **Potencia declarada:** se esperan ~23 apuestas de `b365|none` en el test (2.4 % de los partidos × ~51–55 % de cobertura de Pinnacle). Con esa muestra, el nivel Bueno no tiene potencia estadística y el informe no lo presentará como un resultado firme.
  - Lecturas adicionales: 6 variantes × 4 umbrales sin corrección por comparaciones múltiples; en los escenarios `b365` y `avg` el umbral es 0.01 por defecto (ningún umbral llega a 300 apuestas).
  - Se agrega un **placebo** (CLV de apostar a todos los resultados a esa cuota, sin selección) en validación y test.
  - Se guarda por apuesta: `ps_odds`, `psc_odds`, `p_close`, `p_model` y la fracción de Kelly. Se guardan también la cobertura de Pinnacle por liga y por mes, y hashes del JSON de validación y de las predicciones del holdout (también en el lock).
  - Las comprobaciones previas de las predicciones del holdout se hacen **antes** de reclamar el lock.
- **Lectura honesta de la puerta T008** (validación): pasa en lo formal (CLV medio > 0), pero el escenario `max` no es apostable. La evidencia realista es débil: `b365|none` tiene CLV +0.9 % con un IC que incluye el 0 (+2.9 % en 2022-23, −0.02 % en 2023-24 y −0.4 % en 2024-25). Las variantes con filtro de modelo tienen un IC por encima de 0, pero con ~47 apuestas y sin corregir por comparaciones múltiples.
- (2ª revisión T006, antes de ver el test) "Seguir con cambios" exige además que **el test por sí solo** tenga CLV medio > 0 con ≥ 5 apuestas con CLV en esa variante Bet365. Sin esto, las variantes con filtro (≈ 47 apuestas en validación, ≈ 8 esperadas en el test) llegaban a "seguir con cambios" más de la mitad de las veces aunque el test no tuviera ventaja. El check del nivel Mínimo usa solo variantes Bet365 (no `max`). Antes del lock se verifica que la validación recalculada coincide con el JSON guardado y que las predicciones del holdout tienen las 1 752 filas.
