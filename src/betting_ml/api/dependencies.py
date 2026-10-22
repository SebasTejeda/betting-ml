"""Dependency injection: the composition root (Container) lives in app.state. Routers see it
only through these protocols, built from application types (never adapters)."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Protocol

from fastapi import Depends, Request
from starlette.types import Scope

from betting_ml.api.errors import ApiError
from betting_ml.application.authenticate import Authenticate
from betting_ml.application.compare_matches import CompareMatches, EvaluateManualOdds
from betting_ml.application.manage_bets import ManageBets
from betting_ml.application.predict_matches import PredictMatches
from betting_ml.application.read_backtest import ReadBacktestReport
from betting_ml.application.refresh_odds import RefreshOdds
from betting_ml.application.settle_bets import SettleBets
from betting_ml.application.throttle import RateLimits
from betting_ml.application.track_predictions import TrackPredictions
from betting_ml.config import BookmakersFile, LeaguesFile

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
    def app_api_key(self) -> str:
        """The single machine key (APP_API_KEY); see api/security.py."""

    @property
    def refresher(self) -> Refresher: ...

    @property
    def journal(self) -> JournalApi | None: ...

    @property
    def auth(self) -> Authenticate | None:
        """Owner login (spec 003); None disables session logins."""

    @property
    def rate_limits(self) -> RateLimits | None:
        """Request limits (spec 003, US2); None disables them (functional tests)."""

    @property
    def max_body_bytes(self) -> int: ...

    @property
    def allowed_hosts(self) -> list[str] | None:
        """ALLOWED_HOSTS (spec 003, US4); None disables the Host check."""

    @property
    def secure_cookies(self) -> bool:
        """Secure attribute on the session cookie (APP_ENV=prod)."""


def scope_services(scope: Scope) -> ServicesApi | None:
    """The services seen by a raw ASGI middleware; None only before the app is wired.

    Typed on purpose: a renamed field must fail mypy or raise, never switch a control off.
    """
    services: ServicesApi | None = scope["app"].state.container
    return services


def get_services(request: Request) -> ServicesApi:
    services: ServicesApi = request.app.state.container
    return services


def get_journal(services: ServicesApi = Depends(get_services)) -> JournalApi:
    if services.journal is None:
        raise ApiError(503, "SERVICE_NOT_AVAILABLE", "Servicios de la spec 002 no configurados")
    return services.journal
