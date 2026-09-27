# Progreso

Bitácora del agente. Una línea por tarea: `AAAA-MM-DD · TXXX · qué se hizo · resultado clave`.

## Metas de referencia (se llenan en T023)

| Referencia | Val log loss (F1–F3) |
|---|---|
| Frecuencias por liga | 1.0726 |
| Mercado `Avg` pre-cierre, Shin (meta "Bueno" ≤ 0.9701) | 0.9651 |
| Pinnacle al cierre, Shin (meta "Excelente" < 0.9622) | 0.9622 |

## Hallazgos

### EDA (T011)

- Local gana ~44–45 %, empate ~23–26 %, visita ~29–32 %; LaLiga tiene la mayor ventaja local y la Serie A la menor (y más empates).
- 2020-21 (sin público): victoria local ~40 % y visitante ~35 %. La ventaja de local varía en el tiempo.
- Margen medio: Pinnacle ~2.5 % (cierre) / 2.7 % (pre-cierre), promedio del mercado 4.8 %, Bet365 5.1 %. La mejor cuota entre casas tiene margen ≈ 0 %.
- xG medio ≈ goles medios en todas las ligas (sesgo < 0.05 goles/partido): Understat está bien calibrado; la Bundesliga es la más goleadora.
- Relación goles–xG fuerte pero ruidosa: xG debería estimar la fuerza con menos ruido que los goles.
- El Elo exploratorio refleja los ciclos conocidos (auge del Liverpool 2018-20, dominio del City, caída del Leicester tras 2016).
- Log loss del mercado promedio pre-cierre (Shin) en 2014-25 ≈ 0.966: vara realista a batir.

## Bitácora

- 2026-09-26 · T000 · Paquete SDD creado (constitución, spec, plan, experimentos, contrato, tareas) · listo para T001
- 2026-09-26 · T001 · Esqueleto hexagonal, pyproject (uv), Makefile, ruff/mypy/pytest/pre-commit · lint y test en verde (make no disponible en Windows → recetas vía uv, ver decisions.md)
- 2026-09-26 · T002 · Workflow de GitHub Actions (uv, ruff check/format, pytest sin red; Python 3.11 y 3.12) · listo
- 2026-09-26 · T003 · Settings (pydantic-settings) + leagues/features/team_aliases YAML con validación de esquema · 10 tests en verde
- 2026-09-26 · T004 · Entidades (Match, Fixture, OddsTriple, Probabilities, Prediction, ValueBet) y puertos Protocol · tests en verde
- 2026-09-26 · T005 · domain/odds.py: implícitas, overround, proporcional, Shin vectorizado (bisección), cuota justa, EV, Kelly 25% con tope 2% · cobertura 100%
- 2026-09-26 · T006 · domain/metrics.py: log loss, Brier multiclase (0–2), RPS, ECE top-label 10 bins, accuracy · coinciden con sklearn (tol 1e-9)
- 2026-09-26 · T007 · Adaptador football-data: descarga con caché + metadatos (fecha, sha256), decodificación utf-8/cp1252/latin-1, BbAv/BbMx→avg/max, hora UK→UTC (15:00 imputada si falta) · tests con CSV 2014-15, 2024-25 y 2026-27
- 2026-09-26 · T008 · Adaptador Understat vía endpoint JSON getLeagueData (sin soccerdata; ver decisions.md), pausa 3 s, caché · test con JSON real recortado
- 2026-09-26 · T009 · TeamNameResolver + team_aliases.yaml completo (171 equipos, 5 ligas, 2014-15…2026-27; canónico = nombre football-data) · 100 % de ambas fuentes mapeado; test sobre datos crudos falla si aparece uno nuevo
- 2026-09-26 · T010 · build_dataset + make data de punta a punta con datos reales: 19 837 partidos de entrenamiento, 1 752 holdout, 250 en curso; xG emparejado 99.98 % (4 partidos reprogramados sin emparejar); 0 duplicados; reports/data_quality.md
- 2026-09-26 · T011 · notebooks/01_eda.ipynb ejecutado (resultados por liga, margen por casa, goles vs xG, Elo de 3 equipos) · hallazgos abajo
- 2026-09-26 · T012 · Checkpoint datos con ml-reviewer: APROBADO CON OBSERVACIONES (0 bloqueantes). Corregidas: xG 2ª pasada (100 %), 2 resultados adjudicados, cuotas en vivo Udinese-Roma, 236 cuotas max implausibles, líneas CSV mal formadas avisadas, meta.json Understat. Pendiente para T016: priors de liga con date < d (hora imputada)
- 2026-09-26 · T013 · ml/features/elo.py: Elo por liga (K, ventaja local, multiplicador por margen, regresión 1/3 entre temporadas, ascendidos = media de descendidos) · test: el Elo de un partido no cambia si se altera su propio resultado
- 2026-09-26 · T014 · form.py (goles, puntos, tiros, tiros al arco; últimos 6 + EWMA 0.1; general y por condición; diferencias) y xg.py (xG a favor/en contra, diferencia, suerte) con prior de liga (<3 partidos, fechas estrictamente anteriores) · 50 + 26 features, tests manuales y anti-fuga
- 2026-09-26 · T015 · schedule.py (descanso, jornada, congestión 14 días) y market.py (Shin/proporcional sobre avg|ps|b365 pre-cierre; rechaza fuentes de cierre) · tests en verde
- 2026-09-26 · T016 · ml/features/pipeline.py (5 grupos, 91 features sobre datos reales en ~1 s) + tests anti-fuga: resultados futuros/mismo día no alteran features ≤ d, cuotas de cierre no afectan, patrones prohibidos, holdout solo en módulos permitidos, orden de entrada irrelevante · cobertura ml/features 100 %
- 2026-09-26 · T017 · ml/validation.py: folds F1–F3 (valid 2022-23/2023-24/2024-25), split final y validación interna (última temporada del train) · tests de no solapamiento y orden temporal
- 2026-09-26 · T018 · ml/models/baselines.py: FrequencyBaseline por liga y MarketBaseline(avg|psc|…, Shin|proporcional) con respaldo a frecuencias y cobertura reportada · tests en verde
- 2026-09-26 · T019 · poisson.py/dixon_coles.py: MLE ponderado (L-BFGS, gradiente analítico verificado), decaimiento ξ, ρ de DC, variante sobre xG (ρ en 2 etapas), re-ajuste cada 7 días solo con partidos previos, matriz de goles (1X2 y O/U) · recupera parámetros sintéticos; DC en F3 ll 0.985 en 5 s
- 2026-09-26 · T020 · sklearn_models.py (logística/XGBoost/LightGBM por grupos de features; LightGBM+Optuna en validación interna), calibration.py (temperature scaling, isotónica OvR) y ensemble.py (blend con pesos en validación interna, stacking logístico) · tests en verde
- 2026-09-26 · T021 · ml/betting.py (EV > umbral, 1 apuesta/partido, escenarios avg/max, stake plano y Kelly 25 % tope 2 %, bootstrap 2000, drawdown, CLV vs Pinnacle cierre sin margen, elección de umbral en F1–F3) + ml/plots.py (calibración, ROI acumulado) · tests en verde
- 2026-09-26 · T022 · joblib_registry, experiment_store (CSV upsert por id, JSON de detalle, predicciones), factory de modelos desde YAML (incl. ξ elegido en validación interna), caso de uso run_experiment + CLI exp/conclude + make exp ID=… · experimento de juguete end-to-end con tests/fixtures/toy_matches.csv
- 2026-09-26 · T023 · E01 líneas base en F1–F3: frecuencias 1.0726, mercado Avg (Shin) 0.9651, Avg proporcional 0.9657, Pinnacle cierre 0.9622 · metas en la tabla de arriba
- 2026-09-26 · E02 · Logística multinomial solo Elo · val ll 0.9840 (F1 0.9898, F2 0.9759, F3 0.9864), ECE 0.018; mejor hasta ahora sin cuotas. Regla de parada: sin activar.
- 2026-09-26 · E03 · Poisson (Maher) ξ=0.0019, re-ajuste semanal · val ll 0.9863; no mejora a E02 (0.9840). Regla de parada: 1 experimento sin mejora > 0.002.
- 2026-09-26 · E04 · Dixon-Coles, ξ elegido en validación interna (0.001/0.0019/0.0019) · val ll 0.9859; no mejora a E02. Regla de parada: 2 seguidos sin mejora.
- 2026-09-26 · E05 · Logística Elo + forma + calendario (C=0.05 a priori) · val ll 0.9802 (mejora 0.0038 sobre E02). Contador de parada reiniciado.
- 2026-09-26 · E06 · Logística + xG · val ll 0.9795 (−0.0007 vs E05, ECE 0.025). Regla de parada: 1 sin mejora > 0.002 (mejor: E06 0.9795).
- 2026-09-26 · T024 · E02–E06 corridos: Elo 0.9840 → Poisson 0.9863 → DC 0.9859 → +forma/calendario 0.9802 → +xG 0.9795 (mejor sin cuotas; mercado Avg 0.9651)
- 2026-09-26 · T025 · Checkpoint fuga/validación con ml-reviewer: APROBADO CON OBSERVACIONES (0 bloqueantes; sin fuga, métricas recalculadas coinciden, tests anti-fuga detectan fugas inyectadas). Corregido: conclusión E05, historial de re-ejecuciones, -dirty con configs nuevas, test allow_holdout, equipos inactivos en modelos de goles, n_prev sin nulos, umbral documentado (ROI de validación optimista). E03–E06 re-ejecutados: E03 0.9868, E04 0.9862, E05/E06 sin cambios
- 2026-09-26 · E07 · XGBoost (params a priori) con features de E06 · val ll 0.97948 (= E06). Regla de parada: 2 seguidos sin mejora > 0.002 (mejor 0.9795).
- 2026-09-26 · E08 · LightGBM + Optuna (40 trials, validación interna) · val ll 0.97852, ECE 0.016 (mejor sin cuotas, mejora < 0.002). Regla de parada (familia sin cuotas): 3 seguidos sin mejora > 0.002. Decisión registrada: regla aplicada por familia (sin cuotas / con cuotas).
- 2026-09-26 · E09 · Dixon-Coles sobre xG (ξ en validación interna) · val ll 0.9824 (mejor que DC-goles 0.9862, peor que E08). Regla de parada familia sin cuotas: 4 seguidos → se detiene; E10 y E11 no se corren. champion_no_odds provisional: E08.
- 2026-09-26 · E12 · LightGBM+Optuna con features de E06 + mercado Avg (Shin) · val ll 0.9694 (peor que el mercado solo 0.9651, pero ≤ 0.9701 = nivel Bueno en validación). **Regla de parada: nivel Bueno alcanzado → fin de experimentos** (E13–E15 no se corren).
- 2026-09-26 · T026 · E07 0.9795, E08 0.9785, E09 0.9824 (familia sin cuotas detenida por 4 seguidos sin mejora), E12 0.9694 → nivel Bueno en validación, parada anticipada. E10, E11, E13–E15 no corridos (regla de parada)
