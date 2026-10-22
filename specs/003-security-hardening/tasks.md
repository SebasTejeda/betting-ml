# Tareas — Spec 003

Reglas de ejecución:
- En orden, **una tarea a la vez**: tests (primero los negativos) → implementar → `lint + test` en verde (y `web-test` si toca el frontend) → marcar `[x]` → línea en `PROGRESS.md` → un commit con Conventional Commits en la rama `Daniel`.
- **Al terminar cada tarea se presenta el resultado y se pide confirmación al dueño antes de empezar la siguiente.**
- Nunca `git push`. Las decisiones nuevas van en `specs/003-security-hardening/decisions.md`.
- El contrato de las specs 001 y 002 solo cambia en lo descrito en `contracts/api.md` de esta spec.

---

## Fase 0 — Integración y línea base

- [x] **T000** Redactar la spec 003: `spec.md`, `plan.md`, `contracts/api.md`, `tasks.md` y `decisions.md`.
  - Commit: `docs: spec 003 security hardening`

- [x] **T001** Integrar la spec 003 al repo
  - Agregar el principio **XII. Seguridad e integridad** (spec §8) a `specs/constitution.md`.
  - `CLAUDE.md`: spec activa `specs/003-security-hardening/`, orden de lectura y reglas nuevas (rutas autenticadas, sin secretos en el navegador, auditoría de solo inserción, CI de seguridad).
  - `PROGRESS.md`: sección "Spec 003".
  - Ampliar `ml-reviewer` con un bloque de revisión para la spec 003 (autenticación en todas las rutas, CSRF, tests negativos, auditoría, migraciones sin pérdida de datos).
  - Commit: `docs: integrate spec 003`

- [x] **T002** Línea base de seguridad
  - Añadir las herramientas sin hacer fallar todavía el CI: ruff con `S` (bandit) en modo informe, `pip-audit`, `npm audit`, `gitleaks`; objetivo `make security`.
  - Generar `reports/SECURITY_BASELINE.md`: hallazgos de las herramientas + tabla de la spec §1, cada uno con severidad y la tarea que lo resuelve.
  - Corregir solo lo trivial (sin cambiar comportamiento); el resto queda asignado a su tarea.
  - Commit: `chore(security): baseline scan and make security`

## Fase 1 — Arquitectura

- [x] **T003** Configuración por entorno y fail-fast (US3)
  - `APP_ENV=dev|prod`; claves como `SecretStr`; nuevas variables de `plan.md` §6 en `Settings` y `.env.example`.
  - Validador de `prod`: hash de contraseña, `APP_API_KEY` ≥ 32 caracteres y distinta del ejemplo, `SESSION_SECRET`, `ALLOWED_HOSTS` y `CORS_ORIGINS` explícitos. Falla con mensaje claro y sin imprimir secretos.
  - `ADMIN_API_KEY` como alias temporal de `APP_API_KEY` (aviso en el log).
  - Tests: cada valor inseguro hace fallar `prod`; `dev` arranca; `repr(settings)` sin secretos.
  - Commit: `feat(config): environment-aware settings with fail-fast validation`

- [x] **T004** Dividir la capa API sin cambiar el contrato (US8)
  - `journal.py` → routers `odds`, `bookmakers`, `comparator`, `calculator`, `bets`, `settings`, `backtest`; mappers en `api/mappers/`.
  - `GET /backtest/pinnacle` pasa por el caso de uso `read_backtest` y el puerto `ReportStore` (se acaba la lectura de archivos en el router, §V.3).
  - Servicios tipados con `Protocol` en `dependencies.py`; sin `Any` en las firmas de los routers.
  - Hecho cuando: `betting-ml openapi` produce un `openapi.json` idéntico (salvo el orden de los *tags*, si cambia) y pasan todos los tests existentes sin modificarlos.
  - Commit: `refactor(api): split journal router by resource and type the services`

- [x] **T005** Módulo único de seguridad
  - `api/security.py` con `Principal`, `require_auth` (por ahora solo `X-API-Key`) y `require_write`; se eliminan las verificaciones duplicadas de `admin.py` y `journal.py`.
  - Dependencias a nivel de `APIRouter`, no ruta por ruta.
  - Test generado desde `app.routes`: cada ruta tiene la política declarada (pública / lectura / escritura) y no hay rutas sin clasificar.
  - Commit: `refactor(security): single authentication module applied per router`

## Fase 2 — Identidad y acceso

- [x] **T006** Sesiones de servidor, login y CSRF en escrituras con sesión (US1)
  - Dominio: `Session`, `Principal`; puertos `SessionStore` y `PasswordHasher`.
  - Adaptadores: `Argon2Hasher` (`argon2-cffi`), `SqlSessionStore` (migración 0004: tabla `sessions` con `token_hash` único, `csrf_token`, `created_at`, `last_seen_at`, `expires_at`, `password_fingerprint`).
  - Caso de uso `authenticate`: login (rotación), validación con expiración deslizante y absoluta, logout y purga de vencidas.
  - Router `auth`: `login`, `logout`, `me` según el contrato. CLI `betting-ml hash-password` (sin eco).
  - **Adelantado de T007:** `require_write` acepta la sesión además de `X-API-Key` y exige `X-CSRF-Token` con la sesión (una escritura con cookie nunca existe sin CSRF). Ver `decisions.md`.
  - Tests: contraseña incorrecta, cookie alterada, vencida por inactividad y por máximo, sesión cerrada, cambio de contraseña invalida sesiones, cookie con `HttpOnly`/`SameSite=Strict`/`Secure` según el entorno, CSRF ausente/falso/de otra sesión → 403.
  - Commit: `feat(auth): owner login with argon2id and server-side sessions`

- [x] **T007** Proteger todas las lecturas (US1, US2)
  - `require_read` exige sesión o `X-API-Key`: todas las rutas privadas quedan autenticadas (el CSRF de las escrituras ya está desde T006).
  - Tests: sin credencial → 401 en cada ruta privada (generado desde las rutas de la app).
  - Actualizar la colección de Postman (`X-API-Key` en todas las peticiones privadas) y su test.
  - Tras este commit el frontend no puede leer hasta T009, que va justo después.
  - Commit: `feat(auth): require authentication on every private route`

- [x] **T009** Frontend con login (US1) — se ejecuta antes que T008 (decisión del dueño)
  - Página `/login`, `AuthProvider` (`/auth/me`), rutas protegidas, logout en la barra.
  - Se elimina la clave de `localStorage` (`lib/apiKey.ts` y `ApiKeyButton`); `credentials: "same-origin"` y `X-CSRF-Token` en memoria para las escrituras.
  - Regenerar los tipos (`make web-api`).
  - Tests MSW: login correcto/incorrecto, 429, redirección por 401, CSRF en escrituras, logout; cobertura ≥ 80 %.
  - Commit: `feat(web): login page and cookie session without secrets in local storage`

- [x] **T008** Rate limit y anti fuerza bruta (US2)
  - Puerto `RateLimiter` y adaptador en memoria (ventana deslizante, thread-safe).
  - Login: 5 fallos/min por IP con bloqueo progresivo (1, 5, 15 min); global por sesión/IP; `POST /odds/refresh` 6/hora. `429` con `Retry-After`.
  - `BodyLimitMiddleware`: `413 PAYLOAD_TOO_LARGE`.
  - Tests con reloj falso: límites, bloqueo progresivo, `Retry-After`, 413.
  - Commit: `feat(security): rate limiting, login lockout and body size limit`

- [x] **T010** 🔍 Checkpoint de identidad y acceso
  - `ml-reviewer` (arquitectura y tests) + revisión de seguridad del diff T003–T009 (`security-audit` o `/security-review`).
  - Corregir los hallazgos altos y críticos; registrar el resto en `decisions.md`.
  - Commit: `fix(security): ...` o `docs: checkpoint T010`

## Fase 3 — Endurecimiento HTTP

- [x] **T011** Cabeceras, hosts, CORS y documentación (US3, US4)
  - `RequestIdMiddleware`, `SecurityHeadersMiddleware` (contrato §4), `TrustedHostMiddleware`, CORS explícito; `/docs`, `/redoc` y `/openapi.json` solo en `dev` (el comando `betting-ml openapi` sigue funcionando).
  - Mover el script del tema de `index.html` a `public/theme-init.js`; probar la CSP con el frontend construido (primero en modo `Report-Only`).
  - Tests: cabeceras en 200/401/404/422/500; host no permitido → 400; origen no permitido sin cabeceras CORS; documentación ausente en `prod`.
  - Commit: `feat(security): security headers, trusted hosts and strict cors`

- [x] **T012** Errores y validación estricta (US4)
  - Manejador genérico de 500 con `request_id` y sin traza; 422 sin los valores recibidos.
  - `extra="forbid"` en los modelos de entrada; patrones y longitudes máximas para `match_id`, `bookmaker`, `league`, `note`; rangos de fecha; tope de paginación.
  - Tests: campos extra → 422; `match_id` con caracteres fuera del patrón → 422; excepción forzada → 500 con `request_id` y sin traza.
  - Commit: `feat(api): strict input validation and safe error responses`

## Fase 4 — Integridad de datos

- [x] **T013** Restricciones en la base y SQLite robusto (US5)
  - Migración 0005 (*batch mode*): `CHECK` de `plan.md` §5 y `NOT NULL` faltantes; valida antes y aborta listando las filas inválidas, sin borrar nada.
  - `journal_mode=WAL`, `busy_timeout=5000` y `foreign_keys=ON` verificados al arrancar.
  - Tests: `INSERT` directo con datos imposibles → `IntegrityError`; migración sobre una base con datos válidos e inválidos.
  - Commit: `feat(db): check constraints and robust sqlite pragmas`

- [x] **T014** Concurrencia optimista (US5)
  - Columna `version` en apuestas y ajustes (migración 0006); `PATCH /bets/{id}` y `PUT /settings` con `version`; `409 VERSION_CONFLICT`.
  - Liquidación con `BEGIN IMMEDIATE`: una apuesta no se liquida dos veces.
  - Frontend: envía `version` y ante 409 recarga y avisa.
  - Tests: dos ediciones con la misma versión (una gana); liquidación concurrente.
  - Commit: `feat(journal): optimistic concurrency on bets and settings`

- [x] **T015** Auditoría encadenada (US5)
  - Dominio: `AuditEvent`, canonicalización y encadenado SHA-256 (puro, con tests de propiedad).
  - Migración 0007: tabla `audit_log` + triggers que impiden `UPDATE`/`DELETE`.
  - Registro en la **misma transacción** que el cambio: apuestas (crear, editar, liquidar, borrar), ajustes/límites, login/logout, liquidación automática y refresco de cuotas (actor `scheduler`/`cli`).
  - `betting-ml verify-integrity` (+ `make verify-integrity`).
  - Tests: cadena válida; registro alterado → falla e indica el `seq`; `UPDATE`/`DELETE` → error; apuesta cambiada fuera de la API → detectada.
  - Commit: `feat(audit): append-only hash-chained audit log and verify-integrity`

- [x] **T016** Copias de seguridad y restauración (US6)
  - `betting-ml backup` / `restore` (+ `make backup`/`restore`): API de backup de SQLite, `.sha256`, retención `BACKUP_KEEP`, copia previa al restaurar.
  - Tests: backup en caliente consistente; restore rechaza un archivo con hash distinto o corrupto.
  - Commit: `feat(ops): verified sqlite backup and restore`

- [x] **T017** Integridad de los modelos (US6) y 🔍 checkpoint de integridad
  - SHA-256 de `model.joblib` en `metadata.json`; verificación antes de `joblib.load`; `503 MODEL_INTEGRITY_ERROR`.
  - `betting-ml models-rehash` para los modelos existentes (se ejecuta una vez, tras revisar que son los del repo).
  - Checkpoint `ml-reviewer` de T013–T017 (migraciones sin pérdida, auditoría, concurrencia).
  - Commit: `feat(models): verify model artifact hashes before loading`

## Fase 5 — Operación

- [x] **T018** Logs seguros y eventos de seguridad (US7)
  - `logging_config.py`: JSON en `prod` (`LOG_FORMAT`), `request_id` en cada línea, filtro de redacción (password, cookie, `X-API-Key`, `X-CSRF-Token`, `apiKey`, valores de `SecretStr`).
  - Eventos: login correcto/fallido, bloqueo, 401/403/CSRF, cambio de límites, `verify-integrity` fallido.
  - Tests con `caplog`: ningún secreto en los logs de una petición que los contiene.
  - Commit: `feat(logging): structured logs with redaction and security events`

- [x] **T019** Cadena de suministro y CI (US7)
  - Workflow con `permissions: contents: read` y acciones fijadas por SHA; job `security` (ruff `S`, `pip-audit`, `npm audit --audit-level=high`, `gitleaks`) que ahora **sí** falla.
  - `.github/dependabot.yml` (pip, npm, github-actions); `gitleaks` y `detect-private-key` en pre-commit.
  - Resolver o justificar en `decisions.md` cada hallazgo restante de la línea base.
  - Commit: `ci: security job, pinned actions and dependabot`

- [x] **T020** Docker y despliegue
  - Imagen base fijada por digest; `HEALTHCHECK` sobre `/health`; `--proxy-headers` solo con proxy de confianza; prueba de arranque con `--read-only`.
  - `docs/deploy.md`: Caddy con TLS delante de la API y del frontend construido, variables de `prod` y rotación de claves.
  - Tests: `test_dockerfile.py` ampliado (usuario no root, sin `.env` en la imagen, digest fijado).
  - Commit: `build(docker): hardened image and deployment guide`

## Fase 6 — Cierre

- [x] **T021** 🔍 Auditoría final de seguridad
  - Revisión completa con `security-audit` sobre la rama y `ml-reviewer` sobre la arquitectura.
  - Corregir altos y críticos; registrar los aceptados en `decisions.md`.
  - Commit: `fix(security): final audit findings` o `docs: final security audit`

- [ ] **T022** Documentación y verificación de punta a punta
  - `SECURITY.md` (modelo de amenazas, controles, rotación de claves, recuperación de acceso, backups), sección de seguridad en el README y `reports/SECURITY_BASELINE.md` actualizado con el estado final.
  - Verificación manual con `make dev` y en modo `prod`: login, navegación, apuesta en papel, 409 de límites, logout, `verify-integrity`, backup/restore.
  - `PROGRESS.md` con el resumen de la spec 003.
  - Commit: `docs: spec 003 security documentation and final verification`
