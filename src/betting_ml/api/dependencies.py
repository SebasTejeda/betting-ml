"""Dependency injection: the composition root (Container) lives in app.state. Routers see it
only through these protocols, built from application types (never adapters)."""

from __future__ import annotations

import secrets
from collections.abc import Callable
from typing import TYPE_CHECKING, Protocol

from fastapi import Depends, Header, Request

from betting_ml.api.errors import ApiError
from betting_ml.application.compare_matches import CompareMatches, EvaluateManualOdds
from betting_ml.application.manage_bets import ManageBets
from betting_ml.application.predict_matches import PredictMatches
from betting_ml.application.read_backtest import ReadBacktestReport
from betting_ml.application.refresh_odds import RefreshOdds
from betting_ml.application.settle_bets import SettleBets
from betting_ml.application.track_predictions import TrackPredictions
from betting_ml.config import EXAMPLE_KEY, BookmakersFile, LeaguesFile

if TYPE_CHECKING:
    import pandas as pd


class Refresher(Protocol):
    def fixtures(self) -> int: ...

    def data(self) -> None: ...


class JournalApi(Protocol):
    """Spec-002 use cases (container.JournalServices)."""

    @property
    def refresh_odds(self) -> RefreshOdds: ...

    @property
    def compare(self) -> CompareMatches: ...

    @property
    def calculator(self) -> EvaluateManualOdds: ...

    @property
    def bets(self) -> ManageBets: ...

    @property
    def settle(self) -> SettleBets: ...

    @property
    def bookmakers(self) -> BookmakersFile: ...

    @property
    def app_api_key(self) -> str: ...

    @property
    def read_backtest(self) -> ReadBacktestReport: ...


class ServicesApi(Protocol):
    """Everything the API uses (container.ApiServices)."""

    @property
    def predictor(self) -> PredictMatches: ...

    @property
    def tracking(self) -> TrackPredictions: ...

    @property
    def leagues(self) -> LeaguesFile: ...

    @property
    def read_experiments(self) -> Callable[[], pd.DataFrame]: ...

    @property
    def admin_api_key(self) -> str: ...

    @property
    def refresher(self) -> Refresher: ...

    @property
    def journal(self) -> JournalApi | None: ...


def get_services(request: Request) -> ServicesApi:
    services: ServicesApi = request.app.state.container
    return services


def get_journal(services: ServicesApi = Depends(get_services)) -> JournalApi:
    if services.journal is None:
        raise ApiError(503, "SERVICE_NOT_AVAILABLE", "Servicios de la spec 002 no configurados")
    return services.journal


def require_app_key(
    x_api_key: str | None = Header(None), journal: JournalApi = Depends(get_journal)
) -> None:
    """Spec-002 writes need X-API-Key = APP_API_KEY (moves to api/security.py in T005)."""
    key = journal.app_api_key
    if key in ("", EXAMPLE_KEY):
        raise ApiError(503, "WRITES_DISABLED", "Configura APP_API_KEY en .env para escribir datos")
    if x_api_key is None or not secrets.compare_digest(x_api_key, key):
        raise ApiError(401, "UNAUTHORIZED", "Header X-API-Key inválido o ausente")
