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
