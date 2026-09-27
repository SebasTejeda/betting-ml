# betting-ml

Modelo de machine learning que estima las probabilidades 1X2 (local / empate / visita) de los partidos de las 5 grandes ligas europeas, las compara con las cuotas para detectar *value bets* y las sirve con una API REST. Construido con **Spec-Driven Development** (especificaciones en [`specs/`](specs/), bitácora en [`PROGRESS.md`](PROGRESS.md), decisiones en [`decisions.md`](specs/001-prediction-model/decisions.md)).

> **Juego responsable.** Proyecto educativo. Apostar implica riesgo de pérdida. Este modelo **no** muestra ventaja frente al mercado: no lo uses para apostar dinero real.

## Resultados principales

Informe completo: [`reports/REPORT.md`](reports/REPORT.md).

| | Log loss holdout 2025-26 (1 752 partidos) |
|---|---|
| **Campeón E12**: LightGBM (Optuna) con Elo, forma, calendario, xG y probabilidades del mercado pre-cierre | **0.9810** |
| Mercado promedio pre-cierre (`Avg`, sin margen por Shin) | 0.9777 |
| Mejor modelo sin cuotas, E06: logística con Elo, forma, calendario y xG | 0.9934 |
| E02: logística solo con Elo | 0.9984 |
| Frecuencias por liga | 1.0712 |

- **Nivel alcanzado: Bueno** (spec §6). El campeón queda a 0.0033 del mercado, dentro de la tolerancia de +0.005. Además mejora a las frecuencias y a E02, y su ECE es 0.019.
- **El resultado no es concluyente.** La diferencia con el mercado tiene un IC 95 % de [−0.0008, +0.0074], que contiene el umbral. En la práctica, **el modelo no le gana al mercado**: usar directamente las probabilidades del mercado es igual o mejor.
- **Apuestas simuladas con el campeón** (cuota promedio, umbral fijado en validación): 692 apuestas, ROI −5.7 % con IC 95 % [−15.8 %, +5.5 %] y CLV −6.3 % frente al cierre de Pinnacle. Con la mejor cuota disponible, el ROI es +2.2 % con IC [−7.0 %, +12.4 %]. Ninguna de las dos es evidencia de ventaja.
- **Experimentos:** 10 registrados (13 filas; E01 tiene 4 variantes de línea base) en [`reports/experiments.csv`](reports/experiments.csv) (E01–E09 y E12), buenos y malos. Se detuvieron por la regla de parada de la spec.

## Arquitectura (hexagonal)

```
                 ┌────────────────────────── api/ (FastAPI) ──────────────────────────┐
  Postman  ───▶  │ routers: health · leagues · matches · predictions · model ·        │
                 │          experiments · tracking · admin      (sin lógica de negocio)│
                 └───────────────────────────────┬────────────────────────────────────┘
                                                 │ llama solo a
  cli.py (typer) ──────────────┐                 ▼
                               ▼  ┌──────────── application/ (casos de uso) ─────────────┐
                                  │ build_dataset · run_experiment · select_champion ·    │
                                  │ evaluate_holdout · generate_report · train_production │
                                  │ predict_matches · track_predictions · catalog         │
                                  └───────┬───────────────────────────────┬───────────────┘
                                          │ puertos (Protocol)            │ usa
                                          ▼                               ▼
  ┌──────────── adapters/ ─────────────┐  ┌──── domain/ (puro) ────┐  ┌──────── ml/ ─────────┐
  │ football_data · understat ·        │─▶│ entities · odds (Shin, │◀─│ features/ (Elo, forma,│
  │ fixtures · team_names ·            │  │ EV, Kelly) · metrics · │  │ xG, calendario,       │
  │ parquet_repository ·               │  │ ports                  │  │ mercado) · validation │
  │ joblib_registry · experiment_store │  └────────────────────────┘  │ models/ · betting ·   │
  │ · tracking_store · http · git_info │                              │ plots                 │
  └────────────────────────────────────┘                              └───────────────────────┘
  container.py = raíz de composición: arma los casos de uso con sus adaptadores.
```

Reglas: `domain` no importa infraestructura; la API solo llama a `application`; las features solo usan información previa al partido (tests anti-fuga en [`tests/unit/test_leakage.py`](tests/unit/test_leakage.py)); el holdout 2025-26 se evaluó una sola vez ([`reports/HOLDOUT_USED.lock`](reports/HOLDOUT_USED.lock)).

## Instalación

Requisitos: Python ≥ 3.11 y [uv](https://docs.astral.sh/uv/). GNU make es opcional: en Windows sin make, usa los comandos `uv run …` equivalentes de la tabla de abajo.

```bash
make setup
```

Sin make: `uv sync --extra dev`, seguido de `uv run pre-commit install`. Después copia `.env.example` a `.env` y cambia `ADMIN_API_KEY`.

## Cómo correr

| make | sin make | Qué hace |
|---|---|---|
| `make lint` | `uv run ruff check src tests && uv run ruff format --check src tests && uv run mypy` | Calidad de código |
| `make test` | `uv run pytest` | Tests con cobertura (sin red) |
| `make data` | `uv run betting-ml data` | Descarga football-data + Understat y escribe `data/processed/*.parquet` y `reports/data_quality.md` |
| `make baselines` | `uv run betting-ml exp E01` | Líneas base (E01) |
| `make exp ID=E05` | `uv run betting-ml exp E05` | Corre un experimento de `configs/experiments/` en F1–F3 |
| `make select` | `uv run betting-ml select` | Elige el campeón y escribe `models/champion.json` |
| `make holdout` | `uv run betting-ml holdout` | Evaluación final única (ya hecha: el lock impide repetirla) |
| `make report` | `uv run betting-ml report` | Genera `reports/REPORT.md` |
| `make train-prod` | `uv run betting-ml train-prod` | Re-entrena los modelos de producción con todos los datos |
| `make serve` | `uv run betting-ml serve` | API en `http://localhost:8000` (Swagger en `/docs`) |
| `make track` | `uv run betting-ml track` | Califica las predicciones servidas con los resultados reales |
| `make docker` | `docker build -t betting-ml:latest .` | Imagen de la API (ver comentario en el [`Dockerfile`](Dockerfile); aún no se construyó porque la máquina de desarrollo no tiene Docker) |
| `make all` | — | data → baselines → experimentos → select → holdout (se omite si ya existe el lock) → report → train-prod |

Para servir en una máquina limpia: `make data && make train-prod && make serve`. `train-prod` necesita el lock del holdout, que está versionado.

## Probar la API con Postman

1. Levanta la API con `make serve`.
2. Importa [`postman/betting-ml.postman_collection.json`](postman/betting-ml.postman_collection.json).
3. Ajusta las variables de la colección: `baseUrl` (por defecto `http://localhost:8000`), `date` y `adminApiKey` (la de tu `.env`).
4. Ejecuta la colección con el *Runner*. Cada request trae tests: status, suma de probabilidades ≈ 1 y formato de error.

Contrato completo: [`contracts/api.md`](specs/001-prediction-model/contracts/api.md). Ejemplos:

```bash
curl "http://localhost:8000/api/v1/matches?date=2026-10-03&league=E0"
```

```bash
curl -X POST http://localhost:8000/api/v1/predictions -H "Content-Type: application/json" -d "{\"league\":\"E0\",\"home_team\":\"Arsenal\",\"away_team\":\"Chelsea\",\"odds\":{\"home\":1.98,\"draw\":3.9,\"away\":4.5}}"
```

`fixtures.csv` de football-data se actualiza unas dos veces por semana. Si no hay partidos de las 5 ligas para la fecha pedida, `/matches` responde `200` con una lista vacía y un mensaje.

## Limitaciones

- El campeón es **peor que el mercado solo** en validación y en el holdout. El nivel "Bueno" depende de la tolerancia de +0.005 y no es estadísticamente firme.
- No se probó el stacking con el mercado (E13) porque se activó la regla de parada. Tampoco se corrieron E10, E11, E14 ni E15.
- Pinnacle desapareció de football-data a mitad de 2025-26: la comparación con su cierre en el holdout cubre solo el 51 % de los partidos, y en 2026-27 no hay Pinnacle.
- Solo hay datos de liga. No se incluyen copas, competiciones europeas, lesiones ni alineaciones.
- Las temporadas 2014-15 a 2018-19 no traen hora de inicio (se imputa 15:00 hora del Reino Unido).
- La bandera de valor de la API compara con la mejor cuota de `fixtures.csv`. No es una recomendación de apuesta.

Más detalle en [`reports/REPORT.md`](reports/REPORT.md) §9.
