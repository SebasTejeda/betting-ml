Responde siempre al usuario en español.

# CLAUDE.md — Guía para el agente

Proyecto: modelo de ML para predecir partidos de fútbol (1X2), detectar value bets y servirlo con una API REST; comparador de cuotas con referencia Pinnacle, diario de apuestas y frontend; análisis de partido con mercados derivados y consejos explicados. Se construye con **Spec-Driven Development (SDD)**.

**Spec activa: `specs/003-match-analysis/`** (las specs 001, `specs/001-prediction-model/`, y 002, `specs/002-odds-comparator/`, están terminadas; su código y resultados se mantienen).

## Lee en este orden antes de hacer nada

1. `specs/constitution.md` — reglas no negociables (I–XII).
2. `specs/003-match-analysis/spec.md` — qué se construye y criterio de éxito (spec activa).
3. `specs/003-match-analysis/plan.md` — cómo se construye.
4. `specs/003-match-analysis/contracts/api.md` — extensión del contrato de la API (se suma a los contratos de las specs 001 y 002).
5. `specs/003-match-analysis/tasks.md` — lista de tareas a ejecutar.
6. `specs/003-match-analysis/decisions.md` — decisiones de la spec activa.
7. `PROGRESS.md` — dónde se quedó el trabajo (sección "Spec 003").

Referencia de las specs terminadas: `specs/001-prediction-model/{spec,plan,experiments,decisions}.md` y `reports/REPORT.md`; `specs/002-odds-comparator/{spec,plan,decisions}.md`, `contracts/api.md` y `reports/REPORT_002_backtest.md`.

## Forma de trabajar

- Ejecuta el `tasks.md` de la **spec activa** en orden, **una tarea a la vez**: implementar → tests → `make lint && make test` → marcar `[x]` → línea en `PROGRESS.md` → commit.
- Escribe primero los tests de la lógica de dominio y features (TDD cuando sea práctico).
- La spec manda. Si algo de la spec es imposible o claramente mejorable, **no la ignores**: registra la decisión en el `decisions.md` de la spec activa y sigue.
- Si una fuente de datos falla, reintenta con espera; si sigue fallando, usa la alternativa descrita en la spec y documéntalo.
- Si un resultado es sospechosamente bueno, asume fuga de información y revísalo antes de celebrarlo.
- En los checkpoints 🔍 usa el subagente `ml-reviewer`.
- No preguntes al usuario salvo que estés bloqueado de verdad (credenciales, decisión irreversible). Para todo lo demás, decide con criterio y documenta.
- **Procesos:** si levantas servidores para probar o tomar capturas, hazlo en segundo plano dentro de tu sesión, reutiliza el que ya esté corriendo y ciérralos todos al terminar. No abras ventanas de consola nuevas.

## Reglas duras (resumen de la constitución)

- Nada de fuga: features solo con información previa al partido; cuotas de cierre nunca como feature.
- Cada holdout (2025-26) se usa una sola vez y con su propio lock (spec 003: `reports/HOLDOUT_003_USED.lock`).
- Validación temporal walk-forward; nada de splits aleatorios.
- Arquitectura hexagonal: `domain` sin dependencias de infraestructura; la API solo llama a `application`.
- Código en inglés, documentos y reportes en español.
- Conventional Commits, un commit por tarea. **Nunca `git push`.** Nunca commitear `data/`, `.env` ni `*.joblib`.
- **Juego responsable:** nada que incentive perseguir pérdidas; los límites de US6 de la spec 002 no se pueden saltar desde la API ni el frontend.
- **No scraping** de casas de apuestas; las APIs se usan dentro de sus límites. Cuidar los créditos de The Odds API (spec 003: como máximo 3 llamadas con coste en toda la spec): los tests usan siempre respuestas grabadas en `tests/fixtures/`.
- **Evidencia antes de construir:** ninguna estrategia llega al frontend sin backtest que la respalde (puertas T008 de la spec 002 y T010 de la spec 003).
- **Consejos honestos (XII):** probabilidad, precio y porqué con datos trazables; nunca lenguaje de certeza.
- **Dinero con `Decimal`**, nunca `float` (montos, stakes, bankroll, beneficios).
- **Las API keys** (`ODDS_API_KEY`, `APP_API_KEY`) viven solo en `.env`: nunca en el frontend del repo, en fixtures grabados ni en logs.

## Comandos

```
make setup | lint | test | data | baselines | exp ID=E05 | select | holdout | report | train-prod | serve | track | all
make backtest-002 | backtest-002-final | db-upgrade | odds | settle | web | web-test | dev     (spec 002)
make data-europe | validate-markets | validate-markets-final | analyze HOME=... AWAY=...       (spec 003)
```

Comandos del agente en `.claude/commands/`: `/next` (siguiente tarea), `/exp E07` (correr un experimento según protocolo), `/review` (checkpoint), `/status` (resumen del avance).

## Si se acaba el contexto o se reinicia la sesión

Lee `PROGRESS.md` y la primera tarea sin `[x]` en el `tasks.md` de la spec activa, verifica con `git log --oneline -5` y `git status` que no haya trabajo a medias, y continúa desde ahí.
