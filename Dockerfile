# API de betting-ml. Imagen slim fijada por digest, usuario no root, código de solo lectura.
# Construir:  make docker            (docker build -t betting-ml:latest .)
# Desplegar:  docs/deploy.md         (Caddy con TLS delante, deploy/compose.yaml)
# Ejecutar a mano (raíz de solo lectura; solo data/ es escribible):
#   docker run --rm -p 8000:8000 --read-only --tmpfs /tmp \
#     -v "$(pwd)/data:/app/data" -v "$(pwd)/models:/app/models:ro" \
#     -v "$(pwd)/reports:/app/reports:ro" --env-file .env betting-ml:latest
# Los modelos (models/*/model.joblib) y los datos (data/processed/history.parquet) se generan con
# `make data && make train-prod` y se montan como volúmenes: no se copian a la imagen.
#
# Las imágenes base van por digest (una etiqueta se puede mover); Dependabot no actualiza este
# archivo, así que se renuevan a mano con docs/deploy.md §Actualizar.
FROM python:3.12.15-slim@sha256:cb33f7f771ecec2ef1225cf39b159591a040391bd73e4c01f00fdfc4c47611d2 AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    MPLCONFIGDIR=/tmp/matplotlib \
    PATH="/opt/venv/bin:$PATH"

# libgomp1: runtime de OpenMP que necesitan LightGBM y XGBoost.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.12.5@sha256:e85be844203885286c60ffad8a858d48afb6c5a5c237ca0e67f12e74b8f174b1 /uv /usr/local/bin/uv

WORKDIR /app

# Dependencias primero (capa cacheable), luego el código.
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project

COPY src ./src
COPY configs ./configs
RUN uv sync --frozen --no-dev

# The code stays root's: the app user can only write data/ (models/ and reports/ are mounted
# read-only in the deployment). Nothing under /app/.env: secrets come from the environment.
RUN useradd --create-home --uid 10001 app \
    && mkdir -p /app/data /app/models /app/reports \
    && chown app:app /app/data /app/models /app/reports
USER app

EXPOSE 8000
# The Host is the first of ALLOWED_HOSTS, so the host filter of prod lets the check through.
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s CMD ["betting-ml", "healthcheck"]

# X-Forwarded-For is trusted only from FORWARDED_ALLOW_IPS (the proxy); empty, from nobody.
CMD ["betting-ml", "serve", "--host", "0.0.0.0", "--port", "8000"]
