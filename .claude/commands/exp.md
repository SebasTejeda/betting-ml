---
description: Diseña, corre y registra un experimento según experiments.md (ej. /exp E07)
---

Experimento: `$ARGUMENTS`

1. Lee `specs/001-prediction-model/experiments.md` y `reports/experiments.csv` para ver qué se ha aprendido.
2. Crea o revisa el YAML `configs/experiments/<ID>_<nombre>.yaml` (ID = $ARGUMENTS) con `hypothesis`, modelo, grupos de features, `uses_odds` y parámetros. Si es E14/E15, elige la hipótesis con base en los resultados previos y justifícala.
3. Verifica que no se lea `holdout.parquet` en ningún punto.
4. Corre `make exp ID=$ARGUMENTS`.
5. Revisa las métricas y las figuras. Si el resultado es sospechosamente bueno, investiga fuga antes de continuar.
6. Escribe la `conclusion` en la fila del CSV (1–2 frases: ¿se confirmó la hipótesis? ¿qué sigue?).
7. Evalúa la regla de parada de `experiments.md` §1.5 y anótalo en `PROGRESS.md`.
8. Commit: `exp($ARGUMENTS): <resumen> — val ll <valor>`.
