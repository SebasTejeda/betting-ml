---
description: Ejecuta la siguiente tarea pendiente de la spec activa siguiendo el flujo SDD
---

1. Lee `CLAUDE.md` para saber cuál es la **spec activa** (línea "Spec activa: `specs/<spec>/`"). En adelante, `<spec>` es esa carpeta.
2. Lee `PROGRESS.md` y busca en `specs/<spec>/tasks.md` la primera tarea sin `[x]`.
3. Revisa `git status`: si hay trabajo a medias de esa tarea, continúalo en vez de empezar de cero.
4. Relee las secciones de `specs/<spec>/spec.md`, `plan.md`, `contracts/` (y `experiments.md` si existe) que la tarea menciona.
5. Implementa la tarea con sus tests.
6. Corre `make lint && make test` (sin make: los equivalentes `uv run ...` del README). Corrige hasta que estén en verde.
7. Comprueba cada condición de "Hecho cuando".
8. Marca la tarea con `[x]`, agrega una línea a `PROGRESS.md` en la sección de la spec activa (fecha, ID, qué se hizo, resultado clave) y haz el commit con Conventional Commits.
9. Si la tarea es un checkpoint 🔍, usa el comando `/review`. Si es una puerta 🚦, aplica su regla y, si indica detenerse, detente y avisa al dueño.

Si `$ARGUMENTS` es un número N, repite este proceso para las siguientes N tareas.
