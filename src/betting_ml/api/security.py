"""The single authentication/authorization gate of the API (spec 003, US8).

Every router declares one access policy for all its routes with
``APIRouter(dependencies=[Depends(<policy>)])``: ``public``, ``require_read`` or
``require_write``. tests/integration/test_route_access.py fails on any unclassified route.

Credentials: ``X-API-Key`` (machine clients) or the owner session cookie. Writes made with
the session cookie also need ``X-CSRF-Token``; the machine key does not (browsers never send
it on their own).
"""

from __future__ import annotations

import secrets
from collections.abc import Callable
from enum import StrEnum
from typing import Any

from fastapi import Depends, FastAPI, Header, Request
from fastapi.routing import APIRoute, RouteContext, iter_route_contexts

from betting_ml.api.dependencies import ServicesApi, get_services
from betting_ml.api.errors import ApiError
from betting_ml.config import EXAMPLE_KEY
from betting_ml.domain.security import Principal, PrincipalKind

SESSION_COOKIE = "bml_session"


class Access(StrEnum):
    PUBLIC = "public"
    READ = "read"
    WRITE = "write"


def _same(given: str, expected: str) -> bool:
    """Constant-time comparison on bytes (a non-ASCII header must not raise)."""
    return secrets.compare_digest(given.encode(), expected.encode())


def _unauthorized() -> ApiError:
    return ApiError(401, "UNAUTHORIZED", "Credenciales inválidas o ausentes")


def current_principal(
    request: Request,
    x_api_key: str | None = Header(None),
    services: ServicesApi = Depends(get_services),
) -> Principal | None:
    """Principal of the request, or None without credentials. A wrong key is a 401 even if
    a valid session cookie comes with it."""
    if x_api_key is not None:
        key = services.app_api_key
        if key in ("", EXAMPLE_KEY):
            raise ApiError(
                503, "WRITES_DISABLED", "Configura APP_API_KEY en .env para escribir datos"
            )
        if not x_api_key or not _same(x_api_key, key):
            raise _unauthorized()
        return Principal(PrincipalKind.API_KEY)
    token = request.cookies.get(SESSION_COOKIE)
    if not token or services.auth is None:
        return None
    session = services.auth.validate(token)
    return None if session is None else Principal(PrincipalKind.SESSION, session)


def public() -> None:
    """Explicitly public route (health, login)."""


def require_read() -> Principal | None:
    """Reads stay open until the frontend logs in (T007 requires a principal here)."""
    return None


def require_write(
    principal: Principal | None = Depends(current_principal),
    x_csrf_token: str | None = Header(None),
) -> Principal:
    """State-changing routes: machine key, or owner session + matching X-CSRF-Token."""
    if principal is None:
        raise _unauthorized()
    if principal.session is not None and not (
        x_csrf_token and _same(x_csrf_token, principal.session.csrf_token)
    ):
        raise ApiError(403, "CSRF_FAILED", "Falta el token CSRF o no corresponde a la sesión")
    return principal


POLICIES: dict[Callable[..., Any], Access] = {
    public: Access.PUBLIC,
    require_read: Access.READ,
    require_write: Access.WRITE,
}


def api_routes(app: FastAPI) -> list[RouteContext]:
    """Effective API routes of the app (included routers resolved, prefixes applied)."""
    return [c for c in iter_route_contexts(app.routes) if isinstance(c.original_route, APIRoute)]


def route_access(route: RouteContext) -> list[Access]:
    """Access policies declared on a route (router-level dependencies included)."""
    return [
        POLICIES[dependency.call]
        for dependency in route.dependant.dependencies
        if dependency.call in POLICIES
    ]
