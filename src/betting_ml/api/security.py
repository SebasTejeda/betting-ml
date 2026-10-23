"""The single authentication/authorization gate of the API (spec 003, US8).

Every router declares one access policy for all its routes with
``APIRouter(dependencies=[Depends(<policy>)])``: ``public``, ``require_read`` or
``require_write``. tests/integration/test_route_access.py fails on any unclassified route.

Credentials: ``X-API-Key`` (machine clients) or the owner session cookie. Writes made with
the session cookie also need ``X-CSRF-Token``; the machine key does not (browsers never send
it on their own).
"""

from __future__ import annotations

import ipaddress
import secrets
from collections.abc import Callable, Mapping
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


def client_ip(scope: Mapping[str, Any]) -> str:
    """Rate-limit identity of the connection's client. An IPv6 client is its /64 (one host
    usually owns the whole prefix) and an IPv4-mapped address is its IPv4. Behind a proxy,
    the deployment sets the real address (uvicorn --proxy-headers, T020)."""
    client = scope.get("client")
    host = str(client[0]) if client else "unknown"
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return host
    if isinstance(address, ipaddress.IPv6Address):
        if address.ipv4_mapped is not None:
            return str(address.ipv4_mapped)
        return str(ipaddress.IPv6Network(f"{address}/64", strict=False))
    return str(address)


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
                503, "WRITES_DISABLED", "Configura APP_API_KEY en .env para usar X-API-Key"
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


def require_read(principal: Principal | None = Depends(current_principal)) -> Principal:
    """Every private route, reads included (spec 003, T007): machine key or owner session."""
    if principal is None:
        raise _unauthorized()
    return principal


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
    """Distinct access policies declared on a route (router-level dependencies included); a
    handler may repeat its router's policy to receive the principal."""
    found = [
        POLICIES[dependency.call]
        for dependency in route.dependant.dependencies
        if dependency.call in POLICIES
    ]
    return list(dict.fromkeys(found))
