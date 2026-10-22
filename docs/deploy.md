# Despliegue en producción

Guía para publicar betting-ml en un servidor propio con TLS. Es parte de la spec 003 (T020). Los archivos están en `deploy/`:

- `compose.yaml`: los dos contenedores y su red.
- `Caddyfile`: TLS, proxy, frontend y cabeceras.

## 1. Arquitectura

```
Internet ──443/80──► Caddy (TLS automático, HSTS, cabeceras, log sin credenciales)
                       ├── /api/*, /health ──► api:8000  (uvicorn, sin puertos publicados)
                       └── resto           ──► frontend/dist (estático, index.html para las rutas)
                     red "edge" 172.30.0.0/24: Caddy 172.30.0.2, API 172.30.0.3
```

- **Un solo origen.** El frontend y la API comparten dominio. La cookie de sesión sigue siendo `SameSite=Strict` y CORS no interviene.
- **La API solo es accesible a través de Caddy.** Solo cree `X-Forwarded-For` cuando viene de la IP de Caddy (`FORWARDED_ALLOW_IPS`, la fija el compose), así que el bloqueo del login ve la IP real del cliente y nadie puede elegir otra.
- **Dos contenedores con raíz de solo lectura.**
  - **API:** el único volumen escribible es `data/` (base SQLite, copias y cachés). `models/` y `reports/` se montan de solo lectura, y el código pertenece a `root`, no al usuario `app` (uid 10001) con el que corre.
  - **Caddy:** escribe solo en sus volúmenes de certificados.
- **Imágenes fijadas por digest:** `python`, `uv` y `caddy`.
- **Arranque comprobado en CI.** El job `docker` construye la imagen, la arranca con `--read-only`, sin capacidades, y comprueba `/health`, el uid y que el código no se puede escribir. También valida el `Caddyfile` y el compose.

## 2. Requisitos

- Servidor Linux con Docker Engine y el plugin `docker compose` v2.
- Un dominio (por ejemplo `apuestas.example.com`) con registros A/AAAA hacia el servidor.
- Los puertos 80 y 443 abiertos: Caddy obtiene y renueva el certificado solo.
- Para generar datos, modelos y el frontend: `uv` y Node 24. Puede hacerse en otra máquina y copiar el resultado.

## 3. Preparar

Desde la raíz del repositorio:

```bash
# 1. Datos y modelos. Cada model.joblib queda con su SHA-256 en metadata.json.
uv sync
uv run betting-ml data
uv run betting-ml train-prod
# Si copias modelos entrenados en otra máquina, revísalos y registra su hash una vez:
#   uv run betting-ml models-rehash

# 2. Frontend
(cd frontend && npm ci && npm run build)        # genera frontend/dist

# 3. Permisos: el contenedor escribe data/ como uid 10001
sudo chown -R 10001:10001 data
chmod -R a+rX models reports frontend/dist
```

### `.env` de producción

Crea `.env` en la raíz a partir de `.env.example` y protégelo con `chmod 600 .env`. Nunca entra en la imagen: el compose lo pasa como entorno.

| Variable | Valor en producción |
|---|---|
| `APP_ENV` | `prod`. Lo fija el compose: activa JSON en los logs, cookies `Secure` y HSTS, y quita `/docs`. |
| `APP_PASSWORD_HASH` | Salida de `uv run betting-ml hash-password` (Argon2id con m ≥ 19456, t ≥ 2). |
| `APP_API_KEY` | ≥ 32 caracteres: `python -c "import secrets; print(secrets.token_urlsafe(32))"`. |
| `SESSION_SECRET` | ≥ 32 caracteres, **distinto** de `APP_API_KEY`. |
| `ALLOWED_HOSTS` | El dominio: `apuestas.example.com`. Sin `*`. |
| `CORS_ORIGINS` | `https://apuestas.example.com` (mismo origen; nunca `*`). |
| `FORWARDED_ALLOW_IPS` | No hace falta: lo fija el compose (`172.30.0.2`). Nunca `*`. |
| `ODDS_API_KEY` | La clave de The Odds API (opcional). |
| `ODDS_AUTO_REFRESH` | `true` si quieres el refresco programado de cuotas. |
| `LOG_FORMAT` | Vacío (JSON en `prod`). |
| `BACKUP_KEEP` | Número de copias locales que se conservan (14 por defecto). |

La API **se niega a arrancar** en `prod` si algo de lo anterior es inseguro, y lista las variables que fallan (nunca sus valores).

## 4. Arrancar y comprobar

```bash
export DOMAIN=apuestas.example.com
docker compose -f deploy/compose.yaml up -d --build
docker compose -f deploy/compose.yaml ps            # api: healthy
```

Al arrancar, la API aplica las migraciones pendientes a `data/app.db`. Si alguna encuentra datos que no cumplen las restricciones, aborta sin tocar nada.

Comprobaciones:

```bash
curl -sI https://$DOMAIN/ | grep -iE 'strict-transport|content-security|x-frame'
curl -s https://$DOMAIN/health                       # {"status":"ok",...}
curl -s -o /dev/null -w '%{http_code}\n' https://$DOMAIN/api/v1/bets   # 401 sin credenciales
docker compose -f deploy/compose.yaml exec api betting-ml verify-integrity
```

Después, entra con la contraseña desde el navegador.

## 5. Qué protege cada pieza

| Pieza | Protección |
|---|---|
| Raíz de solo lectura, `tmpfs` en `/tmp` | Un fallo en la API no puede modificar el código ni dejar nada fuera de `data/`. |
| `cap_drop: ALL`, `no-new-privileges`, uid 10001 | Sin privilegios del kernel ni escalada (Caddy solo conserva `NET_BIND_SERVICE`). |
| API sin `ports` | Solo se llega a ella a través de Caddy. |
| `FORWARDED_ALLOW_IPS` = IP de Caddy | El límite de intentos de login usa la IP real del cliente. |
| TLS automático, HSTS | Cookies `Secure` y nada en claro. |
| Cabeceras de Caddy | La misma CSP que la API y que `vite preview` (`frontend/security-headers.ts`). |
| `admin off` y log filtrado de Caddy | No hay API de administración. El log de acceso no lleva `X-Api-Key`, `X-CSRF-Token` ni claves en la query; Caddy ya oculta `Cookie` y `Authorization`. |
| Imágenes por digest | Una etiqueta movida no cambia lo que se despliega. |

## 6. Logs y eventos de seguridad

Los logs de la API son JSON, con `request_id` en cada línea, y las credenciales aparecen como `[REDACTED]`.

```bash
docker compose -f deploy/compose.yaml logs -f api | jq 'select(.logger == "betting_ml.security")'
```

Eventos de seguridad:

- `LOGIN_OK`, `LOGIN_FAILED`, `LOGIN_LOCKED` y `LOGOUT`;
- `ACCESS_DENIED`, con `code`: `UNAUTHORIZED` o `CSRF_FAILED`;
- `SETTINGS_CHANGED`, que incluye los cambios de límites y cuándo entran en vigor;
- `INTEGRITY_CHECK_FAILED` y `MODEL_INTEGRITY_FAILED`.

Un `X-Request-ID` de una respuesta lleva a todas las líneas de esa petición.

## 7. Copias de seguridad y restauración

### Copias diarias, también fuera del servidor

```bash
# crontab -e en el servidor (cada noche a las 03:00)
0 3 * * * cd /srv/betting-ml && docker compose -f deploy/compose.yaml exec -T api betting-ml backup
15 3 * * * cd /srv/betting-ml && docker compose -f deploy/compose.yaml exec -T api betting-ml verify-integrity || echo "verify-integrity falló" | mail -s betting-ml tu@correo
```

- **Qué deja cada copia.** `data/backups/app-AAAAMMDD-HHMMSS.db` más su `.sha256`, ya verificada (integridad de SQLite, tablas y auditoría). Se conservan las `BACKUP_KEEP` más recientes.
- **Sácalas del servidor** con cualquier herramienta (`rclone`, `restic`, `scp`): el `.db` **y** su `.sha256`. Comprueba en el destino:
  ```bash
  sha256sum -c app-20261022-030000.db.sha256
  ```
- **Por qué fuera.** Quien tenga escritura sobre `data/app.db` podría añadir eventos válidos a la auditoría, porque la cadena no lleva clave (riesgo aceptado en `specs/003-security-hardening/decisions.md`, T017). Una copia fuera del servidor conserva el estado real de cada día para compararlo.

### Restaurar

```bash
docker compose -f deploy/compose.yaml stop api
docker compose -f deploy/compose.yaml run --rm --no-deps api \
  betting-ml restore /app/data/backups/app-20261022-030000.db
docker compose -f deploy/compose.yaml start api
docker compose -f deploy/compose.yaml exec api betting-ml verify-integrity
```

Qué hace `restore`:

1. Verifica el hash, SQLite y la auditoría de la copia.
2. Guarda antes el estado actual (`pre-restore-…`).
3. Pide confirmación (`--yes` para scripts).
4. Restaura y cierra todas las sesiones.

Casos especiales:

- **Base actual dañada:** `--force` la guarda en bruto (`unverified-pre-restore-…`) y restaura igualmente.
- **Copia anterior a la auditoría:** necesita `--allow-legacy`.

## 8. Rotación de claves

Los cambios en `.env` exigen **recrear** el contenedor (`up -d`); `restart` no vuelve a leer el archivo.

| Qué | Cómo | Efecto |
|---|---|---|
| `APP_API_KEY` | Genera una nueva, edita `.env` y ejecuta `docker compose -f deploy/compose.yaml up -d api`. Actualiza Postman y los scripts. | La clave anterior deja de valer al instante. |
| `SESSION_SECRET` | Genera uno nuevo, edita `.env` y ejecuta `up -d api`. | Se cierran todas las sesiones: los tokens se guardan como HMAC de este secreto. |
| Contraseña | `uv run betting-ml hash-password`, pega el resultado en `APP_PASSWORD_HASH` y ejecuta `up -d api`. | Se cierran todas las sesiones: llevan la huella de la contraseña. |
| `ODDS_API_KEY` | Regenérala en el panel de The Odds API, edita `.env` y ejecuta `up -d api`. | Las consultas usan la nueva. |

Si sospechas que algo se filtró:

1. Rota lo afectado.
2. Revisa en los logs `ACCESS_DENIED`, `LOGIN_FAILED` y `LOGIN_OK` desde IP desconocidas.
3. Ejecuta `verify-integrity`.
4. Compara el estado con la última copia externa.

## 9. Actualizar

```bash
git pull
(cd frontend && npm ci && npm run build)
docker compose -f deploy/compose.yaml up -d --build
```

- **Dependencias y acciones de CI:** llegan como PR de Dependabot, y la CI debe estar en verde (job `security` incluido).
- **Imágenes base:** Dependabot no las actualiza. Para renovar un digest:
  ```bash
  docker buildx imagetools inspect python:3.12-slim      # "Digest:" del índice
  docker buildx imagetools inspect caddy:2.11
  ```
  Cambia la etiqueta y el digest en `Dockerfile` o en `deploy/compose.yaml`, y deja que la CI construya y arranque la imagen antes de desplegar.
