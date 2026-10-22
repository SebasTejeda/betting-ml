Responde siempre al usuario en español.

# CLAUDE.md — Guía para el agente

Proyecto: modelo de ML para predecir partidos de fútbol (1X2), detectar value bets y servirlo con una API REST; comparador de cuotas con referencia Pinnacle, diario de apuestas y frontend. Se construye con **Spec-Driven Development (SDD)**.

**Spec activa: `specs/004-match-analysis/`** — integración de la rama `Sebastian` (análisis de partido) siguiendo [`integration.md`](specs/004-match-analysis/integration.md). Las specs 001 (`specs/001-prediction-model/`), 002 (`specs/002-odds-comparator/`) y 003 (`specs/003-security-hardening/`) están terminadas; su código y resultados se mantienen.

## Lee en este orden antes de hacer nada

1. `specs/constitution.md` — reglas no negociables (I–XII).
2. `SECURITY.md` — modelo de amenazas y controles que ningún cambio puede debilitar.
3. `specs/004-match-analysis/integration.md` — plan y tareas (I00–I08) de la spec activa.
4. `PROGRESS.md` — estado del proyecto (resúmenes finales de cada spec; sección "Spec 004").

Referencia de las specs terminadas:
- `specs/001-prediction-model/{spec,plan,experiments,decisions}.md` con `reports/REPORT.md`.
- `specs/002-odds-comparator/{spec,plan,decisions}.md` con su `contracts/api.md` y `reports/REPORT_002_backtest.md`.
- `specs/003-security-hardening/{spec,plan,decisions}.md` con su `contracts/api.md`, `reports/SECURITY_BASELINE.md`, `reports/SECURITY_AUDIT_003.md` y `docs/deploy.md`.

El contrato de la API es la suma de los tres `contracts/api.md`.

## Forma de trabajar

- Ejecuta el `tasks.md` de la **spec activa** en orden, **una tarea a la vez**: implementar → tests → `make lint && make test` → marcar `[x]` → línea en `PROGRESS.md` → commit.
- Escribe primero los tests de la lógica de dominio y features (TDD cuando sea práctico).
- La spec manda. Si algo de la spec es imposible o claramente mejorable, **no la ignores**: registra la decisión en el `decisions.md` de la spec activa y sigue.
- Si una fuente de datos falla, reintenta con espera; si sigue fallando, usa la alternativa descrita en la spec y documéntalo.
- Si un resultado es sospechosamente bueno, asume fuga de información y revísalo antes de celebrarlo.
- En los checkpoints 🔍 usa el subagente `ml-reviewer`.
- No preguntes al usuario salvo que estés bloqueado de verdad (credenciales, decisión irreversible). Para todo lo demás, decide con criterio y documenta.
- **Confirmación por paso (pedida por el dueño en la spec 003):** al terminar cada tarea (con su commit), presenta el resultado y pide confirmación antes de empezar la siguiente, salvo que el dueño diga otra cosa para una spec nueva. El trabajo va en la rama `Daniel`.

## Reglas duras (resumen de la constitución)

- Nada de fuga: features solo con información previa al partido; cuotas de cierre nunca como feature.
- El holdout (2025-26) no se toca hasta T029, y solo una vez.
- Validación temporal walk-forward; nada de splits aleatorios.
- Arquitectura hexagonal: `domain` sin dependencias de infraestructura; la API solo llama a `application`.
- Código en inglés, documentos y reportes en español.
- Conventional Commits, un commit por tarea. **Nunca `git push`.** Nunca commitear `data/`, `.env` ni `*.joblib`.
- **Juego responsable:** nada que incentive perseguir pérdidas; los límites de US6 no se pueden saltar desde la API ni el frontend.
- **No scraping** de casas de apuestas; las APIs se usan dentro de sus límites. Cuidar los créditos de The Odds API: los tests usan siempre respuestas grabadas en `tests/fixtures/`.
- **Evidencia antes de construir:** ninguna estrategia llega al frontend sin backtest que la respalde (puerta T008 de la spec 002).
- **Dinero con `Decimal`**, nunca `float` (montos, stakes, bankroll, beneficios).
- **Las API keys** (`ODDS_API_KEY`, `APP_API_KEY`) viven solo en `.env`: nunca en el frontend del repo, en fixtures grabados ni en logs.
- **Seguridad (spec 003):** toda ruta de la API exige autenticación salvo `/health` y el login; nada de secretos en el navegador (`localStorage` incluido); contraseñas solo como hash Argon2id; escrituras con sesión exigen CSRF; la auditoría es de solo inserción; cada control de seguridad lleva tests negativos; las migraciones nunca borran ni corrigen datos en silencio.

## Comandos

```
make setup | lint | test | data | baselines | exp ID=E05 | select | holdout | report | train-prod | serve | track | all
make backtest-002 | backtest-002-final | db-upgrade | odds | settle | web | web-test | dev     (spec 002)
make security | backup | restore FILE=... | verify-integrity                                   (spec 003)
```

En esta máquina no hay `make`: usa los equivalentes `uv run ...` / `npm run ...` del `Makefile`.

Comandos del agente en `.claude/commands/`: `/next` (siguiente tarea), `/exp E07` (correr un experimento según protocolo), `/review` (checkpoint), `/status` (resumen del avance).

## Si se acaba el contexto o se reinicia la sesión

Lee `PROGRESS.md` y verifica con `git log --oneline -5` y `git status` que no haya trabajo a medias. Si hay una spec activa, continúa desde la primera tarea sin `[x]` de su `tasks.md`; si no la hay, pregunta al dueño qué sigue.
