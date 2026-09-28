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

## 2026-09-27 — `/matches` vacío del sábado 26/09/2026 no era un bug (T002)
- Contexto: spec §7 pedía verificar si el filtro de fecha de `/matches` fallaba.
- Hallazgo: el `fixtures.csv` real descargado ese día (`data/raw/fixtures/fixtures_20260927T003301.csv`) solo contiene E2, E3, EC, SC1 y SP2. Las 5 ligas soportadas jugaron por última vez el 20/09 y el calendario de Understat (descargado el 26/09) no tiene partidos suyos entre el 25 y el 28/09 (parón entre jornadas). El parseo `dd/mm/yyyy`, la conversión hora UK → UTC y el filtro por fecha en `America/Lima` son correctos.
- Decisión: no se cambia la lógica; se agrega un test de regresión con un extracto del CSV real (`tests/unit/test_fixtures_20260926.py`).
- Impacto: la lógica de fechas de fixtures se puede reutilizar en la spec 002.

## 2026-09-27 — Backtest en validación: regla del umbral y advertencia sobre `max_odds` (T005)
- Regla del umbral (no fijada en la spec): para cada escenario × variante, el umbral de {0.01, 0.02, 0.03, 0.05} con **mayor CLV medio** en F1–F3 agrupados entre los que tienen **≥ 300 apuestas**; si hay empate o ninguno llega a 300, el menor (más apuestas). Se usa el CLV y no el ROI porque el ROI con cientos de apuestas es mayormente ruido y la puerta T008 se define por CLV.
- Variantes con filtro del modelo: usan las predicciones out-of-fold de F1–F3 guardadas por los experimentos de la spec 001 (E12 y E06, campeones de `models/champion.json`).
- Advertencia: en el escenario `max`, el CLV positivo (+5.7 %) viene casi todo de apuestas a longshots (cuota mediana 6.7) donde la mejor cuota del mercado supera a Pinnacle en un 17 % de media (hasta +83 %). Son precios atípicos o desactualizados de alguna casa, a menudo inaccesibles o con límites bajos, y `Max*` de football-data puede incluir casas o exchanges que no se pueden usar desde Perú. El ROI del mismo escenario es −13 % (IC [−35 %, +14 %]). Se trata `max` como escenario optimista y dudoso; la referencia realista es `b365`.
- Control: el escenario `avg` da CLV medio negativo (−11.7 % con apenas 10 apuestas), como se esperaba: sin precios por encima del mercado promedio no hay valor.

## 2026-09-27 — Estrategia principal y reglas del test final, fijadas antes de verlo (T006/T007)
- Estrategia principal del backtest: **Bet365 sin filtro del modelo** (`b365|none`). Es el escenario realista de "una casa blanda" (spec §6) y no depende del modelo. Decide el nivel de la spec §5 y la conclusión. Los demás escenarios se reportan igual.
- Conclusión: **seguir** si la principal alcanza el nivel Bueno en el test (CLV > 0 y límite inferior del IC del ROI > −3 %); **seguir con cambios** si no, pero algún escenario que no sea el control `avg` tiene CLV > 0 en el test; **no seguir** en otro caso.
- El test final usa los umbrales fijados en validación, las predicciones del holdout de la spec 001 (modelos entrenados sin ver 2025-26) y su propio lock (`reports/HOLDOUT_002_USED.lock`, reclamado antes de leer datos). Las apuestas del test se guardan en `reports/holdout_artifacts/backtest_002_test_bets.parquet`.
- Solo hay cuotas de Pinnacle en ~55 % de 2025-26: en el resto no hay referencia y no se apuesta. Se reporta la cobertura.

## 2026-09-27 — Reglas del test final revisadas tras el checkpoint T006 (antes de ver el test)
- Contexto: `ml-reviewer` bloqueó el diseño del test final (sin fuga). Con las reglas anteriores la conclusión estaba casi decidida: el CLV de `max` es positivo por construcción (sigue al EV casi 1:1 porque mide que el precio máximo supera a Pinnacle, no que se pueda apostar a él), y cualquier escenario con CLV puntual > 0 bastaba para "seguir con cambios".
- Decisiones (fijadas antes de ejecutar T007):
  - `max` y `avg` son **solo informativos**. La evidencia sale de **Bet365**, una casa blanda real.
  - **Seguir:** la estrategia principal `b365|none` alcanza el nivel Bueno en el test (CLV > 0 y límite inferior del IC 95 % del ROI > −3 %).
  - **Seguir con cambios:** si no, pero alguna variante Bet365 (sin filtro o con filtro de modelo) tiene, sumando validación y test con sus umbrales fijos, **≥ 50 apuestas con CLV y límite inferior del IC 95 % del CLV > 0**.
  - **No seguir:** en otro caso.
  - **Potencia declarada:** se esperan ~23 apuestas de `b365|none` en el test (2.4 % de los partidos × ~51–55 % de cobertura de Pinnacle). Con esa muestra, el nivel Bueno no tiene potencia estadística y el informe no lo presentará como un resultado firme.
  - Lecturas adicionales: 6 variantes × 4 umbrales sin corrección por comparaciones múltiples; en los escenarios `b365` y `avg` el umbral es 0.01 por defecto (ningún umbral llega a 300 apuestas).
  - Se agrega un **placebo** (CLV de apostar a todos los resultados a esa cuota, sin selección) en validación y test.
  - Se guarda por apuesta: `ps_odds`, `psc_odds`, `p_close`, `p_model` y la fracción de Kelly. Se guardan también la cobertura de Pinnacle por liga y por mes, y hashes del JSON de validación y de las predicciones del holdout (también en el lock).
  - Las comprobaciones previas de las predicciones del holdout se hacen **antes** de reclamar el lock.
- **Lectura honesta de la puerta T008** (validación): pasa en lo formal (CLV medio > 0), pero el escenario `max` no es apostable. La evidencia realista es débil: `b365|none` tiene CLV +0.9 % con un IC que incluye el 0 (+2.9 % en 2022-23, −0.02 % en 2023-24 y −0.4 % en 2024-25). Las variantes con filtro de modelo tienen un IC por encima de 0, pero con ~47 apuestas y sin corregir por comparaciones múltiples.
- (2ª revisión T006, antes de ver el test) "Seguir con cambios" exige además que **el test por sí solo** tenga CLV medio > 0 con ≥ 5 apuestas con CLV en esa variante Bet365. Sin esto, las variantes con filtro (≈ 47 apuestas en validación, ≈ 8 esperadas en el test) llegaban a "seguir con cambios" más de la mitad de las veces aunque el test no tuviera ventaja. Aun con esta condición, con un test sin ventaja "seguir con cambios" saldría por azar en ~45–50 % de los casos por variante (simulación del revisor): con ~8 apuestas de test ninguna regla puede confirmar nada. Por eso, si la conclusión es "seguir con cambios", la confirmación real es la regla de la spec §5, que se eleva a **condición explícita**: CLV medio > 0 en las primeras 100 apuestas en papel antes de apostar dinero real. El check del nivel Mínimo usa solo variantes Bet365 (no `max`). Antes del lock se verifica que la validación recalculada coincide con el JSON guardado y que las predicciones del holdout tienen las 1 752 filas.

## 2026-09-27 — 🚦 Puerta T008: pasa en lo formal; se pausa para que el dueño confirme los cambios
- Regla (tasks.md T008): detener si ninguna variante tuvo CLV medio > 0 en validación. **Pasa**: Bet365 sin filtro tuvo +0.9 %, y con los filtros E12 y E06, +3.4 % y +2.9 %.
- Resultado del test único (2025-26):
  - La estrategia principal, **Bet365 sin filtro, falló**: 27 apuestas, CLV −3.7 % (IC [−8.0 %, +0.3 %]), ROI −10 %.
  - **Bet365 con filtro del campeón E12** dio CLV +1.1 % con solo 8 apuestas. Sumando validación y test: 57 apuestas, CLV +3.0 % (IC [+0.4 %, +6.0 %]).
  - Bet365 con filtro E06: CLV −0.8 % en el test.
  - Placebos (sin selección) negativos en todas las fuentes. `max`: CLV +2.5 %, pero ROI −52 % (no apostable).
  - Conclusión pre-registrada: **seguir con cambios**. Con un test sin ventaja habría salido así por azar en ~45 % de los casos: la evidencia es débil y descansa sobre todo en la validación.
- Cambios propuestos para las fases siguientes (pendientes de confirmación del dueño):
  1. **Señal de valor = cuota blanda accesible con EV > 1 % sobre Pinnacle *y* modelo de acuerdo** (`p_modelo ≥ p_justa`). "Valor" sin acuerdo del modelo se muestra solo como referencia, no como recomendación.
  2. **Tope de EV**: un EV > 5 % frente a Pinnacle pre-cierre se marca "revisar" (en validación, esos casos tuvieron CLV negativo: suele ser Pinnacle el precio desactualizado), no "valor".
  3. **Periodo de prueba obligatorio**: el panel muestra el progreso hacia 100 apuestas en papel con CLV medio > 0 (spec §5). Opción a decidir: bloquear el registro de apuestas `real` hasta cumplirlo.
  4. El frontend muestra siempre que la evidencia del backtest es débil (enlace a `REPORT_002_backtest.md`).
- Estado: T008 cerrada con la puerta superada. La ejecución automática se detiene aquí antes de T009 (catálogo de casas, persistencia, llamadas reales a The Odds API y frontend), para que el dueño confirme o ajuste estos cambios.

## 2026-09-27 — Fuente del CLV al liquidar apuestas (instrucción del dueño, para T015)
- Decisión: `settle_bets` calcula el CLV con las cuotas de cierre de Pinnacle de football-data (`psc_odds_*`, Shin) cuando existan para el partido, y solo si faltan usa el último snapshot de Pinnacle de The Odds API anterior al inicio (Betfair Exchange neto de comisión como respaldo si tampoco hay Pinnacle). Cada apuesta guarda la fuente del CLV usada.
- Motivo: el cierre de football-data es una referencia de cierre real y homogénea con el backtest; el snapshot de la API puede ser anterior al cierre.
- Impacto: en 2026-27 football-data no publica Pinnacle, así que en la práctica la mayoría del CLV vendrá del snapshot de la API.

## 2026-09-27 — Reorientación de la spec tras la puerta T008 (decisión del dueño)
- Contexto: la puerta pasó en lo formal, pero la estrategia principal falló en el test (Bet365 sin filtro: CLV −3.7 %, 27 apuestas) y la única variante con CLV positivo en el test (filtro del campeón E12) tiene 8 apuestas.
- **La variante con filtro E12 NO se considera validada:** 8 apuestas no son evidencia, y apoyarse en ella después de ver fallar a la principal sería elegir a posteriori.
- Decisiones (reemplazan los 4 cambios propuestos en la entrada de la puerta T008):
  1. **Producto principal:** comparador de mejor cuota + calculadora + diario + límites. La UI destaca la mejor cuota disponible y el margen de cada casa, no las value bets. Justificación medida (`reports/REPORT_002_backtest.md`, `reports/margins_002.json`): la mejor cuota paga de media +5.0 % frente al promedio en validación (+4.9 % en 2026-27), y el margen pagado baja de 4.5 % a 0.5 %.
  2. **La señal de valor (con o sin filtro del modelo) es "EXPERIMENTAL — solo papel":** lleva la etiqueta visible y nunca se muestra como "recomendado". El registro rápido desde la señal crea apuestas `paper` por defecto.
  3. **Contador de progreso** en el panel del diario: apuestas en papel de la señal sobre 100, con su CLV acumulado. Si llega a 100 con CLV > 0, esa será la evidencia real.
  4. **Las apuestas reales no se bloquean en general** (el diario debe registrar todo lo que se apuesta). Si una apuesta **real** viene de la señal experimental y aún no se cumple la condición, la API pide confirmación explícita (409 `EXPERIMENTAL_SIGNAL_UNPROVEN` → `confirm: true`) con el mensaje "Esta señal aún no tiene evidencia (X/100 apuestas en papel, CLV actual Y). ¿Apostar dinero real igual?". La apuesta queda marcada `from_experimental_signal = true`, para analizarla aparte. Las apuestas reales que no vienen de la señal se registran normal.
  5. Los límites de US6 (pérdida mensual, stake máximo y bloqueo al superar el presupuesto mensual) se mantienen tal cual.
  6. Se actualizan `spec.md` (§1, §2, US3–US6, §5), `contracts/api.md` y `tasks.md` (nota de reorientación y T014). `REPORT_002_backtest.md` incluye el escenario `max_odds`, el ahorro de margen de la mejor casa frente al promedio y la nota de que E12 no está validada.

## 2026-09-27 — Casas accesibles desde Perú (T009)
- Decisión: `accessible: true` solo para casas que operan legalmente en Perú según su licencia MINCETUR, hasta donde se pudo determinar: Betsson y Coolbet (también en The Odds API), y las de ingreso manual (Te Apuesto, Inkabet, Doradobet, Apuesta Total, Betano, y Betsson/Coolbet Perú a mano). Pinnacle, los exchanges y el resto de casas europeas quedan como referencia (`accessible: false`).
- Motivo: la mejor cuota "accesible" y la señal experimental no deben apuntar a casas donde no se puede apostar desde Perú.
- Impacto: el dueño puede ajustar la lista a mano en `configs/bookmakers.yaml`. Las claves de The Odds API se verifican con una respuesta real en T011. Las cuotas de Betsson/Coolbet en la API (región eu) pueden no coincidir con las de su web peruana; por eso existen también como entrada manual.

## 2026-09-27 — The Odds API verificada con una llamada real (T011)
- `GET /v4/sports` (no consume créditos): los 5 `sport_key` existen y están activos: `soccer_epl`, `soccer_spain_la_liga`, `soccer_germany_bundesliga`, `soccer_italy_serie_a` y `soccer_france_ligue_one`. Se guardan en `configs/leagues.yaml` (`odds_api`).
- Una sola llamada de cuotas (`soccer_epl`, regiones eu+uk, h2h) costó **2 créditos** (quedan 498 de 500). Es la **1.ª de las 3 llamadas con coste** que permite el dueño durante el desarrollo.
- **Pinnacle sí está incluido en el plan gratis:** aparece en los 20 de 20 eventos. Pinnacle sigue como referencia; Betfair Exchange (eu/uk) queda como respaldo y también está presente.
- La respuesta tiene 39 casas; 14 no estaban en el catálogo y se agregaron como no accesibles.
- Nombres de equipos: 6 de la Premier League no resolvían con los alias existentes. Se agregan como alias `the_odds_api` verificados: Brighton and Hove Albion, Coventry City, Hull City, Ipswich Town, Leeds United y Tottenham Hotspur. Para las otras 4 ligas se usa la búsqueda flexible sobre todos los alias; lo que no resuelva aparece en `unmapped_teams` (error visible) en el primer refresco real, y se completa entonces.
- Los fixtures grabados (`tests/fixtures/the_odds_api/`) no contienen la clave (verificado); los headers de créditos se guardan aparte.

## 2026-09-27 — Correcciones del checkpoint T019 (revisión ml-reviewer)
- Contexto: la revisión 🔍 de T019 bloqueó por 4 problemas. Se corrigen así:
  1. **El diario ya no permite borrar pérdidas:** liquidar a mano solo vale para apuestas pendientes y después del inicio (`MATCH_NOT_STARTED`); borrar solo vale para pendientes antes del inicio (`MATCH_ALREADY_STARTED`); una apuesta liquidada no se re-liquida a mano (`BET_NOT_PENDING`). `settle` revisa las liquidaciones manuales de los últimos 30 días contra el resultado oficial y las corrige (`corrected`).
  2. **Las cuotas manuales no contaminan la referencia:** la calculadora solo acepta casas de ingreso manual (`BOOKMAKER_NOT_MANUAL`), y la referencia, el CLV de respaldo, la señal y la mejora frente a la mejor cuota usan solo cuotas de la API.
  3. **Los límites cuentan la exposición pendiente:** el peor caso es pérdida del mes + apuestas reales pendientes + stake nuevo. Así no se pueden abrir muchas apuestas a la vez sin aviso. El bloqueo 403 sigue midiendo la pérdida realizada, tal como pide US6.
  4. **Créditos:** con el presupuesto bajo se hace una consulta gratis (`/v4/sports`) para detectar la renovación mensual antes de bloquear; el bloqueo responde `429` (ya no un `202` vacío); un fallo a mitad del refresco guarda lo ya pagado; los partidos en juego se descartan.
- Además: cuota con hasta 3 decimales, logs de httpx en WARNING (la URL lleva la clave), aviso para apuestas registradas después del inicio, resumen con `kind=all`, el scheduler opcional (`ODDS_AUTO_REFRESH`) arranca y se detiene con la API, y las bases de datos en archivo se migran con Alembic al arrancar (una base creada antes de Alembic se marca en la revisión inicial).

## 2026-09-27 — Segunda revisión del checkpoint T019: dos formas de saltarse el 403
- Contexto: los 4 bloqueantes originales quedaron resueltos, pero la segunda revisión encontró dos caminos nuevos para evitar el bloqueo mensual.
- **Apuestas reales sin hora de inicio:** una apuesta real sobre un `match_id` sin cuotas de la API no tenía hora de inicio, se podía liquidar a mano como ganada en cualquier momento, y `settle` no la corregía. Decisión: las apuestas **reales** exigen un partido con cuotas de la API (`422 MATCH_WITHOUT_ODDS`); en papel se aceptan, y para ellas la hora mínima de inicio es el comienzo del día del `match_id` (UTC).
- **No liquidar nunca evitaba el 403:** el bloqueo solo miraba la pérdida liquidada. Decisión (opción de dominio, sin red): para el 403, las apuestas reales pendientes de partidos que empezaron hace más de 3 h (`OVERDUE_AFTER`) cuentan como perdidas hasta liquidarse. Es el peor caso y se deshace solo al ejecutar `settle`. El resumen mensual sigue mostrando la pérdida realizada.
- Observaciones atendidas: en el comparador, las cuotas de exchange compiten por la mejor cuota **netas de comisión**; si la consulta gratis de créditos no trae el header del saldo, el bloqueo por créditos se levanta solo al empezar un mes nuevo en Lima (se verificará el header en la llamada real de T030).
- Observaciones documentadas, sin cambio: la reconciliación de `settle` también corrige una `nula` manual si el partido se jugó, y fecha la corrección en el mes en que se hace (conservador). El scheduler automático corre dentro del proceso de la API: usar un solo worker y sin `--reload` si `ODDS_AUTO_REFRESH=true`.

## 2026-09-27 — Tercera revisión del checkpoint T019: resultados manuales sin confirmar
- Problema: una apuesta real marcada a mano como `ganada` o `nula` reducía la pérdida del mes y levantaba el 403 sin ejecutar nunca `settle`.
- Decisión (opción de dominio): cada apuesta guarda quién la liquidó (`result_source`: `manual` u `official`; migración `0002`). Para el límite mensual (403, avisos y `month.current_loss` del resumen), una apuesta real liquidada a mano como `ganada`/`nula` cuenta como perdida hasta que `settle` la confirma con el resultado oficial. Si el resultado manual era correcto se marca `official`; si no, se corrige. Las liquidadas a mano como `perdida` cuentan normal. Las manuales sin confirmar se revisan en cada `settle`, sin límite de antigüedad.
- Impacto: el beneficio y el ROI del resumen siguen mostrando lo registrado; solo el límite usa el peor caso. Un partido aplazado marcado `nula` a mano cuenta como pérdida del mes hasta que haya resultado oficial (conservador). En la UI (T024) se explicará que una apuesta pendiente de un partido aplazado se liquida como `nula`.

## 2026-09-27 — Auditoría final T029 (primera ronda)
- Bloqueante corregido: en la Calculadora, una cuota con veredicto `valor` **es** la señal experimental. El registro sale ahora en papel por defecto y con `from_experimental_signal = true`, así que en real pide la confirmación del 409 y cuenta aparte. Antes salía como real y sin marca.
- Observaciones atendidas:
  - Hoy muestra la cuota justa de la referencia bajo la mejor cuota. La señal indica si el modelo coincide.
  - Partido muestra la probabilidad y la cuota justa de la referencia y la probabilidad del modelo (US3).
  - El resumen mensual suma las apuestas reales vencidas sin liquidar, igual que el 403, y "Mis apuestas" lo explica.
  - El README advierte que el ahorro de margen medido usa `Max` de football-data (casas no accesibles incluidas) y que el ahorro real con casas peruanas aún no está medido.
- Observaciones que quedan documentadas sin cambio (uso personal y local):
  - El dinero se guarda en SQLite como `REAL` (la ida y vuelta es exacta con escala 2) y viaja en el JSON como número.
  - Subir `bankroll_initial` o `max_stake_pct` aplica de inmediato. No relaja el límite de pérdida mensual, que sigue la regla del mes siguiente.
  - `from_experimental_signal` lo declara el cliente; el frontend lo envía siempre desde la señal.
  - La última cuota de una casa que retiró el partido se conserva.

## 2026-09-28 — Apuestas reales sin cuota de referencia (decisión del dueño)
- Cambio: se deja de rechazar con `422 MATCH_WITHOUT_ODDS` las apuestas reales sobre partidos sin cuotas de la API. Se registran marcadas `sin_referencia = true` (campo de dominio `no_reference`; migración `0003`). Reemplaza la decisión de la segunda revisión de T019.
- **Motivo: el diario debe reflejar todas las apuestas reales para que el CLV y los límites sean fiables.** Rechazarlas dejaba fuera del diario dinero realmente apostado, y los límites y el CLV quedaban calculados sobre datos incompletos.
- Reglas:
  - Cuentan para todos los límites de US6: pérdida mensual (incluido el bloqueo 403), stake máximo y exposición pendiente.
  - Se excluyen de la señal de valor: no suman al progreso X/100.
  - Su CLV se calcula al liquidar con el cierre de Pinnacle de football-data (`psc_odds_*`) si está disponible. Sin kick-off no hay respaldo con The Odds API.
- Por qué no se reabre el agujero que cerró el 422:
  - Una victoria o nula marcada a mano cuenta como pérdida para el límite hasta que `settle` la confirma con el resultado oficial.
  - Sin kick-off conocido, liquidar a mano exige que haya empezado el día del partido (según el `match_id`).
  - Una pendiente real sin liquidar cuenta como perdida para el 403 desde el final del día del partido más 3 h (`latest_start`).
- Frontend: la Calculadora tiene la sección "¿El partido no aparece?" (liga, fecha, equipos con nombres canónicos, casa accesible y cuota). Construye el `match_id` con las mismas reglas que el backend, para que `settle` encuentre el resultado oficial. Antes de registrar muestra el aviso "Sin cuota de referencia", y "Mis apuestas" marca estas apuestas.

## 2026-09-28 — Página "Top del día" (/top) (petición del dueño)
- Qué es: una lista única con las cuotas de la señal experimental de todas las ligas para la fecha elegida, ordenadas por EV. Muestra partido, resultado, casa, cuota, EV, si el modelo coincide y un botón "Registrar en papel", con la etiqueta "EXPERIMENTAL — solo papel" visible.
- Implementación: solo frontend. Usa `GET /api/v1/comparator?only_value=true` (la API ya lo permitía), sin cambios en la API.
- "EV positivo" se toma como la señal, es decir, EV por encima del umbral `min_edge` de Ajustes, y se filtra EV > 0. Motivo: el botón registra apuestas en papel marcadas como de la señal. Si se incluyeran cuotas con EV entre 0 y el umbral, entrarían en la evidencia de las 100 apuestas en papel cosas que no son la señal.
- Juego responsable: la página avisa que la lista no tiene evidencia y que un EV alto con cuotas altas suele ser ruido. El registro va a la calculadora en papel por defecto, con el mismo flujo de límites.
