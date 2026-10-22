"""The single authentication/authorization gate of the API (spec 003, US8).

Every router declares one access policy for all its routes with
``APIRouter(dependencies=[Depends(<policy>)])``: ``public``, ``require_read`` or
``require_write``. tests/integration/test_route_access.py fails on any unclassified route.
"""

from __future__ import annotations

import secrets
from collections.abc import Callable
from enum import StrEnum
from typing import Any

from fastapi import Depends, FastAPI, Header
from fastapi.routing import APIRoute, RouteContext, iter_route_contexts

from betting_ml.api.dependencies import ServicesApi, get_services
from betting_ml.api.errors import ApiError
from betting_ml.config import EXAMPLE_KEY
from betting_ml.domain.security import Principal, PrincipalKind


class Access(StrEnum):
    PUBLIC = "public"
    READ = "read"
    WRITE = "write"


def public() -> None:
    """Explicitly public route (health, login)."""


def require_read() -> Principal | None:
    """Reads stay open until owner login exists; T007 requires a principal here."""
    return None


def require_write(
    x_api_key: str | None = Header(None), services: ServicesApi = Depends(get_services)
) -> Principal:
    """State-changing routes: X-API-Key must equal APP_API_KEY (constant-time comparison)."""
    key = services.app_api_key
    if key in ("", EXAMPLE_KEY):
        raise ApiError(503, "WRITES_DISABLED", "Configura APP_API_KEY en .env para escribir datos")
    if not x_api_key or not secrets.compare_digest(x_api_key.encode(), key.encode()):
        raise ApiError(401, "UNAUTHORIZED", "Header X-API-Key inválido o ausente")
    return Principal(PrincipalKind.API_KEY)


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
