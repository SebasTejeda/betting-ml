---
description: Lanza el checkpoint de revisión con el subagente ml-reviewer
---

1. Identifica en `tasks.md` qué checkpoint 🔍 corresponde (o usa `$ARGUMENTS` si se indica).
2. Lanza el subagente `ml-reviewer` indicándole el checkpoint y en qué debe enfocarse.
3. Copia su veredicto y la lista de bloqueantes en `PROGRESS.md`.
4. Corrige todos los bloqueantes (un commit `fix:` por cada uno o agrupados de forma lógica) y vuelve a lanzar la revisión hasta que el veredicto no sea BLOQUEADO.
5. Marca el checkpoint con `[x]`.
