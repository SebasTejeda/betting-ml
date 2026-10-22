"""FastAPI application: routers only call application use cases (constitution §V.3)."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from betting_ml import __version__
from betting_ml.api.dependencies import ServicesApi
from betting_ml.api.errors import register_error_handlers
from betting_ml.api.middleware.body_limit import BodyLimitMiddleware
from betting_ml.api.middleware.rate_limit import RateLimitMiddleware
from betting_ml.api.routers import (
    admin,
    auth,
    backtest,
    bets,
    bookmakers,
    calculator,
    comparator,
    experiments,
    health,
    leagues,
    matches,
    model,
    odds,
    predictions,
    settings,
    tracking,
)
from betting_ml.application.predict_matches import ModelNotAvailableError
from betting_ml.config import ensure_secure, get_settings

logger = logging.getLogger(__name__)
LOCALHOST_ORIGINS = r"https?://(localhost|127\.0\.0\.1|\[::1\])(:\d+)?"
# Order = order of the paths in OpenAPI. Each router declares its access policy (api/security.py).
ROUTERS = (
    health.router,
    auth.login_router,
    auth.reads,
    auth.writes,
    leagues.router,
    matches.router,
    predictions.router,
    model.router,
    experiments.router,
    tracking.router,
    admin.router,
    odds.writes,
    odds.reads,
    bookmakers.router,
    comparator.router,
    calculator.router,
    bets.writes,
    bets.reads,
    settings.reads,
    settings.writes,
    backtest.router,
)


def create_app(services: ServicesApi | None = None) -> FastAPI:
    """``services`` follows ServicesApi (see Container.api_services); by default it is built
    lazily at startup."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if app.state.container is None:
            from betting_ml.container import Container

            ensure_secure(get_settings())  # before loading anything (spec 003, US3)
            app.state.container = Container().api_services()
        try:  # warm-up: load models and Elo state once
            app.state.container.predictor.state()
        except ModelNotAvailableError as exc:
            logger.warning("API started without a trained model: %s", exc)
        auth = getattr(app.state.container, "auth", None)
        if auth is not None:
            auth.purge()  # expired sessions do not outlive a restart
        journal = getattr(app.state.container, "journal", None)
        starter = getattr(journal, "start_auto_refresh", None)
        scheduler = starter() if starter is not None else None
        try:
            yield
        finally:
            if scheduler is not None:
                scheduler.shutdown(wait=False)

    app = FastAPI(
        title="betting-ml API",
        version=__version__,
        description="Predicciones 1X2 y value bets para las 5 grandes ligas (contracts/api.md).",
        lifespan=lifespan,
    )
    app.state.container = services
    # added innermost first: CORS → body limit → rate limit → routers (plan.md §3)
    app.add_middleware(RateLimitMiddleware)
    app.add_middleware(BodyLimitMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=LOCALHOST_ORIGINS,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    register_error_handlers(app)
    for router in ROUTERS:
        app.include_router(router)
    return app


app = create_app()
