"""FastAPI application: routers only call application use cases (constitution §V.3)."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from betting_ml import __version__
from betting_ml.api.errors import register_error_handlers
from betting_ml.api.routers import (
    admin,
    experiments,
    health,
    journal,
    leagues,
    matches,
    model,
    predictions,
    tracking,
)
from betting_ml.application.predict_matches import ModelNotAvailableError

logger = logging.getLogger(__name__)
LOCALHOST_ORIGINS = r"https?://(localhost|127\.0\.0\.1|\[::1\])(:\d+)?"
ROUTERS = (health, leagues, matches, predictions, model, experiments, tracking, admin, journal)


def create_app(services: Any | None = None) -> FastAPI:
    """``services`` exposes predictor, tracking, leagues, read_experiments, admin_api_key and
    refresher (see Container.api_services); by default it is built lazily at startup."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if app.state.container is None:
            from betting_ml.container import Container

            app.state.container = Container().api_services()
        try:  # warm-up: load models and Elo state once
            app.state.container.predictor.state()
        except ModelNotAvailableError as exc:
            logger.warning("API started without a trained model: %s", exc)
        yield

    app = FastAPI(
        title="betting-ml API",
        version=__version__,
        description="Predicciones 1X2 y value bets para las 5 grandes ligas (contracts/api.md).",
        lifespan=lifespan,
    )
    app.state.container = services
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=LOCALHOST_ORIGINS,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    register_error_handlers(app)
    for router in ROUTERS:
        app.include_router(router.router)
    return app


app = create_app()
