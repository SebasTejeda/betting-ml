# Seguridad — betting-ml

Este documento resume qué protege la aplicación, contra quién y qué queda fuera. El detalle está en otros documentos:

- Diseño y decisiones: [`specs/003-security-hardening/`](specs/003-security-hardening/) (`spec.md`, `plan.md`, `decisions.md`).
- Despliegue, logs, copias y rotación paso a paso: [`docs/deploy.md`](docs/deploy.md).
- Hallazgos de partida y su estado: [`reports/SECURITY_BASELINE.md`](reports/SECURITY_BASELINE.md).
- Auditoría final: [`reports/SECURITY_AUDIT_003.md`](reports/SECURITY_AUDIT_003.md).

## 1. Modelo de amenazas

**Qué es la aplicación.** Una herramienta personal de **un solo dueño**. No hay registro de usuarios ni recuperación por correo. La API y el frontend se publican detrás de Caddy con TLS, y la API corre como **un único proceso**.

**Activos:**

- el diario de apuestas, el bankroll y los ajustes, que son datos personales y financieros;
- los **límites de juego responsable** (pérdida mensual y stake máximo), que no se pueden saltar;
- la integridad del historial: qué apuesta se registró, cuándo y con qué importe;
- los secretos: la contraseña, `APP_API_KEY`, `SESSION_SECRET` y `ODDS_API_KEY`, con los créditos de The Odds API;
- los modelos (`models/*.joblib`): cargarlos ejecuta código (pickle).

**Actores y fronteras:**

| Actor | Qué puede intentar | Frontera |
|---|---|---|
| Anónimo en Internet | Leer o cambiar datos, adivinar la contraseña, agotar recursos | Autenticación en toda ruta salvo `/health` y el login, límites de peticiones y cuerpo, `Host` permitido |
| Web de terceros abierta en el navegador del dueño | Hacer peticiones con su sesión (CSRF), incrustar la app (clickjacking) | `SameSite=Strict`, token CSRF, CORS cerrado, `frame-ancestors 'none'` |
| Contenido inyectado en la página (XSS) | Robar credenciales | La cookie es `HttpOnly`, no hay secretos en `localStorage` ni `sessionStorage`, y la CSP no permite scripts inline |
| El propio dueño en un mal momento | Saltarse sus límites | Los límites se aplican en el dominio y la API; el frontend no puede omitirlos |
| Alguien con acceso a disco o a la base | Editar apuestas o límites sin dejar rastro, cambiar un modelo | Auditoría encadenada, triggers, `CHECK`, `verify-integrity`, hash de modelos y copias fuera del servidor |
| Dependencias y CI | Introducir código vulnerable o malicioso | `pip-audit`, `npm audit`, gitleaks, acciones fijadas por SHA, Dependabot, imágenes por digest |

## 2. Controles

Las rutas de Python son relativas a `src/betting_ml/`; las demás, a la raíz del repositorio.

| Control | Cómo | Dónde |
|---|---|---|
| Autenticación | Toda ruta `/api/v1/*` exige sesión o `X-API-Key`, salvo `/health` y `POST /auth/login`. Un test recorre **todas** las rutas registradas. | `api/dependencies.py`, `tests/integration/test_route_access.py` |
| Contraseña | Solo el hash **Argon2id** (`APP_PASSWORD_HASH`). Se genera con `betting-ml hash-password`. | `adapters/argon2_hasher.py` |
| Sesión | Token aleatorio de 256 bits en una cookie `HttpOnly; SameSite=Strict` (y `Secure` en prod). En la base solo se guarda su HMAC. Caduca a los 30 min sin uso o a las 12 h. El logout y el cambio de contraseña la revocan. | `application/authenticate.py` |
| CSRF | Las escrituras con sesión exigen `X-CSRF-Token`. El token llega en la respuesta del login y de `/auth/me`; nunca se guarda en el navegador. | `api/security.py`, `frontend/src/lib/session.ts` |
| Clave de máquina | `APP_API_KEY` (Postman, CLI) se compara en tiempo constante. En prod la API **no arranca** con una clave de menos de 32 caracteres o de ejemplo. | `config.py` |
| Fuerza bruta | 5 intentos de login por minuto por IP (o /64 en IPv6), con bloqueos de 1, 5 y 15 min. Los intentos se cuentan antes de verificar la contraseña. | `application/throttle.py` |
| Abuso | 120 peticiones por minuto por IP, cuerpo máximo de 64 KiB, `Host` permitido y cupo global de refrescos de cuotas. | `api/middleware/` |
| Entrada | Esquemas estrictos (`extra="forbid"`, patrones, rangos). El 422 no devuelve los valores enviados y un 500 no filtra detalles. | `api/schemas_002.py`, `api/errors.py` |
| Cabeceras | CSP sin inline ni `eval`, `X-Frame-Options: DENY`, `nosniff`, `Referrer-Policy`, HSTS en prod y `no-store` en la API. `/docs` está desactivado en prod. | `api/middleware/security_headers.py`, `frontend/security-headers.ts`, `deploy/Caddyfile` |
| Integridad en la base | `CHECK` con los valores reales del esquema, claves foráneas y concurrencia optimista (`version`), así que una edición simultánea da 409 en lugar de pisarse. | `adapters/sql/models.py`, `migrations/` |
| Auditoría | `audit_log` es de **solo inserción**: unos triggers rechazan `UPDATE` y `DELETE`. Cada fila lleva el SHA-256 de la anterior y se escribe en la misma transacción que el cambio. Los logins fallidos auditados tienen un tope global de 100 por hora. | `adapters/sql/audit.py` |
| Verificación | `betting-ml verify-integrity` recorre la cadena, compara las apuestas y los ajustes con su último evento, revisa los PRAGMA y comprueba que los triggers sean los originales. | `application/maintenance.py` |
| Copias | `betting-ml backup`: una copia consistente con la API de backup de SQLite, verificada, con un `.sha256` compatible con `sha256sum -c` y rotación (14 por defecto). `restore` comprueba hash, esquema y cadena antes de reemplazar la base. | `application/maintenance.py` |
| Modelos | Antes de cargar un `.joblib` se comprueba su SHA-256 contra `metadata.json`. | `adapters/joblib_registry.py` |
| Logs | JSON con `request_id`, redacción global de secretos y eventos de seguridad (`LOGIN_OK`, `LOGIN_FAILED`, `LOGIN_LOCKED`, `ACCESS_DENIED`, `LOGOUT`, `SETTINGS_CHANGED`…). | `logging_config.py` |
| Cadena de suministro | `make security` (ruff S, pip-audit, npm audit, gitleaks) falla en CI ante cualquier hallazgo. Las acciones de CI se fijan por SHA y las imágenes Docker por digest; hay Dependabot. | `.github/`, `Dockerfile`, `deploy/` |
| Despliegue | Contenedor no root, raíz de solo lectura, `cap_drop: ALL` y la API sin puerto publicado. Caddy pone TLS y se fía solo de su propio `X-Forwarded-For`. | `deploy/compose.yaml`, `docs/deploy.md` |

Cada control tiene **tests negativos** (el ataque falla) y, en los críticos, una mutación comprobada: el control se desactiva a mano y un test falla.

## 3. Lo que no se protege (riesgos aceptados)

- **Quien controla el servidor controla los datos.** La cadena de auditoría no lleva clave: quien pueda escribir `data/app.db` puede rehacerla entera. `verify-integrity` detecta ediciones parciales, corrupciones y cambios hechos fuera de la API. Contra una reescritura completa, la defensa son las **copias guardadas fuera del servidor** con su `.sha256`: compara la base con la última copia externa.
- **Sin cifrado en reposo.** La base y las copias no están cifradas. Cifra el disco del servidor y el destino de las copias externas.
- **Un solo proceso.** El limitador de peticiones y el bloqueo de login viven en memoria. Con varias réplicas o workers dejarían de ser globales: habría que cambiar el adaptador de `RateLimiter`. Reiniciar el proceso los pone a cero.
- **Un solo usuario.** No hay roles ni cuentas. Si hiciera falta multiusuario, sería una spec nueva.
- **Las cuotas son autodeclaradas.** Las apuestas hechas en casas externas se registran con la cuota que escribe el dueño. La app no puede comprobarla.
- Otros puntos menores aceptados, con su motivo, en `specs/003-security-hardening/decisions.md` (entradas T010, T017 y T021).

## 4. Rotación de claves

Todas las claves viven solo en `.env` (nunca en el repositorio, en el frontend, en los fixtures ni en los logs). Para cambiar una:

1. edita `.env`;
2. **recrea** el contenedor (`docker compose -f deploy/compose.yaml up -d api`), porque `restart` no vuelve a leer el archivo.

| Qué | Efecto |
|---|---|
| `APP_API_KEY` | La anterior deja de valer al instante. Actualiza Postman y los scripts. |
| `SESSION_SECRET` | Se cierran todas las sesiones. |
| Contraseña (`APP_PASSWORD_HASH`) | Se cierran todas las sesiones. |
| `ODDS_API_KEY` | Regenérala en el panel de The Odds API. |

Si sospechas una filtración: rota lo afectado, busca en los logs `ACCESS_DENIED`, `LOGIN_FAILED` y `LOGIN_OK` desde IP desconocidas, ejecuta `verify-integrity` y compara con la última copia externa. Pasos completos en [`docs/deploy.md`](docs/deploy.md) §8.

## 5. Recuperar el acceso

- **Olvidaste la contraseña.** No hay recuperación por correo, a propósito. En el servidor:
  1. ejecuta `uv run betting-ml hash-password` (pide la contraseña nueva sin mostrarla);
  2. pega el hash en `APP_PASSWORD_HASH` del `.env`;
  3. recrea el contenedor.

  Las sesiones anteriores quedan cerradas.
- **Estás bloqueado por intentos fallidos.** El bloqueo dura como mucho 15 minutos. Si alguien está probando contraseñas desde tu misma red, revisa `LOGIN_FAILED` en los logs antes de reiniciar la API (reiniciar borra el contador).
- **Perdiste `APP_API_KEY`.** Genera una nueva (ver §4). No hace falta la anterior.

## 6. Copias de seguridad e integridad

- `betting-ml backup` cada noche (ejemplo de `cron` en `docs/deploy.md` §7). **Copia también `backups/` fuera del servidor**: es la única defensa contra quien reescriba la base.
- Comprueba una copia con `sha256sum -c app-AAAAMMDD-HHMMSS.db.sha256`.
- `betting-ml restore <copia> --yes` verifica el hash, el esquema y la cadena **antes** de reemplazar la base, guarda la base actual como copia previa y deja un evento `DB_RESTORED` en la auditoría.
- `betting-ml verify-integrity` después de cada restauración y, como rutina, una vez por semana. Sale con código distinto de 0 si encuentra un problema.

## 7. Comprobaciones

```bash
uv run pytest            # incluye los tests negativos de cada control
make security            # ruff S, pip-audit, npm audit y gitleaks (sin make: ver el Makefile)
uv run betting-ml verify-integrity
```

## 8. Informar de una vulnerabilidad

No abras un *issue* público. Usa el aviso privado de vulnerabilidades de GitHub del repositorio (*Security → Report a vulnerability*) o escribe directamente al dueño del repositorio. Incluye:

- la versión (commit);
- los pasos para reproducirlo, con datos de prueba;
- el impacto que observaste.

No pruebes contra un despliegue ajeno ni con datos reales. Se responderá en cuanto sea posible, y el arreglo irá con un test que reproduzca el fallo.
