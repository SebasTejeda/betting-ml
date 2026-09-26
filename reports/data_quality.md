# Reporte de calidad de datos

Generado: 2026-09-26T23:13:01+00:00

## Resumen

- Partidos totales: **21839** (entrenamiento 19837, holdout 1752, temporada en curso 250).
- Emparejamiento con xG: **100.00%** de los partidos jugados.
- Duplicados eliminados (liga + fecha + local + visita): 0.
- Filas sin resultado eliminadas: 0.
- Filas con goles negativos eliminadas: 0.
- Resultados (FTR) incoherentes con los goles y corregidos: 0.
- Cuotas inválidas (≤ 1.01) convertidas a nulo: 11.
- Cuotas `max` implausibles (margen < -3%) convertidas a nulo: 236.
- Resultados adjudicados en mesa (goles de Understat distintos de football-data; se usa el marcador del campo y `result_awarded=True`): 2.
- xG emparejado en segunda pasada (liga + temporada + equipos; partidos reprogramados, `xg_date_mismatch=True`): 4.
- Partidos con cuotas de cierre anuladas por `configs/data_overrides.yaml`: 1.
- xG tomado de football-data (respaldo): 1.
- Fallos de la fuente de xG: 0.

## Partidos por liga y temporada

| season | D1 | E0 | F1 | I1 | SP1 |
|---|---|---|---|---|---|
| 2014-15 | 306 | 380 | 380 | 380 | 380 |
| 2015-16 | 306 | 380 | 380 | 380 | 380 |
| 2016-17 | 306 | 380 | 380 | 380 | 380 |
| 2017-18 | 306 | 380 | 380 | 380 | 380 |
| 2018-19 | 306 | 380 | 380 | 380 | 380 |
| 2019-20 | 306 | 380 | 279 | 380 | 380 |
| 2020-21 | 306 | 380 | 380 | 380 | 380 |
| 2021-22 | 306 | 380 | 380 | 380 | 380 |
| 2022-23 | 306 | 380 | 380 | 380 | 380 |
| 2023-24 | 306 | 380 | 306 | 380 | 380 |
| 2024-25 | 306 | 380 | 306 | 380 | 380 |
| 2025-26 | 306 | 380 | 306 | 380 | 380 |
| 2026-27 | 36 | 50 | 45 | 50 | 69 |

## Emparejamiento con xG por liga

| league | % con xG |
|---|---|
| D1 | 100.00% |
| E0 | 100.00% |
| F1 | 100.00% |
| I1 | 100.00% |
| SP1 | 100.00% |

## Equipos mapeados por liga

| league | equipos |
|---|---|
| D1 | 31 |
| E0 | 36 |
| F1 | 35 |
| I1 | 36 |
| SP1 | 33 |

## Partidos sin xG emparejado

Ninguno.

## % de nulos por columna

| columna | % nulos |
|---|---|
| fd_home_xg | 98.86 |
| fd_away_xg | 98.86 |
| ps_over25 | 47.26 |
| ps_under25 | 47.26 |
| psc_over25 | 47.19 |
| psc_under25 | 47.19 |
| b365c_odds_a | 41.82 |
| b365c_odds_d | 41.82 |
| b365c_odds_h | 41.82 |
| avgc_over25 | 41.82 |
| avgc_odds_h | 41.81 |
| avgc_odds_a | 41.81 |
| avgc_odds_d | 41.81 |
| maxc_odds_a | 41.81 |
| maxc_odds_d | 41.81 |
| avgc_under25 | 41.81 |
| maxc_odds_h | 41.81 |
| ps_odds_a | 5.14 |
| ps_odds_h | 5.14 |
| ps_odds_d | 5.14 |
| psc_odds_d | 5.07 |
| psc_odds_a | 5.07 |
| psc_odds_h | 5.07 |
| max_odds_a | 1.09 |
| max_odds_d | 1.09 |
| max_odds_h | 1.09 |
| b365_odds_a | 0.03 |
| b365_odds_h | 0.03 |
| b365_odds_d | 0.03 |
| away_sot | 0.01 |
| home_sot | 0.01 |
| away_shots | 0.01 |
| home_shots | 0.01 |
| avg_under25 | 0.01 |
| avg_over25 | 0.01 |
| max_over25 | 0.01 |
| max_under25 | 0.01 |
