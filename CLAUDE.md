# CLAUDE.md — Guía para el agente

Proyecto: modelo de ML para predecir partidos de fútbol (1X2), detectar value bets y servirlo con una API REST. Se construye con **Spec-Driven Development (SDD)**.

## Lee en este orden antes de hacer nada

1. `specs/constitution.md` — reglas no negociables.
2. `specs/001-prediction-model/spec.md` — qué se construye y criterio de éxito.
3. `specs/001-prediction-model/plan.md` — cómo se construye (arquitectura, stack, validación).
4. `specs/001-prediction-model/experiments.md` — protocolo de experimentos.
5. `specs/001-prediction-model/contracts/api.md` — contrato de la API.
6. `specs/001-prediction-model/tasks.md` — lista de tareas a ejecutar.
7. `PROGRESS.md` — dónde se quedó el trabajo.

## Forma de trabajar

- Ejecuta `tasks.md` en orden, **una tarea a la vez**: implementar → tests → `make lint && make test` → marcar `[x]` → línea en `PROGRESS.md` → commit.
- Escribe primero los tests de la lógica de dominio y features (TDD cuando sea práctico).
- La spec manda. Si algo de la spec es imposible o claramente mejorable, **no la ignores**: registra la decisión en `specs/001-prediction-model/decisions.md` y sigue.
- Si una fuente de datos falla, reintenta con espera; si sigue fallando, usa la alternativa descrita en la spec y documéntalo.
- Si un resultado es sospechosamente bueno, asume fuga de información y revísalo antes de celebrarlo.
- En los checkpoints 🔍 usa el subagente `ml-reviewer`.
- No preguntes al usuario salvo que estés bloqueado de verdad (credenciales, decisión irreversible). Para todo lo demás, decide con criterio y documenta.

## Reglas duras (resumen de la constitución)

- Nada de fuga: features solo con información previa al partido; cuotas de cierre nunca como feature.
- El holdout (2025-26) no se toca hasta T029, y solo una vez.
- Validación temporal walk-forward; nada de splits aleatorios.
- Arquitectura hexagonal: `domain` sin dependencias de infraestructura; la API solo llama a `application`.
- Código en inglés, documentos y reportes en español.
- Conventional Commits, un commit por tarea. **Nunca `git push`.** Nunca commitear `data/`, `.env` ni `*.joblib`.

## Comandos

```
make setup | lint | test | data | baselines | exp ID=E05 | select | holdout | report | train-prod | serve | track | all
```

Comandos del agente en `.claude/commands/`: `/next` (siguiente tarea), `/exp E07` (correr un experimento según protocolo), `/review` (checkpoint), `/status` (resumen del avance).

## Si se acaba el contexto o se reinicia la sesión

Lee `PROGRESS.md` y la primera tarea sin `[x]` en `tasks.md`, verifica con `git log --oneline -5` y `git status` que no haya trabajo a medias, y continúa desde ahí.
