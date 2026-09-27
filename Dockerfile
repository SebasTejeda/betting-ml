# API de betting-ml. Imagen slim, usuario no root.
# Construir:  make docker            (docker build -t betting-ml:latest .)
# Ejecutar:   docker run --rm -p 8000:8000 \
#               -v "$(pwd)/data:/app/data" -v "$(pwd)/models:/app/models" \
#               --env-file .env betting-ml:latest
# Los modelos (models/*/model.joblib) y los datos (data/processed/history.parquet) se generan con
# `make data && make train-prod` y se montan como volúmenes: no se copian a la imagen.
FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH"

# libgomp1: runtime de OpenMP que necesitan LightGBM y XGBoost.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.5 /uv /usr/local/bin/uv

WORKDIR /app

# Dependencias primero (capa cacheable), luego el código.
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project

COPY src ./src
COPY configs ./configs
RUN uv sync --frozen --no-dev

RUN useradd --create-home --uid 10001 app \
    && mkdir -p /app/data /app/models /app/reports \
    && chown -R app:app /app
USER app

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health')" || exit 1

CMD ["uvicorn", "betting_ml.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
