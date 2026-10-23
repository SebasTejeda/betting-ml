# Registro de decisiones — Spec 004

> **Numeración.** Se escribió como *spec 003* en la rama `Sebastian`. Al integrarse en la rama `Daniel` (2026-10-22), donde la spec 003 es la de seguridad, pasó a ser la **spec 004**. Su enmienda a la constitución es la **XIII** y su migración, la `0009`. Las menciones a "spec 003" dentro de este documento se conservan como estaban. Los nombres de sus locks y reportes (`HOLDOUT_003_*`, `REPORT_003_*`) no cambian. La integración: [`integration.md`](integration.md).

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

## 2026-10-22 — Puerta T010: pasa en lo formal, sin ningún mercado `alta`
- Contexto: la puerta dice "si ningún mercado P1 tiene confianza `alta` o `media`, detener aquí". Resultado publicado de T009 (ligas locales): 0 `alta`, 9 `media`, 9 `baja`.
- Decisión: la puerta **pasa** (hay 9 grupos `media`: 1X2, doble oportunidad, empate no apuesta, Más/Menos 0.5, ambos marcan, goles del local Más/Menos 0.5 y 1.5, goles del visitante Más/Menos 0.5 y 1.5). La ejecución se **pausa** aquí a la espera del dueño, como pidió al entregar la spec.
- Motivo: la evidencia es débil: ningún mercado llega a `alta` en el test, los mercados de goles (Más/Menos 1.5–4.5, hándicaps, marcador exacto) quedan `baja` por el sesgo del modelo hacia los goles, y el backtest de Más/Menos 2.5 no tiene valor (CLV −5.7 % ≈ placebo).
- Impacto si se sigue con la fase 2: los consejos de "Mejores opciones" solo pueden salir de los 9 grupos `media` y siempre como EXPERIMENTAL — solo papel; los `baja` se muestran como información con aviso. Cambios a considerar antes de T011: (1) recalibrar λ del modelo (escala elegida en validación interna) como experimento registrado; si mejora, solo se podría volver a medir con datos nuevos (2026-27), porque el test 2025-26 ya se usó; (2) dejar la sección "Mejores opciones" desactivada hasta tener evidencia y mostrar solo "Lo más probable" con el precio honesto.

## 2026-10-22 — Elo propio entre ligas en lugar de ClubElo (T006)
- Contexto: `api.clubelo.com` lleva todo el día con 502. Se evaluó API-Football (RapidAPI) como alternativa: no tiene ratings de fuerza (solo resultados, estadísticas, cuotas y "predicciones" opacas), el plan gratis es de 100 peticiones/día y el histórico parece limitado. El dueño decidió calcular un Elo propio sobre openfootball.
- Decisión:
  - **Fuentes:** ligas de nuestras 5 ligas desde football-data (ya canónicas y completas); ligas medianas desde `openfootball/europe` (`{país}/{temporada}_{código}.txt`, mismo formato Football.TXT); Champions y Europa League desde `openfootball/champions-league`. Cobertura verificada el 2026-10-22: Países Bajos y Portugal 2018-19→2026-27 completos; Escocia, Turquía y Grecia 2018-21 y 2023-27; Suiza 2014-15, 2018-21 y 2023-25 y 2026-27; antes de 2018-19 solo nuestras ligas (Austria y Bélgica no están en `openfootball/europe`). La lista de ligas va en `configs/elo_leagues.yaml`.
  - **Método:** un único Elo para todos los clubes, procesado en orden cronológico con los parámetros de la spec 001 (K = 20, ventaja local 60, multiplicador por margen). Entre temporadas, regresión de 1/3 hacia la media **de su liga** (no hacia 1500, para no borrar la diferencia entre ligas). Un club nuevo en una liga entra con la media de esa liga − 50 (ascendido); un club sin liga conocida, 1500. La diferencia entre ligas solo se aprende con partidos europeos, como en ClubElo.
  - **Sin fuga:** el rating de un día `d` es el resultado de procesar solo partidos con fecha < `d`; se publica con el mismo esquema que ClubElo (`club, country, level, elo`) para que `data-europe` y el análisis no cambien. `level` = 1 si el club jugó en primera división de su país esa temporada.
  - **Huecos:** un club cuyo país no tiene liga en una temporada solo se actualiza con partidos europeos; para el ajuste entre ligas (T006) se usan solo partidos europeos en los que ambos clubes tienen al menos 10 partidos con rating en los 365 días previos.
- Motivo: no depender de un servicio caído; `level` y la liga salen del archivo de origen; sin fuga por construcción; método propio que se puede explicar y testear.
- Impacto: menos clubes y temporadas que ClubElo (los ratings de ligas medianas antes de 2018-19 se apoyan solo en partidos europeos). El adaptador de ClubElo se mantiene por si vuelve, pero deja de ser la fuente por defecto.

## 2026-10-22 — Elo propio construido: primeros resultados y límites (T006, parte 1)
- Contexto: `data-europe` corre el Elo propio (≈ 33 000 partidos: 5 ligas, 6 ligas medianas de openfootball, UCL 2014-26 y UEL 2020-25) y construye el dataset europeo: 2 248 partidos de entrenamiento y 189 del test 2025-26, 95.6 % con rating de ambos clubes.
- Hallazgos:
  - **Error corregido del parser:** las fechas sin año se inferían por el mes ("julio o más tarde → primer año"), lo que fechaba en 2019 la fase final de agosto de 2020 de la Champions y los partidos de julio de 2020 de Portugal. Ahora se elige, entre los dos años de la temporada, el que deja la fecha más cerca de la anterior (y el 29 de febrero solo en años bisiestos). Como `europe_matches` no se había construido antes, no afectó a ningún resultado.
  - **Brechas entre ligas comprimidas:** a 2026-10-19, la media de la Premier es 1 485 y la de Países Bajos 1 357 (≈ 130 puntos; ClubElo suele mostrar el doble), y clubes dominantes de ligas medianas (Feyenoord, PSV, Benfica) salen por encima del Real Madrid. Causa: todas las ligas arrancan en 1 500 en 2014 y las medianas entran en 2018; la diferencia entre ligas solo la mueven unos 250–400 partidos europeos por temporada.
  - Clubes de países sin liga en el catálogo (Austria, Bélgica, Dinamarca, etc.) solo tienen rating por partidos europeos; algunos aparecen con dos nombres entre temporadas ("RB Salzburg" / "FC Red Bull Salzburg").
- Decisión: no usar el Elo crudo como si fuera comparable entre ligas. En el ajuste de T006 la fuerza de cada club se descompone en (rating − media de su liga) + desplazamiento de la liga, y el desplazamiento se **estima con los partidos europeos** (como pide el plan §4), validado walk-forward. Mejoras posibles del Elo (K mayor en partidos europeos, arranque más temprano con temporadas anteriores de football-data, prior por coeficiente UEFA) se evalúan solo si la validación de T006 lo justifica.
- Impacto: los partidos entre ligas llevan siempre el aviso de más incertidumbre; con estos límites es probable que la calibración europea quede en `media` o `baja`.

## 2026-10-22 — Ajuste entre ligas: diseño y validación pre-registrados (T006, antes de ver resultados)
- Contexto: el Elo propio comprime las diferencias entre ligas; el plan §4 pide estimar un desplazamiento de fuerza por liga con partidos europeos y validarlo walk-forward.
- Decisión:
  - **Muestra:** partidos de UCL/UEL de `europe_matches` (sin el test 2025-26) en los que ambos clubes son de un país del catálogo `elo_leagues.yaml` (tienen media de liga en la instantánea): ≈ 1 100 partidos. Los partidos con clubes de otros países no entran; en el análisis, un club sin liga en el catálogo da `503 RATINGS_UNAVAILABLE`.
  - **Modelo (Poisson independiente):** fuerza de un club x = a·s/400 + L_país, con s = Elo del club − media Elo de su liga (nivel dentro de su liga) y L_país = κ·(media de su liga − media de todas)/400 + u_país; log λ_local = α + γ + x_local − x_visita y log λ_visita = α + x_visita − x_local. Se estiman α, γ (ventaja de local en Europa, estimada con los datos), a, κ y u_país con penalización ridge sobre u (el desplazamiento propio de cada liga se aprende de los resultados europeos y, sin datos, vuelve al de su media Elo). Matriz de marcadores = producto de dos Poisson (0..10).
  - **Competidores:** M0 = frecuencias de goles del entrenamiento (sin equipos); M1 = Elo crudo (log λ con la diferencia de Elo, sin descomponer). M2 (el anterior) anida a M1 (u = 0, a = κ).
  - **Validación walk-forward por temporada:** para cada temporada de 2018-19 a 2024-25, se entrena con las temporadas europeas anteriores y se predice esa temporada. La penalización ridge se elige en {1, 5, 20, 100} con validación interna (última temporada del entrenamiento), nunca con la temporada evaluada. Métricas: log loss 1X2 y Más/Menos 2.5, Brier, goles esperados vs reales.
  - **Elección:** M2 se usa si su log loss 1X2 medio walk-forward mejora a M1; si no, se usa M1 y se registra.
  - **Calibración europea (pendiente de T007):** 1X2 y Más/Menos 2.5 con las predicciones walk-forward del modelo elegido en 2018-19…2024-25, misma regla de niveles de T008, línea base = frecuencias europeas del entrenamiento. El test 2025-26 (solo UCL) se evalúa una sola vez con `HOLDOUT_003_EUROPE_USED.lock`.
- Motivo: estimar lo que el Elo no capta (la distancia real entre ligas) con los únicos partidos que la revelan, sin tocar el test.
- Impacto: los niveles europeos se publican aparte (`reports/market_validation_003_europe.json`) y se aplican solo a partidos entre ligas o de competiciones europeas.

## 2026-10-22 — Resultado del ajuste entre ligas (T006) y calibración europea (parte europea de T007)
- Contexto: `validate-cross-league` con 1 096 partidos europeos elegibles (clubes de países del catálogo), walk-forward por temporada 2018-19…2024-25 (914 partidos evaluados).
- Resultado:
  - Log loss 1X2 medio: M0 (frecuencias) 1.0595, M1 (Elo crudo) 1.0157, **M2 (Elo descompuesto + desplazamiento por liga) 0.9965**; M2 gana a M1 en 5 de 7 temporadas. Más/Menos 2.5: 0.6892 / 0.6863 / 0.6855. Goles esperados ≈ reales (2.90 vs 2.94 de media).
  - **Elegido: M2** (regla pre-registrada). Modelo final (todas las temporadas de entrenamiento, ridge 20 elegido en validación interna): ventaja de local en Europa γ = 0.26 (≈ +30 % de goles en casa), a = 0.82, κ = 0.70. Desplazamientos por liga: Premier +0.23, LaLiga +0.16, Bundesliga +0.15, Serie A +0.15, Ligue 1 +0.11, Portugal +0.00, Países Bajos −0.01, Escocia −0.14, Turquía −0.15, Grecia −0.23, Suiza −0.26. Corrige justo lo que el Elo comprimía (Suiza tenía una media Elo casi igual a la de Francia).
  - Calibración europea (regla de T008): **Más/Menos 2.5 `alta`** (ECE 0.012, sesgo +1.7 % / −2.0 %, 501/413 casos) y **1X2 `baja`** (local con ECE 0.041, por encima de 0.04 con solo 914 partidos; sesgo −0.2 %).
- Decisión: el análisis de partidos entre ligas usa M2. 1X2 de partidos europeos queda `baja` (solo información, sin consejos de valor); Más/Menos 2.5 europeo, provisionalmente `alta` hasta la evaluación única del test 2025-26 (solo UCL, lock `HOLDOUT_003_EUROPE_USED.lock`), que pide el dueño cuando quiera.
- Impacto: los demás mercados de partidos europeos (doble oportunidad, goles de cada equipo, etc.) no se calibraron por separado; en la interfaz llevan el nivel del peor entre su nivel de liga y el de 1X2 europeo, y el aviso de partido entre ligas.

## 2026-10-22 — Checkpoint europeo, 1.ª ronda: BLOQUEADO por clubes renombrados; correcciones (sustituye los resultados anteriores de T006)
- Contexto: `ml-reviewer` no encontró fuga (prueba empírica: alterar todos los resultados posteriores a una fecha no cambia la instantánea de esa fecha) pero bloqueó: openfootball/europe cambia el nombre de un mismo club entre temporadas ("PSV Eindhoven" → "PSV", "SL Benfica" → "Sport Lisboa e Benfica", "Celtic FC" → "Celtic" en 2026-27…) y el Elo lo reiniciaba como ascendido, con el mismo club con dos ratings (Benfica 1661 y 1409) y medias de liga contaminadas en 2023-24, 2024-25, el modelo final y el test.
- Decisión (correcciones, antes de abrir el test europeo):
  - `configs/europe_league_aliases.yaml`: nombre canónico por país para clubes de ligas medianas (y de países sin liga con dos nombres en Europa, p. ej. Salzburgo), aplicado a archivos de liga y a Champions/Europa League antes del Elo. Guardia en `build_club_elo`: falla si una liga cambia más de 5 clubes entre temporadas consecutivas. Tras los alias, como máximo 3 (ascensos).
  - Elo: la base de cada liga y temporada se fija en su primer partido (sin cascada de −50 en la primera jornada de una liga nueva; tras un hueco sin datos, la base es la media de sus últimos clubes). `level` = clubes de la última temporada de liga de su país (los descendidos salen al empezar la nueva temporada; antes contaban 400 días).
  - Elegibilidad del ajuste entre ligas: se aplica la regla pre-registrada (≥ 10 partidos con rating en los 365 días previos, que no se estaba aplicando) y se agrega, antes de ver el test, que el último partido con rating sea de ≤ 60 días antes (archivos de liga 2025-26 incompletos: Grecia, Escocia, Turquía, sin Suiza).
  - Ridge: rejilla {0.3, 1, 3, 10, 30, 100, 300} y validación interna con las 2 últimas temporadas de entrenamiento (con una sola temporada de 69–196 partidos era ruido).
- Resultado re-corrido (sustituye al de la entrada "Resultado del ajuste entre ligas"): 1 066 partidos elegibles; log loss 1X2 walk-forward M0 1.0593, M1 1.0115, **M2 0.9831** (gana a M1 en 6 de 7 temporadas); Más/Menos 2.5 0.6891 / 0.6865 / 0.6846. Modelo final: γ = 0.26, a = 0.86, κ = 0.88, ridge 0.3; desplazamientos Premier +0.25, LaLiga +0.19, Serie A +0.18, Bundesliga +0.17, Ligue 1 +0.12, Países Bajos +0.01, Portugal −0.01, Suiza −0.20, Escocia −0.20, Turquía −0.25, Grecia −0.27. Niveles europeos: Más/Menos 2.5 `alta` (ECE 0.016, sesgo +2.7 % / −3.2 %), 1X2 `baja` (local ECE 0.040). El ridge elegido sigue variando mucho entre temporadas (300 → 0.3): con estos tamaños la penalización está mal identificada; se reporta así.
- Salvedades para el informe: (1) en Europa, `alta` en Más/Menos 2.5 significa "calibrado pero con poca capacidad de distinguir partidos" (log loss 0.6856 vs 0.6906 de la línea base); (2) los niveles europeos valen para partidos entre clubes de países del catálogo (49 % de los partidos de UCL/UEL; se excluyen los de Bélgica, Austria, Dinamarca, etc.), que es también el dominio en que la API da análisis; (3) `build_club_elo` lee los partidos de liga de 2025-26 y 2026-27 (ya usados en T009) solo para ratings posteriores.

## 2026-10-22 — Checkpoint europeo, 2.ª ronda: regla de los 60 días sobre el último partido de LIGA (resultado final de T006)
- Contexto: `ml-reviewer` confirmó corregidos los renombres y sin fuga (prueba empírica en 3 fechas, alterando y borrando partidos futuros), pero bloqueó porque la regla de "≤ 60 días" medía el último partido de cualquier tipo: un club con el archivo de liga cortado volvía a ser elegible desde su segundo partido europeo, con su componente de liga congelado. Sobre el ridge: no bloquea (M2 gana a M1 con cualquier ridge fijo de 0.3 a 300; las diferencias salen casi todas de 2018-19).
- Decisión: la instantánea guarda `last_league_match` y la elegibilidad exige un partido **de liga** en los 60 días previos (`home/away_days_since_league`). La guardia de renombres compara también a través de huecos, con margen de 3 clubes nuevos por temporada que falta.
- Resultado final (sustituye a los dos anteriores): 1 026 partidos elegibles (la regla excluye 52: 39 de 2021-22, temporada sin archivos de liga de Escocia, Turquía, Grecia y Suiza; 7 de 2022-23; 6 de 2019-20, Ligue 1 cancelada). Log loss 1X2 walk-forward: M0 1.0587, M1 1.0094, **M2 0.9880** (elegido). Más/Menos 2.5: 0.6903 / 0.6882 / 0.6868. Niveles europeos: **1X2 `baja`** (local ECE 0.042) y **Más/Menos 2.5 `media`** (ECE 0.019, sesgos +3.2 % / −3.9 %, pero "Menos de 2.5" ya no llega a 400 casos positivos). Modelo final: ridge 1, κ = 0.94.
- Lectura del modelo para el informe: ridge y κ se compensan (con ridge 300 los desplazamientos `u` casi desaparecen y κ sube a ≈ 2.5): no se debe leer `u_país` por separado; la fuerza de una liga es κ·(media de su liga − centro)/400 + u_país, y lo interpretable son las λ de cada partido. 1X2 europeo queda `baja` por una ECE de 0.042 con sesgo ≈ 0: con ≈ 900 partidos es ruido, pero se aplica la regla.

## 2026-10-22 — Reglas pre-registradas del test europeo 2025-26 (antes de abrir `europe_holdout`)
- Contexto: el dueño pidió correr el test europeo una sola vez tras la confirmación de `ml-reviewer`.
- Decisión:
  - **Alcance:** partidos de `europe_holdout` (Champions 2025-26; no hay Europa League 2025-26 en openfootball) que cumplan la misma elegibilidad del entrenamiento (clubes de países del catálogo, ≥ 10 partidos con rating en 365 días, partido de liga en los 60 días previos). Una sola vez, lock `reports/HOLDOUT_003_EUROPE_USED.lock` con el hash de `market_validation_003_europe.json` y el commit.
  - **Modelos:** M0, M1 y M2 entrenados con **todos** los partidos europeos elegibles de entrenamiento (2014-15…2024-25); M2 con el ridge elegido por validación interna sobre ese conjunto (el mismo procedimiento del modelo final ya publicado). Los ratings de cada partido del test son la instantánea semanal anterior a él (incluyen la liga 2025-26 jugada hasta ese momento).
  - **Métricas:** log loss 1X2 y Más/Menos 2.5, Brier y goles esperados vs reales para M0/M1/M2; M2 se mantiene aunque pierda (no se re-elige con el test; se reporta).
  - **Calibración:** h2h y totals:2.5 con la regla final de T008, línea base = frecuencias europeas de entrenamiento. Nivel publicado en `reports/market_calibration_europe.json` = peor entre validación y test.
- Motivo: misma disciplina que T009 y la spec 002.
- Impacto: con ≈ 100–150 partidos elegibles en el test, ningún nivel puede ser `alta` (exige ≥ 400 casos positivos), así que el nivel publicado será a lo sumo `media`.

## 2026-10-22 — Resultado del test europeo 2025-26 (una sola vez)
- Contexto: `ml-reviewer` aprobó la regla de los 60 días (3.ª ronda) y se corrió `validate-cross-league --final` (lock `HOLDOUT_003_EUROPE_USED.lock`, commit 2d53cae con las reglas pre-registradas).
- Resultado: 113 partidos elegibles de 189 de la Champions 2025-26. Log loss 1X2: frecuencias 1.0306, Elo crudo 0.9439, **ajuste por liga 0.9298** (el mejor también en el test). Más/Menos 2.5: 0.6736 / 0.6707 / 0.6782; la Champions 2025-26 tuvo 3.41 goles por partido frente a 2.94 esperados, y el ajuste por liga no mejora a la línea base en ese mercado. Niveles en el test: 1X2 `baja` y Más/Menos 2.5 `baja` (ECE de 10 bins > 0.04 en todas las selecciones con solo 113 partidos; ningún sesgo significativo, |z| ≤ 1.2). **Publicados: 1X2 `baja`, Más/Menos 2.5 `baja`.**
- Decisión: los partidos entre ligas se analizan con el ajuste por liga (mejora clara en 1X2 en validación y test), pero **sin consejos de valor**: todos sus mercados se muestran como información, con el aviso de partido entre ligas. El informe `REPORT_003_europe.md` se corrigió a mano en la sección "Cómo leerlo" porque el texto generado describía la validación.
- Impacto: para T013 en adelante, `market_calibration_europe.json` manda para partidos entre ligas o de competiciones europeas: ningún consejo de "Mejores opciones" en esos partidos; "Lo más probable" sí, con el precio honesto.

## 2026-10-22 — Fase 2 sin "Mejores opciones" (decisión del dueño tras T010)
- Contexto: la puerta T010 pasó en lo formal (9 grupos `media` en ligas, 0 `alta`), Más/Menos 2.5 no tiene valor en el backtest y los partidos entre ligas quedaron `baja`.
- Decisión: seguir con T011 en adelante con la sección **"Mejores opciones" desactivada** hasta tener evidencia (`configs/advice.yaml: best_options.enabled: false`): la API devuelve `best_options: []` y un `best_options_note` que explica por qué. Se muestra **"Lo más probable"** con su comentario honesto de precio y la tabla completa de mercados; los mercados `baja` se marcan como "solo información". El motor de razones (US4) se implementa y se prueba igual, para poder activarlo editando la configuración cuando haya evidencia (≥ 100 apuestas en papel con CLV > 0 por mercado, US6), registrándolo aquí.
- Motivo: principio XI (evidencia antes de construir) y XII (consejos honestos): no se presentan como "mejores" selecciones cuyo valor no está demostrado.
- Impacto: el contrato de la API se mantiene (el campo `best_options` existe, vacío) más `best_options_note`; el veredicto `valor` sigue apareciendo en la tabla de mercados como dato, con la etiqueta EXPERIMENTAL — solo papel.

## 2026-10-22 — Forma reciente: fuentes y límite de la temporada actual (T011)
- Decisión: la forma (US2) une partidos de liga (football-data + Understat, con xG) y de UCL/UEL (openfootball, sin xG); todo con fecha estrictamente anterior al partido. Con menos de 4 partidos en la condición (local/visita) se usan todos y se avisa; el xG que falta se marca "sin dato".
- Límite: openfootball aún no publica la Champions/Europa League 2026-27, así que la forma de la temporada actual solo incluye partidos de liga; el análisis lo avisará (T013).

## 2026-10-22 — Motor de consejos: detalles de diseño (T012)
- "Lo más probable": hasta 3 selecciones, una por mercado (para no repetir variantes de lo mismo), sin las triviales (p > 95 %) y **sin mercados `baja`** (se ven en la tabla como información). Cada una lleva su comentario honesto de precio y, además de lo que pide el contrato, sus razones con evidencia (campo extra `reasons`).
- Razones: reglas de `configs/advice.yaml`; una regla no se activa si falta alguno de los números que su texto necesita ("sin dato" no se inventa). Hasta 4 razones: primero a favor, se reserva un lugar para una en contra si existe, y el aviso de partido entre ligas al final. Trazabilidad: cada razón guarda en `evidence` exactamente los valores de su plantilla (test: volver a generar el texto desde la evidencia da el mismo texto).
- Lenguaje: lista de palabras prohibidas validada al cargar `advice.yaml` y aplicada a todos los textos generados.

## 2026-10-22 — Análisis de partido: modelo, confianza y cuotas (T013)
- Modelo: dos clubes de la misma liga de las nuestras fuera de competición europea → Dixon-Coles sobre xG (T005); cualquier otro caso (ligas distintas, ligas medianas, UCL/UEL) → ajuste entre ligas (T006) con la instantánea del lunes previo.
- Confianza por selección: grupo de calibración de ligas (`market_calibration.json`); en partidos entre ligas o europeos, el peor entre el nivel de liga y el europeo (Más/Menos 2.5 y 1X2 calibrados; el resto toma el de 1X2 europeo). Con los niveles publicados, todo partido entre ligas queda `baja`: el análisis muestra la tabla como información y "Lo más probable" vacío con aviso. El nivel de un mercado completo es el peor de sus selecciones; la interfaz usa el de cada selección.
- Cuotas: por ahora solo 1X2 (mejor cuota accesible del comparador de la spec 002); el resto de mercados, con la cuota por evento de T014. Sin cuota: cuota justa y veredicto `sin_cuota`.
- Forma: también incluye los partidos de liga de las ligas medianas (openfootball, ya usados por el Elo), así un club como el Benfica tiene su forma de liga.

## 2026-10-22 — Cuotas por evento sin verificar contra la API real (T014)
- Contexto: T014 pedía hacer antes la llamada pendiente de T004 (market keys reales); sigue sin haber `ODDS_API_KEY` en esta máquina.
- Decisión: se implementa el adaptador con el formato documentado de la v4 (`/sports/{sport}/events` gratis y `/sports/{sport}/events/{id}/odds` con los mercados del catálogo; coste = mercados × regiones), el parser (Over/Under con `point`, goles de equipo con `description`, ambos marcan Yes/No, doble oportunidad por nombres, empate no apuesta), la caché de 30 min en `data/cache/event_odds/` (sin la clave) y la reserva de créditos de la spec 002. Los tests usan `tests/fixtures/the_odds_api/event_odds_SYNTHETIC.json`, construido a mano y marcado como sintético.
- Pendiente (antes de usarlo de verdad): con la clave, hacer la llamada de T004 (eventos de una liga + una petición por evento = 1 de las 3 permitidas), grabar la respuesta real como fixture, comparar el formato (sobre todo los nombres de doble oportunidad y la clave del sport de la Europa League) y ajustar `markets.yaml` (`odds_source: manual` para lo que no exista en el plan gratis).
- Impacto: sin clave, el refresco devuelve error de configuración (503 en la API) y el análisis usa el 1X2 del comparador o solo cuotas justas.

## 2026-10-22 — Apuestas en cualquier mercado y liquidación por marcador (T015)
- Decisión: `Bet` gana `market`, `selection` y `line` (migración 0004; `outcome` pasa a ser opcional y sigue siendo el campo de 1X2, así las apuestas de la spec 002 no cambian). La liquidación usa `domain.markets.settle` con el marcador oficial a 90 minutos de football-data (empate no apuesta → nula si hay empate; hándicap europeo de tres vías). EV y probabilidad justa de referencia solo existen en 1X2 (Pinnacle/Betfair); el resto de mercados se registra con `no_reference` y un aviso. CLV: 1X2 como en la spec 002 y Más/Menos 2.5 de ligas con el cierre de Pinnacle de football-data (`psc_over25/under25`, Shin); los demás mercados quedan sin CLV.
- Límite: las apuestas de partidos europeos no se liquidan solas (football-data solo trae ligas); se liquidan a mano y cuentan para los límites de US6 como cualquier pendiente vencida.
- Los límites de juego responsable de la spec 002 no cambian: el registro pasa por el mismo `check` (403/409) sin importar el mercado.

## 2026-10-22 — Checkpoint T017, 1.ª ronda: BLOQUEADO; correcciones
- Contexto: `ml-reviewer` confirmó sin fuga en forma ni matriz, límites de US6 intactos en los mercados nuevos y "Mejores opciones" imposible de activar desde la API, pero bloqueó por dos puntos.
- Bloqueante 1 (principio XII): 8 reglas escribían "de local"/"de visita" fijo aunque, con menos de 4 partidos en esa condición, los números salen de todos los partidos. Corregido: todas usan `{home,away,team,opp}_venue_text` (vacío en el respaldo, y queda en `evidence`); al cargar `advice.yaml` se rechaza cualquier regla con la condición fija o con una métrica/campo que no existe (un error de tipeo ya no apaga una regla en silencio). Test que recorre las reglas con `fallback_to_all`.
- Bloqueante 2: en 2026-27 football-data no trae cierre de Pinnacle (0 %); el CLV de Más/Menos 2.5 nunca se calcularía y US6 sería imposible. Decisión: CLV de Más/Menos 2.5 con el cierre de Pinnacle si existe y, si no, con el **cierre promedio del mercado** (`avgc_over25/under25`, Shin), con `clv_source = "football_data_avgc"`: es una referencia más débil que Pinnacle y se distingue siempre en los datos. Los demás mercados siguen sin CLV (no hay cierre histórico de referencia), así que solo Más/Menos 2.5 puede llegar a cumplir la condición de US6 por ahora; el aviso al registrar y la nota de "Mejores opciones" lo dicen.
- Observaciones aplicadas: `match_id` validado antes de tocar la caché (no puede leer ni escribir fuera de `data/cache/event_odds`); el refresco exige que `home`/`away` correspondan al `match_id` (422 `MATCH_TEAMS_MISMATCH`); los créditos restantes usan el valor más reciente, no el mínimo histórico; aviso si las cuotas por evento tienen más de 6 h; aviso si la forma tiene más de 30 días; aviso en partidos entre ligas fuera del dominio validado (< 10 partidos en el año o > 60 días sin partido de liga, misma regla que T006); el "empate" del hándicap europeo ya no usa las reglas de empate; `POST /bets` en 1X2 rechaza `selection`/`line` (422); la CLI escribe en UTF-8; test de 409 con un mercado no 1X2.
- Observaciones registradas sin cambio: dos refrescos simultáneos del mismo evento podrían gastar dos veces (uso de una sola persona; se revisará si hace falta un lock); los 5xx de The Odds API se reintentan 3 veces como en la spec 002; la evidencia guarda valores sin redondear y el texto los muestra redondeados (`render(plantilla, evidencia) == texto`); con `--date` en el pasado el análisis entre ligas usa parámetros ajustados con datos posteriores: no sirve para evaluar.

## 2026-10-22 — Checkpoint T017, 2.ª ronda: APROBADO CON OBSERVACIONES
- Aplicado: `GET /analysis` con `match_id` también exige que `home`/`away` correspondan (422 `MATCH_TEAMS_MISMATCH`), para no calcular EV con cuotas en caché de otro partido.
- Registrado: los créditos de The Odds API se reinician en la fecha de suscripción, no el día 1; `_remaining()` compara por mes calendario, así que tras un reinicio a mitad de mes un valor bajo anterior podría bloquear (429) hasta fin de mes: falla del lado seguro. El aviso de cuotas viejas usa la hora real del servidor. T020 debe separar el CLV contra Pinnacle del CLV contra el cierre promedio.

## 2026-10-22 — Auditoría final T024: APROBADO CON OBSERVACIONES (sin bloqueantes)
- Aplicado: el router `analysis` ya no importa de `ml`; `MissingHistoryError` se reexporta desde `application.analyze_match`.
- Registrado sin cambio: el aviso de cuotas por evento viejas (> 6 h) se arma en el router; es texto de presentación y queda ahí por simplicidad (mover a `application` si crece).
- Registrado sin cambio: si no se conoce el saldo de créditos (sin snapshot ni caché con saldo), el primer refresco por evento no comprueba la reserva mínima. El daño máximo es una llamada (~12 créditos) y el saldo queda conocido desde esa respuesta.
- Registrado: `container.py` con 68 % de cobertura (cableado, ejercitado por los tests de integración); 2 avisos de lint en componentes shadcn (`react-refresh/only-export-components`); cuotas por evento pendientes de verificar con una respuesta real.

## 2026-10-22 — Verificación final T025
- Sin `ODDS_API_KEY` ni `APP_API_KEY`: no se gastaron créditos (0 de 3) y el registro en papel devolvió `503 WRITES_DISABLED`. Ambas comprobaciones quedan para cuando el dueño configure las claves.
- El archivo de fixtures de football-data solo traía un partido de las 5 ligas (Levante–Ath Bilbao, 21/10); se usó ese y un Champions hipotético SL Benfica–Real Madrid (04/11) para el análisis entre ligas.
- Los clubes europeos se buscan por su nombre de openfootball ("SL Benfica"); el autocompletado lo sugiere, pero "Benfica" a secas da 404. Mejora futura: alias cortos en `configs/europe_aliases.yaml`.

---

# Integración en la rama `Daniel` (plan: [`integration.md`](integration.md))

## 2026-10-22 — I01: fusión de `origin/Sebastian` (`a52439e`) en `Daniel`
- Contexto: `git merge --no-ff` conserva los 30 commits de la rama. Hubo 18 conflictos de texto y uno que git no detecta: dos migraciones `0004`.
- **Resolución de los conflictos.** Se conservan las dos partes en todos los casos.
  - **`journal.py`.** Se borró en `Daniel` (T004 lo dividió por recurso). Sus cambios se portan:
    - `market`, `selection` y `line` en `api/mappers/journal.py` (`new_bet`, `bet_out`, `summary_out` con `by_market`);
    - la regla "1X2 usa `outcome`, el resto `selection`" pasa a un validador de `BetIn`, así un error da 422 sin eco de los valores.
  - **`settle_bets`.** Se combina nuestro guardado condicional y auditado (`_save` con `BET_SETTLED`/`BET_CLV` y `actor`) con su liquidación por mercado (`status_for_score`) y su CLV por mercado (`_bet_clv`).
  - **Repositorio.** `_values` (el repositorio controla `id` y `version`) con sus tres columnas nuevas.
  - **Contenedor y configuración.** Los dos bloques. `ApiServices.analysis` queda junto a los controles de seguridad.
  - **Frontend.**
    - La ruta `/analysis` va dentro de `RequireAuth`, como todas las páginas.
    - `BetsPage.test.tsx` conserva los tests de las dos ramas.
    - `market` pasa a ser la lista cerrada `BetMarket` en lugar de `string`.
- **Rutas de análisis con nuestro modelo de acceso.** `analysis.py` se divide:
  - `reads` (sesión o `X-API-Key`): búsqueda, partido, análisis, estimación y calibración;
  - `writes` (sesión con CSRF, o `X-API-Key`): el refresco por evento.

  Además:
  - Se sustituye su `require_app_key`, que importaba del `journal.py` borrado. `test_route_access` recorre todas las rutas y las seis nuevas quedan clasificadas.
  - El contenedor deja de ser `Any`: `AnalysisApi` (protocolo tipado) y `get_analysis`.
  - `/markets/calibration` ya no lee archivos en el router (H-21). Lo hace un caso de uso nuevo, `ReadMarketCalibration`, sobre el puerto `ReportStore`, igual que el backtest.
  - Se descarta su `LOCALHOST_ORIGINS`: el CORS sigue siendo la lista explícita `CORS_ORIGINS` de la spec 003.
- **Migración `0004_bet_market_selection` → `0009`.** Ahora revisa la `0008`. Tres cambios sobre la original:
  - **Sellado del cambio de esquema.** El estado auditado de una apuesta es la fila entera, así que añadir columnas hacía que `verify-integrity` diera por alteradas todas las apuestas existentes; lo detectó el test de la 0007. Ahora cada apuesta recibe un evento `SCHEMA_MIGRATED` con su fila antes y después.
  - **Sin blanqueo.** El test de la 0007 mostró que sellar sin comprobar convertía en válida una apuesta manipulada por fuera de la API. Antes de sellar, la migración verifica la cadena y que cada apuesta coincida con su último evento. Si no coinciden, aborta, lista lo que falla y no cambia nada. Con la auditoría vacía (cadena sin usar) no sella.
  - **Downgrade sin pérdida de datos.** El suyo borraba las columnas aunque hubiera apuestas de otros mercados. Ahora aborta en ese caso.
  - El modelo declara `server_default="h2h"`, igual que la migración. Los `CHECK` de las columnas nuevas quedan para I02.
  - Tests nuevos:
    - sellado y verificación en verde;
    - una apuesta manipulada aborta la migración sin cambiar nada (mutación comprobada: sin la guarda fallan 3 tests);
    - una cadena rota no se extiende;
    - el downgrade conserva las apuestas de otros mercados.
- **Regla H-18 (sin `assert` en tiempo de ejecución).** `ruff S` encontró 8 `assert` en su código (`openfootball`, `analyze_match`, `domain/journal`, `domain/markets`, `calibration_markets`). Pasan a errores explícitos (`OpenFootballFormatError`, `InvalidSelectionError`, `ValueError`, `RuntimeError`).
- **Contrato.**
  - `market` es una lista cerrada (`MarketName`) en las entradas y en las salidas: `BetIn`, `BetOut`, `MarketSummaryOut`, `MarketOut` y `AdviceItemOut`.
  - `selection` tiene un patrón cerrado y `line` un rango (el endurecimiento completo va en I03).
  - Se regeneraron `openapi.json` y `schema.d.ts`.
- **Postman.**
  - Su carpeta se llama ahora "Spec 004 — Análisis de partido".
  - Sus peticiones llevan `X-API-Key = {{appApiKey}}`.
  - "POST refrescar sin clave" exige 401: sin credenciales nunca puede llegar a gastar créditos.
- **Fuera de la fusión.** `.claude/launch.json` (ruta personal de su máquina) y el espacio final de `ODDS_API_KEY= ` en `.env.example`.
- **Renumeración.**
  - Su spec pasa a `specs/004-match-analysis/` con una nota de numeración en cada documento.
  - Su enmienda a la constitución pasa a ser la XIII.
  - Sus locks y reportes conservan el nombre (`HOLDOUT_003_*`, `REPORT_003_*`), porque el código los busca así.
  - Sus pruebas únicas **no** se volvieron a ejecutar.
- Resultado: 1198 tests de backend (cobertura 97,9 %) y 72 de frontend, con lint, mypy, typecheck y build en verde.

## 2026-10-22 — I02: integridad de los mercados nuevos en la base
- **Migración nueva `0010` en lugar de editar la `0009`.** La `0009` ya está commiteada en la fusión y puede estar aplicada en una base. Editarla dejaría esas bases sin las restricciones y sin forma de saberlo.
- **Cuatro `CHECK` sobre `bets`**, copia congelada en la migración y en `adapters/sql/models.py`. Un test compara los dos esquemas: ahora son 36 restricciones.
  - `ck_bets_market`: el mercado está en el catálogo de `domain/markets.py`, el mismo de `MarketName` en la API.
  - `ck_bets_outcome_market`: hay `outcome` si y solo si es una apuesta 1X2.
  - `ck_bets_selection`: las selecciones de cada mercado. 1X2 no lleva selección. Un marcador exacto lleva uno o dos dígitos por equipo, el mismo patrón que `BetIn`.
  - `ck_bets_line`: medias líneas de goles (0,5 … 9,5) en `totals` y `team_totals`, líneas enteras (−10 … 10) en el hándicap europeo y ninguna línea en el resto.
- **Cambio respecto al plan.** El plan decía "pasos de 0,25". El dominio solo acepta medias líneas en goles (`validate_selection`) y líneas enteras en el hándicap europeo, sin líneas asiáticas. El `CHECK` sigue al dominio, que es más estricto: una línea de 2,25 sería una apuesta que el sistema no sabe liquidar.
- **Trampa de `NULL` en SQLite.** Un `CHECK` cuya condición da `NULL` se cumple. Por eso cada rama usa `coalesce` o `IS NOT NULL`. Los tests de mutación lo confirman: quitar cualquiera de esas guardas hace fallar un test de comportamiento, no solo la comparación de esquemas.
- **La migración valida antes de alterar**, con el mismo patrón que la `0005`:
  - Si alguna apuesta incumple, aborta y lista solo `rowid` y restricción, nunca valores. No cambia nada.
  - No borra ni corrige datos. Los valores de las filas no cambian, así que no hace falta sellar nada en la auditoría.
  - Su downgrade solo quita sus cuatro restricciones.
  - Mutación comprobada: sin la validación previa, la reconstrucción falla con un `IntegrityError` en lugar del mensaje que lista los `rowid`.
- **Auditoría.** `market`, `selection` y `line` ya formaban parte del estado auditado, porque es la fila entera. Hay un test nuevo de manipulación directa: cambios por SQL que los `CHECK` permiten (otra línea, otra selección, otro mercado válido) los sigue detectando `verify-integrity`.
- **Test de concordancia.** Toda selección que acepta el dominio (`SELECTIONS`, `LINE_MARKETS`) se inserta sin error. Así la base y el dominio no pueden separarse sin que falle un test.
- **Nota.** `_parse_score` del dominio es más permisivo que la API (acepta `"100-0"`). No se toca: la API y la base cierran ese camino.

## 2026-10-22 — I03: API del análisis endurecida
- **Parámetros con los tipos de `api/validation.py`**, como el resto de la API:
  - `TeamQuery` (nuevo) para `q`, `home` y `away`;
  - `MatchId` en la consulta y en la ruta;
  - `LeagueCode` para `competition` y `ApiDate` para `date`;
  - `Kickoff` (nuevo, ISO 8601) para `kickoff`.

  Los patrones son algo más amplios que el catálogo: un equipo bien formado pero desconocido sigue llegando al caso de uso y da su `404`.
- **Trampa de FastAPI encontrada.** Con FastAPI 0.141, `home: TeamQuery = Query()` descarta en silencio las restricciones del tipo `Annotated`: `q=m` daba 200. `home: TeamQuery`, sin `Query()`, las conserva. Para que no vuelva a pasar en ninguna ruta, un test nuevo (`test_every_string_parameter_is_bounded`) recorre el OpenAPI y exige a cada texto de consulta o de ruta un patrón (o lista cerrada) y una longitud máxima. Reintroducir la trampa hace fallar ese test, que señala la ruta.
- **422 sin eco.**
  - El `match_id` con una fecha que no existe en el calendario usa `invalid_parameter`, un ayudante nuevo con el mismo formato que los errores de validación. También lo usa ya `ordered_period`.
  - `MATCH_TEAMS_MISMATCH` deja de devolver el `match_id` en `details`.
  - `NO_HISTORY` y `InvalidMatchIdError` dejan de devolver `str(exc)`, porque su texto podía llevar la competición o el `match_id` recibidos.
  - El `404 TEAM_NOT_FOUND` conserva el nombre buscado. Es el mismo criterio que el `TEAM_NOT_FOUND` de la spec 001, y el nombre ya pasó el patrón (sin control ni `<>`). El frontend lo muestra en su mensaje.
- **Sin `Any`.** El ayudante `_call(fn, *args: Any)` pasa a ser un gestor de contexto (`_domain_errors`). Las llamadas a los casos de uso quedan tipadas de punta a punta. `AnalysisApi` ya era un protocolo tipado desde I01.
- **Parámetros desconocidos en la consulta.** No hay cuerpos de entrada en estas rutas, así que `extra="forbid"` no aplica. Un parámetro de consulta desconocido se ignora, igual que en el resto de la API desde la spec 003, y no se cambia ese criterio solo para estas rutas.
- **Tests negativos.**
  - Las rutas nuevas ya estaban en la cobertura genérica de `test_route_access` (sin credenciales, clave errónea, cookie falsificada y sesión sin CSRF). Un test fija además su clasificación (cinco lecturas y una escritura).
  - En `test_api_003.py`: entrada inválida de cada ruta sin eco, refresco que valida antes de gastar créditos y `413` con cuerpo grande sin gastar créditos.
  - Mutaciones comprobadas: volver a cada eco, a `str` en la ruta o a `= Query()` hace fallar un test.

## 2026-10-22 — I04: créditos de The Odds API en el refresco por evento
- **Acceso.** El refresco ya exigía sesión con CSRF o `X-API-Key` desde I01: es una escritura y `test_route_access` lo cubre.
- **Un solo cupo para toda la API.** El refresco por evento usa el mismo `RateLimits.take_odds_refresh` que `POST /odds/refresh`. `ODDS_REFRESH_MAX_PER_HOUR` limita todas las llamadas con coste, vengan de donde vengan.
- **El cupo se toma justo antes de gastar, no en la entrada de la ruta.** Es una diferencia con `POST /odds/refresh`, que lo toma como dependencia. El refresco por evento tiene una caché de 30 minutos, y descontar antes castigaría volver a pulsar sin gastar nada. El servicio recibe `quota` como parámetro y lo llama:
  - después de la caché;
  - después de la reserva de créditos (`ODDS_BUDGET_LOW`);
  - después de la búsqueda del evento, que es gratis;
  - y justo antes de `event_odds`.

  Sin cupo, `RateLimitedError` da el `429 RATE_LIMITED` de siempre, con `Retry-After`. No se gasta ningún crédito ni se escribe la caché.
- **Evento de seguridad `ODDS_REFRESH`.** Lo deja el servicio, como `SETTINGS_CHANGED` en `manage_bets`, con `actor`, `scope=event`, `match_id`, créditos usados y restantes, y `from_cache`. Esta ruta no cambia nada en la base, así que no hay evento en `audit_log`. El refresco de la spec 002 sí lo tiene (`ODDS_REFRESHED`), porque guarda un snapshot.
- **Clave.**
  - La caché guarda la respuesta cruda del evento. Como defensa adicional, el adaptador redacta su clave en el cuerpo de cada respuesta antes de interpretarla (`_json`). Si la API la repitiera, no llegaría a la caché.
  - Los errores ya la redactaban (`_redact`) y los logs también (`Redactor`).
  - Un test de extremo a extremo usa el cliente real contra una API falsa que repite la clave en un 401 y en el cuerpo de un evento. Comprueba que no aparece en la respuesta de error, en la caché ni en el log escrito.
- Mutaciones comprobadas: quitar el cupo, tomarlo antes de la caché, quitar la redacción del cuerpo, bajar el evento a DEBUG o no pasar el cupo desde la ruta hace fallar algún test.

## 2026-10-22 — I05: juego responsable en todos los mercados
- **Los límites no dependen del mercado.** `check_bet`, `monthly_loss` y `overdue_pending` miran el tipo, el estado, el stake y el beneficio, nunca `market`, `selection` ni `line`. Una apuesta real de cualquier mercado pasa por:
  - la pérdida mensual: bloqueo, que `confirm` no levanta;
  - el stake máximo: aviso con `confirm`;
  - las pendientes de partidos terminados, que cuentan como perdidas.

  Los tests nuevos (`test_responsible_markets.py`) lo fijan para los ocho mercados. Las apuestas en papel nunca se bloquean.
- **Hueco corregido: la evidencia de la señal experimental se mezclaba entre mercados.** `signal_progress` contaba las apuestas en papel de todos los mercados. Con 100 apuestas de 1X2 con CLV positivo, una apuesta real de `totals` marcada como señal experimental pasaba sin el aviso `EXPERIMENTAL_SIGNAL_UNPROVEN`. Eso contradice la US6 de esta spec: "un mercado deja de ser EXPERIMENTAL solo con ≥ 100 apuestas en papel con CLV medio > 0".
  - Ahora `signal_progress(bets, market)` cuenta solo el mercado de la apuesta.
  - El resumen general (`/bets/summary`) sigue contando todo. Las apuestas sin referencia (todas las de los mercados nuevos por ahora) quedan fuera de la señal, como antes.
  - Mutación comprobada: volver a la cuenta mezclada hace fallar el test.
- **Liquidaciones auditadas.** La liquidación automática de los mercados nuevos usa el guardado condicional y auditado (`BET_SETTLED`, con el `actor` de quien la lanza) desde I01. El test comprueba los eventos, que la cadena verifica y que la pérdida cuenta en el límite mensual. Mutación comprobada: una `monthly_loss` que ignore los mercados nuevos hace fallar el test.
- No hay cambios en la API ni en el frontend: el registro y la liquidación ya pasaban por `ManageBets` y `SettleBets`.

## 2026-10-22 — I06: frontend y contrato
- **La página Análisis ya estaba bajo la sesión desde I01.** La ruta va dentro de `RequireAuth`, y todos sus hooks usan el cliente común (`api/client.ts`), que:
  - añade `X-CSRF-Token` a las escrituras;
  - avisa a la sesión ante un 401, y eso lleva al login con "Tu sesión expiró";
  - renueva el token ante un `CSRF_FAILED`.

  No hay `fetch` propio, ni secretos en `localStorage` o `sessionStorage` (allí solo se guarda el tema).
- **CSP.** La página no carga nada externo ni ejecuta scripts inline. Sus `style={{…}}` se aplican por CSSOM, como ya hacía `MatchPage`, y la política de `security-headers.ts` y del `Caddyfile` los admite. La prueba en el navegador con el build real queda para I08, al actualizar el despliegue local.
- **Tests nuevos en `AnalysisPage.test.tsx`.**
  - Un 401 en el análisis lleva al login.
  - El refresco y el registro llevan el token CSRF de la sesión, que no queda en el almacenamiento del navegador. Mutación comprobada: si el cliente deja de enviar el token, el test falla.
  - Un `429 RATE_LIMITED` del cupo por hora (I04) se muestra con su mensaje.
- **Contrato.** Se regeneraron `openapi.json` y `schema.d.ts`: sin cambios desde I03, porque I04 y I05 no tocaron el contrato.
- **Postman.**
  - La carpeta de análisis ya usaba `{{appApiKey}}` desde I01.
  - El refresco con clave deja de aceptar un 401 como respuesta válida, y un 429 debe ser `RATE_LIMITED` u `ODDS_BUDGET_LOW`.
  - Petición nueva: "match_id inválido (422 sin eco)".

## 2026-10-22 — I07: fuentes externas acotadas
- **Cobertura aplazada de la auditoría T021, ya cerrada.** La auditoría de la spec 003 dejó pendiente que `adapters/http.py` no limitaba bytes. Ahora toda descarga por `HttpClient` (ClubElo, openfootball, football-data, fixtures y Understat) lleva:
  - el `timeout` por operación de red que ya tenía;
  - lectura en streaming con un plazo total (`deadline_seconds`, 120 s);
  - un límite de tamaño (`max_bytes`, 20 MB). Hoy el mayor archivo es una temporada de Understat, de unos 0,6 MB. Una `Content-Length` declarada por encima del límite se rechaza antes de leer.

  Superar un límite no se reintenta (`DownloadTooLargeError`, o `DownloadError` por el plazo).
- **`HttpClient.get` devuelve `Download(url, content)`** en lugar de la respuesta de `requests`, porque una respuesta leída en streaming ya no ofrece `.content`. Los adaptadores solo usaban `.content`, así que no cambian. Los dobles de los tests heredan `tests/http_fakes.StreamedBody`.
- **The Odds API**, con el mismo criterio: 5 MB y 60 s por respuesta, leyendo con `httpx.stream`.
  - El cuerpo se cuenta ya descomprimido, así que una bomba gzip también se corta.
  - Al reconstruir la respuesta se quitan `content-encoding` y las cabeceras de longitud, para que httpx no la descomprima dos veces. Lo vigila un test con gzip; la mutación que conserva la cabecera lo hace fallar.
  - El error es un `502 ODDS_API_ERROR` que nombra la ruta, nunca la URL con la clave.
- **Nada ilegible en disco.**
  - openfootball escribía el archivo antes de leerlo. Ahora lo decodifica (UTF-8) y lo parsea, con el control del número de partidos declarado, antes de escribir. Una descarga rota no se cachea ni pisa la copia buena de la temporada en curso.
  - ClubElo ya validaba antes de escribir.
  - Las rutas de la caché salen de la configuración (competición, temporada) o de un `match_id` validado (I01/I03), nunca de datos recibidos.
- **Clave en las URL.** Solo The Odds API lleva clave. Sus errores y logs nombran la ruta y la redactan (`_redact`, I04). Las demás fuentes no usan clave.
- Mutaciones comprobadas: quitar cada límite, el plazo o la validación de openfootball, o conservar `content-encoding`, hace fallar algún test.

