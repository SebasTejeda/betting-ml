# Reporte de calidad de datos

Generado: 2026-10-22T22:54:40+00:00

## Resumen

- Partidos totales: **21935** (entrenamiento 19837, holdout 1752, temporada en curso 346).
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
- xG tomado de football-data (respaldo): 2.
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
| 2026-27 | 54 | 70 | 63 | 70 | 89 |

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
| fd_home_xg | 98.42 |
| fd_away_xg | 98.42 |
| ps_under25 | 47.49 |
| ps_over25 | 47.49 |
| psc_under25 | 47.42 |
| psc_over25 | 47.42 |
| b365c_odds_d | 41.63 |
| b365c_odds_h | 41.63 |
| maxc_odds_a | 41.63 |
| maxc_odds_d | 41.63 |
| avgc_odds_h | 41.63 |
| avgc_odds_d | 41.63 |
| avgc_odds_a | 41.63 |
| maxc_odds_h | 41.63 |
| avgc_over25 | 41.63 |
| b365c_odds_a | 41.63 |
| avgc_under25 | 41.63 |
| ps_odds_h | 5.55 |
| ps_odds_d | 5.55 |
| ps_odds_a | 5.55 |
| psc_odds_d | 5.48 |
| psc_odds_h | 5.48 |
| psc_odds_a | 5.48 |
| max_odds_h | 1.08 |
| max_odds_a | 1.08 |
| max_odds_d | 1.08 |
| b365_odds_a | 0.03 |
| b365_odds_d | 0.03 |
| b365_odds_h | 0.03 |
| away_shots | 0.01 |
| home_sot | 0.01 |
| away_sot | 0.01 |
| home_shots | 0.01 |
| avg_over25 | 0.01 |
| max_over25 | 0.01 |
| avg_under25 | 0.01 |
| max_under25 | 0.01 |
| understat_id | 0.01 |
