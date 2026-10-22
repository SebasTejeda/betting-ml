# Spec 003 — Análisis de partido con mercados y consejos explicados

- **Estado:** aprobada para implementación
- **Dueño:** Sebastián
- **Fecha:** 2026-10-21
- **Depende de:** spec 001 (modelos Dixon-Coles/Poisson, features, datos) y spec 002 (cuotas en vivo, calculadora, diario, límites)
- **Principios:** [`../constitution.md`](../constitution.md) (I–XI) + enmienda XII de §9

## 1. Problema

Hoy la app responde "¿esta cuota tiene valor?" para 1X2. El dueño quiere elegir un partido (por ejemplo, **Real Madrid vs Leipzig**) y ver:

1. Cómo llegan los dos equipos.
2. La probabilidad de **muchos tipos de apuesta**: goles, ambos marcan, goles de un equipo, doble oportunidad, etc.
3. **Consejos explicados**: "Hay alta probabilidad de que Real Madrid marque más de 1.5 goles porque…", siempre diciendo también si la cuota lo paga bien o no.

## 2. Alcance

### Dentro

| Tema | Decisión |
|---|---|
| Competiciones | Las 5 ligas actuales + **Champions League** y **Europa League**. |
| Mercados (P1) | 1X2, doble oportunidad, empate no apuesta, Más/Menos 0.5–4.5 goles, ambos marcan, goles de cada equipo Más/Menos 0.5–2.5, hándicap europeo −1/+1, top 5 marcadores exactos. |
| Mercados (P3, opcional) | Córners y tarjetas totales (solo ligas locales; football-data trae `HC/AC`, `HY/AY`, `HR/AR`). |
| Probabilidades | Salen de la **matriz de marcadores** del modelo de goles (Dixon-Coles de la spec 001, re-ajustado si hace falta). |
| Fuerza entre ligas | Ajuste con ratings **ClubElo** (gratis, comparan clubes de toda Europa) para partidos entre equipos de distintas ligas. |
| Cuotas | The Odds API: endpoint por evento para mercados adicionales (`totals`, `btts`, `team_totals`, `double_chance`, `draw_no_bet`, `spreads`, según los que existan para fútbol). Si no hay cuota, se puede ingresar a mano. |
| Consejos | Texto generado **a partir de datos**, con plantillas: cada razón cita un número real del análisis. |

### Fuera

- Consejos escritos por un LLM (riesgo de inventar datos). Se puede evaluar en una spec futura.
- Mercados de jugadores (goleador, tarjetas a un jugador), faltas, tiros: no hay datos ni cuotas gratuitas confiables.
- Combinadas o "bet builders" (multiplican el margen de la casa; contradice el principio IX).

## 3. Historias de usuario

### US1 — Validación de los mercados derivados (P1, va primero)
**Como** apostador **quiero** saber si las probabilidades de cada mercado son confiables **para** no fiarme de números mal calibrados.

Criterios de aceptación:
- Calibración (log loss / Brier y curva de calibración) de **cada mercado P1** en F1–F3 y luego, una sola vez, en 2025-26 (lock `HOLDOUT_003_USED.lock`), para las ligas locales.
- Más/Menos 2.5: además, backtest de valor con las cuotas históricas de football-data (`B365>2.5`, `Avg>2.5`, `P>2.5`, `PC>2.5` normalizados al esquema canónico), con CLV contra Pinnacle al cierre.
- Champions/Europa League: calibración de 1X2 y Más/Menos 2.5 con resultados históricos de `openfootball/champions-league` (sin cuotas históricas, solo calibración).
- Cada mercado recibe un **nivel de confianza**: `alta` (ECE < 0.02 y mejor que la línea base), `media` (ECE < 0.04), `baja` (resto). Se guarda en `reports/market_calibration.json`.
- **Puerta:** los mercados con confianza `baja` no generan consejos de valor; solo se muestran como información, con aviso.

### US2 — Forma reciente y contexto (P1)
**Como** apostador **quiero** ver cómo llegan los equipos **para** entender el partido.

Criterios de aceptación:
- Por equipo: últimos 6 partidos (rival, competición, resultado, goles, xG si existe), promedios de goles y xG a favor y en contra (general y en condición local/visita), % de partidos con +2.5 goles, % con ambos marcan, % de partidos en que marcó 2 o más, racha actual.
- Enfrentamientos directos de los últimos 5 años (si existen), marcados como **poco predictivos**.
- Rating ClubElo actual de ambos y diferencia.
- Si un dato no existe (por ejemplo, xG en Champions), se indica "sin dato", no se inventa.

### US3 — Tabla de mercados (P1)
**Como** apostador **quiero** ver la probabilidad de cada mercado junto a su cuota **para** comparar.

Criterios de aceptación:
- Por cada selección: probabilidad del modelo, cuota justa (1/p), mejor cuota disponible y casa (si existe), EV y veredicto (`valor` / `justo` / `evitar` / `sin cuota`), y nivel de confianza del mercado.
- Agrupada por mercado; ordenable por probabilidad o por EV.
- Goles esperados de cada equipo (λ local y λ visita) visibles arriba de la tabla.

### US4 — Consejos explicados (P1)
**Como** apostador **quiero** consejos con su porqué **para** decidir con criterio.

Criterios de aceptación:
- Sección **"Mejores opciones"** (hasta 3): selecciones con EV ≥ `min_edge` y confianza `alta` o `media`, ordenadas por EV. Cada una con 2–4 razones basadas en datos, por ejemplo:
  > **Real Madrid más de 1.5 goles — 64 %** · cuota 1.95 · EV +24.8 % · *EXPERIMENTAL — solo papel*
  > - El modelo espera 2.1 goles de Real Madrid en este partido.
  > - Real Madrid marcó 2 o más en 5 de sus últimos 6 partidos de local (promedio 2.4 goles, 2.2 xG).
  > - Leipzig concede 1.7 xG por partido de visita en sus últimos 6.
  > - ⚠️ Partido de Champions: la fuerza entre ligas se ajusta con ClubElo, hay más incertidumbre.
- Sección **"Lo más probable"** (hasta 3): las selecciones con mayor probabilidad, **siempre** con un comentario honesto del precio, por ejemplo: "Muy probable (82 %), pero la cuota 1.15 paga menos de lo justo (1.22): EV −6 %. No conviene."
- Si ninguna selección tiene valor: mensaje explícito "Hoy no hay apuestas con valor en este partido. No apostar también es una decisión."
- Si `EV > 0.15`, el consejo lleva el aviso "EV inusualmente alto: lo más probable es un error del modelo o una cuota desactualizada. Verifica la cuota antes de nada." Los mercados de apuestas rara vez dejan márgenes así.
- Las razones se eligen por reglas deterministas (§7 del plan); cada número mostrado sale del análisis y es trazable en la respuesta de la API (`evidence`).
- Lenguaje prohibido: "segura", "fija", "garantizada", "no falla", o similares. Test automático que lo verifica.
- Todos los consejos de valor llevan la etiqueta **"EXPERIMENTAL — solo papel"** hasta que su mercado cumpla la condición de evidencia (US6).

### US5 — Registrar desde el análisis (P1)
- Cada fila de la tabla y cada consejo tiene "Registrar en papel" (o real, con el flujo de confirmación y límites de la spec 002).
- El diario guarda el mercado, la selección y la línea (por ejemplo, `team_totals / home / over / 1.5`), y la liquidación y el CLV funcionan para los mercados nuevos (CLV solo cuando exista cuota de cierre de referencia).

### US6 — Evidencia por mercado (P2)
- El panel de Mis apuestas muestra el CLV y el n.º de apuestas **por mercado**.
- Un mercado deja de ser "EXPERIMENTAL" solo con ≥ 100 apuestas en papel con CLV medio > 0. Cambio manual en `configs/markets.yaml`, registrado en `decisions.md`.

### US7 — Córners y tarjetas (P3, opcional)
- Modelo de conteo (Poisson o binomial negativa) con features de forma de córners y tarjetas, solo ligas locales, con la misma validación de US1.
- Sin cuotas automáticas: se evalúan con la Calculadora (cuota manual).

## 4. Requisitos no funcionales

- Respuesta del análisis < 2 s con datos en caché (sin contar la llamada a The Odds API).
- Las cuotas por evento se cachean 30 min; refrescar es una acción explícita del usuario con costo visible en créditos.
- Misma arquitectura hexagonal, calidad y CI de las specs anteriores.

## 5. Criterio de éxito

| Nivel | Condición |
|---|---|
| **Mínimo** | Todos los mercados P1 calibrados con nivel asignado; análisis completo funcionando para un partido de liga y uno de Champions. |
| **Bueno** | ≥ 4 mercados con confianza `alta` en el test 2025-26, y Más/Menos 2.5 con CLV medio ≥ 0 en el backtest. |
| **Excelente** | Más/Menos 2.5 con CLV > 0 e IC 95 % del ROI que no incluye el 0 (≥ 300 apuestas) en el test. |

## 6. Riesgos

| Riesgo | Mitigación |
|---|---|
| Partidos entre ligas mal estimados | Ajuste ClubElo + aviso visible + calibración específica en Champions. |
| Los consejos dan una falsa sensación de certeza | Lenguaje prohibido, sección "Lo más probable" con precio honesto, etiquetas EXPERIMENTAL, niveles de confianza. |
| Mercados de The Odds API distintos a los esperados | Verificar los `market keys` reales en T004 y ajustar el catálogo `configs/markets.yaml`. |
| Consumo de créditos por mercados adicionales | Una llamada por evento y región; costo mostrado antes de refrescar; caché. |
| ClubElo o openfootball cambian o caen | Adaptadores detrás de puertos; sin ellos, los partidos entre ligas se muestran sin consejos de valor. |

## 7. Pendientes que se arrastran

- Ninguno bloqueante. Si `configs/markets.yaml` necesita un mercado que The Odds API no ofrece en el plan gratis, se marca `source: manual`.

## 8. Glosario rápido

- **λ (lambda):** goles esperados de un equipo en el partido según el modelo.
- **Matriz de marcadores:** probabilidad de cada resultado exacto (0-0, 1-0, …); sumando celdas sale cualquier mercado de goles.
- **Calibración:** si el modelo dice 60 %, debería pasar cerca del 60 % de las veces.

## 9. Enmienda a la constitución (se agrega en T001)

- **XII. Consejos honestos:** todo consejo muestra su probabilidad, su precio y su porqué con datos verificables; nunca usa lenguaje de certeza; una apuesta probable pero mal pagada se presenta como tal.
