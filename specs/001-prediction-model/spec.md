# Spec 001 — Modelo de predicción de partidos de fútbol (1X2)

- **Estado:** aprobada para implementación
- **Dueño:** Sebastián
- **Fecha:** 2026-09-26
- **Principios:** ver [`../constitution.md`](../constitution.md)

## 1. Problema

Las casas de apuestas publican cuotas que implican una probabilidad para cada resultado, más un margen a su favor. Queremos un sistema que estime **nuestra propia probabilidad** de cada resultado de un partido, la compare con las cuotas disponibles y detecte apuestas con **valor esperado positivo** (*value bets*).

El foco de esta spec es el **modelo**. El comparador de la mejor casa por apuesta queda para la spec 002.

## 2. Alcance

### Dentro del alcance

| Tema | Decisión |
|---|---|
| Ligas | Top 5 de Europa: Premier League (`E0`), LaLiga (`SP1`), Bundesliga (`D1`), Serie A (`I1`), Ligue 1 (`F1`). Configurable para agregar más ligas sin tocar código (`configs/leagues.yaml`). |
| Temporadas de entrenamiento | 2014-15 a 2024-25 (Understat tiene xG desde 2014-15). |
| Holdout | Temporada 2025-26 completa (ver constitución §II). |
| Temporada en curso | 2026-27: solo para predicciones de partidos próximos y seguimiento en vivo. |
| Mercado principal | 1X2 (local / empate / visita). |
| Mercado secundario | Over/Under 2.5 goles, **solo si** el modelo campeón produce una distribución de goles (Poisson / Dixon-Coles). Es "deseable", no obligatorio. |
| Interfaz | API REST (FastAPI) probada con Postman. Sin frontend en esta spec. |

### Fuera del alcance

- Frontend web.
- Comparador en tiempo real de casas de apuestas (spec 002).
- Apuestas en vivo (in-play), hándicaps asiáticos, córners, tarjetas.
- Colocar apuestas reales automáticamente.

## 3. Fuentes de datos

| Fuente | Qué aporta | Acceso |
|---|---|---|
| football-data.co.uk (`mmz4281/{season}/{league}.csv`) | Resultados, estadísticas básicas, cuotas pre-cierre y de cierre de varias casas | CSV directo |
| football-data.co.uk (`fixtures.csv`) | Partidos próximos con cuotas | CSV directo (se actualiza ~2 veces por semana) |
| Understat | xG y xGA por partido y equipo | Scraping (JSON embebido o endpoint interno). Se puede usar la librería `soccerdata` como implementación del adaptador. |

Reglas:
- Descargas con pausa entre peticiones (≥ 3 s en scraping) y caché local: nunca se vuelve a descargar lo que ya está en `data/raw/` salvo la temporada en curso.
- Los nombres de equipos se unifican con `configs/team_aliases.yaml`. Todo equipo sin mapear es un **error** (no se descarta en silencio).

## 4. Historias de usuario

### US1 — Datos limpios y confiables (P1)
**Como** dueño del modelo **quiero** un dataset unificado y limpio de partidos con resultados, cuotas y xG **para** entrenar sin errores.

Criterios de aceptación:
- Un comando (`make data`) descarga, limpia y une todo en `data/processed/matches.parquet` y `data/processed/holdout.parquet`.
- Hay un reporte de calidad `reports/data_quality.md` con: filas por liga y temporada, % de nulos por columna, partidos sin xG emparejado, duplicados eliminados, equipos mapeados.
- ≥ 98 % de los partidos de football-data quedan emparejados con su xG de Understat.
- Las fechas y horas (hora del Reino Unido en la fuente) se convierten a UTC (`kickoff_utc`); no hay partidos duplicados (clave: liga + fecha + local + visita).

### US2 — Líneas base del mercado (P1)
**Como** dueño **quiero** saber qué tan bien predice el mercado **para** tener un rival claro.

Criterios de aceptación:
- Se calculan, sobre los mismos folds de validación, las métricas de: (a) frecuencias históricas por liga, (b) mercado pre-cierre (`Avg*` normalizado), (c) mercado de cierre de Pinnacle (`PSC*` normalizado).
- La normalización del margen usa el **método de Shin** (con el método proporcional como alternativa registrada).

### US3 — Experimentación controlada (P1)
**Como** dueño **quiero** que se prueben hasta 15 modelos de forma ordenada **para** quedarme con el mejor sin sobreajustar.

Criterios de aceptación:
- Cada experimento tiene su YAML, su fila en `reports/experiments.csv` y su commit `exp: ...`.
- El campeón se elige **solo** con métricas de validación (nunca del holdout), según la regla de `experiments.md` §4.
- Se genera un gráfico de calibración y uno de ROI acumulado por experimento en `reports/figures/`.

### US4 — Evaluación final honesta (P1)
**Como** dueño **quiero** un informe final **para** saber si el modelo sirve de verdad.

Criterios de aceptación:
- `reports/REPORT.md` incluye: tabla de experimentos, campeón y por qué, métricas del holdout (campeón vs líneas base), simulación de apuestas con IC 95 %, CLV, análisis por liga, limitaciones y próximos pasos.
- Se indica en qué nivel del criterio de éxito (§6) quedó el modelo.

### US5 — Predicciones de partidos del día vía API (P1)
**Como** usuario **quiero** consultar en Postman los partidos de un día con sus probabilidades y si hay valor **para** decidir qué mirar.

Criterios de aceptación:
- `GET /api/v1/matches?date=YYYY-MM-DD` devuelve los partidos de esa fecha (por defecto, hoy en `America/Lima`) de las ligas soportadas, con probabilidades 1X2, cuota justa, mejor cuota disponible en la fuente y bandera de valor.
- `POST /api/v1/predictions` permite predecir un partido cualquiera (liga + equipos + cuotas opcionales).
- Contrato completo en [`contracts/api.md`](contracts/api.md). Colección de Postman en `postman/betting-ml.postman_collection.json`.
- Si no hay partidos, responde `200` con lista vacía y un mensaje, no un error.

### US6 — Seguimiento en vivo (P2)
**Como** dueño **quiero** que las predicciones hechas para partidos futuros se guarden y luego se califiquen con el resultado real **para** medir el modelo fuera de muestra con el tiempo.

Criterios de aceptación:
- Cada predicción servida por `/matches` se guarda (idempotente por partido + versión de modelo) en `data/tracking/predictions.parquet`.
- `make track` actualiza resultados y `GET /api/v1/tracking/summary` devuelve log loss, aciertos y ROI simulado acumulados.

### US7 — Over/Under 2.5 (P3, opcional)
Solo si el campeón es un modelo de goles. Mismas métricas, en una sección aparte del informe.

## 5. Requisitos no funcionales

- **Arquitectura:** hexagonal (ver constitución §V y `plan.md` §2).
- **Rendimiento:** `/matches` responde en < 1 s con datos ya en caché (sin contar la descarga de `fixtures.csv`, que se cachea 6 h).
- **Reproducibilidad:** `make all` en una máquina limpia reproduce datos → experimentos → informe.
- **Portabilidad:** funciona en Windows, macOS y Linux. Se incluye `Dockerfile` para la API.
- **Calidad:** CI en GitHub Actions con `ruff` + `pytest`.

## 6. Criterio de éxito

Métrica principal: **log loss multiclase (1X2)**. Secundarias: Brier score, ECE (error de calibración), ROI simulado y CLV.

| Nivel | Condición (en el holdout 2025-26) |
|---|---|
| **Mínimo (obligatorio)** | El campeón tiene log loss mejor que la línea base de frecuencias **y** que el mejor modelo sin cuotas de E02 (Elo). ECE < 0.03. |
| **Bueno (meta)** | Log loss del campeón ≤ log loss del mercado pre-cierre (`Avg*`) + 0.005. Es decir, prácticamente igual de bueno que el mercado. |
| **Excelente** | Log loss del campeón < log loss de Pinnacle al cierre, **o** estrategia de valor con ROI > 0 cuyo IC 95 % (bootstrap) no incluye el 0, con ≥ 300 apuestas. |

Regla de parada: el proyecto se da por terminado al alcanzar el nivel **Bueno**, o al agotar los 15 experimentos, o si 4 experimentos seguidos no mejoran el log loss de validación en más de 0.002. Lo que ocurra primero. En todos los casos se entrega el informe.

## 7. Supuestos y riesgos

| Riesgo | Mitigación |
|---|---|
| Understat cambia su estructura o bloquea | Adaptador aislado detrás de un puerto; alternativa `soccerdata`; si falla, el pipeline sigue sin xG y lo marca en el informe. |
| `fixtures.csv` no trae partidos para la fecha pedida | La API devuelve lista vacía con mensaje; se documenta la frecuencia de actualización. |
| Equipos ascendidos sin historial | Elo inicial = promedio de los descendidos de esa liga; features de forma con prior de la liga. |
| Sobreajuste por muchos experimentos | Holdout sagrado + regla de selección solo con validación + preferencia por el modelo más simple ante empate. |
| Nombres de columnas distintos entre temporadas antiguas y nuevas de football-data | Capa de normalización con mapeo explícito y tests. |

## 8. Glosario

- **Probabilidad implícita:** 1 / cuota.
- **Overround / margen:** suma de probabilidades implícitas − 1.
- **Value bet:** apuesta donde `p_modelo × cuota > 1 + umbral`.
- **CLV (closing line value):** cuánto mejor fue la cuota tomada respecto a la de cierre de Pinnacle. CLV positivo sostenido indica un modelo con ventaja real.
- **Log loss:** penaliza estar seguro y equivocarse. Menor es mejor.
