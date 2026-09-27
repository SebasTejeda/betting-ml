# Spec 002 — Comparador de cuotas con referencia Pinnacle y diario de apuestas

- **Estado:** aprobada para implementación
- **Dueño:** Sebastián
- **Fecha:** 2026-09-27
- **Depende de:** spec 001 (modelo, API, matemática de cuotas en `domain/odds.py`)
- **Principios:** [`../constitution.md`](../constitution.md) + enmiendas de §8 de esta spec

## 1. Problema

La spec 001 demostró que el modelo predice casi igual que el mercado, pero no mejor: apostar solo con el modelo dio ROI −5.7 % y CLV −6.3 % en el holdout. La mayor mejora posible ya no está en predecir mejor, sino en **cómo y dónde se apuesta**:

1. **Mejor cuota:** la diferencia entre la cuota promedio y la mejor casa suele ser de 3–5 %.
2. **Referencia sharp:** Pinnacle es la casa más precisa. Su probabilidad sin margen es una "verdad" muy difícil de superar. Cuando una casa blanda paga más que esa probabilidad justa, hay valor esperado positivo, sin depender de ganarle al mercado con un modelo propio.
3. **Disciplina:** registrar cada apuesta, medir el CLV y respetar un presupuesto separa al apostador informado del recreativo.

Objetivo: ser **relativamente mejor que un apostador promedio**, no infalible.

## 2. Alcance

### Dentro

| Tema | Decisión |
|---|---|
| Ligas | Las mismas 5 de la spec 001. |
| Mercado | 1X2. Over/Under 2.5 como P3. |
| Fuente de cuotas en vivo | **The Odds API** (regiones `eu` y `uk`, que incluyen Pinnacle, Betfair Exchange, Betsson, 1xBet, William Hill, etc.). Plan gratis de 500 créditos/mes; el sistema debe funcionar dentro de ese límite. |
| Casas peruanas | **Ingreso manual de cuotas** desde el frontend (la mayoría no está en ninguna API). El scraping de casas peruanas queda **fuera** por defecto (términos de uso y fragilidad); se deja el puerto preparado. |
| Referencia de probabilidad | Pinnacle sin margen (método de Shin, con el método de potencia como alternativa). Si Pinnacle no tiene la cuota, se usa Betfair Exchange (ajustado por comisión) y se indica. |
| Segunda opinión | Probabilidad del modelo campeón de la spec 001. Se muestra si coincide o no con la señal de valor. |
| Diario de apuestas | Registro de apuestas reales o en papel, cálculo de CLV, ROI y evolución del bankroll. |
| Frontend | Web en React + TypeScript. |
| Backtest | Validación histórica de la estrategia "cuota blanda > probabilidad justa de Pinnacle" con los datos de football-data que ya tenemos. |

### Fuera

- Colocar apuestas automáticamente.
- Scraping de casas peruanas (puede ser una spec futura, con revisión de sus términos).
- Apuestas en vivo, combinadas, hándicaps asiáticos.
- App móvil (el frontend debe ser responsive, eso basta).
- Cuentas de usuario y autenticación multiusuario (es una herramienta personal; basta con una API key).

## 3. Historias de usuario

### US1 — Backtest de la estrategia Pinnacle (P1, va primero)
**Como** apostador **quiero** saber si la estrategia de referencia Pinnacle habría funcionado históricamente **para** no construir una herramienta sobre una idea falsa.

Criterios de aceptación:
- Con datos de football-data: probabilidad justa = Shin sobre `ps_odds_*` (Pinnacle pre-cierre). Apuesta si `cuota × p_justa − 1 > umbral`, con la cuota de `max_odds_*` (escenario optimista) y de `b365_odds_*` (escenario "una sola casa blanda").
- Umbral elegido en F1–F3 dentro de {0.01, 0.02, 0.03, 0.05}; evaluado **una vez** en 2025-26 (lock propio `reports/HOLDOUT_002_USED.lock`).
- Métricas: nº de apuestas, ROI, IC 95 % bootstrap, CLV frente a `psc_odds_*`, drawdown, ROI por liga y por rango de cuota.
- Variante con segunda opinión: solo apostar si además `p_modelo ≥ p_justa`. Se compara con la versión sin filtro.
- Resultado en `reports/REPORT_002_backtest.md`, con conclusión clara: **seguir / seguir con cambios / no seguir**.
- **Puerta de decisión:** si ninguna variante tiene CLV medio > 0 en validación, se detiene la spec tras US1 y se informa. El frontend no se construye sobre una estrategia sin evidencia.

### US2 — Captura de cuotas en vivo (P1)
**Como** apostador **quiero** que el sistema descargue las cuotas actuales de varias casas **para** compararlas.

Criterios de aceptación:
- Snapshots de cuotas guardados con fecha y hora (historial, no se sobrescribe).
- Control de presupuesto de créditos: se leen los headers `x-requests-remaining` / `x-requests-used`; si quedan menos de un mínimo configurable (por defecto 50), no se hacen más llamadas automáticas y se avisa en la API y el frontend.
- Refresco manual (botón) y automático opcional (por defecto: 2 veces al día solo los días con partidos).
- Nombres de equipos de The Odds API mapeados con el mismo `team_aliases.yaml`; un equipo sin mapear es error visible, no un descarte silencioso.

### US3 — Comparador por partido (P1)
**Como** apostador **quiero** ver, para cada partido del día, la mejor cuota por resultado, la probabilidad justa y si hay valor **para** decidir rápido.

Criterios de aceptación:
- Lista de partidos por fecha (hoy en `America/Lima` por defecto) con: mejor cuota por resultado y su casa, cuota justa de Pinnacle, EV de la mejor cuota, probabilidad del modelo y bandera "el modelo coincide".
- Detalle de partido: tabla casas × resultados con la mejor cuota resaltada, margen de cada casa y evolución de la cuota de Pinnacle entre snapshots.
- Solo se consideran casas marcadas como **accesibles** en `configs/bookmakers.yaml` para la recomendación (el resto se muestra como referencia). Así la recomendación no apunta a casas donde no se puede apostar desde Perú.

### US4 — Calculadora con cuota manual (P1)
**Como** apostador **quiero** escribir la cuota que veo en una casa peruana **para** saber al instante si tiene valor y cuánto apostar.

Criterios de aceptación:
- Entrada: partido, resultado, casa, cuota. Salida: probabilidad justa (Pinnacle), EV, stake sugerido (Kelly fraccional 25 % con tope de 2 % del bankroll) y veredicto (`valor` / `justo` / `evitar`).
- Botón para registrar la apuesta en el diario directamente desde el resultado.
- Las cuotas manuales se guardan como snapshots de la casa (fuente `manual`).

### US5 — Diario de apuestas y bankroll (P1)
**Como** apostador **quiero** registrar mis apuestas y ver mi rendimiento real **para** saber si voy bien más allá de la suerte.

Criterios de aceptación:
- CRUD de apuestas: partido, resultado, casa, cuota, stake, tipo (`real` / `papel`), estado (`pendiente` / `ganada` / `perdida` / `nula`).
- Liquidación automática con los resultados de football-data (y manual como respaldo).
- CLV automático: comparación con la última cuota de Pinnacle antes del inicio del partido.
- Panel: ROI, beneficio, nº de apuestas, CLV medio, curva de bankroll, rendimiento por liga y por casa, filtro real/papel.
- Mensaje permanente en el panel: con menos de 300 apuestas el ROI es mayormente ruido y el indicador fiable es el CLV.

### US6 — Límites de juego responsable (P1)
**Como** apostador **quiero** que la herramienta me ayude a respetar mis límites **para** no apostar de más.

Criterios de aceptación:
- Configuración de bankroll inicial, presupuesto mensual máximo de pérdida y stake máximo por apuesta.
- Al registrar una apuesta real que supere el stake máximo o haga superar la pérdida mensual, la API responde con advertencia y el frontend pide confirmación explícita. Si el presupuesto mensual ya se superó, se bloquea el registro de apuestas reales hasta el mes siguiente (las de papel siguen permitidas).
- No hay funciones para "recuperar pérdidas" (martingala, subir stakes tras perder).

### US7 — Over/Under 2.5 (P3, opcional)
Misma lógica que US3–US4 para el mercado de totales.

## 4. Requisitos no funcionales

- Misma arquitectura hexagonal y reglas de calidad de la spec 001.
- Persistencia de snapshots y apuestas en **SQLite** (un archivo, con migraciones); los Parquet de la spec 001 se mantienen.
- Frontend: carga inicial < 2 s en local; responsive (usable en el celular).
- Funciona con el plan gratis de The Odds API para uso personal típico (≈ 10 créditos por refresco completo de 5 ligas × 2 regiones).
- La API key de The Odds API vive en `.env`, nunca en el frontend ni en el repo.

## 5. Criterio de éxito

| Nivel | Condición |
|---|---|
| **Mínimo** | Backtest US1 con CLV medio > 0 en validación, y el sistema completo (US2–US6) funcionando de punta a punta. |
| **Bueno** | Lo anterior + en el test 2025-26 la estrategia tiene CLV > 0 y ROI con IC 95 % cuyo límite inferior es > −3 % (pierde poco en el peor caso razonable). |
| **Excelente** | ROI en el test 2025-26 con IC 95 % que no incluye el 0, con ≥ 300 apuestas. |

Fuera del backtest, el éxito real se mide después con el diario: **CLV medio positivo en las primeras 100 apuestas en papel** antes de apostar dinero real (recomendación, no requisito de código).

## 6. Riesgos

| Riesgo | Mitigación |
|---|---|
| La API pública de Pinnacle cerró en julio de 2025 | Se usa la cuota de Pinnacle que publica The Odds API (tomada de su web, con posible retraso). Si deja de estar disponible, se usa Betfair Exchange como referencia. |
| Las casas peruanas no están en The Odds API | Ingreso manual (US4). |
| Las cuotas de las casas europeas pueden no coincidir con las que se ven desde Perú | Por eso la recomendación solo usa casas marcadas como accesibles; el resto es referencia. |
| Créditos del plan gratis agotados | Control de presupuesto (US2) y caché. |
| Backtest optimista porque `max_odds` incluye casas inaccesibles | Se reporta también el escenario de una sola casa (`b365`), más realista. |
| Las casas limitan cuentas ganadoras | Fuera del control del software; se documenta en el informe. |

## 7. Pendientes heredados de la spec 001

- **Verificar el filtro de fecha de `/matches`**: el sábado 26/09/2026 no devolvió partidos de las 5 ligas. Confirmar con el `fixtures.csv` real si es un bug (fechas `dd/mm/yyyy`, zona horaria) antes de reutilizar esa lógica.
- Documentar en el README la decisión de aplicar la regla de parada por separado a modelos con y sin cuotas.

## 8. Enmiendas a la constitución (se agregan en T001)

- **IX. Juego responsable:** el software no incluye funciones que incentiven perseguir pérdidas; los límites de US6 no se pueden desactivar sin editar la configuración a mano.
- **X. Respeto a términos de uso:** no se hace scraping de casas de apuestas sin una spec que lo justifique y revise sus términos. Las APIs se usan dentro de sus límites.
- **XI. Evidencia antes de construir:** ninguna estrategia de apuesta se expone en el frontend sin un backtest que la respalde (puerta de US1).
