# Tareas — Spec 003

Mismas reglas: en orden, una a la vez, `lint + test` en verde, marcar `[x]`, línea en `PROGRESS.md`, un commit por tarea, nunca `git push`. Decisiones en `specs/003-match-analysis/decisions.md`. Responder siempre en español.

Regla de créditos de The Odds API: como máximo **3 llamadas que consuman créditos** en toda la spec. Los tests usan respuestas grabadas en `tests/fixtures/`.

Regla de procesos: si levantas servidores para probar o tomar capturas, hazlo en segundo plano dentro de tu sesión, reutiliza el que ya esté corriendo y ciérralos todos al terminar. No abras ventanas de consola nuevas.

---

## Fase 0 — Integración

- [x] **T001** Integrar la spec 003: principio XII en `specs/constitution.md`; "Spec activa: `specs/003-match-analysis/`" en `CLAUDE.md` (más la regla de procesos de arriba si aún no está); sección "Spec 003" en `PROGRESS.md`; bloque de revisión 003 en `ml-reviewer` (fuga en la forma reciente y en la matriz, calibración por mercado, lock propio, lenguaje de los consejos, trazabilidad de la evidencia, fórmula de EV de "empate no apuesta").
  - Commit: `docs: integrate spec 003`

## Fase 1 — Mercados derivados y validación (puerta)

- [x] **T002** `domain/markets.py` + `configs/markets.yaml` con todos los mercados P1, nombres en español y líneas. Tests de propiedades y casos a mano.
  - Commit: `feat(domain): derived goal markets`
- [x] **T003** Fuentes europeas: adaptadores `clubelo.py` y `openfootball.py` (verificar formato real de ambos; caché; mapeo de nombres con `team_aliases.yaml`, fallando si falta alguno), comando `data-europe`. Fixtures de test sin red.
  - Commit: `feat(adapters): clubelo and openfootball sources`
- [x] **T004** Normalizar las cuotas históricas Más/Menos 2.5 de football-data al esquema canónico (`ou25_*`). Verificar con **una** llamada a The Odds API los `market keys` de fútbol disponibles (eventos de una liga), grabar la respuesta como fixture y ajustar `markets.yaml`.
  - Commit: `feat(data): over/under historical odds and market keys`
- [x] **T005** `ml/models/goal_model.py` (misma liga) usando el mejor modelo de goles validado en la spec 001; matriz de marcadores walk-forward. Tests.
  - Commit: `feat(models): score matrix for any fixture`
- [x] **T006** `ml/models/cross_league.py`: desplazamiento de fuerza por liga con ClubElo, ventaja de local europea estimada, validación walk-forward en partidos europeos. Registrar en `decisions.md` cómo quedó. **Al terminar:** la calibración europea (1X2 y Más/Menos 2.5 en UCL/UEL) que quedó pendiente en T007.
  - Commit: `feat(models): cross-league strength adjustment`
- [x] **T007** `ml/calibration_markets.py` + `validate-markets` en F1–F3: calibración por mercado, backtest de valor de Más/Menos 2.5 con CLV, calibración en partidos europeos; figuras en `reports/figures/003_*`.
  - Commit: `feat(validation): market calibration on validation folds`
- [x] 🔍 **T008** Checkpoint `ml-reviewer` (fuga, uso de cuotas de cierre solo para CLV, calibración creíble).
- [x] **T009** `validate-markets --final` una sola vez (lock `HOLDOUT_003_USED.lock`), `reports/market_calibration.json` con niveles de confianza y `reports/REPORT_003_markets.md` con nivel de la spec §5.
  - Commit: `exp(003): final market validation — <nivel>`
- [x] **T010** 🚦 **Puerta:** si ningún mercado P1 tiene confianza `alta` o `media`, detener aquí y avisar al dueño. Registrar en `decisions.md`.

## Fase 2 — Análisis y consejos

- [x] **T011** `application/team_form.py` (US2) con tests anti-fuga: la forma de un partido en fecha `d` no cambia si se alteran partidos en fecha ≥ `d`.
- [x] **T012** `domain/advice.py` + `configs/advice.yaml` (motor de consejos, plan §7): reglas a favor, en contra y de contexto; evidencia trazable; aviso de EV > 0.15; comentario de precio; mensaje sin valor. Tests: cada regla, lenguaje prohibido, máximo 4 razones, números del texto = números de la evidencia.
- [x] **T013** `application/analyze_match.py` que une matriz, mercados, cuotas, confianza, forma y consejos.
- [x] **T014** Adaptador de cuotas por evento en `the_odds_api.py` + estimación de costo + caché de 30 min. **Antes:** la llamada de verificación de market keys que quedó pendiente en T004 (decisions.md).
- [x] **T015** Routers según `contracts/api.md` + cambio en `POST /bets` para `market/selection/line` + liquidación por mercado (incluida la regla de "empate no apuesta" y hándicap europeo). Migración de base de datos.
- [x] **T016** Tests de API (incluidos 404/422/429/503 y partido entre ligas) y carpeta "Spec 003" en Postman.
  - Commits: uno por tarea.
- [x] 🔍 **T017** Checkpoint `ml-reviewer` del backend (consejos honestos, evidencia, liquidación por mercado, límites de US6 de la spec 002 intactos).

## Fase 3 — Frontend

- [x] **T018** Página **Análisis** (plan §9) con el estilo del rediseño: buscador, encabezado tipo marcador, Mejores opciones, Lo más probable, Forma reciente, Tabla de mercados, botón de refresco con costo.
- [x] **T019** Botón "Analizar" en Hoy y Partido; registro desde la tabla y desde los consejos (papel por defecto, flujo de confirmación y límites).
- [x] **T020** Panel de Mis apuestas: CLV y n.º de apuestas por mercado (US6). Separar el CLV contra Pinnacle del CLV contra el cierre promedio (`football_data_avgc`), que es una referencia más débil (checkpoint T017).
- [x] **T021** Tests de frontend con MSW (análisis completo, sin valor, entre ligas, sin cuotas, error de equipo).
  - Commits: uno por tarea.

## Fase 4 — Opcional (P3)

- [~] **T022** (pospuesto por decisión del dueño, 2026-10-22) Córners y tarjetas (US7) con su validación. Solo si el dueño lo confirma al llegar aquí; si no, marcar como "pospuesto" en `PROGRESS.md`.

## Fase 5 — Cierre

- [x] **T023** README: sección spec 003 (cómo leer el análisis, qué significa cada nivel de confianza, por qué "lo más probable" no es "lo mejor", comandos sin make).
- [ ] 🔍 **T024** Auditoría final `ml-reviewer`.
- [ ] **T025** Verificación final: tests en verde; levantar API y frontend en segundo plano; analizar un partido real próximo de liga y uno de Champions (máximo 2 llamadas de cuotas por evento, dentro del límite de 3 de la spec); capturas de la página Análisis; registrar una apuesta en papel de un mercado nuevo; cerrar todos los procesos. Resumen en `PROGRESS.md`.
  - Commit: `chore: spec 003 final verification`
