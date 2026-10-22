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
