# Plan técnico — Spec 001

Cómo se implementa [`spec.md`](spec.md) respetando la [`constitución`](../constitution.md).

## 1. Stack

| Capa | Herramienta |
|---|---|
| Lenguaje | Python 3.11+ |
| Gestor de entorno | `uv` (alternativa: `pip` + `venv`; ambos deben funcionar con `pyproject.toml`) |
| Datos | `pandas`, `numpy`, `pyarrow` (Parquet) |
| Scraping / HTTP | `requests`, `beautifulsoup4`; `soccerdata` permitido como implementación del adaptador de Understat |
| Modelos | `scipy` (Poisson / Dixon-Coles por máxima verosimilitud), `scikit-learn`, `xgboost`, `lightgbm` |
| Ajuste de hiperparámetros | `optuna` (presupuesto limitado, ver `experiments.md`) |
| Gráficos | `matplotlib` |
| API | `fastapi`, `uvicorn`, `pydantic` v2, `pydantic-settings` |
| CLI | `typer` |
| Config | YAML (`pyyaml`) + `.env` |
| Calidad | `ruff`, `mypy` (modo gradual), `pytest`, `pytest-cov`, `pre-commit`, `httpx` (tests de API) |
| CI | GitHub Actions |
| Contenedor | `Dockerfile` para la API |

## 2. Arquitectura (hexagonal)

```
betting-ml/
├── CLAUDE.md
├── README.md
├── pyproject.toml
├── Makefile
├── Dockerfile
├── .env.example
├── .gitignore
├── .pre-commit-config.yaml
├── .github/workflows/ci.yml
├── configs/
│   ├── leagues.yaml              # ligas soportadas, temporadas, códigos por fuente
│   ├── team_aliases.yaml         # nombre canónico ← alias por fuente
│   ├── features.yaml             # ventanas, parámetros Elo, etc.
│   └── experiments/E01_*.yaml … E15_*.yaml
├── data/                         # (ignorado por git)
│   ├── raw/football_data/{season}/{league}.csv
│   ├── raw/understat/{league}/{season}.json
│   ├── raw/fixtures/fixtures_{timestamp}.csv
│   ├── interim/
│   ├── processed/matches.parquet     # 2014-15 … 2024-25
│   ├── processed/holdout.parquet     # 2025-26 (solo se lee en evaluación final)
│   ├── processed/current.parquet     # 2026-27 jugados hasta hoy
│   └── tracking/predictions.parquet
├── models/                       # binarios ignorados por git; *.json sí se versiona
│   ├── champion.json
│   └── {version}/model.joblib + metadata.json
├── reports/
│   ├── experiments.csv
│   ├── data_quality.md
│   ├── REPORT.md
│   ├── HOLDOUT_USED.lock
│   └── figures/
├── notebooks/01_eda.ipynb        # solo exploración; nada de lógica que no esté en src/
├── postman/betting-ml.postman_collection.json
├── specs/ …
├── src/betting_ml/
│   ├── domain/                   # PURO: sin IO, sin frameworks
│   │   ├── entities.py           # Match, Team, Fixture, OddsTriple, Prediction, ValueBet
│   │   ├── odds.py               # implícitas, overround, Shin, proporcional, cuota justa, EV, Kelly
│   │   ├── metrics.py            # log loss, Brier, RPS, ECE, accuracy
│   │   └── ports.py              # Protocols: MatchDataSource, XgDataSource, FixtureSource,
│   │                             #   MatchRepository, ModelRegistry, ProbabilisticModel, Clock
│   ├── application/              # casos de uso (orquestan puertos)
│   │   ├── build_dataset.py
│   │   ├── run_experiment.py
│   │   ├── select_champion.py
│   │   ├── evaluate_holdout.py
│   │   ├── predict_matches.py
│   │   └── track_predictions.py
│   ├── ml/
│   │   ├── features/             # elo.py, form.py, xg.py, market.py, schedule.py, pipeline.py
│   │   ├── models/               # baselines.py, poisson.py, dixon_coles.py, sklearn_models.py, ensemble.py
│   │   ├── validation.py         # folds walk-forward
│   │   ├── betting.py            # simulación de apuestas, bootstrap, CLV
│   │   └── plots.py
│   ├── adapters/                 # implementan los puertos
│   │   ├── football_data.py
│   │   ├── understat.py
│   │   ├── fixtures.py
│   │   ├── team_names.py
│   │   ├── parquet_repository.py
│   │   └── joblib_registry.py
│   ├── api/
│   │   ├── main.py               # create_app()
│   │   ├── routers/              # health, leagues, matches, predictions, model, experiments, tracking, admin
│   │   ├── schemas.py            # modelos Pydantic de request/response
│   │   ├── errors.py
│   │   └── dependencies.py       # inyección de adaptadores
│   ├── config.py                 # Settings (pydantic-settings)
│   ├── container.py              # composición: arma casos de uso con sus adaptadores
│   └── cli.py                    # typer: data, features, experiment, select, holdout, predict, track, serve
└── tests/
    ├── unit/ (domain, features, models, betting)
    ├── integration/ (pipeline con fixtures CSV pequeños, API con TestClient)
    └── fixtures/                 # CSV/JSON mini de ejemplo (sin red)
```

Reglas de dependencia: `api → application → domain`; `adapters → domain`; `ml → domain`; `application` recibe adaptadores y modelos **inyectados** desde `container.py`. `domain` no importa nada del proyecto fuera de sí mismo.

## 3. Pipeline de datos

1. **Descarga** (`make data`)
   - football-data: para cada liga y temporada, `https://www.football-data.co.uk/mmz4281/{yyYY}/{league}.csv` (ej. `1415`, `2526`, `2627`). Leer con `encoding="latin-1"` como fallback.
   - Understat: xG por partido para cada liga y temporada (año de inicio: 2014 … 2026).
   - Caché: si el archivo crudo existe y la temporada está cerrada, no se vuelve a descargar.
2. **Normalización de columnas**
   - Las temporadas antiguas usan `BbAvH/BbMxH/...`; las nuevas `AvgH/MaxH/...`. Mapear a un esquema canónico: `avg_odds_{h,d,a}`, `max_odds_{h,d,a}`, `ps_odds_{h,d,a}` (Pinnacle pre-cierre), `psc_odds_{h,d,a}` (Pinnacle cierre), `avgc_odds_{h,d,a}`, `b365_odds_{h,d,a}`, y las de Over/Under 2.5 si existen.
   - Esquema canónico mínimo: `match_id, league, season, date, kickoff_utc, home_team, away_team, home_goals, away_goals, result (H/D/A), home_shots, away_shots, home_sot, away_sot, home_xg, away_xg` + cuotas.
3. **Limpieza**
   - Eliminar filas vacías de los CSV, duplicados, partidos sin resultado (en temporadas cerradas).
   - Validar: cuotas > 1.01; goles ≥ 0; resultado coherente con los goles.
   - Unificar nombres con `team_aliases.yaml`; fallar si hay equipos sin mapear (y listar cuáles).
4. **Emparejamiento con xG**: por liga + fecha (± 1 día) + equipos canónicos. Reportar no emparejados.
5. **Salida**: `matches.parquet`, `holdout.parquet`, `current.parquet` + `reports/data_quality.md`.

## 4. Features (todas pre-partido)

Implementadas en `ml/features/`, cada una como función pura `df -> df` que recibe los partidos ordenados por fecha. La regla técnica anti-fuga: cualquier agregado se calcula con `shift(1)` sobre el historial del equipo, o iterando cronológicamente y guardando el estado **antes** de actualizarlo.

| Grupo | Features | Notas |
|---|---|---|
| Elo | `elo_home`, `elo_away`, `elo_diff`, `elo_p_home` | Por liga. K y ventaja de local en `features.yaml`; multiplicador por margen de goles; regresión 1/3 a la media entre temporadas; ascendidos entran con la media de los descendidos. |
| Forma | goles a favor/en contra, puntos, tiros, tiros al arco (últimos 6 y EWMA α=0.1), por equipo, general y según condición local/visita | Con prior de la liga cuando hay < 3 partidos. |
| xG | xG a favor/en contra y diferencia (últimos 6, EWMA), "suerte" = goles − xG | La más importante esperada. |
| Calendario | días de descanso, jornada del torneo, partidos en los últimos 14 días | |
| Mercado | probabilidades implícitas normalizadas (Shin) de `avg_odds_*` pre-cierre | Solo en experimentos marcados `uses_odds: true`. Nunca de cierre. |
| Fuerza DC | ataque/defensa de Dixon-Coles ajustado con datos previos | Solo para stacking (E12+). |

El `FeaturePipeline` produce un DataFrame con columnas `features.yaml → groups` y el target `result` codificado `H=0, D=1, A=2`.

## 5. Validación

Walk-forward con ventana expansiva por temporada:

| Fold | Entrena con | Valida en |
|---|---|---|
| F1 | 2014-15 … 2021-22 | 2022-23 |
| F2 | 2014-15 … 2022-23 | 2023-24 |
| F3 | 2014-15 … 2023-24 | 2024-25 |
| **Final** | 2014-15 … 2024-25 | **2025-26 (holdout, una vez)** |
| Producción | 2014-15 … 2025-26 + 2026-27 jugados | partidos futuros |

- Modelos estadísticos (Poisson/Dixon-Coles/Elo) se re-ajustan dentro del fold cada 7 días de calendario usando solo partidos anteriores (más fiel a la realidad).
- Modelos de ML (logística, XGBoost, LightGBM) se entrenan una vez por fold; sus features ya son dinámicas.
- Hiperparámetros: búsqueda solo dentro del conjunto de entrenamiento de cada fold (validación interna = última temporada del train).
- Métrica de selección: **promedio de log loss en F1–F3**.

## 6. Modelos

Interfaz común (`domain/ports.py`):

```python
class ProbabilisticModel(Protocol):
    name: str
    uses_odds: bool
    def fit(self, train: pd.DataFrame) -> "ProbabilisticModel": ...
    def predict_proba(self, matches: pd.DataFrame) -> np.ndarray: ...  # shape (n, 3): [H, D, A], filas suman 1
    def predict_goal_matrix(self, matches: pd.DataFrame) -> np.ndarray | None: ...  # opcional, para O/U
```

Implementaciones: `FrequencyBaseline`, `MarketBaseline(source="avg"|"psc")`, `EloModel`, `PoissonModel`, `DixonColesModel(xi)`, `SklearnModel(estimator, features)`, `CalibratedModel(base, method)`, `BlendModel(models, weights)`.

## 7. Tests obligatorios

- `domain/odds.py`: casos conocidos (cuotas 2.0/3.5/4.0 → overround correcto; Shin suma 1; EV y Kelly).
- `domain/metrics.py`: log loss y Brier contra `sklearn.metrics`; RPS con un caso a mano.
- **Anti-fuga** (`tests/unit/test_leakage.py`):
  - Cambiar los resultados de todos los partidos con fecha ≥ `d` (goles, xG, tiros) no altera ninguna feature de los partidos con fecha ≤ `d`.
  - Ninguna columna de features contiene los patrones `psc_`, `avgc_`, `home_goals`, `away_goals`, `home_xg`, `away_xg` (del propio partido).
  - Los folds no se solapan y todo `train.date.max() < valid.date.min()`.
- **Holdout**: `evaluate_holdout` falla si existe `HOLDOUT_USED.lock`; ningún módulo salvo `evaluate_holdout.py`, `build_dataset.py` y `config.py` referencia `holdout.parquet` (test con `grep`).
- Adaptadores: parseo con archivos de ejemplo en `tests/fixtures/` (sin red).
- API: `TestClient` para cada endpoint del contrato, incluidos errores 404/422 y lista vacía.

## 8. Comandos (`Makefile` → `cli.py`)

| Comando | Qué hace |
|---|---|
| `make setup` | crea entorno, instala dependencias y hooks de pre-commit |
| `make lint` / `make test` | ruff + mypy / pytest con cobertura |
| `make data` | descarga + limpieza + reporte de calidad |
| `make baselines` | E01 y líneas base de mercado |
| `make exp ID=E05` | corre un experimento y agrega fila a `experiments.csv` |
| `make select` | elige campeón según la regla y escribe `models/champion.json` |
| `make holdout` | evaluación final única + figuras |
| `make report` | genera `reports/REPORT.md` |
| `make train-prod` | re-entrena el campeón con todo lo disponible |
| `make serve` | levanta la API en `:8000` |
| `make track` | califica predicciones pasadas |
| `make all` | data → baselines → experimentos → select → holdout → report → train-prod |

## 9. Configuración (`.env.example`)

```
TIMEZONE=America/Lima
DATA_DIR=data
MODELS_DIR=models
REPORTS_DIR=reports
FIXTURES_CACHE_HOURS=6
SCRAPE_DELAY_SECONDS=3
ADMIN_API_KEY=cambia-esto
SEED=42
```

## 10. CI (`.github/workflows/ci.yml`)

En cada push/PR: instalar con `uv`, `ruff check`, `ruff format --check`, `pytest` (sin red, usando `tests/fixtures`). No se descargan datos ni se entrenan modelos en CI.
