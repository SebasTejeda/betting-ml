# Registro de decisiones — Spec 003

Formato:

```
## AAAA-MM-DD — Título corto
- Contexto:
- Decisión:
- Motivo:
- Impacto:
```

## 2026-10-21 — Consejos por reglas, no por LLM
- Contexto: el dueño quiere consejos explicados ("hay alta probabilidad de X porque…").
- Decisión: generar las razones con reglas deterministas y plantillas que citan números del análisis.
- Motivo: un LLM puede inventar datos o usar lenguaje de certeza; las reglas son verificables y testeables.
- Impacto: textos algo más rígidos; se puede evaluar una redacción con LLM en una spec futura, siempre a partir de la evidencia estructurada.

## 2026-10-21 — Champions y Europa League con ClubElo
- Contexto: el modelo de la spec 001 solo compara equipos de la misma liga.
- Decisión: ajuste de fuerza entre ligas con ClubElo y calibración con resultados de openfootball.
- Motivo: fuentes gratuitas y abiertas; permiten partidos como Real Madrid vs RB Leipzig.
- Impacto: más incertidumbre en partidos entre ligas, señalada en la interfaz; sin cuotas históricas europeas, solo se valida la calibración.

## 2026-10-21 — Sin mercados de jugadores, faltas ni tiros
- Contexto: el dueño mencionó mercados como faltas o tiros.
- Decisión: fuera de alcance; córners y tarjetas quedan como P3 opcional.
- Motivo: no hay datos ni cuotas gratuitas confiables para faltas, tiros o jugadores; córners y tarjetas sí tienen datos históricos en football-data.
- Impacto: menos mercados, pero todos los mostrados son medibles.
