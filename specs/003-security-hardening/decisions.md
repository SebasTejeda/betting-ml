# Registro de decisiones — Spec 003

Formato:

```
## AAAA-MM-DD — Título corto
- Contexto:
- Decisión:
- Motivo:
- Impacto:
```

## 2026-10-22 — Un solo dueño con contraseña, no multiusuario
- Contexto: la spec 002 dejó fuera las cuentas ("basta con una API key"). El proyecto pasa a tratarse como aplicación web expuesta.
- Decisión: login de un único dueño con contraseña (hash Argon2id en `.env`). Sin registro, sin recuperación por correo y sin OAuth.
- Motivo: cubre el riesgo real (acceso de terceros a datos personales y a los límites) sin la superficie de una gestión de usuarios.
- Impacto: reemplaza la API key del navegador. El dominio no se modela por usuario; si algún día hay multiusuario, se hará en una spec nueva.

## 2026-10-22 — Sesión de servidor con cookie HttpOnly en lugar de JWT o de la clave en localStorage
- Contexto: la clave de escritura vive hoy en `localStorage`, legible por cualquier XSS.
- Decisión: token aleatorio de 256 bits en una cookie `HttpOnly; SameSite=Strict` (+ `Secure` en prod); en la base solo su SHA-256.
- Motivo: JavaScript no puede leer la cookie; la sesión se revoca al instante (logout, cambio de contraseña) sin listas de revocación ni claves de firma.
- Impacto: necesita protección CSRF (token *double-submit* + `SameSite=Strict`) y una migración (tabla `sessions`).

## 2026-10-22 — También se protegen las lecturas
- Contexto: hoy `/bets`, `/bets/summary` y `/settings` son públicas.
- Decisión: toda ruta `/api/v1/*` exige autenticación, salvo `/health` y el login.
- Motivo: el diario, el bankroll y los límites son datos personales y financieros.
- Impacto: Postman y la CLI usan `X-API-Key`; el frontend usa la sesión.

## 2026-10-22 — Una sola clave de máquina
- Contexto: hay dos claves (`ADMIN_API_KEY` y `APP_API_KEY`) y dos verificaciones duplicadas.
- Decisión: `APP_API_KEY` es la única; `ADMIN_API_KEY` se acepta como alias durante una versión, con aviso.
- Motivo: menos superficie y una sola implementación que testear.
- Impacto: actualizar `.env` y la colección de Postman.

## 2026-10-22 — Rate limit en memoria, detrás de un puerto
- Contexto: la API corre como un único proceso de uso personal.
- Decisión: limitador de ventana deslizante en memoria, detrás del puerto `RateLimiter`.
- Motivo: sin dependencias externas (Redis) para un solo proceso.
- Impacto: con varios procesos o réplicas habría que cambiar el adaptador; queda documentado.

## 2026-10-22 — Alcance de la auditoría encadenada
- Contexto: el dueño pide garantizar la integridad de los datos.
- Decisión: `audit_log` de solo inserción (triggers) con cadena SHA-256, escrita en la misma transacción que el cambio, y `verify-integrity`.
- Motivo: detecta cambios hechos fuera de la API, corrupciones y ediciones accidentales, y da trazabilidad completa del dinero y de los límites.
- Impacto: no impide que alguien con acceso al archivo `.db` reescriba toda la cadena; eso lo cubren los backups con hash guardados fuera del equipo (documentado en `SECURITY.md`).

## 2026-10-22 — Dependencias mínimas
- Contexto: cada dependencia nueva es superficie de ataque.
- Decisión: solo `argon2-cffi` en tiempo de ejecución. Cabeceras, CSRF y rate limit son middlewares propios; las herramientas de análisis (`pip-audit`, `gitleaks`) van solo en dev/CI.
- Motivo: poco código propio y bien testeado frente a librerías con mantenimiento incierto.
- Impacto: más tests propios (ver `plan.md` §8).

## 2026-10-22 — Rama de trabajo y confirmación por tarea
- Contexto: el dueño pidió ejecutar el plan paso a paso con confirmación.
- Decisión: el trabajo se hace en la rama `Daniel`, un commit por tarea, y tras cada tarea se pide confirmación antes de seguir. Nunca `git push`.
- Motivo: control del dueño sobre cada cambio.
- Impacto: excepción explícita a la regla de CLAUDE.md "no preguntes al usuario salvo bloqueo", válida solo para esta spec.

## 2026-10-22 — T009 (frontend con login) antes que T008 (rate limit)
- Contexto: T007 protege las lecturas y el frontend solo aprende a iniciar sesión en T009; con el orden original quedaba sin poder leer durante dos commits.
- Decisión: el dueño aprobó ejecutar T009 justo después de T007 y antes de T008. Los IDs no cambian.
- Motivo: la rama queda usable salvo en un único commit; el rate limit no depende del frontend.
- Impacto: los tests del frontend simulan el `429` del login con MSW antes de que el backend lo implemente.

## 2026-10-22 — El CSRF de las escrituras con sesión se adelanta a T006
- Contexto: `POST /auth/logout` es una escritura con sesión; en T006 la sesión ya existe.
- Decisión: `require_write` acepta la sesión desde T006 y exige `X-CSRF-Token` en ese mismo commit. T007 queda solo para proteger las lecturas.
- Motivo: no debe existir ni un commit en el que una escritura con cookie funcione sin CSRF.
- Impacto: T007 es más pequeña; los tests de CSRF viven en `tests/integration/test_api_auth.py`.

## 2026-10-22 — Tokens de sesión con HMAC y secreto temporal en dev
- Contexto: el plan pedía guardar el SHA-256 del token y usar SESSION_SECRET como "huella".
- Decisión: se guarda HMAC-SHA256(SESSION_SECRET, token), y la huella de la contraseña es HMAC-SHA256(SESSION_SECRET, APP_PASSWORD_HASH). En `dev` sin SESSION_SECRET se usa un secreto aleatorio por proceso.
- Motivo: con la base filtrada pero sin el secreto no se puede comprobar ningún token; rotar SESSION_SECRET o la contraseña cierra todas las sesiones.
- Impacto: en `dev` sin SESSION_SECRET las sesiones no sobreviven a un reinicio de la API (en `prod` el secreto es obligatorio desde T003).

## 2026-10-22 — Purga de sesiones al arrancar y en cada login
- Contexto: el plan proponía purgar las sesiones vencidas al arrancar y cada hora.
- Decisión: se purgan al arrancar la API, en cada login y una a una al detectarlas vencidas al validar; sin tarea horaria.
- Motivo: una sesión vencida nunca se acepta (se comprueba en cada petición); la purga solo limpia filas, así que no hace falta un scheduler.
- Impacto: pueden quedar filas vencidas hasta el siguiente login o reinicio; no tienen efecto.

## 2026-10-22 — El login cuenta intentos antes de comprobar la contraseña
- Contexto: la spec pide 5 fallos por minuto e IP con bloqueo progresivo (1, 5, 15 min). Contar solo los fallos *después* de verificar deja pasar intentos en paralelo mientras Argon2 calcula.
- Decisión: cada intento se cuenta de forma atómica antes de verificar y un login correcto borra la cuenta. El 6.º intento en un minuto responde `429 TOO_MANY_ATTEMPTS` con `Retry-After` y bloquea la IP 1, 5 y luego 15 minutos (tope). Durante el bloqueo no se comprueba la contraseña, ni siquiera la correcta. El nivel de bloqueo se recuerda 24 h o hasta un login correcto.
- Motivo: es el mismo límite visto desde fuera, pero sin carreras; además, un cliente bloqueado no consume CPU de Argon2.
- Impacto: el quinto intento fallido sigue siendo `401`; el sexto ya es `429`.

## 2026-10-22 — Límite global por IP, no por sesión
- Contexto: la spec dice "global por sesión/IP".
- Decisión: el límite global (`RATE_LIMIT_PER_MINUTE`) se cuenta por IP del cliente, también para peticiones sin credencial.
- Motivo: una cookie inventada distinta en cada petición no debe dar un cupo nuevo; con un solo dueño, la IP basta.
- Impacto: detrás de un proxy hay que pasar la IP real (`uvicorn --proxy-headers` con `--forwarded-allow-ips`); se configura en T020 (Docker).

## 2026-10-22 — Cupo de refrescos de cuotas global y después de autenticar
- Contexto: `POST /odds/refresh` gasta créditos de The Odds API.
- Decisión: `ODDS_REFRESH_MAX_PER_HOUR` (6) refrescos manuales en cualquier hora móvil, para toda la API y no por cliente. Se cuenta después de `require_write`, así que una petición anónima no consume el cupo del dueño. El refresco automático programado no pasa por la API y no cuenta.
- Motivo: el riesgo es el saldo de créditos, que es uno solo.
- Impacto: `429 RATE_LIMITED` con `Retry-After`.

## 2026-10-22 — Límites desactivables en los tests, límite de cuerpo siempre activo
- Contexto: los tests funcionales hacen cientos de peticiones por minuto con el mismo cliente.
- Decisión: si los servicios no traen `rate_limits`, no hay límite de peticiones (`ApiServices` lo deja en `None` por defecto; el `Container` siempre lo configura). El límite de cuerpo aplica siempre, con 64 KB por defecto.
- Motivo: no hay que tocar los tests funcionales y la configuración real no puede quedarse sin límites.
- Impacto: `tests/integration/test_api_limits.py` prueba los límites con servicios que sí los traen.

## 2026-10-22 — Checkpoint T010: hallazgos corregidos y riesgos aceptados
- Contexto: revisión de T003–T009 (incluida T008) con `ml-reviewer` (veredicto BLOQUEADO por un bloqueante) y una revisión de seguridad independiente (`security-audit`, sin hallazgos críticos ni altos).
- Decisión — corregido en este checkpoint:
  - **Bloqueante:** el cableado real de los controles (`Container.api_services`) no tenía tests. Ahora `test_container_security.py` comprueba el freno del login, los límites, el tamaño máximo del cuerpo y la cookie `Secure` en prod. Además, `Authenticate` exige `throttle`: ya no existe un modo sin freno.
  - `test_route_access` usa un `Authenticate` real (la cookie inventada pasa por la validación) y prueba el CSRF en **cada** escritura con sesión: sin token, con un token falso o con uno ajeno → 403.
  - El cupo de refrescos y el límite global pasan a `application/throttle.py` (`RateLimits.take_*`, `RateLimitedError`): los routers no tienen lógica.
  - La identidad del cliente para los límites agrupa IPv6 por /64 y convierte la IPv4 mapeada en IPv4.
  - Como máximo 2 verificaciones Argon2 en paralelo (64 MiB cada una), para que una ráfaga de logins desde muchas direcciones no agote la memoria.
  - `betting-ml serve` no confía en `X-Forwarded-For` (`proxy_headers=False`). Con el valor por defecto de uvicorn, un cliente local podía usar una IP nueva en cada petición y saltarse el bloqueo.
  - El frontend borra la clave `betting-ml.apiKey` que dejaron las versiones anteriores en `localStorage`, y ante `403 CSRF_FAILED` (por ejemplo, un login en otra pestaña) vuelve a pedir el token, así que reintentar funciona.
  - `APP_ENV=prod` rechaza un hash Argon2id con parámetros por debajo del mínimo de OWASP (m=19456, t=2).
  - `hash-password` se registra antes del bloque `__main__` (`python -m betting_ml.cli hash-password` fallaba).
  - Se quita el código muerto de `/auth/me`. `route_access` deduplica la política cuando un handler repite la de su router.
  - Segunda revisión de `ml-reviewer`: APROBADO CON OBSERVACIONES. Se corrigen también:
    - El semáforo de Argon2 esperaba sin límite y podía ocupar todos los hilos de la API. Ahora falla rápido: si no hay plaza en 2 s, responde `503 LOGIN_BUSY` con `Retry-After: 5`.
    - El `Dockerfile` arranca uvicorn con `--no-proxy-headers`, igual que `serve`.
    - `refreshCsrf` del frontend no tapa el 403 original si falla la red.
- Decisión — aceptado o asignado:
  - Con más de 10 000 claves, el limitador expulsa los contadores más antiguos (puede reiniciar el nivel de bloqueo de una IP o el cupo de refrescos), nunca los bloqueos vivos. Riesgo bajo: requiere más de 10 000 direcciones, y los créditos tienen además la reserva mínima de la spec 002.
  - Una página de terceros que el dueño visite puede gastar su cupo global por IP (peticiones simples sin credencial). Es una denegación de servicio menor y temporal (60 s). Si se observa, se dará un cupo aparte a las sesiones válidas.
  - `CORS_ORIGINS` acepta `http://` en prod pero el mensaje dice `https://`: se resuelve en T011 junto con CORS.
  - Las lecturas con la clave de ejemplo responden `WRITES_DISABLED`; el nombre se mantiene por compatibilidad con el contrato 002.
  - `SessionStore` tipado con `Any`: se deja así porque el puerto no importa el modelo.
- Motivo: corregir todo lo barato y con un camino de explotación concreto; documentar el resto con su condición de disparo.
- Impacto: suben los tests de backend y de frontend; el contrato de la API no cambia.

## 2026-10-22 — T011: orden de los middlewares, hosts por servicios y cabeceras
- Contexto: el plan (§3) ponía `RequestId → TrustedHost → SecurityHeaders` de fuera hacia dentro.
- Decisión:
  - `SecurityHeadersMiddleware` va el **más externo**: así las cabeceras llegan también al 400 de host, al 413 y al 429, y el middleware convierte cualquier excepción no controlada en `500 INTERNAL_ERROR` con `request_id` y sin traza, que después relanza para que el servidor registre la traza (T012 y T018 completan el registro).
  - `ALLOWED_HOSTS` se lee de los servicios en cada petición, como los límites. El `Container` siempre lo fija (hay un test que lo comprueba) y los tests funcionales lo omiten.
  - CORS, HSTS y la documentación se fijan al crear la app con `create_app(services, config)`. Los tests usan la configuración por defecto, nunca el `.env` del desarrollador (fixture en `tests/conftest.py`).
  - `Cache-Control: no-store` va en **todas** las respuestas de la API (el contrato decía "autenticadas"): todas son JSON con datos personales o sin valor para la caché.
  - La CSP no se aplica a `/docs` ni `/redoc`, que solo existen en `dev` y cargan sus propios scripts.
  - En prod, `CORS_ORIGINS` solo admite `https://`, coherente con HSTS y con las cookies `Secure` (pendiente de T010).
  - CORS con orígenes, métodos y cabeceras explícitos, y `allow_credentials=True`, porque los orígenes son explícitos (prod rechaza `*`).
  - Zod se configura con `jitless` para no usar `new Function`, que la CSP bloquea.
- Motivo: que ninguna respuesta, ni siquiera un error de un middleware o una excepción, salga sin cabeceras; y que los tests no dependan de la máquina.
- Impacto: verificado en Chrome con `vite preview` (CSP aplicada): consola sin violaciones, el script del tema funciona desde un archivo y la fuente se carga con `font-src 'self'`. El servidor web de producción (T020, `docs/deploy.md`) debe enviar las mismas cabeceras que `frontend/security-headers.ts`.

## 2026-10-22 — T012: patrones algo más anchos que los datos y 500 registrado sin relanzar
- Contexto: la tarea pide patrones y longitudes máximas para `match_id`, `bookmaker`, `league` y `note`, rangos de fecha, tope de paginación y un 500 sin traza.
- Decisión:
  - Las reglas viven en tipos (`api/validation.py`) que sirven igual en cuerpos, consultas y rutas.
  - Los patrones son **algo más anchos** que los datos de hoy (cualquier liga de 1–8 alfanuméricos, cualquier casa en minúsculas). Así un valor bien formado pero desconocido sigue recibiendo su 404 del caso de uso, y solo lo malformado se corta con 422.
  - El 422 devuelve solo `loc`, `msg` y `type`: nunca `input` ni `ctx`, que podrían repetir una contraseña, un token o el texto ofensivo. Esto vale también para un JSON malformado.
  - `from` posterior a `to` es un 422 y no un resultado vacío.
  - El 500 ya no se relanza (T011 lo relanzaba para que el servidor registrara la traza). Ahora el middleware registra la traza con `logger.exception` en `betting_ml.api.errors`, junto con el `request_id`, el método y la ruta, y responde el 500 uniforme. Solo relanza si la respuesta ya había empezado. Motivo: una sola entrada de log por error, enlazable con el `request_id` que ve el cliente; T018 añadirá la redacción de secretos.
  - El frontend valida la moneda con el mismo patrón (solo letras) antes de enviarla.
- Impacto: verificado con mutaciones. Sin `extra="forbid"` fallan 7 tests; con los errores de Pydantic sin filtrar fallan 54.

## 2026-10-22 — T013: restricciones con los valores reales del esquema y PRAGMA verificados
- Contexto: la tabla del plan (§5) se escribió antes de leer `adapters/sql/models.py`, como el propio plan advierte.
- Decisión:
  - **Valores reales.** `outcome` se guarda como `H`/`D`/`A`, no `home`/`draw`/`away`. La cuota de `odds_quotes` se llama `odds`, no `price`. Las casas tienen `source` `api`/`manual` y `role` `reference`/`exchange`/`soft`. Los snapshots tienen `source` `the_odds_api`/`manual`.
  - **Restricciones añadidas sobre el plan:**
    - `ck_bets_settlement`: pendiente ⇔ sin beneficio y sin fecha de liquidación.
    - `ck_bets_profit`: perdida → −stake, nula → 0, ganada → ≥ 0, siempre en céntimos.
    - `result_source` ∈ {manual, official}; `fair_probability` ∈ [0, 1]; EV y CLV ∈ [−1, 1000]. Ambos valen cuota × probabilidad − 1.
    - Moneda `[A-Z]{3}`; `min_edge` ∈ [0, 1]; mes de `settings_history` con forma `YYYY-MM`; créditos ≥ 0.
    - Sesiones: hash de 64 caracteres y `last_seen_at ≥ created_at`.
  - **Pendiente para otras tareas.** `version >= 1` llega con la columna en T014 (migración 0006) y `audit_log` en T015.
  - **NOT NULL.** No faltaba ninguno: la migración 0001 ya coincide con los modelos.
  - **Migración 0005.**
    - Es una copia congelada de las reglas de los modelos; un test compara ambos esquemas.
    - Primero valida y, si hay filas inválidas, aborta listando `tabla.restricción: rowid …` (solo rowids, nunca valores) sin tocar nada.
    - Las bases creadas desde los modelos se saltan la reconstrucción.
    - El *batch mode* de Alembic 1.20 **conserva** los CHECK al reconstruir una tabla. Por eso el *downgrade* los quita uno a uno, y las migraciones futuras (0006) no los perderán.
  - **Cuotas inválidas.** El adaptador de The Odds API descarta las cuotas ≤ 1 o no numéricas, las cuenta y lo registra en el log. Así una cuota rara no hace fallar el snapshot entero con la nueva restricción.
  - **PRAGMA.** `foreign_keys=ON`, `busy_timeout=5000` y `journal_mode=WAL` se fijan en cada conexión. Una base en memoria no admite WAL y queda en `memory`. `prepare()` los relee y falla al arrancar (`DatabaseConfigError`) si alguno no se aplicó.
  - **`synchronous`.** Se mantiene en `FULL`, el valor por defecto: en WAL, `NORMAL` puede perder las últimas transacciones si se corta la luz, y aquí prima la integridad.
- Impacto:
  - Con WAL, la base son tres archivos (`app.db`, `-wal`, `-shm`). La copia de seguridad de T016 debe usar la API de *backup* de SQLite y no copiar el archivo.
  - Mutaciones comprobadas. Sin una restricción en 0005 fallan 3 tests; sin la validación previa, 1; sin WAL, 2.
  - Quitar `busy_timeout` no rompe nada porque `sqlite3` ya usa 5 s por defecto. Un test comprueba que `check_pragmas` detecta un timeout distinto.

## 2026-10-22 — T014: UPDATE condicional en lugar de `BEGIN IMMEDIATE`
- Contexto: el plan pedía que la liquidación usara `BEGIN IMMEDIATE` para no liquidar dos veces una apuesta.
- Decisión:
  - Toda escritura de una apuesta o de los ajustes es **un solo UPDATE condicional**: `... SET ..., version = version + 1 WHERE id = ? AND version = ?`. En SQLite cada sentencia es atómica y toma el bloqueo de escritura. De dos escritores con la misma versión, solo uno cambia la fila; el otro recibe `VersionConflictError`.
  - Esto da la garantía de `BEGIN IMMEDIATE` (ninguna apuesta se liquida dos veces) **sin cambiar el modo de transacción de todo el motor**. Con pysqlite, `BEGIN IMMEDIATE` obliga a desactivar su gestión de transacciones y afectaría a todas las escrituras.
  - La liquidación automática (`SettleBets`) guarda cada apuesta así. Si una apuesta cambió desde que la leyó (una liquidación manual u otra ejecución), la deja como está, la registra en el log y no la cuenta. La siguiente ejecución la reconcilia con el resultado oficial.
  - El caso de uso también compara la versión enviada con la leída, para responder 409 antes de validar el estado. El UPDATE condicional sigue siendo la garantía real frente a carreras.
  - Los ajustes por defecto, nunca guardados, tienen `version = 0`. El primer guardado es un `INSERT ... ON CONFLICT DO NOTHING`: de dos primeros guardados, solo uno gana. Un guardado perdedor no escribe historial (misma transacción).
  - El 409 lleva `details.current_version`.
  - Frontend:
    - Envía la `version` que leyó.
    - Ante un 409 en una apuesta, recarga la lista y muestra el aviso.
    - Ante un 409 en los ajustes, recarga el formulario con los valores guardados en otro lugar, nunca los sobrescribe a ciegas, y avisa. El siguiente guardado lleva la versión nueva.
  - Postman guarda la versión en variables de la colección y añade una petición con versión vieja (409).
- Impacto:
  - Migración 0006: columna `version` (las filas existentes empiezan en 1) con `CHECK version >= 1`. El *batch mode* conserva las restricciones de 0005; el test de esquema migrado = modelos lo comprueba (30 CHECK).
  - Mutaciones comprobadas:
    - UPDATE de apuestas sin la condición de versión: fallan 3 tests.
    - Ajustes sin la condición: falla 1.
    - Liquidación que no captura el conflicto: fallan 2.
    - Formulario que no se recarga tras el 409: falla 1.

## 2026-10-22 — T015: auditoría registrada por los repositorios, estados en crudo y línea base
- Contexto: la auditoría debe ir en la misma transacción que el cambio, cubrir apuestas, ajustes, login/logout, liquidación y cuotas, y `verify-integrity` debe comparar cada apuesta con su último evento.
- Decisión:
  - **Dónde vive.** El dominio puro está en `domain/audit.py`, no en `security.py` como decía el plan, porque son conceptos distintos. El caso de uso `VerifyIntegrity` está en `application/maintenance.py`, donde T016 añadirá los backups. El adaptador está en `adapters/sql/audit.py`.
  - **Toda escritura de los repositorios SQL añade su evento en la misma transacción**, aunque quien llame no lo pida. No hay forma de cambiar una apuesta, los ajustes o un snapshot por la aplicación sin dejar rastro.
    - Los casos de uso pasan `AuditInfo(actor, acción)`. Sin actor conocido, el actor es `system`.
    - Actores: `session`, `api_key`, `cli` y `scheduler`. Además: `migration` (línea base), `anonymous` (login fallido) y `system`.
    - La API toma el actor del `Principal` autenticado. La CLI tiene `--actor cli|scheduler` en `settle` y `odds`, y el refresco automático usa `scheduler`.
  - **Estados en crudo.** El "antes" y el "después" son la fila tal como la guarda SQLite (`SELECT *`), leída dentro de la transacción. Así el evento escrito ahora, la línea base de la migración y la comprobación de `verify-integrity` ven exactamente los mismos valores, sin conversiones de `Decimal` ni de fechas.
    - Incluyen `version`, así que un cambio que no la suba también se detecta.
    - De los snapshots de cuotas se guarda un resumen (fuente, ligas, nº de cuotas, créditos), no las cuotas.
  - **Bloqueo primero.** Cada escritura auditada empieza con una escritura que no toca filas (`UPDATE audit_log SET seq = seq WHERE 0`) y que toma el bloqueo de escritura de SQLite. pysqlite no abre la transacción hasta la primera escritura; sin esto, dos altas simultáneas leían la misma cabeza de la cadena. Un test con 4 hilos lo demuestra: sin el bloqueo falla con `UNIQUE constraint failed: audit_log.seq`.
  - **Línea base.** La migración 0007 crea la tabla y los *triggers* y sella un evento `BASELINE` por cada apuesta y ajuste ya existentes. Desde entonces, una apuesta sin eventos es una inserción hecha fuera de la aplicación.
    - La migración usa las funciones puras del dominio. El formato del *payload* lleva `"v": 1` y nunca cambia en el sitio.
  - **Login y logout.** Se auditan `LOGIN_OK`, `LOGIN_FAILED` (con la IP del cliente) y `LOGOUT`. Nunca se guardan la contraseña, el token ni su hash.
    - Las sesiones caducadas que se borran al usarse o en la purga son mantenimiento y no se auditan.
    - Los intentos bloqueados por fuerza bruta no llegan a Argon2 ni a la auditoría: los registrará el log de seguridad (T018). Esto también limita lo que un atacante puede hacer crecer la tabla.
  - **`verify-integrity`** comprueba cinco cosas y termina con código 1 si alguna falla:
    - `PRAGMA integrity_check` y `PRAGMA foreign_key_check`.
    - La cadena: secuencia sin huecos, enlace, hash y columnas iguales a lo firmado.
    - Cada apuesta y los ajustes iguales al "después" de su último evento.
    - Las filas sin eventos.
    - Las filas que faltan sin un evento de borrado.
- Alcance (riesgo aceptado, ya previsto en la spec):
  - La cadena no detecta que se recorten los **últimos** registros si las filas afectadas vuelven a su estado anterior.
  - Tampoco detecta que alguien con el archivo `.db` reescriba toda la cadena. Eso lo cubren las copias de seguridad con hash fuera del equipo (T016).
- Impacto: mutaciones comprobadas.
  - Sin el evento en `update`: fallan 5 tests.
  - Sin los *triggers*: falla 1 (en las bases de archivo los crea la migración, que cubren otros tests).
  - Sin comprobar el hash: fallan 41.
  - Sin comparar estados: fallan 5.
  - Sin el bloqueo previo: falla el test de concurrencia.

## 2026-10-22 — T016: copias con la API de backup de SQLite y restauración verificada dentro de SQLite
- Contexto: `betting-ml backup` / `restore` con `.sha256`, retención `BACKUP_KEEP` y copia previa al restaurar. La base está en WAL, así que copiar el archivo `.db` a mano puede dejar fuera lo que aún está en el `-wal` o capturar una página a medio escribir.
- Decisión:
  - **Copia en caliente con la API de backup de SQLite** (`sqlite3.Connection.backup`), en un solo paso y bajo el bloqueo de lectura de SQLite. Es coherente aunque la API esté escribiendo. Un test toma 6 copias mientras otro hilo crea y edita apuestas; todas pasan las comprobaciones de SQLite y la auditoría.
  - **Cada copia es un único archivo.** Se pasa a `journal_mode=DELETE` (sin `-wal` ni `-shm`), así el SHA-256 del `.db` identifica la copia completa.
    - El `.sha256` va al lado, en formato `sha256sum` (`<hash>  <nombre>`), y se puede comprobar con `sha256sum -c` en otra máquina.
    - La copia se verifica (`integrity_check`, `foreign_key_check`, tablas de la aplicación) antes de escribir el hash. Si falla, se borra y el comando termina con código 1.
  - **Nombres y retención.** Los nombres son `app-AAAAMMDD-HHMMSS.db`, con sufijo `-2`, `-3`… si coinciden en el mismo segundo.
    - La rotación ordena por (fecha, sufijo) leídos del nombre, no por orden alfabético. Por orden alfabético, `…-2.db` va antes que `….db` y se habría borrado la copia más nueva. Un test lo cubre.
    - Los archivos que no siguen el formato nunca se borran.
    - Las copias previas a una restauración (`pre-restore-…`) rotan aparte, también con `BACKUP_KEEP`, y no desplazan a las copias normales.
  - **La restauración verifica antes de tocar nada.** Lo que se comprueba, en orden:
    1. Existe la copia.
    2. Existe su `.sha256`, que contiene un SHA-256 válido que coincide con el archivo.
    3. Las comprobaciones de SQLite y las tablas de betting-ml pasan.
    4. Si la copia tiene `audit_log`, pasa la verificación completa de T015: cadena, y apuestas y ajustes iguales a su último evento.
    - El paso 4 importa. Quien edita una apuesta en la copia y recalcula el `.sha256` supera los pasos 1–3, pero no la auditoría. Un test lo demuestra.
    - Los candidatos se abren en **solo lectura e inmutables** (`mode=ro&immutable=1`): verificarlos nunca escribe un byte, así que su hash sigue valiendo.
    - No se acepta como copia la propia base activa.
  - **Restaurar es copiar dentro de SQLite, no cambiar archivos.** Primero se guarda una copia verificada del estado actual (`pre-restore-…`). Después la API de backup escribe la copia sobre la base activa, bajo el bloqueo de SQLite, y la base vuelve a WAL.
    - Mover o renombrar archivos con conexiones abiertas (y en Windows, con archivos bloqueados) puede dejar un `-wal` viejo aplicado sobre la base nueva.
    - La rotación nunca borra la copia que se está restaurando. Así, deshacer una restauración desde su `pre-restore` funciona aunque `BACKUP_KEEP=1`.
  - **Confirmación.** `restore` verifica, muestra los problemas (código 1) o pide confirmación. `--yes` la omite, para scripts.
    - Se recomienda detener la API antes de restaurar. Si sigue en marcha, la restauración espera a su bloqueo de escritura y es coherente, pero las sesiones en curso verán el cambio de golpe.
    - Restaurar una copia de un esquema anterior funciona: la API la migra al arrancar (las migraciones validan antes de cambiar nada, T013).
  - **Arquitectura.**
    - El puerto `DatabaseFiles` está en el dominio.
    - El adaptador es `adapters/sql/backup.py`.
    - Los casos de uso `BackupDatabase` y `RestoreDatabase` están en `application/maintenance.py`, junto a `VerifyIntegrity`, que reutilizan.
    - El contenedor los construye desde la configuración sin abrir la base por `db_sessions`, así que no se migra nada antes de copiar o restaurar.
- Alcance: las copias se quedan en `data/backups/`, en la misma máquina. Sacarlas fuera del equipo (con su `.sha256`) es parte del despliegue (T020, `docs/deploy.md`). Es lo que cubre el riesgo, aceptado en T015, de que alguien con el archivo reescriba toda la cadena.
- Impacto: mutaciones comprobadas, todas detectadas.
  - Sin comparar el hash: fallan 2 tests.
  - Sin la verificación de auditoría: fallan 2.
  - Sin la copia previa: fallan 3.
  - Sin proteger el candidato de la rotación: falla 1.
  - Copia en WAL: falla 1.
  - Aceptar la base activa: falla 1.
  - Rotar por orden alfabético: falla 1.
  - Conservar una copia que no pasó la verificación: falla 1.

## 2026-10-22 — T017: hash de los modelos y checkpoint 🔍 de integridad (T013–T017)
- Contexto: `joblib.load` ejecuta el código que nombre el pickle (A08). La spec pide registrar el SHA-256 de `model.joblib` en `metadata.json` y no cargar nada que no coincida.
- Decisión (modelos):
  - **Clave.** `metadata.json` guarda el hash en la clave `sha256`. `JoblibModelRegistry.save` lo escribe siempre.
  - **Carga.** `load` lee el archivo una vez, calcula el hash de esos bytes y deserializa **los mismos bytes** (`io.BytesIO`), así que no hay ventana para cambiar el archivo entre la comprobación y la carga. Se rechazan con `ModelIntegrityError`:
    - un hash que falte o no tenga formato SHA-256;
    - un `metadata.json` ilegible;
    - un hash distinto.
  - **API.** La aplicación convierte el error en `ModelNotVerifiedError`, subclase de `ModelNotAvailableError`. Así, todo lo que ya trataba el "modelo no disponible" sigue funcionando: `/health` responde `model_loaded=false`, el arranque registra un error en el log y la lista de ligas muestra 0 equipos.
    - Las rutas responden `503 MODEL_INTEGRITY_ERROR` con `details.version` y sin rutas de archivo.
    - Un test con un pickle malicioso (con control positivo de que ejecuta código) demuestra que nunca se deserializa.
  - **Escritura de `metadata.json`.** Se escribe en un temporal y se cambia con `os.replace`: una escritura interrumpida nunca deja medio archivo.
  - **`betting-ml models-rehash` (+ make).** Lista cada modelo con su hash y su estado (`sin registrar`, `ya registrado` o `DISTINTO DEL REGISTRADO`) y pide confirmación (`--yes` para scripts).
    - Solo registra los que no tienen hash, y solo si el archivo sigue teniendo el hash que se mostró.
    - Nunca reemplaza un hash distinto: termina con código 1 y no escribe nada.
  - **Nota operativa.**
    - Los `metadata.json` versionados de E06 y E12 no tienen hash, y en esta máquina no hay `model.joblib`, así que hoy no cambia nada.
    - `train-prod` guarda los modelos nuevos ya con su hash.
    - Si se copian modelos de otra máquina, hay que revisarlos y ejecutar `models-rehash`. Hasta entonces la API responde `503 MODEL_INTEGRITY_ERROR`.
- Alcance (riesgo aceptado, hallazgo M3 del checkpoint): esto es **integridad, no autenticidad**. Quien puede reemplazar `model.joblib` también puede reescribir `metadata.json`.
  - El ancla es git: `metadata.json` está versionado, así que un hash nuevo o cambiado aparece en `git diff` y en la revisión.
  - Para autenticidad haría falta un HMAC con una clave fuera de `models/` (ver "Decisión del dueño (M2 y M3)" más abajo).

### Checkpoint 🔍 (ml-reviewer, T013–T017)
Veredicto inicial: **bloqueado** por dos hallazgos altos, ambos reproducidos. Lo confirmado como correcto:
- Las migraciones 0005–0007 conservan filas, CHECK, claves foráneas e índices al subir de 0004 a la última.
- Toda escritura de apuestas, ajustes y snapshots va con su evento y su `version`.
- Los backups son coherentes.
- Ninguna otra ruta deserializa modelos.

Corregido en este mismo commit, con tests negativos:
- **A1 (alto): el historial de límites no estaba auditado.** El límite vigente se calcula a partir de `settings_history` (subir el límite solo aplica el mes siguiente). Un `UPDATE ... SET effective_from` por SQL aplicaba la subida al instante y `verify-integrity` no decía nada.
  - Ahora cada fila del historial es una entidad auditada (`settings_change`, evento `SETTINGS_HISTORY_ADDED` con `effective_from`, en la misma transacción que el cambio de ajustes).
  - `verify-integrity` la compara con su último evento, igual que las apuestas: detecta filas cambiadas, borradas o insertadas.
  - La **migración 0008** sella un `BASELINE` de las filas existentes tras la cabeza de la cadena. No cambia ni borra nada, y no repite el sellado si se vuelve a subir.
- **A2 (alto): el downgrade de 0007 borraba la auditoría.** Después, subir de nuevo sellaba un `BASELINE` nuevo sobre datos manipulados ("blanqueo"). Ahora el downgrade **aborta** si `audit_log` tiene algún evento y no toca nada. El downgrade de 0008 no borra sus eventos.
- **M1 (medio): no se podía restaurar justo cuando la base activa estaba dañada.** La copia previa fallaba y la CLI terminaba con un traceback.
  - Ahora `restore` explica el problema y termina con código 1.
  - Con `--force` guarda una copia en bruto (`unverified-pre-restore-…db`, con su `-wal`/`-shm`, nunca rotada) y restaura igualmente sobre archivos nuevos (la API debe estar parada).
- **M2/E5 (medio): una copia sin `audit_log` se restauraba sin verificar su contenido.** Bastaba con editarla, borrar la tabla, marcarla como 0006 y recalcular el `.sha256`. Ahora se rechaza salvo `--allow-legacy` explícito. Esto corrige la afirmación del "paso 4" de T016.
- **Bajos corregidos:**
  - `restore` cierra todas las sesiones (una cerrada después de la copia habría revivido con ella) y registra el evento `DB_RESTORED` con el archivo, su hash y la copia previa.
  - `verify-integrity` comprueba que existen los triggers de solo inserción.
  - `metadata.json` se escribe de forma atómica y, si está ilegible, cuenta como fallo de integridad.
  - `models-rehash` registra solo los hashes que el dueño vio.
  - El test de páginas corruptas comprobaba `"" in p` (siempre verdadero); ahora exige el error de SQLite.
  - Si la copia en caliente falla porque la base está dañada, se informa como problema y no como excepción de `sqlite3`.

No corregido (riesgo aceptado, con su alcance real):
- **M2, encadenado sin clave.**
  - **Corrección al alcance declarado en T015:** no hace falta reescribir toda la cadena para engañarla. Quien tiene escritura sobre el archivo `.db` y conoce el formato puede **añadir** eventos válidos al final y cuadrar cualquier cambio. Las copias externas tampoco lo detectan, porque la cadena antigua sigue siendo prefijo de la nueva; sí conservan el estado real anterior para compararlo.
  - Lo que la cadena sí garantiza:
    - detecta cambios hechos fuera de la aplicación sin forjar eventos (SQL a mano, herramientas, errores);
    - detecta registros alterados, borrados o reordenados;
    - detecta triggers eliminados.
  - Protege frente a errores y manipulaciones ingenuas, no frente a un atacante con acceso al archivo y conocimiento del código.
- **TOCTOU local de `restore`.** La copia se vuelve a leer del disco tras verificarla. Aprovecharlo exige escribir en `data/backups/` durante la restauración, es decir, acceso local de escritura.
- **Snapshots y cuotas.** No se comparan con sus eventos (se audita un resumen). Las cuotas vienen de la API y se pueden volver a pedir.
- **Borrado de apuestas.** `delete` no condiciona en SQL por `status`. La ventana de carrera es prácticamente nula porque el caso de uso lo niega tras el inicio del partido.
- **Importación del dominio en 0007/0008.** Usan `domain.audit` en vivo. Su formato lleva `"v": 1` y nunca cambia en el sitio: un formato nuevo sería `v: 2` y conservaría el de `v1`.
- **Downgrade de 0006.** Elimina la columna `version`. Es metadato de concurrencia, no son datos del usuario.
- **Columna `ts_utc` de `audit_log`.** No se compara con la firmada. La hora firmada va en el payload; la columna es una copia para consultas.
- **Test de concurrencia.** El test de 2 hilos de `test_concurrency.py` no es determinista, pero lo cubre el test determinista con `RacingRepository`.

**Decisión del dueño (M2 y M3), 2026-10-22: se acepta el riesgo y se sigue sin HMAC.** La propuesta descartada por ahora era encadenar la auditoría con **HMAC** y firmar los hashes de los modelos con una clave nueva que solo esté en `.env` (`AUDIT_KEY`). Así, forjar eventos o modelos exigiría robar también `.env`.
- Costes:
  - un secreto más que custodiar y respaldar aparte (sin él no se puede verificar la cadena);
  - formato `v: 2`;
  - una migración que firme la cabeza actual.
- Se puede retomar en T021 si la auditoría final lo pide.

- Impacto: mutaciones comprobadas, todas detectadas.
  - **T017:**
    - Sin comparar el hash del modelo: fallan 5 tests.
    - Aceptar modelos sin hash: fallan 6.
    - Guardar sin hash: fallan 9.
    - Rehash que reemplaza un hash distinto: falla 1.
    - Sin el código `MODEL_INTEGRITY_ERROR`: falla 1.
    - Error sin traducir: falla 1.
  - **Checkpoint:**
    - Historial fuera de la verificación: fallan 4.
    - Downgrade que borra la auditoría: falla 1.
    - Aceptar una copia sin auditoría: fallan 2.
    - Sin exigir `--force`: fallan 2.
    - Sesiones que reviven: falla 1.
    - Sin comprobar triggers: falla 1.
    - Rehash sin comparar lo mostrado: falla 1.

## 2026-10-22 — T018: un único manejador de logs con redacción en el formateador
- Contexto: logs en JSON en `prod` con `request_id`, método, ruta, estado y duración. Ninguna contraseña, cookie, `X-API-Key`, `apiKey` ni `ODDS_API_KEY`. Además, eventos de seguridad. La imagen Docker arranca `uvicorn` directamente, y uvicorn configura sus propios loggers antes de cargar la app. Su log de acceso escribe la URL **con la query string** y sin `request_id`.
- Decisión:
  - **`logging_config.configure_logging`** instala un único manejador en el logger raíz. Se llama en el arranque de la API (`lifespan`, después de la configuración de uvicorn, a la que sustituye) y en la CLI.
    - El formato es JSON o texto según `LOG_FORMAT`: JSON por defecto en `prod`, texto en `dev`.
    - Los loggers `uvicorn` y `uvicorn.error` pasan al manejador de la aplicación.
    - `uvicorn.access` se desactiva. Lo sustituye `betting_ml.access`, con una línea por petición: método, ruta **sin query string**, estado, duración y cliente. Una excepción no capturada se registra como 500.
  - **`request_id` en cada línea.** El middleware fija un `ContextVar` que copia un filtro del manejador. Llega también a las rutas síncronas (threadpool) y a los manejadores de errores. Fuera de una petición vale `-`.
  - **La redacción va en el formateador, no en quien escribe el log**, así que cubre cualquier logger: los de la aplicación, uvicorn, httpx o un `logger.info(headers)` descuidado. En JSON se redacta cada valor **antes** de serializar; sobre el JSON ya escapado, los patrones no verían las comillas. Se redacta:
    - el valor literal de cada `SecretStr` de la configuración (8 caracteres o más);
    - los pares `nombre=valor`, `nombre: valor`, `"nombre": "valor"` y `('nombre', b'valor')`, cuando el nombre contiene password, secret, token, cookie, api-key/apikey, authorization o `bml_session` (con `Bearer`/`Basic` incluidos);
    - los hashes Argon2 completos (sus parámetros llevan comas).
  - **Eventos de seguridad** en `betting_ml.security`. En JSON van con el campo `event`; en texto, como `EVENTO clave=valor`:
    - `LOGIN_OK`, `LOGOUT`, `LOGIN_FAILED` y `LOGIN_LOCKED`, este último con `retry_after`;
    - `ACCESS_DENIED` en todo 401/403, con su `code` (`UNAUTHORIZED`, `CSRF_FAILED`…);
    - `SETTINGS_CHANGED`, con cada cambio y el mes en que entra en vigor;
    - `INTEGRITY_CHECK_FAILED`, con el número de problemas y los tres primeros;
    - `MODEL_INTEGRITY_FAILED` al arrancar.
    - Todos llevan el cliente y nunca la contraseña, el token ni la clave.
  - **Tests.** Leen la **salida real del manejador**, que es lo que llega al log. `caplog` captura antes de los filtros y del formateador del manejador, así que no demostraría la redacción; solo se usa para los eventos de la capa de aplicación.
    - Un test end to end envía contraseña, clave correcta e incorrecta, cookie de sesión, token CSRF y `?apiKey=` en la query, y escribe una línea descuidada con cabeceras, cuerpo, URL de The Odds API y el hash.
    - Comprueba que ningún secreto aparece en la salida, que hay una línea de acceso por petición sin query string, que los eventos salen en orden y que cada uno lleva el `request_id` de su petición.
- Impacto: mutaciones comprobadas, todas detectadas.
  - Sin redactar los valores de los secretos: fallan 4 tests.
  - Sin los pares entre comillas: fallan 5.
  - Sin los pares sin comillas: fallan 8.
  - Sin los hashes Argon2: falla 1.
  - JSON sin redactar: fallan 2.
  - Access log de uvicorn activo: falla 1.
  - Ruta con query string: fallan 2.
  - Sin `request_id`: fallan 2.
  - Sin el evento 401/403: falla 1.
  - Sin el evento de bloqueo: falla 1.
