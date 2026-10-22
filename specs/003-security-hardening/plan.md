# Plan técnico — Spec 003 (seguridad, integridad y arquitectura)

Plan de desarrollo de [`spec.md`](spec.md). El contrato nuevo de la API está en [`contracts/api.md`](contracts/api.md) y las tareas en [`tasks.md`](tasks.md).

## 1. Estrategia

Se avanza **de adentro hacia afuera**, para que cada control nuevo se monte sobre una base ordenada:

| Fase | Objetivo | Tareas |
|---|---|---|
| 0. Preparación | Integrar la spec y medir el punto de partida (línea base de seguridad). | T001–T002 |
| 1. Arquitectura | Configuración por entorno, routers por recurso, contenedor tipado y un único módulo de seguridad. Sin cambiar el contrato. | T003–T005 |
| 2. Identidad y acceso | Login con sesión, CSRF, protección de todas las rutas, rate limit y frontend con login. | T006–T010 🔍 |
| 3. Endurecimiento HTTP | Cabeceras, CORS, hosts, errores y validación estricta. | T011–T012 |
| 4. Integridad de datos | Restricciones en la base, concurrencia, auditoría encadenada, backups y hash de modelos. | T013–T017 🔍 |
| 5. Operación | Logs seguros, cadena de suministro en CI y Docker endurecido. | T018–T020 |
| 6. Cierre | Auditoría final, documentación y verificación de punta a punta. | T021–T022 🔍 |

Cada tarea sigue el flujo del proyecto: tests primero (sobre todo los **negativos**), implementar, `lint + test` (+ `web-test` si toca el frontend), marcar `[x]`, línea en `PROGRESS.md` y un commit (Conventional Commits) en la rama `Daniel`. **Después de cada tarea se pide confirmación al dueño antes de seguir.**

## 2. Stack añadido

| Necesidad | Herramienta | Motivo |
|---|---|---|
| Hash de contraseña | `argon2-cffi` (Argon2id) | Recomendación de OWASP; resistente a GPU. |
| Tokens y comparaciones | `secrets`, `hmac.compare_digest` (stdlib) | Aleatoriedad criptográfica y comparación en tiempo constante. |
| Rate limit, CSRF, cabeceras | Middlewares propios (Starlette) | Poco código, sin dependencias abandonadas, fáciles de testear. |
| Análisis estático | ruff con reglas `S` (bandit) | Ya se usa ruff; no suma una herramienta. |
| Vulnerabilidades | `pip-audit`, `npm audit` | Bases de datos de CVE de PyPI y npm. |
| Secretos | `gitleaks` (pre-commit y CI) | Detecta claves antes de que lleguen al historial. |
| Dependencias | Dependabot | Actualizaciones de pip, npm y Actions. |

## 3. Arquitectura objetivo

```
src/betting_ml/
├── api/
│   ├── main.py                 # create_app(): middlewares en orden + routers
│   ├── security.py             # NUEVO: require_auth, require_csrf, Principal, verificación de clave
│   ├── middleware/             # NUEVO
│   │   ├── request_id.py       #   X-Request-ID + contexto de logging
│   │   ├── security_headers.py #   CSP, nosniff, frame, referrer, permissions, HSTS, no-store
│   │   ├── body_limit.py       #   413 para cuerpos > 64 KB
│   │   └── rate_limit.py       #   ventana deslizante por clave (IP/sesión/ruta)
│   ├── errors.py               # + 500 genérico con request_id; 422 sin valores de entrada
│   ├── dependencies.py         # get_services() tipado (Protocol)
│   ├── mappers/                # NUEVO: dominio -> schemas (sale de journal.py)
│   └── routers/
│       ├── auth.py             # NUEVO: login, logout, me
│       ├── odds.py  bookmakers.py  comparator.py  calculator.py
│       ├── bets.py  settings.py  backtest.py      # salen de journal.py
│       └── (los de la spec 001 sin cambios funcionales)
├── application/
│   ├── authenticate.py         # NUEVO: login/logout/validar sesión (usa puertos)
│   ├── audit.py                # NUEVO: registrar eventos, verificar cadena
│   ├── maintenance.py          # NUEVO: backup, restore, verify-integrity
│   └── read_backtest.py        # NUEVO: sale del router
├── domain/
│   ├── ports.py                # + SessionStore, AuditLog, PasswordHasher, RateLimiter, ReportStore
│   ├── security.py             # NUEVO: Session, Principal, AuditEvent, canonicalización y hash de cadena (puro)
│   └── (sin cambios en la lógica de apuestas y límites)
├── adapters/
│   ├── argon2_hasher.py        # NUEVO
│   ├── memory_rate_limiter.py  # NUEVO
│   ├── sql/                    # + SessionRow, AuditRow, columnas version, CHECKs
│   ├── sql/backup.py           # NUEVO: API de backup de SQLite + SHA-256
│   ├── report_store.py         # NUEVO
│   └── joblib_registry.py      # + verificación SHA-256 antes de joblib.load
├── logging_config.py           # NUEVO: JSON en prod, filtro de redacción
└── config.py                   # + APP_ENV, SecretStr, validación fail-fast
```

Reglas:
- El **dominio** solo conoce conceptos puros: `Session` (id hasheado, expiraciones), `AuditEvent` y la función que encadena hashes. No conoce cookies ni HTTP.
- **`api/security.py`** traduce HTTP → `Principal` (`kind: session|api_key`) y es la única puerta de autenticación. Los routers privados se registran con `dependencies=[Depends(require_auth)]` a nivel de `APIRouter`; las escrituras añaden `require_csrf`.
- La auditoría se escribe en **la misma transacción** que el cambio auditado (los repositorios SQL reciben el evento), para que no haya cambios sin rastro ni rastros sin cambio.

### Orden de los middlewares (de afuera hacia adentro)

1. `RequestIdMiddleware`: asigna o propaga `X-Request-ID`.
2. `TrustedHostMiddleware`: `ALLOWED_HOSTS`.
3. `SecurityHeadersMiddleware`: cabeceras en **todas** las respuestas, también en errores.
4. `CORSMiddleware`: orígenes explícitos y `allow_credentials=True` solo con orígenes concretos.
5. `BodyLimitMiddleware`: 413.
6. `RateLimitMiddleware`: global; el login y el refresco tienen límites propios por dependencia.
7. Routers (autenticación y CSRF como dependencias).

## 4. Diseño de autenticación y sesiones

```
Navegador                         API                                   SQLite
   │ POST /auth/login {password}   │                                      │
   │──────────────────────────────►│ rate limit (IP) ─► Argon2id.verify   │
   │                               │ token = secrets.token_urlsafe(32)    │
   │                               │ csrf  = secrets.token_urlsafe(32)    │
   │                               │ INSERT sessions(sha256(token), ...) ─►│
   │◄──────────────────────────────│ Set-Cookie bml_session=token;        │
   │  200 {csrf_token, expires_at} │   HttpOnly; SameSite=Strict; Secure  │
   │                               │ audit: LOGIN_OK                     ─►│
   │ GET /api/v1/bets (cookie)     │                                      │
   │──────────────────────────────►│ require_auth: sha256(cookie) ─► sesión vigente
   │                               │ desliza la expiración por inactividad│
   │ POST /api/v1/bets (cookie +   │                                      │
   │   X-CSRF-Token)               │ require_csrf: compare_digest(header, csrf de la sesión)
```

- **Por qué sesión de servidor y no JWT:** se puede revocar al instante (logout, cambio de contraseña), el token no lo lee JavaScript (`HttpOnly`) y no hay que gestionar claves de firma ni listas de revocación.
- **CSRF:** el token CSRF se entrega en el cuerpo del login y en `GET /auth/me`; el frontend lo guarda **en memoria** (no en `localStorage`) y lo envía en `X-CSRF-Token`. `SameSite=Strict` es la primera barrera; el token, la segunda.
- **Clave de máquina:** `X-API-Key` válida produce un `Principal(kind="api_key")` y no necesita CSRF (no la envía el navegador de forma automática). Para Postman y la CLI.
- **Cambio de contraseña:** regenerar `APP_PASSWORD_HASH` y reiniciar invalida todas las sesiones (cada sesión guarda la huella del hash vigente).
- **Expiración:** `SESSION_IDLE_MINUTES=30` y `SESSION_MAX_HOURS=12`; las sesiones vencidas se purgan al arrancar y cada hora.

## 5. Integridad de datos

### Restricciones (migración 0005)

| Tabla | Restricciones |
|---|---|
| `bets` | `odds > 1`, `stake > 0`, `kind IN ('real','paper')`, `status IN ('pendiente','ganada','perdida','nula')`, `outcome IN ('home','draw','away')`, `profit` nulo si está pendiente, `version >= 1` |
| `settings` | `bankroll >= 0`, `monthly_loss_limit >= 0`, `max_stake > 0`, `0 < kelly_fraction <= 1`, `version >= 1` |
| `odds_quotes` | `price > 1` |
| `sessions` | `expires_at > created_at`, `token_hash` único |
| `audit_log` | `seq` único y creciente, `hash` de 64 hex, `prev_hash` igual al `hash` del registro anterior (lo verifica la aplicación) |

La migración valida los datos antes de recrear las tablas (SQLite necesita *batch mode* para añadir `CHECK`). Si hay filas inválidas, aborta y las lista; nunca borra ni corrige en silencio. Los nombres reales de las columnas se toman de `adapters/sql/models.py` al implementarla.

### Auditoría encadenada

```
hash_n = SHA-256( hash_{n-1} || canonical_json(seq, ts_utc, actor, action, entity, entity_id, before, after) )
hash_0 = SHA-256("betting-ml-audit-genesis")
```

- `canonical_json`: claves ordenadas, sin espacios, `Decimal` como texto: el mismo evento produce siempre el mismo hash.
- Triggers `BEFORE UPDATE` y `BEFORE DELETE` sobre `audit_log` con `RAISE(ABORT, ...)`.
- `verify-integrity` recorre la cadena, compara el estado de cada apuesta con su último evento y corre `PRAGMA integrity_check` y `PRAGMA foreign_key_check`.

### Concurrencia

- Columna `version` en `bets` y `settings`. `PATCH` y `PUT` reciben `version`; el `UPDATE ... WHERE id = ? AND version = ?` que no afecta filas devuelve `409 VERSION_CONFLICT`.
- La liquidación usa `BEGIN IMMEDIATE` para no liquidar dos veces la misma apuesta.
- SQLite: `journal_mode=WAL`, `busy_timeout=5000` y `foreign_keys=ON`, comprobados al arrancar.

### Backups y modelos

- `backup`: `sqlite3.Connection.backup()` (copia consistente en caliente) → `data/backups/app-AAAAMMDD-HHMMSS.db` + `.sha256`; retención `BACKUP_KEEP=14`.
- `restore`: verifica el SHA-256 y `integrity_check` de la copia, respalda el estado actual y reemplaza con la API detenida.
- Modelos: `metadata.json` guarda `sha256` de `model.joblib`; `JoblibRegistry.load` lo verifica antes de deserializar. Los modelos existentes se migran con `betting-ml models-rehash` (una sola vez, tras inspección manual).

## 6. Configuración nueva (`.env.example`)

```
APP_ENV=dev                          # dev | prod
APP_PASSWORD_HASH=                   # betting-ml hash-password
APP_API_KEY=                         # >= 32 caracteres (python -c "import secrets;print(secrets.token_urlsafe(32))")
SESSION_SECRET=                      # >= 32 bytes; huella de sesiones
SESSION_IDLE_MINUTES=30
SESSION_MAX_HOURS=12
ALLOWED_HOSTS=localhost,127.0.0.1
CORS_ORIGINS=http://localhost:5173
RATE_LIMIT_PER_MINUTE=120
LOGIN_MAX_ATTEMPTS_PER_MINUTE=5
ODDS_REFRESH_MAX_PER_HOUR=6
MAX_BODY_BYTES=65536
BACKUP_KEEP=14
LOG_FORMAT=text                      # text | json (json por defecto en prod)
```

`ADMIN_API_KEY` se acepta durante una versión como alias de `APP_API_KEY`, con un aviso en el log.

## 7. Frontend

- Página `/login`. Un `AuthProvider` con TanStack Query (`/auth/me`) protege todas las rutas; un `401` lleva al login.
- Se elimina `lib/apiKey.ts` y el botón de clave: **nada de secretos en `localStorage`**.
- `openapi-fetch` con `credentials: "same-origin"` y `X-CSRF-Token` (en memoria) en las escrituras.
- El script de tema de `index.html` se mueve a `public/theme-init.js` para cumplir la CSP sin `unsafe-inline`.
- Tests MSW: login correcto e incorrecto, 429 del login, redirección por 401, CSRF enviado en escrituras, logout.

## 8. Tests de seguridad (obligatorios)

| Control | Tests negativos mínimos |
|---|---|
| Autenticación | Sin credenciales → 401 en **cada** ruta de OpenAPI salvo la lista pública (test generado desde `app.routes`); cookie alterada, vencida o de sesión cerrada → 401; contraseña incorrecta → 401 con mensaje genérico. |
| CSRF | Escritura con cookie sin token o con token de otra sesión → 403; con `X-API-Key` no se exige. |
| Rate limit | 6.º intento de login en un minuto → 429 con `Retry-After`; bloqueo progresivo. |
| Cabeceras | Presentes en 200, 401, 404, 422 y 500. |
| Configuración | `APP_ENV=prod` con cada valor inseguro → el arranque falla; `repr(settings)` no contiene secretos. |
| Errores | Excepción no controlada → 500 sin traza y con `request_id`; 422 sin el valor enviado. |
| Base de datos | `INSERT` directo con cuota 0.5 o stake negativo → `IntegrityError`; `UPDATE`/`DELETE` en `audit_log` → error. |
| Auditoría | Alterar un registro (saltando el trigger en el test) → `verify-integrity` falla e indica el `seq`. |
| Concurrencia | Dos `PATCH` con la misma versión → uno 200 y otro 409. |
| Modelos | `model.joblib` alterado → no se carga. |
| Logs | Petición con contraseña, cookie y clave → nada de eso aparece en los logs capturados. |

## 9. Comandos nuevos

```
make security        # ruff --select S, pip-audit, npm audit, gitleaks
make backup | restore FILE=... | verify-integrity
betting-ml hash-password            # pide la contraseña sin eco y muestra el hash Argon2id
betting-ml models-rehash            # una vez, para modelos anteriores a esta spec
```

## 10. CI

- `permissions: contents: read` a nivel de workflow; acciones fijadas por SHA (con el tag como comentario).
- Job `security`: `ruff check --select S`, `pip-audit` (con `uv export`), `npm audit --audit-level=high` y `gitleaks`.
- `.github/dependabot.yml` para `pip`, `npm` (`/frontend`) y `github-actions`, semanal.
- El test de la colección de Postman y el de OpenAPI siguen corriendo con las rutas de `auth`.

## 11. Despliegue

- Dockerfile: imagen base fijada por digest, usuario no root (ya existe), `--proxy-headers --forwarded-allow-ips` solo con un proxy de confianza, `HEALTHCHECK` sobre `/health`.
- `docs/deploy.md`: ejemplo con Caddy (TLS automático) delante de la API y del frontend construido; contenedor con `--read-only` y volúmenes solo para `data/`, `models/` y `reports/`.

## 12. Revisiones 🔍

- **T010** (tras identidad y acceso), **T017** (tras integridad) y **T021** (final).
- Revisión de arquitectura y calidad con `ml-reviewer`; revisión de seguridad con la skill `security-audit` (o `/security-review`) sobre el diff de la spec.
- Hallazgos altos y críticos se corrigen antes de seguir; el resto se registra en `decisions.md`.
