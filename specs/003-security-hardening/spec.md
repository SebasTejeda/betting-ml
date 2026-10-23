# Spec 003 — Endurecimiento de seguridad, integridad de datos y arquitectura

- **Estado:** propuesta, pendiente de aprobación del dueño
- **Dueño:** Daniel
- **Fecha:** 2026-10-22
- **Depende de:** spec 001 (modelo y API) y spec 002 (comparador, diario, frontend)
- **Principios:** [`../constitution.md`](../constitution.md) + enmienda XII de §8 de esta spec
- **Referencias:** OWASP Top 10 (2021), OWASP ASVS 4.0 nivel 2 (como guía, no como certificación)

## 1. Problema

El proyecto nació como herramienta personal servida en `localhost`. Ahora es un proyecto web: la API y el frontend pueden quedar expuestos en una red o en internet. El diario guarda dinero, bankroll y límites de juego responsable, así que su **integridad** es tan importante como su confidencialidad.

Estado actual (auditoría inicial, 2026-10-22):

| Área | Situación | Riesgo (OWASP) |
|---|---|---|
| Autenticación | Una clave estática (`APP_API_KEY`) en `localStorage` del navegador; solo protege escrituras. Dos implementaciones duplicadas (`admin.py`, `journal.py`) y dos claves (`ADMIN_API_KEY`, `APP_API_KEY`). | A07 Fallos de autenticación; robo de la clave por XSS |
| Control de acceso | Las lecturas (`/bets`, `/bets/summary`, `/settings`) son públicas: cualquiera que alcance la API ve apuestas y bankroll. | A01 Control de acceso roto |
| Fuerza bruta | Sin límite de intentos ni de peticiones. | A07, A04 |
| Cabeceras HTTP | Sin CSP, `X-Frame-Options`, `X-Content-Type-Options`, `Referrer-Policy`, HSTS ni `Cache-Control`. CORS con `allow_methods=["*"]` y `allow_headers=["*"]`. `/docs` y `/openapi.json` siempre expuestos. | A05 Configuración insegura |
| Errores | Sin manejador genérico de 500; el 422 devuelve `exc.errors()` con los valores de entrada. | A05, A09 |
| Validación | `match_id` y `bookmaker` solo con longitud mínima; sin `extra="forbid"`; paginación sin tope explícito. | A03 Inyección (indirecta), A04 |
| Integridad de datos | Sin restricciones `CHECK` en la base; sin control de concurrencia; sin auditoría de cambios en apuestas; sin copias de seguridad. | A08 Fallos de integridad |
| Artefactos | `joblib.load` (pickle) de `models/` sin verificar hash. | A08 |
| Secretos | `Settings` acepta la clave de ejemplo y claves cortas; no usa `SecretStr`. | A02, A05 |
| Registro | Sin request id, sin eventos de seguridad, sin filtro de redacción global. | A09 Fallos de registro |
| Cadena de suministro | Sin `pip-audit`, `npm audit`, escaneo de secretos ni Dependabot; acciones de CI sin fijar por SHA y sin `permissions`. | A06 Componentes vulnerables |
| Arquitectura | `journal.py` (442 líneas) mezcla seis recursos y lee archivos directamente (viola §V.3); contenedor tipado como `Any`. | Mantenibilidad: los controles se aplican de forma desigual |

## 2. Alcance

### Dentro

| Tema | Decisión |
|---|---|
| Usuario | **Un solo dueño** (herramienta personal). Login con contraseña; sin registro público. |
| Autenticación web | Contraseña con hash **Argon2id** en `.env`; **sesión del lado del servidor** con cookie `HttpOnly`, `SameSite=Strict` y `Secure` en producción. |
| Autenticación de máquina | `X-API-Key` (una sola clave, `APP_API_KEY`) para Postman, CLI y scripts. `ADMIN_API_KEY` se retira (alias con aviso durante una versión). |
| Control de acceso | **Todas** las rutas `/api/v1/*` exigen sesión o clave, salvo `/health` y `/api/v1/auth/login`. |
| CSRF | Token *double-submit* (`X-CSRF-Token`) en toda petición de escritura con sesión de cookie. |
| Límite de peticiones | Login: 5 intentos/minuto por IP con bloqueo progresivo. Global: límite por sesión/IP configurable. Respuesta `429` con `Retry-After`. |
| Cabeceras | CSP estricta, `frame-ancestors 'none'`, `nosniff`, `Referrer-Policy`, `Permissions-Policy`, HSTS (solo producción), `Cache-Control: no-store` en respuestas autenticadas. |
| Entornos | `APP_ENV=dev|prod`. En `prod` el arranque **falla** si la configuración es insegura (claves de ejemplo o cortas, sin hash de contraseña, CORS abierto). |
| Integridad de datos | Restricciones `CHECK` en la base; control optimista de concurrencia; **registro de auditoría encadenado con hashes** (solo inserción); copias de seguridad verificadas; hash SHA-256 de los modelos. |
| Registro | Logs estructurados con `request_id`, redacción de secretos y eventos de seguridad. |
| Cadena de suministro | `pip-audit`, `npm audit`, `gitleaks`, reglas `S` (bandit) de ruff, Dependabot, acciones fijadas por SHA. |
| Arquitectura | Routers por recurso, mappers separados, casos de uso para todo acceso a archivos, contenedor tipado con `Protocol`. |
| Despliegue | Docker endurecido y guía de despliegue detrás de un *reverse proxy* con TLS. |

### Fuera

- Cuentas multiusuario, registro, recuperación de contraseña por correo, OAuth/SSO.
- 2FA/TOTP (queda como mejora futura; se deja el punto de extensión).
- WAF, SIEM o monitoreo externo.
- Cifrado en reposo de la base SQLite (se documenta: depende del cifrado de disco del sistema).
- Cambios en el modelo, en la estrategia o en la lógica de juego responsable (solo se protegen).

## 3. Historias de usuario

### US1 — Solo yo accedo a mis datos (P1)
**Como** dueño **quiero** iniciar sesión con contraseña **para** que nadie más vea ni cambie mis apuestas, bankroll o límites.

Criterios de aceptación:
- `POST /api/v1/auth/login` con contraseña correcta crea una sesión y fija la cookie `bml_session` (`HttpOnly`, `SameSite=Strict`, `Path=/`, `Secure` en `prod`). Con contraseña incorrecta: `401` con mensaje genérico (no revela si existe el usuario).
- El token de sesión tiene 256 bits aleatorios; en la base solo se guarda su **hash SHA-256**. Expira tras 30 min de inactividad y a las 12 h como máximo (configurable). El login rota la sesión (fijación de sesión imposible).
- `POST /api/v1/auth/logout` invalida la sesión en el servidor. `GET /api/v1/auth/me` indica si hay sesión activa.
- Sin sesión ni `X-API-Key` válida, toda ruta `/api/v1/*` (lecturas incluidas) responde `401`, salvo `/health` y el login.
- La contraseña nunca se guarda en claro: `.env` contiene `APP_PASSWORD_HASH` generado con `betting-ml hash-password`.

### US2 — Protección contra abuso (P1)
**Como** dueño **quiero** que la API resista fuerza bruta y peticiones abusivas **para** que nadie adivine mi contraseña ni agote los créditos de The Odds API.

Criterios de aceptación:
- Login: máximo 5 intentos fallidos por minuto e IP; luego `429` con `Retry-After` y bloqueo progresivo (1, 5, 15 min).
- Límite global configurable por sesión/IP (por defecto 120 peticiones/min) y uno más estricto para `POST /odds/refresh` (por defecto 6/hora), además del presupuesto de créditos existente.
- Escrituras con sesión de cookie sin `X-CSRF-Token` válido: `403 CSRF_FAILED`.
- Cuerpo de petición mayor a 64 KB: `413`.

### US3 — Configuración segura por defecto (P1)
**Como** dueño **quiero** que la aplicación se niegue a arrancar en producción con una configuración insegura **para** no exponerla por descuido.

Criterios de aceptación:
- `APP_ENV=prod` exige: `APP_PASSWORD_HASH` válido, `APP_API_KEY` de ≥ 32 caracteres y distinta del ejemplo, `SESSION_SECRET` de ≥ 32 bytes, `ALLOWED_HOSTS` y `CORS_ORIGINS` explícitos. Si falta algo, el proceso termina con un mensaje claro (sin imprimir secretos).
- En `prod`: `/docs`, `/redoc` y `/openapi.json` desactivados; HSTS activo; cookies `Secure`.
- Las claves en `Settings` son `SecretStr`: no aparecen en `repr`, logs ni trazas.

### US4 — Cabeceras y errores seguros (P1)
**Como** dueño **quiero** que el navegador y la API apliquen las protecciones estándar **para** reducir XSS, clickjacking y fugas de información.

Criterios de aceptación:
- Toda respuesta lleva: `Content-Security-Policy` (sin `unsafe-inline` en scripts), `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`, `Permissions-Policy` restrictiva y `Cross-Origin-Opener-Policy: same-origin`. Las respuestas autenticadas llevan además `Cache-Control: no-store`.
- El script del tema en `index.html` se mueve a un archivo propio (o se permite por hash) para que la CSP no necesite `unsafe-inline`.
- `TrustedHostMiddleware` con `ALLOWED_HOSTS`; CORS solo con orígenes, métodos y cabeceras explícitos y `allow_credentials` coherente con la cookie.
- Un error no controlado responde `500 INTERNAL_ERROR` con un `request_id` y **sin traza**; la traza va al log con el mismo `request_id`.
- Los errores `422` describen el campo y el problema, sin devolver el valor recibido.

### US5 — Integridad de los datos del diario (P1)
**Como** dueño **quiero** que mis apuestas, ajustes y límites no puedan quedar corruptos ni alterarse sin rastro **para** confiar en mi ROI, mi CLV y mis límites de juego responsable.

Criterios de aceptación:
- La base rechaza datos imposibles aunque se salte la API: `CHECK` en cuota > 1, stake > 0, estado y tipo dentro de su lista, montos con 2 decimales, CLV y EV en rangos razonables, etc.
- Control optimista de concurrencia: apuestas y ajustes tienen `version`; una edición con versión vieja responde `409 VERSION_CONFLICT`.
- Cada creación, edición, liquidación y borrado de apuesta, cada cambio de ajustes o límites y cada login/logout queda en `audit_log`: fecha UTC, actor (`session`/`api_key`/`cli`/`scheduler`), acción, entidad, valores antes/después (sin secretos) y `hash = SHA-256(hash_anterior + registro canónico)`.
- `audit_log` es de solo inserción: *triggers* de SQLite impiden `UPDATE` y `DELETE`.
- `betting-ml verify-integrity` comprueba `PRAGMA integrity_check`, `PRAGMA foreign_key_check`, la cadena de hashes de la auditoría y que el estado actual de cada apuesta coincide con su último evento. Termina con código ≠ 0 si algo falla.
- SQLite en modo WAL con `busy_timeout` y `foreign_keys=ON` verificados al arrancar.

### US6 — Copias de seguridad y artefactos confiables (P2)
**Como** dueño **quiero** respaldos verificables y modelos que no hayan sido alterados **para** recuperarme de un fallo y no ejecutar código ajeno.

Criterios de aceptación:
- `betting-ml backup` crea una copia consistente con la API de *backup* de SQLite en `data/backups/`, con su SHA-256 y una retención configurable (por defecto 14). `betting-ml restore <archivo>` verifica el hash y la integridad antes de reemplazar, y guarda una copia del estado previo.
- Al guardar un modelo se registra el SHA-256 de `model.joblib` en `metadata.json`; al cargarlo se verifica y, si no coincide, **no se carga** (`503 MODEL_INTEGRITY_ERROR`).

### US7 — Trazabilidad y cadena de suministro (P2)
**Como** dueño **quiero** logs útiles y dependencias vigiladas **para** detectar incidentes y vulnerabilidades conocidas.

Criterios de aceptación:
- Logs en JSON (en `prod`) con `request_id`, método, ruta, estado y duración; nunca con contraseñas, cookies, `X-API-Key`, `apiKey` ni `ODDS_API_KEY` (filtro de redacción probado).
- Eventos de seguridad registrados: login correcto o fallido, bloqueo por fuerza bruta, `401`/`403`/`CSRF_FAILED`, cambio de límites, `verify-integrity` fallido.
- CI ejecuta `pip-audit`, `npm audit --audit-level=high`, `gitleaks` y ruff con reglas `S`; falla ante vulnerabilidades altas o secretos. Dependabot activo para pip, npm y GitHub Actions. Acciones fijadas por SHA y `permissions: contents: read`.

### US8 — Arquitectura que facilite aplicar los controles (P1)
**Como** mantenedor **quiero** una capa API ordenada y tipada **para** que los controles de seguridad se apliquen igual en todas las rutas.

Criterios de aceptación:
- `journal.py` se divide en routers por recurso (`odds`, `bookmakers`, `comparator`, `calculator`, `bets`, `settings`, `backtest`) con mappers en `api/mappers/`.
- Ningún router lee archivos ni toca infraestructura: el informe de backtest pasa por un caso de uso y un puerto (`ReportStore`).
- `get_container` devuelve servicios tipados (`Protocol`), sin `Any` en las firmas de los routers.
- La autenticación y la autorización viven en un único módulo (`api/security.py`) y se aplican por dependencia a nivel de router, no ruta por ruta.
- El contrato público de las specs 001 y 002 no cambia salvo lo añadido en `contracts/api.md` de esta spec (verificado con el OpenAPI exportado).

## 4. Requisitos no funcionales

- Misma arquitectura hexagonal; el dominio no conoce cookies, sesiones ni HTTP.
- Todo control de seguridad tiene **tests negativos** (qué se rechaza), no solo positivos.
- Cobertura: ≥ 90 % en `api/security.py`, en la auditoría y en las sesiones; se mantiene el 80 % del dominio y el 60 % global.
- Dependencias nuevas mínimas: `argon2-cffi` (hash de contraseña). Rate limit, cabeceras y CSRF se implementan en el proyecto (pocas líneas, sin dependencias abandonadas).
- Latencia añadida por los middlewares < 5 ms por petición en local.
- No se rompe el uso en `localhost` en `dev`: login con contraseña igual que en `prod`, pero cookies sin `Secure` y `/docs` visibles.

## 5. Criterio de éxito

| Nivel | Condición |
|---|---|
| **Mínimo** | US1–US5 y US8 hechas: login con sesión, todas las rutas protegidas, CSRF, rate limit, cabeceras, configuración fail-fast, restricciones en la base, concurrencia optimista y auditoría encadenada con `verify-integrity`. |
| **Bueno** | Lo anterior + US6 y US7: backups verificados, hash de modelos, logs seguros y CI de seguridad en verde. |
| **Excelente** | Lo anterior + auditoría final sin hallazgos altos ni críticos y guía de despliegue con TLS probada con Docker. |

## 6. Riesgos

| Riesgo | Mitigación |
|---|---|
| Romper el frontend o Postman al proteger las lecturas | Contrato nuevo documentado, tests MSW del login, colección de Postman con login o `X-API-Key`. |
| Quedar fuera de la aplicación (olvidar la contraseña) | `betting-ml hash-password` regenera el hash en `.env`; documentado en `SECURITY.md`. |
| La auditoría encadenada no protege contra quien tenga el archivo `.db` y reescriba toda la cadena | Se documenta el alcance: detecta cambios accidentales y los hechos fuera de la API; los backups con hash y fuera del equipo cubren el resto. |
| El rate limit en memoria no sirve con varios procesos | La API corre con un proceso (uso personal); se deja el puerto `RateLimiter` para cambiarlo por Redis si se escala. |
| Migraciones con `CHECK` fallan sobre datos existentes que no las cumplen | La migración valida primero y aborta con la lista de filas a corregir; nunca borra datos. |
| Una CSP estricta rompe estilos o librerías del frontend | Se prueba en `dev` con `Content-Security-Policy-Report-Only` antes de activarla. |

## 7. Límites que no cambian

- Las reglas de juego responsable (US6 de la spec 002) se mantienen idénticas; la auditoría registra además cada cambio de límites.
- Los holdouts y sus locks no se tocan.
- No se hace `git push` (lo hace el dueño). El trabajo va en la rama `Daniel`.

## 8. Enmienda a la constitución (se agrega en T001)

- **XII. Seguridad e integridad:**
  1. Toda ruta de la API exige autenticación, salvo las explícitamente públicas (`/health`, login).
  2. Ningún secreto se guarda en el navegador ni en el repo; las contraseñas solo como hash Argon2id.
  3. Los datos de dinero y límites tienen restricciones en la base, control de concurrencia y auditoría de solo inserción.
  4. Todo control de seguridad tiene tests negativos y CI de seguridad (dependencias y secretos) en verde antes de cada commit a la rama principal.
  5. En producción, la aplicación no arranca con una configuración insegura.
