# Registro de decisiones — Spec 002

Formato:

```
## AAAA-MM-DD — Título corto
- Contexto:
- Decisión:
- Motivo:
- Impacto:
```

## 2026-09-27 — Pinnacle como referencia vía The Odds API
- Contexto: la API pública de Pinnacle cerró en julio de 2025.
- Decisión: usar la cuota de Pinnacle que publica The Odds API (región `eu`) y Betfair Exchange como respaldo.
- Motivo: es la forma gratuita y legal disponible; el plan gratis alcanza para uso personal.
- Impacto: la cuota puede tener retraso; se muestra la hora de la última actualización.

## 2026-09-27 — Casas peruanas por ingreso manual
- Contexto: ninguna API de cuotas revisada cubre las casas con licencia de MINCETUR.
- Decisión: ingreso manual en la calculadora; sin scraping.
- Motivo: términos de uso y fragilidad del scraping.
- Impacto: un paso manual por apuesta, pero con evaluación instantánea.

## 2026-09-27 — Reutilizar 2025-26 como test del backtest
- Contexto: 2025-26 ya se usó como holdout del modelo en la spec 001.
- Decisión: usarlo también como test de la estrategia de referencia, con su propio lock.
- Motivo: la estrategia no aprende parámetros del modelo; su único hiperparámetro (umbral) se fija en F1–F3.
- Impacto: la variante con filtro del modelo sí hereda que el campeón se eligió sin ver 2025-26, así que sigue siendo válida.
