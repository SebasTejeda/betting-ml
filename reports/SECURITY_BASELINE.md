# Línea base de seguridad — spec 003

- **Fecha:** 2026-10-22 (T002)
- **Rama / commit de partida:** `Daniel` @ `c5884ca`
- **Cómo se repite:** `make security` (sin make: los comandos del objetivo `security` del `Makefile`). Está en **modo informe** hasta T019: muestra los hallazgos sin fallar.

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
