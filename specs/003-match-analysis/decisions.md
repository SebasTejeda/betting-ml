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

## 2026-10-22 — Fuentes europeas: cobertura real de openfootball (T003)
- Contexto: el plan proponía `openfootball/champions-league` o su exportación JSON (`football.json`).
- Decisión: usar los archivos Football.TXT de `openfootball/champions-league` (`{temporada}/cl.txt` y `el.txt`), con un parser propio. La exportación JSON tiene huecos (sin Champions 2020-24 y sin Europa League).
- Motivo: verificado el 2026-10-22: Champions de 2014-15 a 2025-26 completa; Europa League solo de 2020-21 a 2024-25 (no hay `el.txt` de 2025-26). El parser lee el 100 % de los partidos que declara cada archivo (salvo 2 no jugados de la UEL 2021-22).
- Impacto: el test 2025-26 de partidos europeos solo tiene Champions; la Europa League se valida solo en las temporadas de validación.

## 2026-10-22 — Resultado a los 90 minutos en partidos europeos (T003)
- Contexto: las eliminatorias pueden ir a prórroga y penaltis ("4-2 pen. 1-0 a.e.t. (1-0, 1-0)").
- Decisión: guardar el resultado de los 90 minutos (primer par dentro del paréntesis) y marcar `extra_time`.
- Motivo: los mercados de goles se liquidan a los 90 minutos.
- Impacto: los partidos con prórroga cuentan como empate a los 90 minutos para el modelo y la calibración.

## 2026-10-22 — ClubElo: instantánea semanal anterior al partido (T003)
- Contexto: hace falta el rating de cada club antes de cada partido europeo sin pedir un día por partido.
- Decisión: usar la instantánea del lunes anterior o igual al día previo al partido (`domain.ratings.snapshot_date`), cacheada en `data/raw/clubelo/`.
- Motivo: no hay fuga (la instantánea es estrictamente anterior al partido); son unas 25 peticiones por temporada en vez de una por partido.
- Impacto: el rating no incluye partidos jugados entre ese lunes y el partido europeo (por ejemplo, una jornada de liga entre semana); la información tiene como mucho una semana de antigüedad.

## 2026-10-22 — Nombres de clubes europeos (T003)
- Contexto: openfootball usa nombres largos ("Club Atlético de Madrid", "FC Internazionale Milano") y ClubElo nombres cortos; hay cientos de clubes extranjeros.
- Decisión: los clubes de nuestras 5 ligas se resuelven con alias `openfootball` y `clubelo` en `team_aliases.yaml`, y faltar uno es un error. Los clubes extranjeros se emparejan con ClubElo por nombre normalizado dentro de su país, con correcciones manuales en `configs/europe_aliases.yaml`. Los que no se emparejan quedan sin rating, se listan en `reports/europe_data_quality.md` y se excluyen del ajuste entre ligas. Mónaco (MCO en openfootball) cuenta como Francia.
- Motivo: mantener la regla de la spec 001 (nada se descarta en silencio) donde importa (nuestras ligas) sin mantener a mano cientos de alias que solo sirven para calibrar.
- Impacto: algunos partidos europeos entre clubes extranjeros pueden quedar fuera del ajuste; el reporte dice cuáles.

## 2026-10-22 — ClubElo caído durante T003 (pendiente)
- Contexto: el 2026-10-22, `api.clubelo.com` respondió 502 en todos los reintentos (la web sí funciona).
- Decisión: implementar el adaptador con el formato CSV documentado (`Rank,Club,Country,Level,Elo,From,To`), validarlo al descargar y no cachear respuestas inválidas. Seguir reintentando; cuando la API responda, correr `data-europe`, comparar con el formato real y completar los alias `clubelo`. Si el formato difiere, se corrige en un commit `fix(adapters)` aparte.
- Motivo: no bloquear el resto de la spec por una caída temporal de un servicio gratuito.
- Impacto: `europe_matches.parquet` y los alias `clubelo` quedan pendientes hasta que ClubElo vuelva. T006 (ajuste entre ligas) los necesita.

## 2026-10-22 — Cuotas Más/Menos 2.5: nombres canónicos (T004)
- Contexto: la tarea pedía normalizar las cuotas históricas Más/Menos 2.5 al esquema canónico `ou25_*`.
- Decisión: mantener el esquema que ya existía desde la spec 001, `{fuente}_over25` / `{fuente}_under25` (`avg`, `max`, `ps`, `psc`, `avgc`), y agregar las que faltaban: `b365`, `b365c` y `maxc`.
- Motivo: renombrar rompería la spec 001 sin ganar nada; las columnas ya siguen los mismos prefijos que las cuotas 1X2 (los de cierre terminan en `c` y solo se usan para el CLV).
- Impacto: Pinnacle y Bet365 Más/Menos existen desde 2019-20 (≈ 99 % de los partidos), así que cubren F1–F3 y el test 2025-26; el promedio y el máximo existen en todas las temporadas.

## 2026-10-22 — Verificación de los market keys de The Odds API pendiente (T004)
- Contexto: T004 pedía una llamada real a The Odds API para verificar los `market keys` de fútbol, grabar la respuesta como fixture y ajustar `configs/markets.yaml`. En esta máquina no hay `.env` y el dueño no tiene la clave a mano.
- Decisión (del dueño): cerrar T004 sin la llamada. `configs/markets.yaml` queda con las claves esperadas según la documentación de The Odds API (`h2h`, `totals`, `btts`, `team_totals`, `double_chance`, `draw_no_bet`); hándicap europeo y marcador exacto quedan como `manual`.
- Motivo: no bloquear la fase de modelos y validación (T005–T010), que no necesita cuotas en vivo.
- Impacto: la llamada (1 de las 3 permitidas) se hace antes de T014 (adaptador de cuotas por evento), que es la primera tarea que depende de esas claves. Si algún mercado no existe en el plan gratis, se marca `odds_source: manual` y se registra aquí.

## 2026-10-22 — Reglas pre-registradas de la validación de mercados (T007, antes de ver resultados)
- Contexto: US1 pide un nivel de confianza por mercado y un backtest de valor de Más/Menos 2.5; para no ajustar las reglas a los resultados, se fijan antes de correr `validate-markets`.
- Decisión:
  - **Grupo calibrado:** un mercado en una línea (`totals:2.5`), un equipo de `team_totals` en una línea (`team_totals:home:1.5`) o un mercado sin líneas (`h2h`, `btts`, `double_chance`, `draw_no_bet`, `correct_score`). Cada grupo tiene su propio nivel: no tiene sentido que Más de 0.5 (≈ 93 %) y Más de 4.5 compartan nivel.
  - **Métricas:** binarias por selección (cada selección es un evento sí/no), agrupadas dentro del grupo: log loss, Brier y ECE con 10 bins de igual ancho. Empate no apuesta se evalúa solo en partidos decididos, con p = P(gana) / (1 − P(empate)). Marcador exacto: los 5 más probables de cada partido.
  - **Línea base:** frecuencia de cada selección en la misma liga durante las temporadas de entrenamiento del fold, suavizada como (k + 0,5)/(n + 1).
  - **Niveles:** `alta` si ECE < 0.02 y el modelo mejora a la línea base en log loss **y** Brier; `media` si ECE < 0.04; `baja` el resto (spec US1).
  - **Backtest Más/Menos 2.5:** probabilidad del modelo (matriz walk-forward) contra la cuota **pre-cierre** de cada escenario (`b365` realista, `avg` control, `max` mejor precio, no apostable); una apuesta por partido (el lado con mayor EV); umbrales {0, 2, 4, 6, 8, 10 %}; se elige el umbral con mayor CLV medio entre los que tienen ≥ 300 apuestas en F1–F3 (empate → el menor). CLV = cuota × p de Pinnacle al cierre (Shin) − 1; el cierre nunca entra en la decisión. Placebo: CLV de apostar los dos lados de todos los partidos al precio del escenario.
- Motivo: mismas garantías que la spec 002 (umbral elegido en validación, cierre solo para medir, control y placebo).
- Impacto: estos niveles son provisionales (F1–F3); los definitivos salen de la evaluación única de T009.

## 2026-10-22 — T007 adelantada sin la parte europea
- Contexto: ClubElo sigue caído (502) y T006 (ajuste entre ligas) no se puede hacer; el dueño pidió adelantar T007 con las ligas locales.
- Decisión: T007 cubre la calibración de todos los mercados P1 en las 5 ligas y el backtest de Más/Menos 2.5. La calibración de Champions/Europa League se hace al terminar T006.
- Motivo: la calibración de las ligas no depende de ClubElo.
- Impacto: T008 (checkpoint) revisa la parte local; la europea entra en la revisión de T009 o en un checkpoint adicional si cambia algo de fondo.

## 2026-10-22 — Resultado de la validación F1–F3: calibración buena, sin valor en Más/Menos 2.5 (T007)
- Contexto: `validate-markets` en 5 330 partidos de validación (F1–F3).
- Resultado: 14 de 18 grupos con confianza `alta` y 4 `media` (empate no apuesta, Más/Menos 3.5 y 4.5, goles del local Más/Menos 2.5); ninguno `baja`. El backtest de Más/Menos 2.5 es negativo en todos los escenarios: Bet365 umbral 10 % → 1 098 apuestas, ROI −11.7 % [−18.3, −4.8], CLV −4.8 % [−5.2, −4.4], igual al placebo (−4.8 %); el promedio (control) da CLV −5.4 %; el máximo, CLV −1.7 % (placebo −1.5 %). El 73–76 % de las apuestas son "Más": el modelo sobreestima la frecuencia de más de 2.5 goles (55.3 % vs 53.5 %), lo que se ve como "valor" contra la cuota pero el cierre no lo confirma.
- Decisión: los niveles de confianza se usan para mostrar probabilidades con aviso; la señal de valor en Más/Menos 2.5 no tiene evidencia y sigue EXPERIMENTAL — solo papel (principio XI). No se ajusta nada a la vista de estos resultados antes de T009.
- Impacto: el criterio "Bueno" de la spec (Más/Menos 2.5 con CLV medio ≥ 0) no se cumple en validación. La puerta T010 solo mira la confianza, así que se pasaría; los consejos de valor deben dejar clara la falta de evidencia.

## 2026-10-22 — Checkpoint T008: nivel de confianza por selección (cambio posterior a ver resultados, más estricto)
- Contexto: `ml-reviewer` bloqueó T008. La ECE agrupada por grupo mezclaba selecciones complementarias (un "Más" sobreestimado y su "Menos" caen en los mismos bins y sus errores se cancelan) y un umbral absoluto de ECE no ve sesgos relativos grandes en selecciones poco probables (Más de 4.5: p media 0.178 vs frecuencia 0.155, +14 %), que se convierten en EV ficticio.
- Decisión: el nivel se calcula **por selección** (marcador exacto: por rango, top1…top5) y el grupo toma el de su peor selección. `alta`: ECE < 0.02, |sesgo relativo| < 5 % (sesgo = media(p) / frecuencia − 1) y el grupo mejora a la línea base; `media`: ECE < 0.04 y |sesgo relativo| < 10 %; `baja`: el resto. Doble oportunidad se marca `derived_from: h2h` (sus selecciones son complementos binarios de 1X2, no es evidencia independiente). El placebo del backtest se reporta por lado y ponderado con la misma mezcla Más/Menos de las apuestas.
- Motivo: la regla pre-registrada era demasiado laxa. Este cambio se hizo **después** de ver los resultados de F1–F3, pero solo puede bajar niveles (nunca favorece al modelo), y se fija antes de la evaluación única de T009.
- Impacto: de 14 `alta` / 4 `media` / 0 `baja` se pasa a **6 `alta` / 8 `media` / 4 `baja`**. `baja` (solo información, sin consejos de valor): Más/Menos 4.5 (+14.2 %), goles del local Más/Menos 2.5 (+11.8 %), hándicap europeo −1 (+11.0 % en el local) y marcador exacto (top4 −10.3 %). La entrada anterior decía que el CLV de Bet365 era "igual al placebo": con la misma mezcla de lados el placebo es −5.1 % y la estrategia −4.8 % (0.3 pp mejor), que no cambia la conclusión. En b365 y max el umbral elegido es el extremo de la rejilla (10 %); las cifras del umbral elegido son optimistas porque se eligieron con F1–F3.

## 2026-10-22 — Causa del sesgo hacia "Más": λ sigue al xG (T008)
- Contexto: el revisor midió que los goles esperados del modelo superan a los reales (F3: 3.02 vs 2.83; local en F3: 1.69 vs 1.50), lo que explica la sobreestimación de Más de 2.5 y que el 73–76 % de las apuestas del backtest sean "Más".
- Decisión: no se toca el modelo antes de T009. Una recalibración de λ (escala elegida en validación interna, nunca con la temporada de validación del fold) queda como experimento registrado para después de la spec, con su propio test.
- Motivo: E09 se ajusta sobre xG y su ξ se eligió por log loss 1X2, no por totales; corregirlo ahora a la vista de F1–F3 sería ajustar al conjunto de validación sin protocolo.
- Impacto: los niveles `baja` y `media` de los mercados de muchos goles reflejan este sesgo; el frontend debe mostrarlo.

## 2026-10-22 — Regla final de niveles, fijada antes de T009 (checkpoint T008, 2.ª ronda)
- Contexto: en la 2.ª ronda `ml-reviewer` aprobó con observaciones y advirtió que el sesgo relativo es ruido en selecciones poco frecuentes (Menos de 0.5 tiene ≈ 320 casos en F1–F3: error relativo ≈ 5 %; en el test de T009 tendrá ≈ 110). Con la regla anterior, los niveles de las selecciones raras cambiarían por azar en la evaluación única.
- Decisión (regla definitiva para T009):
  - `baja`: ECE ≥ 0.04, o sesgo relativo > 10 % **y** significativo (|z| ≥ 2, con EE = (p̄/f)·√((1 − f)/(n·f))).
  - `alta`: ECE < 0.02, |sesgo relativo| < 5 %, el grupo mejora a la línea base (log loss y Brier agrupados del grupo) y ≥ 400 casos positivos.
  - `media`: el resto, incluido un sesgo grande no significativo ("muestra insuficiente para certificar").
  - El JSON publica `positives`, `rel_bias_se` y `rel_bias_z` por selección.
- Motivo: no premiar ni castigar selecciones por ruido; no se exige que todo el IC quede dentro de ±5 % porque con el test de T009 casi nada llegaría a `alta`.
- Impacto: en F1–F3 los niveles no cambian (6 `alta` / 8 `media` / 4 `baja`); los 4 `baja` son significativos (|z| 2.7–3.9) y estables en las tres temporadas; totals:0.5 sigue `media`, ahora por muestra (z +1.1). La comparación con la línea base es por grupo (agrupada), no por selección: se dirá en el informe de T009.

## 2026-10-22 — Reglas pre-registradas de la evaluación final de mercados (T009, antes de abrir el holdout)
- Contexto: el dueño pidió correr T009 con las ligas locales aunque ClubElo siga caído.
- Decisión:
  - **Alcance:** test 2025-26 de las 5 ligas, una sola vez, con lock `reports/HOLDOUT_003_USED.lock` (guarda el hash de `market_validation_003.json` y de las matrices del test). Los partidos europeos de 2025-26 (`europe_holdout`) se evalúan **aparte**, una sola vez, con su propio lock `reports/HOLDOUT_003_EUROPE_USED.lock`, cuando T006 esté hecha.
  - **Modelo:** el mismo de T005: Dixon-Coles sobre xG, ξ = 0.003 (el que E09 eligió en validación interna en F2 y F3), entrenado con 2014-15…2024-25 y walk-forward sobre 2025-26 con re-ajuste cada 7 días (los partidos del test entran a la historia solo cuando ya se jugaron).
  - **Línea base:** frecuencias por liga de todas las temporadas de entrenamiento (2014-15…2024-25).
  - **Niveles:** misma regla final de T008 calculada en el test. El nivel publicado en `reports/market_calibration.json` (el que lee la API) es el **peor entre validación y test** de cada grupo.
  - **Backtest Más/Menos 2.5:** umbrales fijados en validación (b365 10 %, avg 8 %, max 10 %), sin re-elegir; CLV contra el cierre de Pinnacle; placebo con la misma mezcla de lados.
  - **Nivel de la spec (§5):** `Bueno` si ≥ 4 grupos `alta` en el test **y** CLV medio de Bet365 (escenario principal) ≥ 0; `Excelente` si además CLV > 0 y el IC 95 % del ROI excluye el 0 con ≥ 300 apuestas; si no, `Mínimo` siempre que todos los mercados P1 tengan nivel, con la salvedad de que el análisis de partido (T013) y la parte europea aún no existen.
- Motivo: fijar todo antes de mirar el test, como en las specs 001 y 002.
- Impacto: T010 (puerta) se decide con los niveles publicados.
