"""Uniform error format: {"error": {"code", "message", "details"}} (contracts/api.md)."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from betting_ml.application.predict_matches import (
    InvalidMatchError,
    ModelNotAvailableError,
    UnknownLeagueError,
    UnknownTeamError,
)


class ApiError(Exception):
    def __init__(
        self, status: int, code: str, message: str, details: dict[str, Any] | None = None
    ) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.details = details or {}


def error_response(
    status: int, code: str, message: str, details: dict[str, Any] | None = None
) -> JSONResponse:
    body = {"error": {"code": code, "message": message, "details": jsonable_encoder(details or {})}}
    return JSONResponse(status_code=status, content=body)


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(_: Request, exc: ApiError) -> JSONResponse:
        return error_response(exc.status, exc.code, exc.message, exc.details)

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

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        return error_response(
            422, "VALIDATION_ERROR", "Parámetros de entrada inválidos", {"errors": exc.errors()}
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = {404: "NOT_FOUND", 405: "METHOD_NOT_ALLOWED"}.get(exc.status_code, "HTTP_ERROR")
        return error_response(exc.status_code, code, str(exc.detail))
