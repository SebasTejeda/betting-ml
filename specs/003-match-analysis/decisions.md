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
