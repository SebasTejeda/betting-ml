# Tareas — Spec 001

Instrucciones para el agente:
- Ejecuta las tareas **en orden**. Marca `[x]` al terminar cada una y registra una línea en `PROGRESS.md`.
- "Hecho cuando" es obligatorio: si no se cumple, la tarea no está terminada.
- Tras cada tarea: `make lint && make test` en verde → commit con el mensaje indicado (o uno equivalente con Conventional Commits).
- Si tomas una decisión que no está en la spec o el plan, anótala en `specs/001-prediction-model/decisions.md` (fecha, decisión, motivo).
- Los **checkpoints de revisión** (🔍) se hacen con el subagente `ml-reviewer` (`.claude/agents/ml-reviewer.md`). Corrige todo lo que marque como bloqueante antes de seguir.

---

## Fase 0 — Base del proyecto

- [x] **T001** Inicializar repo y esqueleto
  - `git init` si no es un repo. Crear la estructura de carpetas de `plan.md` §2 (con `__init__.py`), `pyproject.toml` (dependencias de `plan.md` §1, config de ruff, pytest y coverage), `.gitignore` (data/, models/**/*.joblib, .env, .venv, __pycache__, .ipynb_checkpoints), `.env.example`, `.pre-commit-config.yaml`, `Makefile` con todos los targets de `plan.md` §8 (los que aún no existan pueden imprimir "pendiente").
  - Hecho cuando: `make setup && make lint && make test` corren sin error (con 1 test trivial).
  - Commit: `chore: project skeleton with tooling`

- [x] **T002** CI
  - `.github/workflows/ci.yml` según `plan.md` §10.
  - Commit: `ci: lint and test workflow`

- [x] **T003** Configuración
  - `config.py` (Settings con pydantic-settings), `configs/leagues.yaml` (5 ligas, códigos football-data y Understat, temporadas), `configs/features.yaml` (parámetros por defecto), `configs/team_aliases.yaml` vacío con el formato documentado.
  - Hecho cuando: test que carga los tres YAML y valida su esquema.
  - Commit: `feat(config): settings and yaml configs`

## Fase 1 — Dominio

- [x] **T004** Entidades y puertos: `domain/entities.py`, `domain/ports.py` (según `plan.md` §6).
  - Commit: `feat(domain): entities and ports`

- [x] **T005** Matemática de cuotas: `domain/odds.py` (implícitas, overround, normalización proporcional y de Shin, cuota justa, EV, Kelly fraccional con tope).
  - Hecho cuando: tests de `plan.md` §7 en verde y cobertura del módulo ≥ 90 %.
  - Commit: `feat(domain): odds math with shin normalization`

- [x] **T006** Métricas: `domain/metrics.py` (log loss, Brier multiclase, RPS, ECE, accuracy).
  - Hecho cuando: coinciden con `sklearn` donde aplique (tolerancia 1e-9).
  - Commit: `feat(domain): evaluation metrics`

## Fase 2 — Datos

- [x] **T007** Adaptador football-data: descarga con caché, lectura robusta (encoding), normalización al esquema canónico (`plan.md` §3.2), incluido el mapeo `BbAv*/BbMx*` → `avg_*/max_*`.
  - Hecho cuando: tests con CSV de ejemplo de una temporada antigua y una nueva en `tests/fixtures/`.
  - Commit: `feat(adapters): football-data source`

- [x] **T008** Adaptador Understat: xG por partido, con pausa entre peticiones y caché. Inspecciona primero la página real para ver cómo expone los datos hoy; si el scraping directo no funciona, usa `soccerdata`. Documenta en `decisions.md` qué método quedó.
  - Hecho cuando: test de parseo con JSON de ejemplo guardado en `tests/fixtures/`.
  - Commit: `feat(adapters): understat xg source`

- [x] **T009** Nombres de equipos: `adapters/team_names.py` + completar `team_aliases.yaml` para las 5 ligas y todas las temporadas (descarga los datos para descubrir todos los nombres).
  - Hecho cuando: 100 % de los equipos de ambas fuentes mapeados; test que falla si aparece uno nuevo sin mapear.
  - Commit: `feat(data): team name normalization`

- [x] **T010** Caso de uso `build_dataset`: limpieza, validaciones, emparejamiento con xG, separación `matches / holdout / current`, `reports/data_quality.md`. Conecta en `cli.py` y `make data`.
  - Hecho cuando: `make data` corre de punta a punta con datos reales; emparejamiento xG ≥ 98 %; sin duplicados; reporte generado.
  - Commit: `feat(data): dataset build pipeline and quality report`

- [x] **T011** EDA breve en `notebooks/01_eda.ipynb`: % local/empate/visita por liga, margen promedio por casa, goles vs xG, evolución del Elo de 3 equipos. Resume hallazgos en 5–8 bullets en `PROGRESS.md`.
  - Commit: `docs(eda): exploratory analysis`

- [x] 🔍 **T012** Checkpoint de revisión de datos con `ml-reviewer` (foco: calidad, emparejamiento, zona horaria, duplicados).

## Fase 3 — Features y validación

- [x] **T013** `ml/features/elo.py` (según `plan.md` §4). Test: el Elo de un partido no cambia si se altera su propio resultado.
  - Commit: `feat(features): elo ratings`
- [x] **T014** `ml/features/form.py` y `ml/features/xg.py` (ventanas y EWMA, con prior de liga).
  - Commit: `feat(features): rolling form and xg`
- [x] **T015** `ml/features/schedule.py` y `ml/features/market.py` (solo cuotas pre-cierre).
  - Commit: `feat(features): schedule and market features`
- [x] **T016** `ml/features/pipeline.py` que arma todo según `features.yaml` + **tests anti-fuga** completos de `plan.md` §7.
  - Hecho cuando: tests anti-fuga en verde; cobertura de `ml/features/` ≥ 80 %.
  - Commit: `feat(features): feature pipeline with leakage tests`
- [x] **T017** `ml/validation.py` con los folds F1–F3 y la separación final. Tests de no solapamiento.
  - Commit: `feat(ml): walk-forward validation`

## Fase 4 — Infraestructura de modelado

- [x] **T018** `ml/models/baselines.py` (frecuencias, mercado `avg`, mercado `psc`).
- [x] **T019** `ml/models/poisson.py` y `ml/models/dixon_coles.py` (MLE con `scipy.optimize`, decaimiento temporal, re-ajuste cada 7 días dentro del fold, matriz de goles para O/U). Tests con datos sintéticos donde se conocen los parámetros verdaderos.
- [ ] **T020** `ml/models/sklearn_models.py` (wrapper genérico con selección de features por grupos), calibración y `ensemble.py` (blend y stacking).
- [ ] **T021** `ml/betting.py` (simulación de `experiments.md` §5, bootstrap, drawdown, CLV) + `ml/plots.py` (calibración y ROI acumulado).
- [ ] **T022** `adapters/joblib_registry.py` y caso de uso `run_experiment` + `make exp ID=...` que lee `configs/experiments/{ID}_*.yaml`, corre F1–F3, guarda figuras, agrega la fila a `experiments.csv` e incluye el hash del commit.
  - Hecho cuando: un experimento de juguete corre end-to-end con datos de `tests/fixtures`.
  - Commits: uno por tarea (`feat(models): ...`, `feat(betting): ...`, `feat(app): experiment runner`).

## Fase 5 — Experimentos

- [ ] **T023** E01 (líneas base). Anota en `PROGRESS.md` el log loss del mercado `Avg` y de Pinnacle al cierre: son las metas del nivel "Bueno" y "Excelente".
- [ ] **T024** E02 → E06, uno por uno, según `experiments.md`. Después de cada uno, lee la tabla y ajusta la hipótesis del siguiente si hace falta (registrándolo).
- [ ] 🔍 **T025** Checkpoint con `ml-reviewer` tras E06 (foco: fuga de información, validación, métricas creíbles). Si un resultado parece "demasiado bueno" (log loss menor que Pinnacle al cierre sin usar cuotas), **se asume bug** hasta demostrar lo contrario.
- [ ] **T026** E07 → E15 (o hasta la regla de parada). E14 y E15: elige hipótesis según lo aprendido y justifícala.
- [ ] **T027** `make select`: aplica la regla de `experiments.md` §4 y escribe `models/champion.json`.
  - Commit: `feat(app): champion selection — <ID>`
- [ ] 🔍 **T028** Checkpoint con `ml-reviewer` antes de tocar el holdout (última oportunidad de detectar problemas).

## Fase 6 — Evaluación final e informe

- [ ] **T029** `make holdout` (una sola vez, `experiments.md` §6).
  - Commit: `exp(final): holdout evaluation — level <nivel>`
- [ ] **T030** `make report` → `reports/REPORT.md` con todo lo pedido en spec US4, escrito en español claro, con tablas y figuras enlazadas.
  - Commit: `docs(report): final model report`

## Fase 7 — Producción y API

- [ ] **T031** `make train-prod`: re-entrena campeón y `champion_no_odds` con todo lo disponible; versión con fecha.
- [ ] **T032** Adaptador `fixtures.py` (football-data `fixtures.csv` con caché de 6 h; conversión de horario a UTC y filtro por fecha en `America/Lima`).
- [ ] **T033** Casos de uso `predict_matches` y `track_predictions` (US5 y US6).
- [ ] **T034** API FastAPI completa según `contracts/api.md`: routers, schemas, errores uniformes, inyección desde `container.py`, CORS abierto para `localhost`.
- [ ] **T035** Tests de API con `TestClient` (todos los endpoints, casos de error, lista vacía, suma de probabilidades = 1).
- [ ] **T036** Colección de Postman `postman/betting-ml.postman_collection.json` (ver contrato).
- [ ] **T037** `Dockerfile` (imagen slim, usuario no root) y target `make docker`.
  - Commits: uno por tarea.

## Fase 8 — Cierre

- [ ] **T038** `README.md` final: qué es, resultados principales (nivel alcanzado y métricas clave), arquitectura (diagrama en texto), cómo instalar, cómo correr, cómo probar con Postman, limitaciones y aviso de juego responsable.
- [ ] 🔍 **T039** Auditoría final con `ml-reviewer` sobre todo el repo (arquitectura, calidad, fuga, reproducibilidad). Corregir hallazgos bloqueantes.
- [ ] **T040** Verificación final: `make lint`, `make test` (cobertura según constitución), `make serve` + probar 3 endpoints con `curl`. Resumen final en `PROGRESS.md`.
  - Commit: `chore: final verification`
