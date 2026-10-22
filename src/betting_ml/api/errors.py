"""Uniform error format: {"error": {"code", "message", "details"}} (contracts/api.md)."""

from __future__ import annotations

import math
from typing import Any

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from betting_ml.adapters.the_odds_api import OddsApiError
from betting_ml.application.authenticate import InvalidCredentialsError, LoginDisabledError
from betting_ml.application.compare_matches import (
    BookmakerNotFoundError,
    MatchNotFoundError,
    NoReferenceError,
    NotManualBookmakerError,
)
from betting_ml.application.manage_bets import (
    BetNotFoundError,
    BetNotPendingError,
    LimitWarningError,
    MonthlyLimitReachedError,
)
from betting_ml.application.predict_matches import (
    InvalidMatchError,
    ModelNotAvailableError,
    UnknownLeagueError,
    UnknownTeamError,
)
from betting_ml.application.read_backtest import BacktestReportNotFoundError
from betting_ml.application.refresh_odds import OddsBudgetLowError
from betting_ml.application.throttle import TooManyAttemptsError


class ApiError(Exception):
    def __init__(
        self,
        status: int,
        code: str,
        message: str,
        details: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.details = details or {}
        self.headers = headers


def error_response(
    status: int,
    code: str,
    message: str,
    details: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    body = {"error": {"code": code, "message": message, "details": jsonable_encoder(details or {})}}
    return JSONResponse(status_code=status, content=body, headers=headers)


def retry_after(seconds: float) -> dict[str, str]:
    """``Retry-After`` header in whole seconds (at least 1)."""
    return {"Retry-After": str(max(1, math.ceil(seconds)))}


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(_: Request, exc: ApiError) -> JSONResponse:
        return error_response(exc.status, exc.code, exc.message, exc.details, exc.headers)

    @app.exception_handler(UnknownLeagueError)
    async def _league(_: Request, exc: UnknownLeagueError) -> JSONResponse:
        return error_response(404, "LEAGUE_NOT_FOUND", str(exc), {"league": exc.league})

    @app.exception_handler(UnknownTeamError)
    async def _team(_: Request, exc: UnknownTeamError) -> JSONResponse:
        return error_response(
            404, "TEAM_NOT_FOUND", str(exc), {"team": exc.team, "league": exc.league}
        )

    @app.exception_handler(InvalidMatchError)
    async def _invalid(_: Request, exc: InvalidMatchError) -> JSONResponse:
        return error_response(422, "VALIDATION_ERROR", str(exc))

    @app.exception_handler(ModelNotAvailableError)
    async def _model(_: Request, exc: ModelNotAvailableError) -> JSONResponse:
        return error_response(503, "MODEL_NOT_AVAILABLE", str(exc))

    @app.exception_handler(OddsBudgetLowError)
    async def _budget(_: Request, exc: OddsBudgetLowError) -> JSONResponse:
        details = {"credits_remaining": exc.remaining, "min_reserve": exc.reserve}
        return error_response(429, "ODDS_BUDGET_LOW", str(exc), details)

    @app.exception_handler(OddsApiError)
    async def _odds_api(_: Request, exc: OddsApiError) -> JSONResponse:
        return error_response(502, "ODDS_API_ERROR", str(exc), {"status": exc.status})

    @app.exception_handler(MonthlyLimitReachedError)
    async def _monthly(_: Request, exc: MonthlyLimitReachedError) -> JSONResponse:
        code = exc.check.code.value if exc.check.code else "MONTHLY_LIMIT_REACHED"
        return error_response(
            403, code, " ".join(exc.check.messages), {"messages": list(exc.check.messages)}
        )

    @app.exception_handler(LimitWarningError)
    async def _warning(_: Request, exc: LimitWarningError) -> JSONResponse:
        code = exc.check.code.value if exc.check.code else "LIMIT_WARNING"
        details = {
            "messages": list(exc.check.messages),
            "hint": "Repite la petición con confirm: true",
        }
        return error_response(409, code, " ".join(exc.check.messages), details)

    @app.exception_handler(BetNotFoundError)
    async def _bet_missing(_: Request, exc: BetNotFoundError) -> JSONResponse:
        return error_response(404, "BET_NOT_FOUND", str(exc), {"id": exc.bet_id})

    @app.exception_handler(BetNotPendingError)
    async def _bet_not_pending(_: Request, exc: BetNotPendingError) -> JSONResponse:
        return error_response(409, exc.code, str(exc))

    @app.exception_handler(NotManualBookmakerError)
    async def _not_manual(_: Request, exc: NotManualBookmakerError) -> JSONResponse:
        return error_response(422, "BOOKMAKER_NOT_MANUAL", str(exc), {"bookmaker": exc.key})

    @app.exception_handler(MatchNotFoundError)
    async def _match_missing(_: Request, exc: MatchNotFoundError) -> JSONResponse:
        return error_response(404, "MATCH_NOT_FOUND", str(exc), {"match_id": exc.match_id})

    @app.exception_handler(BookmakerNotFoundError)
    async def _book_missing(_: Request, exc: BookmakerNotFoundError) -> JSONResponse:
        return error_response(404, "BOOKMAKER_NOT_FOUND", str(exc), {"bookmaker": exc.key})

    @app.exception_handler(NoReferenceError)
    async def _no_reference(_: Request, exc: NoReferenceError) -> JSONResponse:
        return error_response(422, "NO_REFERENCE", str(exc), {"match_id": exc.match_id})

    @app.exception_handler(InvalidCredentialsError)
    async def _credentials(_: Request, exc: InvalidCredentialsError) -> JSONResponse:
        return error_response(401, "INVALID_CREDENTIALS", str(exc))

    @app.exception_handler(TooManyAttemptsError)
    async def _too_many(_: Request, exc: TooManyAttemptsError) -> JSONResponse:
        return error_response(
            429,
            "TOO_MANY_ATTEMPTS",
            str(exc),
            {"retry_after": exc.retry_after},
            retry_after(exc.retry_after),
        )

    @app.exception_handler(LoginDisabledError)
    async def _login_disabled(_: Request, exc: LoginDisabledError) -> JSONResponse:
        return error_response(503, "LOGIN_DISABLED", str(exc))

    @app.exception_handler(BacktestReportNotFoundError)
    async def _backtest_missing(_: Request, exc: BacktestReportNotFoundError) -> JSONResponse:
        return error_response(404, "BACKTEST_NOT_FOUND", str(exc))

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        return error_response(
            422, "VALIDATION_ERROR", "Parámetros de entrada inválidos", {"errors": exc.errors()}
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = {404: "NOT_FOUND", 405: "METHOD_NOT_ALLOWED", 413: "PAYLOAD_TOO_LARGE"}.get(
            exc.status_code, "HTTP_ERROR"
        )
        return error_response(exc.status_code, code, str(exc.detail))
