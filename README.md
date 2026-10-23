# betting-ml

Modelo de machine learning que estima las probabilidades 1X2 (local / empate / visita) de los partidos de las 5 grandes ligas europeas, las compara con las cuotas del mercado y las sirve con una API REST (la spec 001 buscaba *value bets*; no encontró ventaja). La spec 002 le suma un **comparador de mejor cuota** con Pinnacle como referencia, una calculadora para casas peruanas, un **diario de apuestas con límites de juego responsable** y un frontend web. La spec 004 agrega el **análisis de un partido**: probabilidades de muchos mercados (goles, ambos marcan, goles de cada equipo, doble oportunidad…), lo más probable con su precio honesto y la forma reciente de los dos equipos; la spec 003 lo endurece todo (login, auditoría, copias). Construido con **Spec-Driven Development** (especificaciones en [`specs/`](specs/), bitácora en [`PROGRESS.md`](PROGRESS.md), decisiones en [`decisions.md`](specs/001-prediction-model/decisions.md)).

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

Sin make: `uv sync --extra dev`, seguido de `uv run pre-commit install`. Después copia `.env.example` a `.env` y rellena:

- `APP_API_KEY`: una clave larga e inventada (32 caracteres o más), para Postman y la CLI;
- `APP_PASSWORD_HASH`: la salida de `uv run betting-ml hash-password` (la contraseña con la que entras al frontend).

Para producción hacen falta además `APP_ENV=prod`, `SESSION_SECRET`, `ALLOWED_HOSTS` y `CORS_ORIGINS`: ver los comentarios de `.env.example` y [`docs/deploy.md`](docs/deploy.md).

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
| `make docker` | `docker build -t betting-ml:latest .` | Imagen endurecida de la API (la construye el job `docker` de CI). Despliegue con Caddy y TLS: [`docs/deploy.md`](docs/deploy.md) |
| `make all` | — | data → baselines → experimentos (omite los ya registrados) → select y holdout (si ya existe el lock, se validan y se omiten) → report → train-prod |

Para servir en una máquina limpia: `make data && make train-prod && make serve`. `train-prod` necesita el lock del holdout, que está versionado.

## Probar la API con Postman

1. Levanta la API con `make serve`.
2. Importa [`postman/betting-ml.postman_collection.json`](postman/betting-ml.postman_collection.json).
3. Ajusta las variables de la colección: `baseUrl` (por defecto `http://localhost:8000`), `date` y `appApiKey` (el `APP_API_KEY` de tu `.env`). Todas las rutas salvo `/health` exigen la cabecera `X-API-Key`.
4. Ejecuta la colección con el *Runner*. Cada request trae tests: status, suma de probabilidades ≈ 1 y formato de error.

Contrato completo: [`contracts/api.md`](specs/001-prediction-model/contracts/api.md). Ejemplos:

```bash
curl -H "X-API-Key: $APP_API_KEY" "http://localhost:8000/api/v1/matches?date=2026-10-03&league=E0"
```

```bash
curl -X POST http://localhost:8000/api/v1/predictions -H "X-API-Key: $APP_API_KEY" -H "Content-Type: application/json" -d "{\"league\":\"E0\",\"home_team\":\"Arsenal\",\"away_team\":\"Chelsea\",\"odds\":{\"home\":1.98,\"draw\":3.9,\"away\":4.5}}"
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

La app pide **iniciar sesión** con la contraseña del dueño (su hash Argon2id va en `APP_PASSWORD_HASH`; se genera con `betting-ml hash-password`). La sesión vive en una cookie `HttpOnly` que el navegador no puede leer y caduca tras 30 minutos sin uso o 12 horas en total; el botón **Salir** la cierra. El navegador no guarda ninguna clave ni contraseña: `APP_API_KEY` queda solo para Postman y la línea de comandos.

> **Juego responsable.** Apuesta solo lo que puedas perder. Esta app no encontró una ventaja que permita ganar apostando: su valor es ahorrar margen eligiendo la mejor cuota y **medir** con honestidad. Los límites mensuales existen para que no persigas pérdidas. Si sientes que pierdes el control, pide ayuda.

## Spec 004 — Análisis de partido con mercados

Especificación en [`specs/004-match-analysis/`](specs/004-match-analysis/) (escrita como "spec 003" en la rama `Sebastian`) y decisiones en [`decisions.md`](specs/004-match-analysis/decisions.md). Informes: [`REPORT_003_markets.md`](reports/REPORT_003_markets.md) (ligas) y [`REPORT_003_europe.md`](reports/REPORT_003_europe.md) (partidos entre ligas).

**Qué hace.** Eliges dos equipos (por ejemplo, Real Madrid y RB Leipzig) y la página **Análisis** muestra:

- **Goles esperados** de cada equipo (λ) y, a partir de ellos, la probabilidad de cada resultado exacto. Con esa "matriz de marcadores" se calculan todos los mercados: 1X2, doble oportunidad, empate no apuesta, Más/Menos 0.5–4.5, ambos marcan, goles de cada equipo, hándicap europeo y los 5 marcadores más probables.
- Para cada selección: probabilidad, **cuota justa** (1/p), mejor cuota disponible, EV y nivel de confianza.
- **Lo más probable**, con un comentario honesto del precio ("Muy probable (82 %), pero la cuota 1.15 paga menos de lo justo (1.22): EV −5.6 %. No conviene.") y razones basadas en datos ("El modelo espera 2.1 goles de Real Madrid…").
- La **forma reciente** (últimos 6 partidos, promedios de goles y xG, % de partidos con más de 2.5 goles, ambos marcan, racha) y los enfrentamientos directos, que tienen poco poder predictivo.

**Cómo se calcula.** Dos equipos de la misma liga usan Dixon-Coles sobre xG (el mejor modelo de goles de la spec 001). Los partidos entre ligas (Champions, Europa League) usan un **Elo propio entre ligas** sobre resultados de openfootball, porque ClubElo estuvo caído, con un desplazamiento de fuerza por liga estimado con los partidos europeos. Todo usa solo información anterior al partido.

**Cómo leer el nivel de confianza.** Mide si las probabilidades de ese mercado acertaron en el pasado (calibración), no si conviene apostar:

| Nivel | Qué significa |
|---|---|
| **Alta** | Calibración muy buena (ECE < 0.02), sesgo menor al 5 %, mejor que la frecuencia histórica y al menos 400 casos |
| **Media** | Calibración aceptable o muestra insuficiente para certificar más |
| **Baja** | Calibración mala o un sesgo grande y significativo: **solo información**, nunca se destaca |

Resultado actual: en ligas, **0 alta, 9 media y 9 baja**. Los mercados de muchos goles (Más/Menos 1.5–4.5, hándicaps, marcador exacto) salen `baja` porque el modelo espera más goles de los que hay. En partidos entre ligas, 1X2 y Más/Menos 2.5 salen `baja`: ese análisis es solo información.

**Por qué "lo más probable" no es "lo mejor".** Que algo sea probable no significa que la cuota lo pague bien: las casas ya lo saben y pagan menos de lo justo. Una apuesta solo tiene valor si la cuota es mayor que la cuota justa, y aun así hay que medirlo. El backtest de Más/Menos 2.5 **no encontró valor**: las selecciones que el modelo veía con "valor" tuvieron un CLV de −5.7 % en la prueba 2025-26, igual que apostar a ciegas. Por eso la sección **"Mejores opciones" está desactivada** (decisión del dueño) y todo lo que se registre desde el análisis va **en papel por defecto**, con la etiqueta EXPERIMENTAL — solo papel.

**Cuotas por evento.** El botón "Actualizar cuotas de este partido" baja de The Odds API los mercados adicionales del partido. Muestra antes el costo (mercados × regiones: unos 12 créditos con `eu,uk`) y guarda la respuesta 30 minutos, así que un segundo refresco no gasta créditos. Sin `ODDS_API_KEY` el análisis usa las cuotas 1X2 del comparador o solo cuotas justas.

**Evidencia por mercado.** Mis apuestas tiene un panel con el CLV de cada mercado, **separando** el CLV contra Pinnacle del CLV contra el cierre promedio del mercado (una referencia más débil, la única que hay en 2026-27 para Más/Menos 2.5), y el progreso hacia 100 apuestas en papel con CLV positivo. Solo con esa evidencia un mercado deja de ser experimental (cambio manual en `configs/markets.yaml`).

### Comandos (spec 004)

| make | sin make | Qué hace |
|---|---|---|
| `make data-europe` | `uv run betting-ml data-europe` | Descarga ligas y Champions/Europa League de openfootball, calcula el Elo propio entre ligas y arma el dataset europeo |
| `make analyze HOME="Real Madrid" AWAY="Barcelona"` | `uv run betting-ml analyze "Real Madrid" "Barcelona" --date 2026-10-26` | Análisis por consola (`--competition UCL` para partidos europeos) |
| `make validate-markets` | `uv run betting-ml validate-markets` | Calibración de los mercados y backtest de Más/Menos 2.5 en validación |
| `make validate-markets-final` | `uv run betting-ml validate-markets --final` | Prueba única en 2025-26 (ya hecha: el lock impide repetirla) |
| `make validate-cross-league` | `uv run betting-ml validate-cross-league` | Validación walk-forward del ajuste entre ligas (`--final`: prueba europea única, ya hecha) |

Antes del análisis hacen falta los datos: `uv run betting-ml data` (ligas) y `uv run betting-ml data-europe` (Europa y Elo).

### Cómo usar la página Análisis

- Como el resto de la app, la página exige iniciar sesión. Desde **Hoy** o **Partido**, pulsa **Analizar**; o entra a **Análisis** (`/analysis`), escribe el local y la visita (el autocompletado sugiere nombres) y, si quieres, la fecha y la competición. Si hay un partido próximo entre los dos, se usa solo.
- Arriba verás los goles esperados y los avisos (partido entre ligas, cuotas viejas, forma desactualizada). Léelos antes que nada.
- **Lo más probable**: cada tarjeta dice la probabilidad, si la cuota la paga bien o mal y por qué. "Registrar en papel" la anota en el diario.
- **Mercados**: abre cada grupo; puedes ordenar por EV. Lo marcado como "Solo información" no está suficientemente calibrado.
- Para registrar una selección sin cuota, escribe la cuota que te ofrece tu casa.

## Seguridad (spec 003)

Especificación en [`specs/003-security-hardening/`](specs/003-security-hardening/). El modelo de amenazas, los controles y lo que queda fuera están en [`SECURITY.md`](SECURITY.md).

- **Acceso.** Toda ruta exige autenticación salvo `/health` y el login:
  - el frontend usa una sesión con cookie `HttpOnly` y token CSRF;
  - Postman y la CLI usan `X-API-Key`.

  El navegador no guarda ningún secreto. La contraseña solo existe como hash Argon2id.
- **Abuso.** Límite de intentos de login con bloqueo progresivo, límite de peticiones por IP, cuerpo máximo de 64 KiB, `Host` permitido, CSP estricta y cabeceras de seguridad. En prod, `/docs` está desactivado y la API no arranca con claves débiles.
- **Integridad de los datos.**
  - `CHECK` en la base y concurrencia optimista: una edición simultánea da 409.
  - Auditoría de solo inserción encadenada con SHA-256.
  - Copias verificadas con `.sha256`.
  - Hash de los modelos antes de cargarlos.
- **Fuentes externas y créditos (spec 004).** Descargas con tope de tamaño y de tiempo; un solo saldo de créditos de The Odds API para el comparador y el análisis, con su reserva y su cupo por hora.

| make | sin make | Qué hace |
|---|---|---|
| `make security` | ver el objetivo `security` del `Makefile` | ruff S, pip-audit, npm audit y gitleaks (falla ante cualquier hallazgo, igual que en CI) |
| `make verify-integrity` | `uv run betting-ml verify-integrity` | Comprueba la cadena de auditoría, los datos actuales frente a su último evento, los PRAGMA y los triggers |
| `make backup` | `uv run betting-ml backup` | Copia consistente de `data/app.db` con su `.sha256` y rotación |
| `make restore FILE=…` | `uv run betting-ml restore <copia> --yes` | Verifica la copia y solo entonces reemplaza la base (guarda antes la actual) |
| — | `uv run betting-ml hash-password` | Genera el hash Argon2id de la contraseña para `APP_PASSWORD_HASH` |

Despliegue en producción (Docker, Caddy con TLS, copias externas, rotación de claves): [`docs/deploy.md`](docs/deploy.md). Estado final de los hallazgos: [`reports/SECURITY_BASELINE.md`](reports/SECURITY_BASELINE.md) y [`reports/SECURITY_AUDIT_003.md`](reports/SECURITY_AUDIT_003.md).

## Limitaciones

- El campeón es **peor que el mercado solo** en validación y en el holdout. El nivel "Bueno" depende de la tolerancia de +0.005 y no es estadísticamente firme.
- No se probó el stacking con el mercado (E13) porque se activó la regla de parada. Tampoco se corrieron E10, E11, E14 ni E15.
- Pinnacle desapareció de football-data a mitad de 2025-26: la comparación con su cierre en el holdout cubre solo el 51 % de los partidos, y en 2026-27 no hay Pinnacle.
- Solo hay datos de liga. No se incluyen copas, competiciones europeas, lesiones ni alineaciones.
- Las temporadas 2014-15 a 2018-19 no traen hora de inicio (se imputa 15:00 hora del Reino Unido).
- La bandera de valor de la API compara con la mejor cuota de `fixtures.csv`. No es una recomendación de apuesta.

- Spec 002: la señal de valor no tiene evidencia (ver arriba). Las cuotas de Betsson y Coolbet que llegan de The Odds API (región eu) pueden no coincidir con las de su web peruana. Las casas peruanas se ingresan a mano.
- Spec 002: el CLV de 2026-27 sale casi siempre del último snapshot de Pinnacle antes del inicio, no de su cierre real, porque football-data ya no publica Pinnacle.
- Spec 004: ningún mercado llegó a confianza alta en la prueba 2025-26, y no hay evidencia de valor en Más/Menos 2.5. El modelo de goles sobreestima los partidos con muchos goles (se ajusta sobre xG); recalibrarlo queda como experimento futuro.
- Spec 004: el Elo entre ligas es propio (ClubElo estuvo caído) y cubre 11 países; los clubes de otros países no tienen análisis entre ligas (`503 RATINGS_UNAVAILABLE`). openfootball va con semanas de retraso en las ligas medianas y aún no tiene la Champions 2026-27, así que la forma de esos clubes puede estar atrasada (la app lo avisa).
- Spec 004: las cuotas por evento se implementaron con el formato documentado de The Odds API y un fixture sintético; falta verificarlas con una respuesta real (decisions.md).
- Spec 004: las apuestas de partidos europeos no se liquidan solas (football-data solo trae ligas): hay que liquidarlas a mano. Solo 1X2 y Más/Menos 2.5 de liga tienen CLV.
- Spec 004: córners y tarjetas (US7, opcional) quedaron pospuestos.

Más detalle en [`reports/REPORT.md`](reports/REPORT.md) §9.
