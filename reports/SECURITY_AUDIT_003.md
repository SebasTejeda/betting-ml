# Auditoría final de seguridad — spec 003 (T021)

## 1. Alcance y método

| | |
|---|---|
| Fuente | rama `Daniel`, commit `dc64fed`, árbol limpio |
| Perfil | **quick**: una ola de cazadores y un crítico final. **Es una pasada parcial.** |
| Alcance | `src/betting_ml`, `migrations`, `frontend/src`, `frontend/security-headers.ts`, `frontend/vite.config.ts`, `Dockerfile`, `deploy/`, `.github/`, `pyproject.toml`, `Makefile` |
| Presupuesto | 16 invocaciones de agente; se usaron 14: 4 de reconocimiento, 6 cazadores, 1 crítico y 3 verificadores |
| Ejecución | solo lectura del código fuente |
| Ejecuciones previas | ninguna para este repositorio |

- **Sin ejecución de código.** El equipo (Windows 11, sin Docker ni WSL) no puede aplicar el sandbox que exige el método: entorno vacío, sin red, objetivo de solo lectura y límites de recursos. Por eso ningún agente ejecutó código del proyecto ni se promovió ningún artefacto, y **ningún hallazgo puede quedar `confirmed`**: los candidatos que sobrevivieron quedan en `needs_validation`.
- **Validadores.** Se llamaron a través de su función exportada `validateDocument`, porque Node en Windows no ofrece `O_NOFOLLOW` para su lector de archivos. Las entradas son archivos escritos por el auditor.
- **Antecedentes.** `reports/SECURITY_BASELINE.md` (T002) y los riesgos aceptados de `specs/003-security-hardening/decisions.md` se usaron como contexto, no como un ledger de esta herramienta.

## 2. Postura

No hay hallazgos confirmados ni críticos o altos.

Los controles principales resisten la revisión de código en todas las rutas:

- autenticación por ruta (una sola política, probada sobre `app.routes`);
- CSRF ligado a la sesión;
- sesiones con HMAC;
- límite de intentos antes de Argon2;
- auditoría encadenada de solo inserción;
- carga de modelos verificada sobre los mismos bytes;
- restauración verificada;
- registros con redacción de secretos;
- CI con permisos mínimos y acciones fijadas;
- contenedores de solo lectura.

Quedan **dos pistas de disponibilidad** que dependen de cómo se despliegue: la red IPv6 y la tasa de Argon2 en el host.

## 3. Hallazgos confirmados

Ninguno: la ejecución local no estaba disponible (ver §1).

## 4. NEEDS VALIDATION

Detalle en `NEEDS-VALIDATION.md`.

| Pista | Traza | Bloqueo | Siguiente paso local | Comprobación del dueño |
|---|---|---|---|---|
| Con un registro AAAA, todos los clientes IPv6 comparten una sola clave de bloqueo de login y de límite global | `deploy/compose.yaml:38` (puertos sin IP) → `:59` (red `edge` solo IPv4) → `Caddyfile:14` → `compose.yaml:15` → `api/security.py:42` → `application/throttle.py:79` | Comportamiento del demonio Docker (userland-proxy, ipv6) y existencia del AAAA | Compose sin cambios en una VM aislada: `curl -6` y `curl -4`, y comparar el campo `client` en los logs | `dig AAAA`, `docker info`, y contar `remote_ip` en los logs de Caddy |
| Los fallos de login anónimos añaden filas permanentes a `audit_log` sin tope global | `routers/auth.py:35` → `api/security.py:55` → `throttle.py:82` → `authenticate.py:77-80` → `adapters/sql/audit.py:124` | Tiempo de Argon2 y bytes por fila; alcance IPv6; límites fuera del repositorio | Sandbox con 10 clientes IPv6 sintéticos; contar filas por cliente y comprobar que no hay tope agregado | Tiempo de un verify en el host, disco libre y 14 copias de backup |

## 5. Rechazado

- `manage_bets.create:real-bet-on-started-match-offsets-monthly-loss`. El cazador planteó que apostar "real" sobre un partido ya jugado anulaba la pérdida mensual. El verificador lo rechazó por tres motivos:
  1. Con el bloqueo activo, `create` devuelve 403 antes de mirar el partido.
  2. Las cuotas son autodeclaradas por diseño, y la misma compensación funciona antes del inicio.
  3. Solo afecta al propio dueño.
- Queda como nota de producto (§6).

## 6. Endurecimiento (no son hallazgos)

**Despliegue**
- `APP_ENV` es `dev` por defecto y la imagen escucha en `0.0.0.0` fuera del compose; `make serve` también escucha en `0.0.0.0`.
- La cookie no usa el prefijo `__Host-`.
- Los hooks de pre-commit están fijados por etiqueta.

**Límites y disponibilidad**
- El límite de login es solo por IP o /64, sin presupuesto global.
- El limitador en memoria expulsa por orden de inserción y puede vaciar los contadores de seguridad.
- `/health` recarga el modelo en cada llamada mientras el servicio está degradado.
- `admin/refresh` y `odds/refresh` no impiden ejecuciones simultáneas.

**Integridad**
- `verify-integrity` comprueba los triggers solo por nombre, no por su SQL.
- `joblib_registry.path()` no valida la versión.

**Validación de entradas**
- Importes de ajustes enormes acaban en un 500 (`InvalidOperation`).
- `fixtures._odds` acepta `inf`.
- `Credits.from_headers` no captura `OverflowError`.
- `TextFormatter` (dev) no escapa saltos de línea.
- `MODEL_NOT_AVAILABLE` muestra la ruta de `models/` a usuarios autenticados.

**Producto**
- Las apuestas registradas después del inicio y las cuotas muy por encima del mercado podrían marcarse o excluirse del cálculo del límite.

**Patrones positivos**
- Una sola política por router, con un test que recorre todas las rutas.
- Comparaciones en tiempo constante.
- Sin secretos en el navegador.
- Hash del modelo sobre los mismos bytes que se cargan.
- `after_restore` purga las sesiones.
- Lockfiles con hashes, y `--locked`/`--frozen` en CI y en la imagen.

## 7. Cobertura (ledger)

- **Resultado:** 15 unidades. 10 cubiertas, 3 con candidato (2 en `needs_validation` y 1 rechazada), 0 bloqueadas y 2 aplazadas.
- **Aplazadas por el crítico final (perfil quick):**
  - liquidación desde los resultados de football-data (`settle_bets.py`): correcciones, colisiones de `match_id` y CLV;
  - límites de tamaño y de parseo en las descargas de football-data, fixtures y Understat (`adapters/http.py` no limita bytes).
- **Bloques no asignados:** Wildcard, Feature abuse, HTTP framing, Federated identity, MFA, IAM y Release. No se afirma una cobertura completa.

## 8. Estado tras T021 (commit de esta tarea)

| Origen | Punto | Estado |
|---|---|---|
| Auditoría (needs_validation) | IPv6 colapsado en la pasarela del bridge | **Corregido en el despliegue**. La red `edge` tiene IPv6 (ULA `fd00:30::/64`) y `FORWARDED_ALLOW_IPS` incluye las dos direcciones de Caddy. La guía exige Docker ≥ 27 y explica cómo comprobarlo. Tests: `test_ipv6_clients_keep_their_own_address`. |
| Auditoría (needs_validation) | Crecimiento de `audit_log` por logins fallidos anónimos | **Corregido**. Un presupuesto global de 100 `LOGIN_FAILED` auditados por hora (`LoginThrottle.audit_failure`). Todos siguen en el log de seguridad y cuentan para el bloqueo. |
| ml-reviewer M1 | Los middlewares leían el contenedor con `getattr` sobre `Any`, así que un campo renombrado apagaba el control sin aviso | **Corregido**. Ahora usan `scope_services()` tipado con `ServicesApi`, y mypy comprueba que `ApiServices` cumple el protocolo. Los stubs declaran explícitamente los controles apagados. Hay un test de punta a punta con el contenedor real (400, 413 y 429). |
| ml-reviewer M2 | `APP_API_KEY` aparecía en el `repr` de `ApiServices` | **Corregido** con `field(repr=False)` y su test. |
| Auditoría (endurecimiento) | Importes de ajustes enormes daban 500 | **Corregido**: 12 dígitos y 2 decimales, ahora 422. |
| Auditoría y ml-reviewer | `verify-integrity` comprobaba los triggers solo por nombre | **Corregido**. Ahora compara su SQL y rechaza cualquier trigger inesperado. |
| Resto de §6 y observaciones bajas del ml-reviewer | Endurecimiento | Registrado en `specs/003-security-hardening/decisions.md` (T021): aceptado o pendiente. |

Mutaciones: 8, todas detectadas por un test (host, límite global, tamaño del cuerpo, presupuesto de auditoría, cuerpo del trigger, trigger extra, clave en `repr` e importes sin límite).

## Anexo — pistas que se validaron (texto de la auditoría)

## 1. Colapso de la IP de clientes IPv6 detrás de la red `edge` solo IPv4

`deploy/compose.yaml:edge-ipv4-only-network:docker-proxy-client-ip-collapse`

### Traza
1. `deploy/compose.yaml:36-39`: Caddy publica 80, 443 y 443/udp sin IP de host, así que escucha también en `[::]`. `docs/deploy.md:28` pide registros A/AAAA.
2. `deploy/compose.yaml:55-59`: la red `edge` solo tiene la subred 172.30.0.0/24 y no tiene `enable_ipv6`. Con el userland-proxy por defecto, una conexión IPv6 llega a Caddy desde la pasarela del bridge.
3. `deploy/Caddyfile:14`: no hay `trusted_proxies`, así que Caddy pone en `X-Forwarded-For` su par de conexión, es decir, la pasarela.
4. `deploy/compose.yaml:15` y `src/betting_ml/cli.py:184-185`: uvicorn cree a 172.30.0.2, por lo que el cliente pasa a ser la pasarela.
5. `src/betting_ml/api/security.py:42-56`: la pasarela es una dirección IPv4 y la agrupación por /64 nunca se aplica. Todos los clientes IPv6 acaban con la misma clave.
6. `src/betting_ml/application/throttle.py:76-89`: seis contraseñas erróneas bloquean `login-lock:<pasarela>` durante 1, 5 y 15 minutos, y la contraseña correcta del dueño se rechaza sin comprobarla.
7. El mismo cliente puede agotar el cubo de 120 peticiones/min compartido (`api/middleware/rate_limit.py:27`), también con API key.

### Frontera
Un cliente anónimo de internet consigue bloquear el login y limitar a todos los demás usuarios IPv6, incluido el dueño. Se rompe la garantía de `docs/deploy.md:18` y `:100`. El efecto es solo de disponibilidad.

### Bloqueos
- Comportamiento del demonio Docker en el host: versión, `userland-proxy`, `ipv6` e `ip6tables`.
- Si el dominio tiene AAAA y el host tiene IPv6 pública.

### Plan local
VM Linux aislada con Docker por defecto, secretos ficticios y `DOMAIN=localhost`:
1. Ejecuta `curl -4` y `curl -6` contra `/health` y compara el campo `client` del log JSON de la API y el `remote_ip` de Caddy.
2. Si colapsa, envía 6 logins erróneos por IPv6 y luego uno correcto desde otro origen IPv6: debería devolver 429.
3. Regresión: añade `enable_ipv6` con una subred ULA, o publica solo en `0.0.0.0`.

### Comprobación del dueño
`dig AAAA $DOMAIN`, `docker info`, `/etc/docker/daemon.json`, `ss -ltnup` y el recuento de `remote_ip` en los logs de Caddy. No provoques bloqueos en producción.

## 2. Crecimiento del log de auditoría por logins fallidos anónimos

`betting_ml/application/authenticate.py:Authenticate.login:anonymous-login-failed-audit-append-unbounded`

### Traza
1. `src/betting_ml/api/routers/auth.py:35`: el login es público.
2. `src/betting_ml/api/security.py:55`: la identidad del cliente es la IPv4 o el /64.
3. `src/betting_ml/application/throttle.py:82`: permite 5 intentos/min por cliente y luego bloquea; no lleva cuenta global.
4. `src/betting_ml/application/authenticate.py:77-80`: cada fallo añade `LOGIN_FAILED`.
5. `src/betting_ml/adapters/sql/audit.py:124`: la escritura toma el lock global y añade una fila que no se puede borrar (`migrations/versions/0007_audit_log.py:28-30`).

### Frontera
Un cliente anónimo con muchas identidades (un /48 IPv6 o una botnet) hace crecer `app.db` y las 14 copias de backup al ritmo de Argon2 (2 en paralelo). Además compite por el lock de escritura con el diario. El límite de `decisions.md:223` es solo por cliente.

### Bloqueos
- Tiempo de verificación Argon2 y bytes por fila.
- Si la API es accesible por IPv6 y si hay límites fuera del repositorio.
- Disco libre y política de copias.

### Plan local
Sandbox con base temporal, Argon2 real y 10 clientes IPv6 sintéticos:
1. Comprueba que entran 5 filas por cliente antes de cada bloqueo, sin tope agregado.
2. Mide los bytes por fila.
3. Comprueba que `DELETE` aborta.

### Comprobación del dueño
Mide el tiempo de un verify en el host. Las filas por día son aproximadamente `2 / t × 86 400`; multiplícalas por los bytes por fila y por 15 copias, y compáralo con el disco libre. Haz un `SELECT` de solo lectura sobre una copia.
