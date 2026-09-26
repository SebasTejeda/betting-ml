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
