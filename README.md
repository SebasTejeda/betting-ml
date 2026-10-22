# betting-ml

Modelo de machine learning que estima las probabilidades 1X2 (local / empate / visita) de los partidos de las 5 grandes ligas europeas, las compara con las cuotas del mercado y las sirve con una API REST (la spec 001 buscaba *value bets*; no encontró ventaja). La spec 002 le suma un **comparador de mejor cuota** con Pinnacle como referencia, una calculadora para casas peruanas, un **diario de apuestas con límites de juego responsable** y un frontend web. Construido con **Spec-Driven Development** (especificaciones en [`specs/`](specs/), bitácora en [`PROGRESS.md`](PROGRESS.md), decisiones en [`decisions.md`](specs/001-prediction-model/decisions.md)).

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
- **Regla de parada aplicada por familia:** la regla se aplicó por separado a los modelos sin cuotas y con cuotas (decidido antes de correr E09, tras ver E06–E08); con la regla global literal no se habría probado ningún modelo con cuotas. Ver [`decisions.md`](specs/001-prediction-model/decisions.md#2026-09-26--regla-de-parada-aplicada-por-familia-de-modelos-antes-de-correr-e09).

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

Sin make: `uv sync --extra dev`, seguido de `uv run pre-commit install`. Después copia `.env.example` a `.env` y cambia `APP_API_KEY` (y, para producción, las variables de seguridad de la spec 003: ver los comentarios de `.env.example`).

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
| `make all` | — | data → baselines → experimentos (omite los ya registrados) → select y holdout (si ya existe el lock, se validan y se omiten) → report → train-prod |

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

## Spec 002 — Comparador de cuotas, diario y frontend

Especificación en [`specs/002-odds-comparator/`](specs/002-odds-comparator/) y decisiones en [`decisions.md`](specs/002-odds-comparator/decisions.md).

**Qué hace.** Para cada partido del día muestra la **mejor cuota disponible** por resultado, la casa que la paga y el **margen** de cada casa, con la cuota justa de Pinnacle (sin margen, método de Shin) como referencia. Incluye una calculadora para cuotas escritas a mano (Te Apuesto, Inkabet y otras casas peruanas que no están en The Odds API), un diario de apuestas reales y en papel con CLV y curva de bankroll, y límites de pérdida mensual y stake máximo que no se pueden saltar ni desde la API ni desde el frontend.

**Resultados del backtest** ([`reports/REPORT_002_backtest.md`](reports/REPORT_002_backtest.md)). Conclusión: *seguir con cambios*, nivel **Mínimo (backtest)**.

| | Validación 2022-25 | Temporada 2026-27 |
|---|---|---|
| Margen medio de la cuota promedio | 4.5 % | 6.5 % |
| Margen medio de la mejor cuota | 0.5 % | 2.7 % |
| La mejor cuota paga más que el promedio | +5.0 % | +4.9 % |

- **Eso justifica el comparador:** elegir la mejor casa ahorra unos 4 puntos de margen por apuesta. Es la única ventaja medida. **Salvedad:** la "mejor cuota" del backtest es la columna `Max` de football-data, que incluye casas y exchanges no accesibles desde Perú. Con solo Betsson, Coolbet y las casas peruanas el ahorro será menor, y aún no está medido: el diario lo mide con "mejor cuota vs promedio" en tus apuestas.
- **La señal de valor no está validada.** La estrategia principal (Bet365 sin filtro) tuvo un CLV de −3.7 % en la prueba 2025-26 (27 apuestas). La variante con el filtro del modelo E12 tiene solo 8 apuestas y se eligió después de ver el fallo: no es evidencia. Por eso la señal se muestra como **"EXPERIMENTAL — solo papel"**. El diario cuenta el progreso hacia 100 apuestas en papel con CLV positivo, que sería la evidencia real.

### Configuración

1. Crea una cuenta gratis en [the-odds-api.com](https://the-odds-api.com). El plan gratis da 500 créditos al mes, y cada refresco cuesta unos 2 créditos por liga (regiones eu+uk, mercado 1X2).
2. En `.env` (copiado de `.env.example`) pon `ODDS_API_KEY=<tu clave>` y `APP_API_KEY=<una clave larga inventada por ti>`. Las claves viven solo en `.env`: nunca en el repo, en los fixtures ni en los logs.
3. Ajusta, si quieres, `ODDS_MIN_CREDITS_RESERVE` (reserva que no se gasta, 50 por defecto) y `ODDS_AUTO_REFRESH=true` con `ODDS_AUTO_REFRESH_TIMES=10:00,16:00` (hora de Lima) para refrescar solo en días con partidos. Con el refresco automático activado, levanta la API con un solo worker y sin `--reload`.
4. Requisitos del frontend: Node.js 20 o superior (probado con 24). Instala con `cd frontend && npm ci`.
5. Crea la base de datos: `uv run betting-ml db-upgrade` (la API también aplica las migraciones al arrancar).

### Comandos

| make | sin make | Qué hace |
|---|---|---|
| `make db-upgrade` | `uv run betting-ml db-upgrade` | Migraciones de la base SQLite (`data/app.db`) |
| `make odds` | `uv run betting-ml odds` | Refresca cuotas de The Odds API (**consume créditos**) |
| `make settle` | `uv run betting-ml settle` | Liquida apuestas con resultados oficiales y calcula el CLV |
| `make backtest-002` | `uv run betting-ml backtest-002` | Backtest en validación (repetible) |
| `make backtest-002-final` | `uv run betting-ml backtest-002-final` | Prueba única en 2025-26 (ya hecha: el lock impide repetirla) |
| `make web-api` | `uv run betting-ml openapi` y luego `cd frontend && npm run gen:api` | Exporta el contrato OpenAPI y regenera los tipos del frontend |
| `make web` | `cd frontend && npm run dev` | Frontend en `http://localhost:5173` (con proxy de `/api` a `:8000`) |
| `make web-test` | `cd frontend && npm run lint && npm run typecheck && npm test` | Calidad y tests del frontend (MSW, sin red) |
| `make dev` | dos terminales: `uv run betting-ml serve` y `cd frontend && npm run dev` | API y frontend juntos |

### Cómo usar cada página

- **Hoy** (`/`): elige fecha y liga. Para cada partido verás la mejor cuota por resultado y su casa, y el margen de la mejor combinación frente al promedio. Por defecto solo cuentan las casas accesibles desde Perú (se puede desmarcar). El botón **Actualizar cuotas** gasta créditos y muestra cuántos quedan; bajo la reserva, el refresco se bloquea. En el celular, la tabla se ve como tarjetas.
- **Top del día** (`/top`): todas las cuotas de la señal con EV positivo de todas las ligas para la fecha, ordenadas por EV, con el botón "Registrar en papel". Lleva la etiqueta EXPERIMENTAL — solo papel: no es una recomendación.
- **Partido** (`/match/:id`): todas las casas × resultados con la mejor cuota resaltada, el margen de cada casa, el gráfico de la cuota de referencia en el tiempo y una calculadora rápida.
- **Calculadora** (`/calculator`): elige el partido, el resultado, una casa de ingreso manual y la cuota que ves. Te dice la cuota justa, el EV y la mejor cuota disponible, y te deja registrar la apuesta. Si la API pide confirmación (stake alto, cerca del límite o dinero real sobre la señal experimental), la app muestra el motivo y solo registra si confirmas. Si el presupuesto mensual está agotado, las apuestas reales quedan **bloqueadas** hasta el mes siguiente (en papel se puede seguir).
- **Mis apuestas** (`/bets`): tabla filtrable (real, papel o todas; por estado) con liquidación a mano (solo después del inicio del partido) y borrado (solo antes). El panel muestra el CLV medio, el % de CLV positivo, el beneficio, el ROI, el uso del límite mensual, el progreso de la señal experimental (X/100), la curva de bankroll y el CLV por liga y casa. **Liquidar con resultados oficiales** confirma o corrige lo marcado a mano. Una apuesta real marcada a mano como ganada o nula cuenta como perdida para el límite hasta que se confirme. Si un partido se aplaza, márcala como nula.
- **Partidos sin cuotas:** en la Calculadora, "¿El partido no aparece?" registra la apuesta igual, marcada *sin cuota de referencia*. Cuenta para todos los límites, no entra en la señal y su CLV sale del cierre de Pinnacle de football-data si existe.
- **Backtest** (`/backtest`): conclusión, margen pagado por tipo de cuota y resultados de la prueba con sus intervalos de confianza.
- **Ajustes** (`/settings`): bankroll, moneda, límite de pérdida mensual (bajarlo aplica al instante; subirlo, desde el mes siguiente), stake máximo, fracción de Kelly y umbral de la señal.

La app usa tema oscuro por defecto; el botón de sol/luna de la barra superior cambia al tema claro y lo recuerda en el navegador. En el celular la navegación está en una barra inferior.

La primera vez, pulsa **Configurar clave** (arriba a la derecha) y pega tu `APP_API_KEY`: sin ella no se puede escribir (refrescar, registrar, liquidar ni guardar ajustes). La clave se guarda solo en el `localStorage` de tu navegador, porque es una herramienta personal que corre en tu máquina. No uses la app en un equipo compartido.

> **Juego responsable.** Apuesta solo lo que puedas perder. Esta app no encontró una ventaja que permita ganar apostando: su valor es ahorrar margen eligiendo la mejor cuota y **medir** con honestidad. Los límites mensuales existen para que no persigas pérdidas. Si sientes que pierdes el control, pide ayuda.

## Limitaciones

- El campeón es **peor que el mercado solo** en validación y en el holdout. El nivel "Bueno" depende de la tolerancia de +0.005 y no es estadísticamente firme.
- No se probó el stacking con el mercado (E13) porque se activó la regla de parada. Tampoco se corrieron E10, E11, E14 ni E15.
- Pinnacle desapareció de football-data a mitad de 2025-26: la comparación con su cierre en el holdout cubre solo el 51 % de los partidos, y en 2026-27 no hay Pinnacle.
- Solo hay datos de liga. No se incluyen copas, competiciones europeas, lesiones ni alineaciones.
- Las temporadas 2014-15 a 2018-19 no traen hora de inicio (se imputa 15:00 hora del Reino Unido).
- La bandera de valor de la API compara con la mejor cuota de `fixtures.csv`. No es una recomendación de apuesta.

- Spec 002: la señal de valor no tiene evidencia (ver arriba). Las cuotas de Betsson y Coolbet que llegan de The Odds API (región eu) pueden no coincidir con las de su web peruana. Las casas peruanas se ingresan a mano.
- Spec 002: el CLV de 2026-27 sale casi siempre del último snapshot de Pinnacle antes del inicio, no de su cierre real, porque football-data ya no publica Pinnacle.

Más detalle en [`reports/REPORT.md`](reports/REPORT.md) §9.
