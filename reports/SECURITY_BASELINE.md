# Línea base de seguridad — spec 003

- **Fecha:** 2026-10-22 (T002)
- **Rama / commit de partida:** `Daniel` @ `c5884ca`
- **Cómo se repite:** `make security` (sin make: los comandos del objetivo `security` del `Makefile`). Desde T019 falla ante cualquier hallazgo, también en CI.
- **Estado final:** los 21 hallazgos están resueltos (ver §4, actualizado en T022). La auditoría final está en [`SECURITY_AUDIT_003.md`](SECURITY_AUDIT_003.md).

Severidad: **Crítica** (explotable a distancia, con impacto directo en datos o dinero), **Alta**, **Media**, **Baja**.

## 1. Escaneos automáticos

| Herramienta | Alcance | Resultado inicial | Acción en T002 | Estado tras T002 |
|---|---|---|---|---|
| `gitleaks git` 8.30.1 | Historial completo (109 commits) | Sin secretos | — | ✅ Limpio |
| `gitleaks dir` 8.30.1 | Árbol de trabajo | 237 avisos, **todos** dentro de `.venv/` (código de terceros); 0 en archivos del proyecto | `.gitleaks.toml` excluye `.venv/`, `node_modules/` y `frontend/dist/` | ✅ Limpio |
| `pip-audit` (producción) | `uv export --no-dev` | `pillow` 12.3.0 (24 CVE, transitiva vía matplotlib), `certifi` 2026.7.22 (1 CVE) | Lockfile: `pillow` 13.0.0, `certifi` 2026.10.19 | ✅ 0 vulnerabilidades |
| `pip-audit` (dev) | `uv export --extra dev` | Lo anterior + `virtualenv` 21.13.0 (5 CVE, vía pre-commit) | Lockfile: `virtualenv` 21.14.12 | ✅ 0 vulnerabilidades |
| `npm audit --omit=dev` | Dependencias del bundle | 0 vulnerabilidades | — | ✅ Limpio |
| `npm audit` (todo) | Incluye herramientas de desarrollo | 13 (9 altas, 4 medias): `vite` 8.3.0–8.3.2 (servidor de desarrollo), `vitest`, `source-map-js`, `hono`, `@modelcontextprotocol/sdk` y la cadena de `shadcn` | `npm audit fix` sin cambios mayores + `vitest` y `@vitest/coverage-v8` ^5.0.5 → `vite` 8.3.5, `vitest` 5.0.5, `source-map-js` 1.2.2, `hono` 4.13.13 | ⚠️ 10 restantes (7 altas, 3 medias), ver H-17 |
| `ruff --select S` (bandit) | `src/` | 6: `S101` `assert` ×4, `S607` ruta parcial de `git` ×2 | — | ⚠️ Abiertos, ver H-18 |

Tras los cambios: backend con 314 tests en verde y 1 omitido (cobertura del 98.4 %), ruff y mypy limpios; frontend con 49 tests, lint, typecheck y build en verde.

## 2. Hallazgos y tarea que los resuelve

| ID | Hallazgo | OWASP | Severidad | Evidencia | Tarea |
|---|---|---|---|---|---|
| H-01 | Lecturas sin autenticación: apuestas, resumen, bankroll y ajustes visibles para cualquiera que alcance la API | A01 | **Crítica** si la API se expone fuera de localhost | `api/routers/journal.py`: solo las escrituras usan `require_app_key` | T005, T007 |
| H-02 | La clave de escritura vive en `localStorage`: un XSS la roba y da escritura total | A07 | Alta | `frontend/src/lib/apiKey.ts` | T006, T009 |
| H-03 | Una única clave estática compartida, sin expiración ni revocación ni sesión | A07 | Alta | `config.py` (`app_api_key`) | T006 |
| H-04 | Sin límite de intentos ni de peticiones: fuerza bruta de la clave y abuso del refresco | A07, A04 | Alta | Sin middleware de rate limit | T008 |
| H-05 | Sin cabeceras de seguridad (CSP, `X-Frame-Options`, `nosniff`, `Referrer-Policy`, HSTS, `no-store`) | A05 | Media | `api/main.py` | T011 |
| H-06 | CORS con `allow_methods=["*"]` y `allow_headers=["*"]`; sin `TrustedHostMiddleware` | A05 | Media | `api/main.py` | T011 |
| H-07 | `/docs`, `/redoc` y `/openapi.json` siempre expuestos | A05 | Baja | `FastAPI(...)` sin desactivarlos | T011 |
| H-08 | Se aceptan la clave de ejemplo y claves cortas; sin `SecretStr`; sin distinción dev/prod | A02, A05 | Media | `config.py`: `admin_api_key = "cambia-esto"`, `app_api_key = "cambia-esto"` | T003 |
| H-09 | Sin manejador genérico de 500 y el 422 devuelve los valores de entrada (`exc.errors()` incluye `input`) | A05, A09 | Media | `api/errors.py` | T012 |
| H-10 | Validación de entrada laxa: `match_id`/`bookmaker` solo con longitud mínima, sin `extra="forbid"`, sin máximo de cuerpo | A03, A04 | Media | `api/schemas_002.py` | T008, T012 |
| H-11 | La base acepta datos imposibles si se escribe fuera de la API (sin `CHECK`) | A08 | Media | `adapters/sql/models.py` | T013 |
| H-12 | Sin control de concurrencia: ediciones simultáneas se pisan; liquidación sin bloqueo explícito | A04, A08 | Media | `adapters/sql/repositories.py` | T014 |
| H-13 | Sin auditoría de cambios en apuestas (solo hay historial de ajustes); un cambio no deja rastro | A08, A09 | Alta (integridad del dinero y de los límites) | Tablas `bets` y `settings_history` | T015 |
| H-14 | Sin copias de seguridad de `data/app.db` | A08 | Media | — | T016 |
| H-15 | `joblib.load` (pickle) de `models/` sin verificar hash: un archivo reemplazado ejecuta código | A08 | Media (requiere acceso de escritura a `models/`) | `adapters/joblib_registry.py:34` | T017 |
| H-16 | Logs sin `request_id`, sin eventos de seguridad y sin filtro global de redacción (la clave de The Odds API sí se redacta en su adaptador) | A09 | Media | `adapters/the_odds_api.py` (redacción local) | T018 |
| H-17 | Dependencias de desarrollo vulnerables restantes: cadena de la CLI `shadcn` (`@shadcn/registry`, `ts-morph`, `fast-glob`, `micromatch`, `braces`) y `vitest`/`@vitest/mocker`/`@vitest/coverage-v8` (moderadas). No llegan al bundle de producción. `shadcn` no se puede quitar sin más: `src/index.css` importa `shadcn/tailwind.css` | A06 | Baja (solo herramientas locales) | `npm audit` | T019 |
| H-18 | `assert` como comprobación en tiempo de ejecución (desaparecen con `python -O`) y `git` invocado sin ruta absoluta | — | Baja | `adapters/fixtures.py:128`, `ml/models/ensemble.py:64`, `ml/models/factory.py:50,54`, `adapters/git_info.py:15,22` | T019 |
| H-19 | CI sin `permissions` mínimos, acciones sin fijar por SHA, sin escaneo de dependencias ni de secretos, sin Dependabot | A06, A08 | Media | `.github/workflows/ci.yml` | T019 |
| H-20 | Imagen Docker sin digest fijado; despliegue sin TLS documentado | A05, A02 | Media | `Dockerfile` | T020 |
| H-21 | `journal.py` (442 líneas) lee archivos en el router (viola §V.3); servicios tipados como `Any`; autenticación duplicada en `admin.py` y `journal.py` | — (arquitectura) | Media: los controles se aplican de forma desigual | `api/routers/journal.py:417-430`, `api/dependencies.py` | T004, T005 |

## 3. Lo que ya estaba bien

- Comparación de claves en tiempo constante (`secrets.compare_digest`) y escrituras deshabilitadas (`503`) con la clave de ejemplo.
- La clave de The Odds API se redacta en los errores del adaptador; los fixtures grabados no contienen ningún `apiKey` (búsqueda en `tests/fixtures/`) y `gitleaks git` no encuentra secretos en el historial.
- Acceso a la base solo con el ORM de SQLAlchemy (sin SQL construido con texto); `foreign_keys=ON` en SQLite.
- YAML con `yaml.safe_load`; sin `eval`, `pickle` de datos externos ni `shell=True`.
- Imagen Docker con usuario no root y sin `.env` (está en `.dockerignore`).
- Dinero con `Decimal` y límites de juego responsable que no se pueden saltar desde la API.

## 4. Estado final (T022)

Rama `Daniel`, después de T021 (`7dda585`) y de las correcciones de T022.

### Escaneos

| Herramienta | Resultado en T002 | Resultado final |
|---|---|---|
| `gitleaks git` 8.30.1 (historial, 129 commits) | Limpio | ✅ Sin secretos |
| `gitleaks dir` 8.30.1 (árbol) | Limpio con `.gitleaks.toml` | ✅ Sin secretos |
| `pip-audit` (producción y desarrollo, con hashes) | 0 tras actualizar el lockfile | ✅ 0 vulnerabilidades |
| `npm audit` (todo, también desarrollo) | 10 (7 altas, 3 medias) | ✅ 0 vulnerabilidades |
| `ruff --select S` (`src`, `tests`, `migrations`) | 6 avisos | ✅ Limpio |

Tests: 938 backend en verde y 1 omitido (cobertura del 98.9 %) y 59 de frontend. ruff, mypy, lint y typecheck limpios.

### Hallazgos

| ID | Estado | Cómo quedó |
|---|---|---|
| H-01 | ✅ Resuelto (T005, T007) | Toda ruta `/api/v1/*` exige sesión o `X-API-Key`, salvo `/health` y el login. `test_route_access.py` recorre todas las rutas registradas. |
| H-02 | ✅ Resuelto (T009) | El frontend usa la sesión. El navegador no guarda ningún secreto, y la clave antigua se borra de `localStorage` al cargar. |
| H-03 | ✅ Resuelto (T006) | Sesiones de servidor con caducidad por inactividad (30 min) y total (12 h), revocables con el logout o con el cambio de contraseña. Los tokens se guardan como HMAC. |
| H-04 | ✅ Resuelto (T008, T021) | Login limitado por IP o /64 con bloqueo progresivo. Límite global por IP y cupo de refrescos de cuotas. La red de Docker tiene IPv6 para que cada cliente conserve su IP. |
| H-05 | ✅ Resuelto (T011) | CSP, `X-Frame-Options`, `nosniff`, `Referrer-Policy`, HSTS en prod y `no-store`. La misma política en la API, `vite preview` y Caddy. |
| H-06 | ✅ Resuelto (T011) | CORS con métodos, cabeceras y orígenes explícitos; `Host` permitido. |
| H-07 | ✅ Resuelto (T011) | `/docs`, `/redoc` y `/openapi.json` desactivados en prod. |
| H-08 | ✅ Resuelto (T003) | `SecretStr`. En prod la API no arranca con claves de ejemplo, cortas o vacías. |
| H-09 | ✅ Resuelto (T012) | Un 500 genérico registrado con su `request_id`; el 422 no devuelve los valores enviados. |
| H-10 | ✅ Resuelto (T008, T012, T021) | Esquemas con `extra="forbid"`, patrones y rangos (incluidos los importes de ajustes); cuerpo máximo de 64 KiB. |
| H-11 | ✅ Resuelto (T013) | `CHECK` con los valores reales del esquema, verificados en la migración. |
| H-12 | ✅ Resuelto (T014) | Concurrencia optimista (`version`): una edición simultánea da 409. Liquidación con `UPDATE` condicional. |
| H-13 | ✅ Resuelto (T015, T021) | `audit_log` de solo inserción con cadena SHA-256. `verify-integrity` comprueba también el SQL de los triggers. |
| H-14 | ✅ Resuelto (T016, T022) | `backup` y `restore` verificados, con `.sha256` compatible con `sha256sum -c` (con LF también en Windows desde T022). |
| H-15 | ✅ Resuelto (T017) | SHA-256 de cada modelo comprobado antes de `joblib.load`. |
| H-16 | ✅ Resuelto (T018) | Logs JSON con `request_id`, redacción global y eventos de seguridad. |
| H-17 | ✅ Resuelto (T019) | Fuera la CLI de `shadcn` (su CSS se copió con su licencia). `npm audit` da 0. |
| H-18 | ✅ Resuelto (T019) | `RuntimeError` explícitos en lugar de `assert`; `git` invocado por ruta absoluta. |
| H-19 | ✅ Resuelto (T019) | CI con permisos mínimos, acciones por SHA, job `security` que falla y Dependabot. |
| H-20 | ✅ Resuelto (T020, T021) | Imágenes por digest, contenedor endurecido y Caddy con TLS (`docs/deploy.md`). La imagen la construye el job `docker` de CI; esta máquina no tiene Docker. |
| H-21 | ✅ Resuelto (T004, T005) | Routers sin E/S de archivos y servicios tipados con `ServicesApi`, sin `Any`. La autenticación tiene una sola implementación. |

Lo que se acepta y queda fuera (cadena de auditoría sin clave, sin cifrado en reposo, un solo proceso) está en [`SECURITY.md`](../SECURITY.md) §3.
