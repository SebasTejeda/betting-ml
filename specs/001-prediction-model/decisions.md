# Registro de decisiones

Decisiones tomadas durante la implementación que no estaban en la spec o que la modifican. Formato:

```
## AAAA-MM-DD — Título corto
- Contexto:
- Decisión:
- Motivo:
- Impacto:
```

## 2026-09-26 — Alcance inicial
- Contexto: el dueño quería "lo más grande posible" sin definir ligas.
- Decisión: top 5 ligas europeas, 2014-15 a 2025-26, mercado 1X2 (O/U 2.5 opcional).
- Motivo: son las ligas con xG gratuito en Understat y cuotas completas en football-data; más ligas se agregan por config.
- Impacto: ~20 000 partidos de entrenamiento; la API cubre los partidos de esas 5 ligas.

## 2026-09-26 — `make` no disponible en la máquina de desarrollo (Windows)
- Contexto: la máquina Windows del agente no tiene GNU make instalado (ni choco/scoop).
- Decisión: el `Makefile` se escribe igual (lo usan CI, Linux, macOS y Docker) y todas sus recetas delegan en `uv run ...`. En local se ejecutan las mismas recetas directamente (`uv run ruff ...`, `uv run pytest`, `uv run betting-ml ...`). Para tener `make` en Windows: `winget install ezwinports.make` o usar WSL/Git Bash con make.
- Motivo: no instalar software de sistema sin permiso del dueño; las recetas son 1:1 con la CLI.
- Impacto: ninguno funcional; los comandos equivalentes se documentan en el README.

## 2026-09-26 — Python del entorno
- Contexto: la máquina tiene Python 3.14; el proyecto exige ≥ 3.11.
- Decisión: `requires-python = ">=3.11"`; `mypy` sin `python_version` fijo (usa el intérprete activo) porque los stubs de numpy usan sintaxis 3.12+.
- Motivo: todas las dependencias (xgboost, lightgbm, pyarrow…) tienen wheels para 3.14.
- Impacto: CI prueba en 3.11 y 3.12.
