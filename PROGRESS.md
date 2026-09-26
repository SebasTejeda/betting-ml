# Progreso

Bitácora del agente. Una línea por tarea: `AAAA-MM-DD · TXXX · qué se hizo · resultado clave`.

## Metas de referencia (se llenan en T023)

| Referencia | Val log loss (F1–F3) |
|---|---|
| Frecuencias por liga | — |
| Mercado `Avg` pre-cierre (meta "Bueno" + 0.005) | — |
| Pinnacle al cierre (meta "Excelente") | — |

## Bitácora

- 2026-09-26 · T000 · Paquete SDD creado (constitución, spec, plan, experimentos, contrato, tareas) · listo para T001
- 2026-09-26 · T001 · Esqueleto hexagonal, pyproject (uv), Makefile, ruff/mypy/pytest/pre-commit · lint y test en verde (make no disponible en Windows → recetas vía uv, ver decisions.md)
- 2026-09-26 · T002 · Workflow de GitHub Actions (uv, ruff check/format, pytest sin red; Python 3.11 y 3.12) · listo
- 2026-09-26 · T003 · Settings (pydantic-settings) + leagues/features/team_aliases YAML con validación de esquema · 10 tests en verde
- 2026-09-26 · T004 · Entidades (Match, Fixture, OddsTriple, Probabilities, Prediction, ValueBet) y puertos Protocol · tests en verde
- 2026-09-26 · T005 · domain/odds.py: implícitas, overround, proporcional, Shin vectorizado (bisección), cuota justa, EV, Kelly 25% con tope 2% · cobertura 100%
- 2026-09-26 · T006 · domain/metrics.py: log loss, Brier multiclase (0–2), RPS, ECE top-label 10 bins, accuracy · coinciden con sklearn (tol 1e-9)
