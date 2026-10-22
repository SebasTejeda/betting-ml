"""Spec 003, T005: every route declares exactly one access policy, built from app.routes so a
new unclassified route fails here, and every write route rejects missing or wrong keys."""

from __future__ import annotations

import re
from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.routing import RouteContext
from fastapi.testclient import TestClient

from betting_ml.api.main import create_app
from betting_ml.api.security import Access, api_routes, route_access

KEY = "route-access-test-key-0123456789abcdef"
WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
PUBLIC = {("GET", "/health"), ("POST", "/api/v1/auth/login")}
# POST that computes without changing state: authenticated like a read, no CSRF.
READ_ONLY_POSTS = {("POST", "/api/v1/predictions")}


def _app(key: str = KEY) -> Any:
    services = SimpleNamespace(predictor=SimpleNamespace(state=lambda: None), app_api_key=key)
    services.journal = None
    services.auth = None
    services.secure_cookies = False
    return create_app(services)  # type: ignore[arg-type]


def _routes() -> list[tuple[str, str, RouteContext]]:
    return [
        (method, route.path, route)
        for route in api_routes(_app())
        for method in sorted(route.methods or ())
    ]


def _url(path: str) -> str:
    return re.sub(r"\{(\w+)\}", lambda m: "1" if m.group(1).endswith("id") else "E0", path)


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(_app()) as test_client:
        yield test_client


def test_every_route_declares_exactly_one_policy() -> None:
    routes = _routes()
    assert len(routes) >= 24
    for method, path, route in routes:
        assert len(route_access(route)) == 1, f"{method} {path}: {route_access(route)}"


def test_only_health_and_login_are_public() -> None:
    public = {(m, p) for m, p, r in _routes() if route_access(r) == [Access.PUBLIC]}
    assert public == PUBLIC


def test_state_changing_methods_are_writes() -> None:
    for method, path, route in _routes():
        access = route_access(route)[0]
        if method in WRITE_METHODS and (method, path) not in READ_ONLY_POSTS | PUBLIC:
            assert access is Access.WRITE, f"{method} {path} must be a write"
        if method == "GET":
            assert access is not Access.WRITE, f"{method} {path} must not be a write"


def _writes() -> list[tuple[str, str]]:
    return [(m, p) for m, p, r in _routes() if route_access(r) == [Access.WRITE]]


@pytest.mark.parametrize("headers", [{}, {"X-API-Key": "wrong"}, {"X-API-Key": ""}])
def test_every_write_rejects_missing_or_wrong_key(
    client: TestClient, headers: dict[str, str]
) -> None:
    writes = _writes()
    assert len(writes) >= 8
    for method, path in writes:
        response = client.request(method, _url(path), headers=headers)
        assert response.status_code == 401, f"{method} {path}: {response.status_code}"
        assert response.json()["error"]["code"] == "UNAUTHORIZED"


def test_every_write_is_disabled_with_the_example_key() -> None:
    with TestClient(_app("cambia-esto")) as client:
        for method, path in _writes():
            response = client.request(method, _url(path), headers={"X-API-Key": "cambia-esto"})
            assert response.status_code == 503, f"{method} {path}"
            assert response.json()["error"]["code"] == "WRITES_DISABLED"
