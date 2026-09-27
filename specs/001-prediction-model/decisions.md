# Registro de decisiones

Decisiones tomadas durante la implementación que no estaban en la spec o que la modifican. Formato:

```
## AAAA-MM-DD — Título corto
- Contexto:
- Decisión:
- Motivo:
- Impacto:
```

## 2026-09-26 — Alcance inicial
- Contexto: el dueño quería "lo más grande posible" sin definir ligas.
- Decisión: top 5 ligas europeas, 2014-15 a 2025-26, mercado 1X2 (O/U 2.5 opcional).
- Motivo: son las ligas con xG gratuito en Understat y cuotas completas en football-data; más ligas se agregan por config.
- Impacto: ~20 000 partidos de entrenamiento; la API cubre los partidos de esas 5 ligas.

## 2026-09-26 — `make` no disponible en la máquina de desarrollo (Windows)
- Contexto: la máquina Windows del agente no tiene GNU make instalado (ni choco/scoop).
- Decisión: el `Makefile` se escribe igual (lo usan CI, Linux, macOS y Docker) y todas sus recetas delegan en `uv run ...`. En local se ejecutan las mismas recetas directamente (`uv run ruff ...`, `uv run pytest`, `uv run betting-ml ...`). Para tener `make` en Windows: `winget install ezwinports.make` o usar WSL/Git Bash con make.
- Motivo: no instalar software de sistema sin permiso del dueño; las recetas son 1:1 con la CLI.
- Impacto: ninguno funcional; los comandos equivalentes se documentan en el README.

## 2026-09-26 — Python del entorno
- Contexto: la máquina tiene Python 3.14; el proyecto exige ≥ 3.11.
- Decisión: `requires-python = ">=3.11"`; `mypy` sin `python_version` fijo (usa el intérprete activo) porque los stubs de numpy usan sintaxis 3.12+.
- Motivo: todas las dependencias (xgboost, lightgbm, pyarrow…) tienen wheels para 3.14.
- Impacto: CI prueba en 3.11 y 3.12.

## 2026-09-26 — Método de acceso a Understat
- Contexto: las páginas de liga de Understat ya no incrustan `datesData` en el HTML (JSON embebido). El propio `js/league.min.js` de la página pide los datos por AJAX a `/getLeagueData/{liga}/{año}`.
- Decisión: el adaptador `adapters/understat.py` llama directamente a ese endpoint JSON (cabeceras `X-Requested-With` y `Referer`), con pausa ≥ 3 s entre peticiones, reintentos y caché del JSON crudo tal cual en `data/raw/understat/{liga}/{año}.json`. No se usa `soccerdata`.
- Motivo: es la misma fuente que consume la web, devuelve JSON limpio (id, equipos, goles, xG, fecha-hora) y evita una dependencia pesada.
- Impacto: si Understat cambia el endpoint, solo cambia este adaptador (puerto `XgDataSource`). Alternativa documentada: `soccerdata.Understat`.

## 2026-09-26 — Hallazgos de football-data al inspeccionar los CSV reales
- Temporadas 2014-15 a 2018-19 no tienen columna `Time`: la hora de inicio se imputa a 15:00 (hora del Reino Unido) y se marca `kickoff_time_imputed=True`. La fecha es la correcta, que es lo que importa para el orden temporal.
- 2025-26 (holdout) solo tiene cuotas de Pinnacle (`PSH/PSCH`) en ~55 % de los partidos; 2026-27 no las tiene. La línea base "Pinnacle al cierre" del holdout se calcula sobre el subconjunto con `PSC*` y se reporta el tamaño; como referencia de cierre completa se reporta también `AvgC*`.
- 2026-27 trae `HxG/AxG` en football-data: se guardan como `fd_home_xg/fd_away_xg` (respaldo si Understat falla para la temporada en curso).

## 2026-09-26 — Correcciones tras el checkpoint de datos (T012)
- Contexto: `ml-reviewer` aprobó con observaciones (sin bloqueantes).
- Decisiones:
  - La fecha-hora de Understat **no** es UTC fiable (a veces hora UK, a veces horas de relleno tras medianoche). Solo se usa su fecha para el emparejamiento ±1 día; la hora de inicio canónica siempre sale de football-data.
  - Emparejamiento xG en dos pasadas: (1) liga + equipos + fecha ±1 día (spec); (2) para los no emparejados, liga + temporada + equipos, clave única dentro de una temporada de liga. Recupera los partidos reprogramados/reanudados (marcados `xg_date_mismatch=True`). Lleva el emparejamiento al 100 % en train.
  - Resultados adjudicados en mesa (goles de Understat ≠ football-data: Sassuolo-Pescara 2016-17, Union Berlin-Bochum 2024-25): se usa el marcador del campo para etiqueta y features (las casas liquidan con el resultado del campo) y se marca `result_awarded=True`; el oficial queda en `official_*_goals`.
  - `configs/data_overrides.yaml`: correcciones manuales documentadas. Udinese-Roma 2023-24 (suspendido y reanudado) tiene cuotas de cierre de juego en vivo → se anulan (`closing_odds_invalid=True`).
  - Cuotas `max` con margen < −3 % (224 partidos, sobre todo 2014-19, `BbMx*`) son errores: se anulan para no inflar el ROI "optimista".
  - Hora imputada (15:00 UK) en 2014-15…2018-19: **no sirve para ordenar dentro de un día**. Toda feature que agregue partidos de otros equipos (priors/medias de liga) se calcula con partidos de fecha estrictamente anterior (`date < d`); las features por equipo no se ven afectadas (un equipo juega una vez por día). Un test anti-fuga lo cubre (T016).
  - El xG de respaldo de football-data (solo 2026-27, 1 partido hoy) viene de otro proveedor (≈ 0.19 xG menos por local que Understat): queda marcado en `xg_source` y se vigila en la API; no se usa en entrenamiento.
  - Las filas mal formadas del CSV se cuentan y se avisan (antes se descartaban en silencio); una hora UK ambigua ahora es error.
  - Understat también guarda `.meta.json` con fecha de descarga y sha256.

## 2026-09-26 — Correcciones tras el checkpoint de fuga y validación (T025)
- Contexto: `ml-reviewer` aprobó con observaciones (sin fuga, sin bloqueantes; métricas recalculadas de forma independiente y coincidentes).
- Decisiones:
  - **Umbral de apuestas:** se elige sobre las predicciones agrupadas de F1–F3 (experiments.md §5) entre {0.02, 0.05, 0.08, 0.10}, exigiendo **≥ 100 apuestas**; si ningún umbral llega, se usa 0.10 (el más conservador); empates → el umbral mayor. Como el ROI de validación se mide sobre las mismas predicciones con las que se eligió el umbral, es **optimista**: el informe lo dice y la única medida honesta del ROI es el holdout.
  - **Re-ejecución de un experimento** (mismo ID tras un bug): la fila anterior pasa a `reports/experiments_history.csv` y la nueva empieza sin conclusión (se vuelve a escribir).
  - **`git_commit`** marca `-dirty` también con archivos nuevos o modificados en `src/`, `configs/` o `pyproject.toml`.
  - **Modelos de goles:** un equipo sin partidos en la liga en los últimos 365 días (ascendido o que vuelve tras años) usa la fuerza de "ascendido" (media de los 3 más débiles activos), coherente con el Elo. El arranque en caliente del optimizador se reinicia en cada llamada de predicción.
  - **Prior de liga en features:** el nº de partidos previos cuenta solo valores no nulos de cada estadística.
  - **Hiperparámetro C de la logística:** en E05/E06 se fijó a priori (C=0.05). En adelante, cuando se ajuste, será con la validación interna (última temporada del train), igual que ξ.

## 2026-09-26 — Regla de parada aplicada por familia de modelos (antes de correr E09)
- Contexto: tras E08, la familia sin cuotas lleva 3 experimentos seguidos sin mejorar el mejor log loss en más de 0.002 (E06 −0.0007, E07 ±0, E08 −0.001). Aplicada de forma global, la regla podría cortar el backlog en E09 sin probar nunca E12–E13, que son los únicos que pueden responder al nivel "Bueno" (definido respecto del mercado: ningún modelo sin cuotas puede acercarse a 0.965).
- Decisión: la regla de parada de spec §6 / experiments.md §1.5 se aplica **por familia**: (a) sin cuotas (candidatas a `champion_no_odds`) y (b) con cuotas (candidatas a campeón con mercado). Cada familia lleva su propio contador. Si la familia sin cuotas llega a 4 seguidos sin mejora, no se corren más experimentos sin cuotas (se saltan E10/E11 si no han corrido) y se pasa a E12. Se mantiene el tope global de 15 experimentos y el orden del backlog dentro de cada familia.
- Motivo: experiments.md §4 exige dos campeones (`champion` y `champion_no_odds`) y los niveles de éxito se definen contra el mercado; la regla busca no sobre-explorar, no impedir evaluar la hipótesis central "mercado + nuestras señales > mercado solo". Se registra **antes** de ver el resultado de E09 para no condicionarla al resultado.
- Impacto: como máximo 15 experimentos en total; el informe explica qué se saltó y por qué.

## 2026-09-26 — Correcciones tras el checkpoint previo al holdout (T028)
- Contexto: `ml-reviewer` bloqueó por dos puntos irreversibles una vez usado el holdout; sin fuga ni errores en la selección del campeón. Ensayo general con 2024-25 como pseudo-holdout: reproduce exactamente las métricas de F3.
- Decisiones:
  - `evaluate_holdout` guarda predicciones por partido de los 6 modelos y todas las apuestas simuladas (`reports/holdout_artifacts/*.parquet`), el `describe()` de cada modelo entrenado (incl. hiperparámetros de Optuna del split final), la cobertura de cuotas y el IC bootstrap pareado (2000) de las diferencias de log loss del campeón frente a E01-avg, E02, frecuencias y champion_no_odds.
  - En el holdout completo, `E01-psc` se guarda como `E01-psc_with_freq_fallback` (Pinnacle donde hay cuota, frecuencias donde no): no es la línea base de Pinnacle. La comparación con Pinnacle al cierre se hace solo en el subconjunto con `PSC*` (se reportan tamaño y E01-avg en ese subconjunto).
  - El nivel "Excelente" por estrategia de valor usa solo la estrategia del campeón (no se elige la mejor de dos sobre el holdout).
  - `make all` omite el holdout si ya existe el lock (`betting-ml holdout --skip-if-done`) para poder llegar a `report` y `train-prod`.
  - Se re-ejecuta `make select` con el árbol limpio antes del holdout (trazabilidad del commit).
- Riesgos que el informe debe explicar: E12 es peor que el mercado Avg en los tres folds y llega a "Bueno" solo por la tolerancia de +0.005 (usar directamente el mercado sería mejor); E13 (stacking) no se probó por la parada; la regla por familia se registró tras ver E06–E08; el ECE sobre 1 752 partidos es ruidoso (E06 sube a 0.028 en F3); en 2025-26/2026-27 cambia el mercado de football-data (menos casas, margen de `avg` más alto; impacto medido en 2024-25: +0.0004 en E12); LightGBM usa `n_jobs=4` sin modo determinista (resultados idénticos en esta máquina, posibles diferencias en el último decimal en otras).
- (T028, 2ª revisión: APROBADO CON OBSERVACIONES) Los artefactos `reports/holdout_artifacts/*.parquet` **se versionan** a propósito: son pequeños y son la única copia de algo irrepetible. `holdout --skip-if-done` falla (código 1) si el lock no está en `completed`. El margen de "Bueno" (+0.005) cae dentro del IC de la diferencia campeón − mercado (ensayo en 2024-25: +0.0036, IC [−0.0005, +0.0077]); el informe lo presentará como resultado no concluyente.

## 2026-09-27 — Entrenamiento de producción (T031)
- Decisión: `make train-prod` exige el lock del holdout en estado `completed` y entrena con 2014-15…2025-26 + los partidos jugados de 2026-27 (plan §5). El conjunto completo se guarda como `data/processed/history.parquet`, que es lo único que lee la API (nunca abre `holdout.parquet`). Los modelos con Optuna se re-entrenan con los hiperparámetros elegidos en el split final del holdout (guardados en `holdout_results.json`), en lugar de volver a tunear con la validación interna, que en producción sería la temporada en curso (≈ 250 partidos).
- Versión: `{experimento}-{tipo}-{fecha}` en `models/`, y `models/production.json` apunta a las versiones activas.

## 2026-09-27 — Docker no disponible en la máquina de desarrollo (T037)
- Contexto: esta máquina Windows no tiene Docker instalado.
- Decisión: se entrega `Dockerfile` (python:3.12-slim, `uv sync --frozen --no-dev`, usuario no root uid 10001, healthcheck a `/health`) y `.dockerignore` (sin `.env`, `data/`, `models/`), más `make docker`. Datos, modelos y reportes se montan como volúmenes. Se valida con un test estático; la construcción real queda pendiente de una máquina con Docker (o CI).
- Impacto: la imagen no se ha construido todavía; el README lo indica.

## 2026-09-27 — Correcciones tras la auditoría final (T039)
- Contexto: `ml-reviewer` bloqueó por tres puntos (sin fuga; cifras del informe recalculadas y coincidentes).
- Decisiones:
  - `make all` usa solo los experimentos corridos (E01–E09, E12) y `betting-ml exp --skip-existing`, que no vuelve a correr (ni borra conclusiones de) los experimentos ya registrados.
  - Con el lock del holdout en su sitio, `make select` se niega a re-elegir campeón, y `train-prod` y `report` fallan si `champion.json` no coincide con los campeones evaluados en el holdout.
  - La tabla de experimentos del informe muestra el IC 95 % del ROI (constitución §IV.2).
  - API: probabilidades redondeadas a 4 decimales tras el ajuste de suma; local = visita → 422; la temporada de una fila de predicción se deriva de su fecha; el seguimiento guarda las value bets con el umbral validado del modelo (no con `min_edge` de la petición); `/admin/refresh` responde 503 si la clave es la de ejemplo; contrato actualizado (market null / value_bets [] sin cuotas; significado de `odds`).
  - `/admin/refresh` reconstruye los datasets con `build_dataset` (reescribe `data/processed/*` y `reports/data_quality.md`) y el historial de servicio; esto sí lee el holdout (ya evaluado) desde el contenedor. La API de predicción sigue leyendo solo `history.parquet`.
  - Dockerfile con uv 0.12.5 (la versión que generó `uv.lock`).
  - Pendientes documentados (no bloqueantes): `SEED` de `.env` no se usa (la semilla 42 está fijada en el código), CI no corre mypy, parte de la narrativa del informe es fija en el generador.
