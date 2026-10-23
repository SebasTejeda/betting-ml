# Spec 004 — Integración del análisis de partido (rama `Sebastian`) en la rama `Daniel`

- **Estado:** aprobada por el dueño (2026-10-22), en ejecución
- **Fecha:** 2026-10-22
- **Origen:** `origin/Sebastian` @ `a52439e`, 30 commits sobre `52db62d` (el mismo punto de partida que `Daniel`)
- **Destino:** rama `Daniel` @ `8d9f779`, con la spec 003 de seguridad terminada
- **Principios:** [`../constitution.md`](../constitution.md) y [`../../SECURITY.md`](../../SECURITY.md). Ningún control de seguridad se debilita para que entre una funcionalidad.

## 1. Qué trae la rama `Sebastian`

Su "spec 003 — Análisis de partido con mercados y consejos explicados" está terminada, salvo córners y tarjetas, que quedaron pospuestos.

| Área | Qué añade |
|---|---|
| **Mercados derivados** | Además del 1X2: doble oportunidad, empate no apuesta, Más/Menos 0.5–4.5, ambos marcan, goles por equipo, hándicap europeo y marcador exacto. Todos salen de la matriz de marcadores Dixon-Coles (`domain/markets.py`, `ml/models/goal_model.py`). |
| **Validación** | Calibración por mercado en F1–F3, con prueba única en 2025-26 (`HOLDOUT_003_USED.lock`) y otra europea (`HOLDOUT_003_EUROPE_USED.lock`). Hay niveles de confianza por mercado. Más/Menos 2.5 no tiene valor demostrado, así que "Mejores opciones" queda desactivada y todo registro es en papel por defecto. |
| **Champions y Europa League** | Datos de openfootball y ClubElo, un Elo propio entre ligas y un ajuste de fuerza entre ligas. Esto es solo información: la confianza es baja. |
| **Análisis** | Forma reciente sin fuga, enfrentamientos directos, motor de consejos con evidencia trazable y lenguaje de certeza prohibido por test (`domain/advice.py`, `application/analyze_match.py`). |
| **Cuotas por evento** | The Odds API por evento: estima el coste antes, respeta la reserva de créditos, guarda caché de 30 min y no guarda la clave (`application/event_odds.py`). |
| **API** | `/teams/search`, `/analysis`, `/analysis/fixture`, `/analysis/{id}/odds/estimate`, `POST /analysis/{id}/odds/refresh` y `/markets/calibration`. Las apuestas aceptan cualquier mercado (`market`, `selection`, `line`). |
| **Diario** | CLV y apuestas por mercado. Liquidación de los mercados nuevos. |
| **Frontend** | Página **Análisis** (805 líneas), botones "Analizar", registro desde el análisis, panel por mercado en Mis apuestas y 13 tests MSW nuevos. |
| **CLI** | `data-europe`, `analyze`, `validate-markets` y `validate-cross-league`. |
| **Tests** | 570 backend y 62 frontend en su rama. |

## 2. Diagnóstico de la integración

**Conflictos de texto (18).**
- Documentación: `CLAUDE.md`, `PROGRESS.md`, `README.md`, `Makefile`, `specs/constitution.md` y `.claude/agents/ml-reviewer.md`.
- Backend: `config.py`, `container.py`, `api/main.py`, `api/schemas_002.py`, `domain/ports.py`, `adapters/sql/models.py`, `adapters/sql/repositories.py` y `application/settle_bets.py`.
- Frontend: `frontend/src/App.tsx` y `BetsPage.test.tsx`.
- Postman: la colección.
- `api/routers/journal.py`: se borró en `Daniel` (se dividió en routers por recurso) y él lo modificó.

**Conflictos que git no ve:**

| Problema | Consecuencia si se fusiona tal cual |
|---|---|
| Hay dos migraciones `0004`: nuestra `0004_sessions` y su `0004_bet_market_selection`. | Alembic no arranca (revisión duplicada), y la API aplica migraciones al arrancar. |
| Las dos ramas se llaman "spec 003" (`003-security-hardening` y `003-match-analysis`) y las dos añaden la enmienda **XII** a la constitución. | Documentación contradictoria. |
| Sus routers son anteriores a la spec 003: lecturas públicas, escrituras con `require_app_key` de `journal.py` y contenedor tipado `Any`. | Rompe la regla "toda ruta exige autenticación". Lo detecta `test_route_access.py`. |
| `bets.outcome` pasa a admitir `NULL` y aparecen `market`, `selection` y `line` sin `CHECK`. | La base aceptaría apuestas imposibles (H-11 otra vez). |
| La auditoría encadenada y `verify-integrity` no conocen las columnas nuevas. | Un cambio de mercado o de línea no dejaría rastro verificable (H-13 otra vez). |
| `POST /analysis/{id}/odds/refresh` gasta créditos y no pasa por el cupo `ODDS_REFRESH_MAX_PER_HOUR`. | Se podrían agotar los créditos dentro de la reserva. |
| Hay esquemas de entrada sin `extra="forbid"` y parámetros de consulta sin patrón (`q`, equipos, `match_id`). | Entrada laxa (H-10 otra vez). |
| `.claude/launch.json` tiene una ruta personal (`C:/Users/Sebastian Tejeda/...`), y `.env.example` deja `ODDS_API_KEY= ` con un espacio final. | Configuración que solo funciona en su máquina, y una clave vacía que no lo parece. |

**Lo que está bien y se conserva.**
- Su frontend usa el mismo cliente `openapi-fetch` (`api`, `unwrap`), así que hereda nuestra sesión y nuestro CSRF sin cambios. No guarda nada en `localStorage`.
- Las cuotas por evento respetan la reserva, y los tests usan fixtures grabados (`event_odds_SYNTHETIC.json`).
- Los locks de sus pruebas únicas y sus reportes son evidencia. **No se vuelven a ejecutar.**

## 3. Decisiones propuestas

1. **Fusionar, no reescribir.** Un `git merge --no-ff origin/Sebastian` conserva sus 30 commits, su autoría y sus locks. Los conflictos se resuelven en el commit de fusión, y las adaptaciones de seguridad van después, en commits propios, una tarea a la vez.
2. **Su spec pasa a ser la 004.** `specs/003-match-analysis/` se renombra a `specs/004-match-analysis/` y se actualizan las referencias en la documentación. Los nombres de los locks y reportes (`HOLDOUT_003_*`, `REPORT_003_*`) **no cambian**, porque el código los busca por nombre. Su enmienda a la constitución pasa a ser la **XIII**.
3. **Su migración pasa a ser la `0009`.** Revisa la `0008`, y los `CHECK` y la auditoría de las columnas nuevas van en la misma migración.
4. **Fuera de la fusión:** `.claude/launch.json` (configuración personal) y el espacio de `.env.example`.
5. Cualquier otra desviación se registra en `specs/004-match-analysis/decisions.md`, como siempre.

## 4. Tareas

Una a la vez: implementar, tests (incluidos los negativos), `lint` y `test` en verde, marcar `[x]`, una línea en `PROGRESS.md` y un commit. Al terminar cada tarea se pide la confirmación del dueño.

- [x] **I00** Este plan, aprobado por el dueño.
  - Commit: `docs(004): integration plan for the match analysis branch`
- [x] **I01** Fusión de `origin/Sebastian` con todo en verde.
  - Se resuelven los 18 conflictos conservando las dos partes: los routers por recurso de `Daniel` con los cambios de su `journal.py`, `ServicesApi` tipado con sus servicios nuevos, y la configuración con los dos bloques.
  - Se renombran la spec y la enmienda, y la migración pasa a `0009`.
  - Sus rutas se protegen con la autenticación que ya existe, así que `test_route_access` cubre todas.
  - Commit de fusión: `merge: match analysis from Sebastian into Daniel`
- [x] **I02** Integridad de los datos de los mercados nuevos.
  - `CHECK` en la `0009`:
    - `market` dentro de `configs/markets.yaml`;
    - `selection` con un patrón cerrado;
    - `line` en un rango y en pasos de 0.25;
    - `outcome` obligatorio si y solo si `market = 'h2h'`.
  - La migración valida antes de alterar y nunca corrige en silencio.
  - La auditoría y `verify-integrity` incluyen `market`, `selection` y `line`, con un test de manipulación directa.
- [x] **I03** API del análisis endurecida.
  - Parámetros con patrón y longitud. Esquemas de entrada con `extra="forbid"`.
  - Un 422 sin eco de los valores, y los errores nuevos con el formato del contrato.
  - El servicio de análisis tipado en `ServicesApi`, sin `Any`.
  - Tests negativos de cada ruta: sin sesión, sin CSRF, entrada inválida y cuerpo grande.
- [ ] **I04** Créditos de The Odds API.
  - El refresco por evento exige sesión con CSRF o `X-API-Key`.
  - Cuenta en el cupo `ODDS_REFRESH_MAX_PER_HOUR` y deja un evento de seguridad (`ODDS_REFRESH`).
  - Tests de que no gasta créditos sin cupo ni por debajo de la reserva, y de que la clave no aparece en la caché, en los logs ni en los errores.
- [ ] **I05** Juego responsable en todos los mercados.
  - Una apuesta real de cualquier mercado pasa por los mismos límites: pérdida mensual, stake máximo y `confirm`.
  - Las liquidaciones de los mercados nuevos quedan auditadas y la pérdida mensual las cuenta.
  - Tests de que `market`, `selection` o `line` no sirven para saltarse un límite.
- [ ] **I06** Frontend y contrato.
  - Página Análisis bajo sesión: un 401 lleva al login, el refresco y el registro llevan CSRF, sin secretos en el almacenamiento y CSP compatible.
  - Se regeneran `openapi.json` y `schema.d.ts`.
  - Tests MSW de las dos ramas en verde, más un test de 401 en Análisis.
  - Postman con `appApiKey` en la carpeta de análisis.
- [ ] **I07** Fuentes externas nuevas (ClubElo, openfootball, cuotas por evento).
  - Timeout y límite de bytes por descarga (era cobertura aplazada de la auditoría T021).
  - Redacción de la clave en las URL y validación de lo que se escribe en disco.
- [ ] **I08** 🔍 Checkpoint y cierre.
  - `ml-reviewer` sobre la integración. `make security` limpio.
  - Verificación de punta a punta en dev y prod: login, Análisis, registro en papel de otro mercado, 409 de límites, `verify-integrity`, backup y restore.
  - `SECURITY.md`, README, `docs/deploy.md` (`data-europe`) y `PROGRESS.md` actualizados.
  - El despliegue local se actualiza con `db-upgrade` y `data-europe`.

## 5. Criterio de éxito

| Nivel | Condición |
|---|---|
| **Mínimo** | I01–I05: la funcionalidad de las dos ramas funciona, con todas las rutas autenticadas, la base con `CHECK` y auditoría para los mercados nuevos, y los créditos y límites protegidos. |
| **Bueno** | Lo anterior + I06–I07: el frontend completo bajo sesión y las fuentes externas acotadas. |
| **Excelente** | Lo anterior + I08 sin bloqueantes, y el despliegue local actualizado y verificado. |

## 6. Riesgos

| Riesgo | Mitigación |
|---|---|
| Una resolución de conflicto pierde un control de seguridad | Los tests negativos de la spec 003 corren en cada tarea. `test_route_access` recorre todas las rutas. |
| Romper sus resultados o volver a usar un holdout | Los locks y reportes no se tocan. `validate-markets` y `validate-cross-league` no se ejecutan en modo final. |
| Datos existentes que no cumplen los `CHECK` nuevos | La migración lista las filas y aborta; no borra ni corrige. |
| Gastar créditos de The Odds API | Los tests solo usan fixtures. La verificación final usa la estimación de coste, sin refresco real, salvo que el dueño lo pida. |
