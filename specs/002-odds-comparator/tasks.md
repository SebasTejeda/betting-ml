# Tareas — Spec 002

Mismas reglas de ejecución que la spec 001: en orden, una tarea a la vez, `lint + test` en verde, marcar `[x]`, línea en `PROGRESS.md`, un commit por tarea con Conventional Commits, nunca `git push`. Las decisiones nuevas van en `specs/002-odds-comparator/decisions.md`.

---

## Fase 0 — Integración y pendientes

- [x] **T001** Integrar la spec 002 al repo
  - Agregar a `specs/constitution.md` los principios IX, X y XI de `spec.md` §8.
  - Actualizar `CLAUDE.md`: agregar "Spec activa: `specs/002-odds-comparator/`" con su orden de lectura, y las reglas nuevas (juego responsable, no scraping, evidencia antes de construir, dinero con `Decimal`, la API key nunca en el frontend del repo).
  - Actualizar `.claude/commands/next.md` y `status.md` para que lean la **spec activa** declarada en `CLAUDE.md` en vez de una ruta fija.
  - Agregar en `PROGRESS.md` una sección "Spec 002".
  - Ampliar `ml-reviewer` con un bloque de revisión para la spec 002: backtest (uso de `psc_` solo para CLV, lock propio), dinero con `Decimal`, límites de US6 imposibles de saltar desde la API, seguridad de la API key y consumo de créditos.
  - Commit: `docs: integrate spec 002`

- [ ] **T002** Investigar el `/matches` vacío del sábado 26/09/2026 (spec §7). Reproducir con el `fixtures.csv` real guardado en `data/raw/fixtures/`. Si es un bug (fecha `dd/mm`, zona horaria, filtro de ligas), corregirlo con un test de regresión que use un extracto de ese CSV. Si no lo es, documentar por qué no había partidos.
  - Commit: `fix(fixtures): ...` o `docs: ...`

- [ ] **T003** README: documentar la decisión de la regla de parada por modelos con/sin cuotas (spec 001) en una línea con enlace a `decisions.md`.
  - Commit: `docs(readme): stop-rule decision`

## Fase 1 — Backtest (puerta de decisión)

- [ ] **T004** Dominio: método de potencia en `odds.py`, `value.py`, `clv.py` con tests (casos a mano; propiedad: las probabilidades justas suman 1; el stake nunca es negativo ni supera el tope).
  - Commit: `feat(domain): value, clv and power normalization`

- [ ] **T005** `application/backtest_pinnacle.py` + `make backtest-002` (F1–F3): escenarios `max`, `b365`, `avg`; variantes con y sin filtro del modelo; elección del umbral; figuras en `reports/figures/002_*`.
  - Hecho cuando: el escenario de control `avg` da CLV ≤ 0 aproximadamente (si no, investigar antes de seguir).
  - Commit: `feat(backtest): pinnacle reference strategy on validation folds`

- [ ] 🔍 **T006** Checkpoint `ml-reviewer` del backtest antes del test final (fuga, uso de `psc_`, elección del umbral).

- [ ] **T007** `make backtest-002-final` (una sola vez, lock `HOLDOUT_002_USED.lock`) + `reports/REPORT_002_backtest.md` con el nivel de la spec §5 y la conclusión **seguir / seguir con cambios / no seguir**.
  - Commit: `exp(002): final backtest — <conclusión>`

- [ ] **T008** 🚦 **Puerta.** Si ninguna variante tuvo CLV medio > 0 en validación: detener aquí, escribir el resumen en `PROGRESS.md` y avisar al dueño. Si pasa, continuar. Registrar la decisión en `decisions.md`.

## Fase 2 — Datos en vivo y persistencia

- [ ] **T009** `configs/bookmakers.yaml` con las casas de The Odds API (regiones `eu`, `uk`) y las peruanas de ingreso manual (Betsson, Te Apuesto, Inkabet, Doradobet, Apuesta Total, Betano, Coolbet; ajustar la lista). Marcar `accessible: true` solo para las que operan en Perú. Test de esquema.
  - Commit: `feat(config): bookmakers catalog`
- [ ] **T010** SQLite + SQLAlchemy + Alembic: modelos, repositorios, migración inicial, `make db-upgrade`. Tests con base en memoria.
  - Commit: `feat(db): sqlite persistence with migrations`
- [ ] **T011** Adaptador `the_odds_api.py`: verificar los `sport_key` reales (una llamada a `/v4/sports`, que no consume créditos), cliente con lectura de créditos, mapeo de equipos y eventos, grabar 1–2 respuestas reales como fixtures de test (sin la API key).
  - Commit: `feat(adapters): the odds api client`
- [ ] **T012** Caso de uso `refresh_odds` + control de presupuesto + scheduler opcional + `make odds`.
  - Commit: `feat(app): odds refresh with credit budget`

## Fase 3 — Casos de uso y API

- [ ] **T013** `compare_matches` (US3) y `evaluate_manual_odds` (US4).
- [ ] **T014** `domain/limits.py` + `manage_bets` (US5, US6) con tests exhaustivos de límites (incluido el cambio de mes en hora de Lima y la regla de subir el límite).
- [ ] **T015** `settle_bets` con CLV y `make settle`.
- [ ] **T016** Routers nuevos según `contracts/api.md`, con `X-API-Key` en escrituras y errores uniformes.
- [ ] **T017** Tests de API de todos los endpoints nuevos (incluidos 403/409/429).
- [ ] **T018** Actualizar la colección de Postman con una carpeta "Spec 002".
  - Commits: uno por tarea.

- [ ] 🔍 **T019** Checkpoint `ml-reviewer` del backend (límites no evitables, dinero en `Decimal`, créditos, contrato).

## Fase 4 — Frontend

- [ ] **T020** Proyecto `frontend/` con Vite + React + TS + Tailwind + TanStack Query + React Router + ESLint/Prettier + Vitest. Generación de tipos desde `/openapi.json` (`npm run gen:api`). `make web`, `make dev`.
  - Commit: `feat(web): frontend skeleton`
- [ ] **T021** Página **Hoy** (tabla y tarjetas en el celular, botón de refresco con créditos).
- [ ] **T022** Página **Partido** (tabla casas × resultados, margen, gráfico de referencia, calculadora rápida).
- [ ] **T023** Página **Calculadora** + registrar apuesta (con el flujo de confirmación de límites).
- [ ] **T024** Página **Mis apuestas** (tabla, liquidación y panel con KPIs y gráficos).
- [ ] **T025** Páginas **Backtest** y **Ajustes**.
- [ ] **T026** Tests de frontend con MSW: cada página renderiza datos, estados vacíos, errores y el flujo de límites (409 → confirmación; 403 → bloqueo).
  - Commits: uno por tarea (`feat(web): ...`, `test(web): ...`).

## Fase 5 — Cierre

- [ ] **T027** CI: job de frontend.
- [ ] **T028** README: sección de la spec 002 (qué hace, cómo configurar la API key de The Odds API, cómo usar cada página, comandos sin `make`, resultados del backtest y aviso de juego responsable).
- [ ] 🔍 **T029** Auditoría final con `ml-reviewer`.
- [ ] **T030** Verificación final: backend y frontend en verde; levantar `make dev`, hacer un refresco real de cuotas (≈ 10 créditos), revisar Hoy, registrar una apuesta de papel desde la calculadora y ver que aparece en el panel. Resumen en `PROGRESS.md`.
  - Commit: `chore: spec 002 final verification`
