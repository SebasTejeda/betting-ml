# Contrato de la API — extensión de la spec 003

Se suma a [`../../001-prediction-model/contracts/api.md`](../../001-prediction-model/contracts/api.md) y a [`../../002-odds-comparator/contracts/api.md`](../../002-odds-comparator/contracts/api.md). Los cuerpos y respuestas de las rutas existentes **no cambian**; cambian la autenticación, las cabeceras y algunos errores.

## 1. Autenticación

| Ruta | Pública | Credencial aceptada |
|---|---|---|
| `GET /health` | sí | — |
| `POST /api/v1/auth/login` | sí (con rate limit) | — |
| Resto de `/api/v1/*` (lectura) | no | cookie `bml_session` **o** `X-API-Key` |
| Resto de `/api/v1/*` (escritura) | no | cookie `bml_session` + `X-CSRF-Token` **o** `X-API-Key` |
| `/docs`, `/redoc`, `/openapi.json` | solo en `APP_ENV=dev` | — |

### `POST /api/v1/auth/login`

```json
// petición
{ "password": "..." }
// 200
{ "csrf_token": "...", "expires_at": "2026-10-22T20:30:00Z", "idle_minutes": 30 }
```
- Fija `Set-Cookie: bml_session=<token>; HttpOnly; SameSite=Strict; Path=/; Max-Age=43200` (+ `Secure` en `prod`).
- `401 INVALID_CREDENTIALS` (mensaje genérico) · `429 TOO_MANY_ATTEMPTS` con `Retry-After` · `422` si falta `password` · `503 LOGIN_DISABLED` sin hash configurado · `503 LOGIN_BUSY` con `Retry-After` si hay demasiadas verificaciones de contraseña en curso.

### `POST /api/v1/auth/logout`
- Requiere sesión + `X-CSRF-Token`. `204`; borra la cookie e invalida la sesión en el servidor.

### `GET /api/v1/auth/me`
```json
{ "authenticated": true, "kind": "session", "csrf_token": "...", "expires_at": "..." }
```
- Sin sesión: `401 UNAUTHORIZED`.

## 2. Cambios en rutas existentes

| Ruta | Cambio |
|---|---|
| `PATCH /api/v1/bets/{id}` | El cuerpo incluye `version` (entero). Versión vieja → `409 VERSION_CONFLICT` con `details.current_version`. |
| `PUT /api/v1/settings` | Igual: `version` obligatoria; `409 VERSION_CONFLICT`. |
| `BetOut`, `SettingsOut` | Añaden `version`. |
| `POST /api/v1/admin/refresh` | Usa la clave única `APP_API_KEY` (`ADMIN_API_KEY` solo como alias temporal en `.env`). Con la clave de ejemplo responde `503 WRITES_DISABLED`, igual que el resto de escrituras (antes `503 ADMIN_DISABLED`). Hecho en T005. |

## 3. Errores nuevos

| Estado | Código | Cuándo |
|---|---|---|
| 400 | `INVALID_HOST` | Cabecera `Host` fuera de `ALLOWED_HOSTS`. |
| 401 | `UNAUTHORIZED` | Sin credencial o credencial inválida/vencida. |
| 401 | `INVALID_CREDENTIALS` | Login con contraseña incorrecta. |
| 403 | `CSRF_FAILED` | Escritura con cookie sin `X-CSRF-Token` válido. |
| 409 | `VERSION_CONFLICT` | Edición concurrente. |
| 422 | `VALIDATION_ERROR` | Entrada inválida: campo desconocido, fuera de patrón, de longitud o de rango; `details.errors` lleva solo `loc`, `msg` y `type`, nunca el valor recibido. |
| 413 | `PAYLOAD_TOO_LARGE` | Cuerpo > `MAX_BODY_BYTES`. |
| 429 | `TOO_MANY_ATTEMPTS` / `RATE_LIMITED` | Login o límite global/ruta superado (`Retry-After`). |
| 503 | `LOGIN_BUSY` | Todas las plazas de verificación Argon2 ocupadas; el login falla rápido (`Retry-After: 5`). |
| 500 | `INTERNAL_ERROR` | Error no controlado; `details.request_id`, sin traza. |
| 503 | `MODEL_INTEGRITY_ERROR` | El hash del modelo no coincide. |

Formato uniforme sin cambios: `{"error": {"code", "message", "details"}}`. Toda respuesta incluye `X-Request-ID`.

Validación de entrada (T012, `api/validation.py`):

| Campo | Regla |
|---|---|
| Cuerpos de entrada | `extra="forbid"`: un campo desconocido es 422. |
| `league` | `^[A-Za-z0-9]{1,8}$` (cuerpo, consulta y ruta). |
| `match_id` | `^[A-Za-z0-9]{1,8}-\d{4}-\d{2}-\d{2}-[a-z0-9-]{1,140}$`, 14–160 caracteres. |
| `bookmaker` | `^[a-z0-9_]{1,40}$`. |
| `home_team`, `away_team` | 1–60 caracteres, sin caracteres de control ni `<>`. |
| `note` | ≤ 500 caracteres, sin caracteres de control (salvo tabulador y saltos de línea). |
| `currency` | `^[A-Z]{3}$`. |
| Fechas (`date`, `from`, `to`, `match_date`) | 2000-01-01 a 2099-12-31; `from` ≤ `to`. |
| Paginación | `page` ≤ 10 000, `size` ≤ 500. |
| `bet_id` | 1 a 2³¹−1. |
| `odds` (calculadora) | > 1 y ≤ 1000. |

## 4. Cabeceras de respuesta

```
Content-Security-Policy: default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline';
  img-src 'self' data:; font-src 'self'; connect-src 'self'; frame-ancestors 'none';
  base-uri 'none'; form-action 'self'; object-src 'none'
X-Content-Type-Options: nosniff
X-Frame-Options: DENY
Referrer-Policy: no-referrer
Permissions-Policy: camera=(), microphone=(), geolocation=(), payment=()
Cross-Origin-Opener-Policy: same-origin
Strict-Transport-Security: max-age=31536000; includeSubDomains      (solo prod)
Cache-Control: no-store                                             (todas las respuestas de la API)
X-Request-ID: <uuid>
```

`style-src 'unsafe-inline'` se mantiene porque Tailwind/Recharts generan estilos en línea; los scripts no lo permiten. Probada en T011 con el frontend construido (`vite preview` la aplica; el servidor de desarrollo la envía como `Report-Only`, porque Vite inyecta un script en línea). La API la envía en todas sus respuestas salvo `/docs` y `/redoc` (solo existen en `dev`). `frontend/security-headers.ts` y `api/middleware/security_headers.py` comparten la misma política (un test lo comprueba).
