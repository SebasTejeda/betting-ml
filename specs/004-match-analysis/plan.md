# Plan técnico — Spec 004

> **Numeración.** Se escribió como *spec 003* en la rama `Sebastian`. Al integrarse en la rama `Daniel` (2026-10-22), donde la spec 003 es la de seguridad, pasó a ser la **spec 004**. Su enmienda a la constitución es la **XIII** y su migración, la `0009`. Las menciones a "spec 003" dentro de este documento se conservan como estaban. Los nombres de sus locks y reportes (`HOLDOUT_003_*`, `REPORT_003_*`) no cambian. La integración: [`integration.md`](integration.md).

Extiende el repo sin romper las specs 001 y 002. Misma arquitectura hexagonal; lo nuevo va en módulos nuevos.

## 1. Fuentes nuevas

| Fuente | Uso | Notas |
|---|---|---|
| ClubElo API (`http://api.clubelo.com/`) | Rating de cada club por fecha (`/{YYYY-MM-DD}` devuelve todos los clubes en CSV; `/{Club}` devuelve la historia de un club) | Verificar formato y nombres en T003. Caché diaria. Mapear nombres con `team_aliases.yaml`. |
| `openfootball/champions-league` (GitHub, dominio público) | Resultados históricos de Champions y Europa League para calibrar | Descargar los archivos del repo (o su exportación JSON en `openfootball/football.json` si cubre las temporadas). Verificar en T003. |
| The Odds API — cuotas por evento | Mercados adicionales | `GET /v4/sports/{sport}/events` (lista eventos, sin costo de mercados) y `GET /v4/sports/{sport}/events/{eventId}/odds?regions=eu&markets=...`. Costo ≈ mercados × regiones por evento. Verificar los `market keys` de fútbol disponibles en el plan gratis en T004 (1–2 llamadas como máximo). `sport_key` de Champions: `soccer_uefa_champs_league`; Europa League: verificar. |
| football-data (ya existe) | Cuotas históricas Más/Menos 2.5 y córners/tarjetas | Normalizar `B365>2.5`, `B365<2.5`, `Avg>2.5`, `Avg<2.5`, `P>2.5`, `P<2.5`, `PC>2.5`, `PC<2.5` (y sus variantes antiguas `BbAv>2.5`, etc.). |

## 2. Estructura (solo lo nuevo)

```
configs/
├── markets.yaml            # catálogo: key, nombre en español, selecciones, líneas, fuente de cuota, experimental: true|false
└── advice.yaml             # umbrales de las reglas de consejos (probabilidad alta, n.º mínimo de partidos, etc.)
src/betting_ml/
├── domain/
│   ├── markets.py          # derivación de mercados desde la matriz de marcadores (funciones puras)
│   ├── advice.py           # motor de consejos: reglas → razones con evidencia; filtro de lenguaje prohibido
│   └── ports.py            # + RatingsSource, InternationalResultsSource, EventOddsSource
├── ml/
│   ├── models/goal_model.py        # fachada: matriz de marcadores para cualquier par de equipos (misma liga o entre ligas)
│   ├── models/cross_league.py      # ajuste de fuerza con ClubElo
│   ├── models/counts.py            # P3: córners y tarjetas
│   └── calibration_markets.py      # US1
├── application/
│   ├── validate_markets.py         # US1
│   ├── analyze_match.py            # US2–US4
│   └── team_form.py                # US2
├── adapters/
│   ├── clubelo.py
│   ├── openfootball.py
│   └── the_odds_api.py             # + endpoint por evento
└── api/routers/analysis.py
frontend/src/features/analysis/     # página Análisis
reports/
├── market_calibration.json
├── REPORT_003_markets.md
└── HOLDOUT_003_USED.lock
```

## 3. Derivación de mercados (`domain/markets.py`)

Entrada: matriz `M[i, j]` = P(local marca i, visita marca j), i, j ∈ 0..10, que suma 1 (renormalizar tras truncar).

| Mercado | Fórmula |
|---|---|
| 1X2 | Σ i>j, Σ i=j, Σ i<j |
| Doble oportunidad | 1X = P(1)+P(X); X2; 12 |
| Empate no apuesta | P(1) / (P(1)+P(2)) (el empate devuelve la apuesta). **EV = P(1)·cuota + P(X) − 1**, no la fórmula simple |
| Más/Menos L | Σ i+j > L |
| Ambos marcan | Σ i≥1, j≥1 |
| Goles de un equipo Más/Menos L | marginal de i (o de j) > L |
| Hándicap europeo −1 local | i − j ≥ 2 gana; i − j = 1 empate del hándicap; resto pierde (tres vías) |
| Marcador exacto | top 5 celdas |

Tests: propiedades (cada mercado suma 1 entre sus selecciones; Más 2.5 + Menos 2.5 = 1; coherencia entre 1X2 y doble oportunidad) y casos a mano con una matriz pequeña conocida.

## 4. Modelo de goles para cualquier par de equipos (`goal_model.py`)

- **Misma liga:** Dixon-Coles ya existente (ataque/defensa por equipo, ventaja de local, ρ, decaimiento temporal), opcionalmente con xG (el mejor de E04/E09 de la spec 001 según validación).
- **Entre ligas (`cross_league.py`):**
  1. Cada equipo tiene ataque/defensa relativos a su liga.
  2. Se estima un **desplazamiento de fuerza por liga** a partir de ClubElo: diferencia de rating medio de la liga respecto de una referencia, convertida a log-goles con una regresión ajustada en partidos europeos históricos (openfootball + ClubElo en la fecha del partido).
  3. Ventaja de local reducida configurable para torneos europeos (estimar con los datos; no suponer).
  4. Validación: log loss 1X2 y Más/Menos 2.5 en partidos europeos con walk-forward por temporada.
- Si falta el rating ClubElo de un equipo: no hay análisis entre ligas para ese partido (error claro).
- Partidos de Champions sin xG: se usan solo goles y ratings; se indica en la respuesta.

## 5. Validación de mercados (US1)

- Para cada partido de validación, la matriz se calcula **solo con información previa** (mismo esquema walk-forward y re-ajuste cada 7 días de la spec 001).
- Métricas por mercado y selección: log loss binario/multiclase, Brier, ECE (10 bins), curva de calibración; comparación con una línea base de frecuencias históricas de ese mercado en la liga.
- Más/Menos 2.5: backtest de valor como en la spec 002 (umbral elegido en F1–F3, una apuesta por partido, CLV contra `PC>2.5/PC<2.5`).
- Nivel de confianza según la spec US1; escrito en `reports/market_calibration.json` y leído por la API.

## 6. Forma reciente (`team_form.py`)

- Fuente: partidos de liga (football-data + Understat) y europeos (openfootball), unidos por equipo canónico y ordenados por fecha.
- Métricas de la spec US2. Todas calculadas con partidos **anteriores** a la fecha del partido analizado.
- Muestras chicas: si hay < 4 partidos en una condición (por ejemplo, de visita), se usa el total y se indica.

## 7. Motor de consejos (`domain/advice.py`)

Determinista y testeable. Entrada: tabla de mercados (p, cuota, EV, confianza), forma de ambos equipos, λ, contexto (competición, entre ligas sí/no).

1. **Candidatos de valor:** `EV ≥ min_edge` y confianza `alta`/`media` → hasta 3 por EV.
2. **Lo más probable:** top 3 por probabilidad, excluyendo selecciones triviales (p > 0.95) → siempre con comentario de precio.
3. **Razones:** cada mercado tiene una lista ordenada de *reglas de razón* en `advice.yaml`. Una regla se activa solo si su condición se cumple con los datos, y produce una frase con números. Ejemplos para "goles de un equipo Más 1.5":
   - `lambda_team ≥ 1.8` → "El modelo espera {λ:.1f} goles de {equipo}."
   - `scored_2plus_last6 ≥ 4` → "{equipo} marcó 2 o más en {n} de sus últimos 6 partidos{condición}."
   - `opp_xga_last6 ≥ 1.5` → "{rival} concede {xga:.1f} xG por partido{condición} en sus últimos 6."
   - `cross_league` → "⚠️ Partido entre ligas: la fuerza se ajusta con ClubElo, hay más incertidumbre."
   - Reglas en contra (también se muestran si se activan): "{rival} recibió 0 goles en 3 de sus últimos 6."
4. Máximo 4 razones por consejo, al menos 1 a favor; si ninguna regla a favor se activa, el consejo se muestra sin razones y con "El valor viene del precio, no de una tendencia clara."
5. Cada razón devuelve `text` + `evidence` (los valores usados) para que el frontend y los tests puedan verificarla.
6. Filtro de lenguaje prohibido aplicado a todos los textos (test con lista de palabras).
7. Comentario de precio para "Lo más probable": `p`, cuota justa, mejor cuota, EV y veredicto en una frase.

## 8. API

Ver [`contracts/api.md`](contracts/api.md). Endpoints: búsqueda de equipos, búsqueda de partido próximo entre dos equipos, análisis, refresco de cuotas de un evento.

## 9. Frontend — página **Análisis** (`/analysis`)

- Buscador con autocompletado de dos equipos (y fecha opcional); si hay un partido próximo entre ellos, se selecciona solo.
- Encabezado tipo marcador: equipos, competición, fecha, ratings ClubElo, λ de cada uno, aviso "entre ligas" si aplica.
- **Mejores opciones** (tarjetas destacadas con razones) y **Lo más probable** (tarjetas con comentario de precio).
- **Forma reciente**: últimos 6 de cada equipo (chips V/E/D con color), promedios y porcentajes; H2H plegable.
- **Tabla de mercados** por grupos plegables, con probabilidad (barra), cuota justa, mejor cuota y casa, EV con color, confianza (badge) y botón Registrar.
- Botón "Actualizar cuotas de este partido" mostrando el costo estimado en créditos.
- Mismo estilo visual que el rediseño; responsive; etiquetas EXPERIMENTAL y aviso de juego responsable visibles.
- Enlaces: desde Hoy y Partido, botón "Analizar".

## 10. Comandos nuevos

| Comando | Qué hace | Sin make |
|---|---|---|
| `make data-europe` | Descarga ClubElo y openfootball | `uv run betting-ml data-europe` |
| `make validate-markets` | US1 en F1–F3 | `uv run betting-ml validate-markets` |
| `make validate-markets-final` | US1 en 2025-26 (una vez) | `uv run betting-ml validate-markets --final` |
| `make analyze HOME=... AWAY=...` | Análisis por consola | `uv run betting-ml analyze "Real Madrid" "RB Leipzig"` |
