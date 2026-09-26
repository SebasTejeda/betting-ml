---
description: Ejecuta la siguiente tarea pendiente de tasks.md siguiendo el flujo SDD
---

1. Lee `CLAUDE.md`, `PROGRESS.md` y busca en `specs/001-prediction-model/tasks.md` la primera tarea sin `[x]`.
2. Revisa `git status`: si hay trabajo a medias de esa tarea, continúalo en vez de empezar de cero.
3. Relee las secciones de `spec.md`, `plan.md` o `experiments.md` que la tarea menciona.
4. Implementa la tarea con sus tests.
5. Corre `make lint && make test`. Corrige hasta que estén en verde.
6. Comprueba cada condición de "Hecho cuando".
7. Marca la tarea con `[x]`, agrega una línea a `PROGRESS.md` (fecha, ID, qué se hizo, resultado clave) y haz el commit con Conventional Commits.
8. Si la tarea es un checkpoint 🔍, usa el comando `/review`.

Si `$ARGUMENTS` es un número N, repite este proceso para las siguientes N tareas.
