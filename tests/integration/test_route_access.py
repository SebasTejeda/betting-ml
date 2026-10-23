"""Spec 003, T005/T007/T010: every route declares exactly one access policy, built from
app.routes so a new unclassified route fails here; every private route (reads included) rejects
missing or wrong credentials, and every write made with the session needs its CSRF token."""

from __future__ import annotations

import re
from collections.abc import Iterator
from datetime import timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.routing import RouteContext
from fastapi.testclient import TestClient

from betting_ml.adapters.argon2_hasher import Argon2Hasher
from betting_ml.adapters.memory_rate_limiter import MemoryRateLimiter
from betting_ml.adapters.sql.db import prepare, session_factory
from betting_ml.adapters.sql.repositories import SqlSessionStore
from betting_ml.api.main import create_app
from betting_ml.api.security import Access, api_routes, client_ip, route_access
from betting_ml.application.authenticate import Authenticate
from betting_ml.application.throttle import LoginThrottle
from betting_ml.config import DEFAULT_MAX_BODY_BYTES

KEY = "route-access-test-key-0123456789abcdef"
WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
PUBLIC = {("GET", "/health"), ("POST", "/api/v1/auth/login")}
# POST that computes without changing state: authenticated like a read, no CSRF.
READ_ONLY_POSTS = {("POST", "/api/v1/predictions")}
PASSWORD = "route-access-owner-password"
HASHER = Argon2Hasher(time_cost=1, memory_cost=1024, parallelism=1)
HASH = HASHER.hash(PASSWORD)


def _app(key: str = KEY) -> Any:
    """Stub use cases, but the real session login: a forged cookie goes through validation."""
    auth = Authenticate(
        sessions=SqlSessionStore(session_factory(prepare("sqlite:///:memory:"))),
        hasher=HASHER,
        password_hash=HASH,
        secret=b"route-access-secret-0123456789abcdef",
        idle=timedelta(minutes=30),
        max_age=timedelta(hours=12),
        throttle=LoginThrottle(MemoryRateLimiter(), max_attempts=1000),
    )
    services = SimpleNamespace(predictor=SimpleNamespace(state=lambda: None), app_api_key=key)
    services.journal = None
    services.auth = auth
    services.secure_cookies = False
    services.rate_limits = services.allowed_hosts = None  # controls off on purpose (T021)
    services.max_body_bytes = DEFAULT_MAX_BODY_BYTES
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


def _private(access: Access | None = None) -> list[tuple[str, str]]:
    return [
        (m, p)
        for m, p, r in _routes()
        if route_access(r) != [Access.PUBLIC] and (access is None or route_access(r) == [access])
    ]


def test_reads_and_writes_are_both_covered() -> None:
    assert len(_private(Access.READ)) >= 14
    assert len(_private(Access.WRITE)) >= 8


@pytest.mark.parametrize(
    "headers",
    [{}, {"X-API-Key": "wrong"}, {"X-API-Key": ""}, {"X-API-Key": KEY + "x"}],
    ids=["none", "wrong", "empty", "suffix"],
)
def test_every_private_route_rejects_missing_or_wrong_key(
    client: TestClient, headers: dict[str, str]
) -> None:
    for method, path in _private():
        response = client.request(method, _url(path), headers=headers)
        assert response.status_code == 401, f"{method} {path}: {response.status_code}"
        assert response.json()["error"]["code"] == "UNAUTHORIZED"


def test_forged_session_cookie_is_not_a_credential(client: TestClient) -> None:
    client.cookies.set("bml_session", "forged-session-token")
    for method, path in _private():
        response = client.request(method, _url(path))
        assert response.status_code == 401, f"{method} {path}: {response.status_code}"


def test_valid_key_passes_the_gate_on_every_read() -> None:
    # The stub services lack the use cases, so a route may fail after the gate (500/503/422):
    # only the gate's own answers matter here.
    with TestClient(_app(), raise_server_exceptions=False) as client:
        for method, path in _private(Access.READ):
            response = client.request(method, _url(path), headers={"X-API-Key": KEY})
            assert response.status_code not in (401, 403), f"{method} {path}"


def test_every_private_route_is_disabled_with_the_example_key() -> None:
    with TestClient(_app("cambia-esto")) as client:
        for method, path in _private():
            response = client.request(method, _url(path), headers={"X-API-Key": "cambia-esto"})
            assert response.status_code == 503, f"{method} {path}"
            assert response.json()["error"]["code"] == "WRITES_DISABLED"


def test_every_session_write_needs_the_csrf_token() -> None:
    """With a valid session cookie, each write answers 403 without the token, 403 with another
    one, and passes the gate with its own (the stub use cases may fail afterwards)."""
    with TestClient(_app(), raise_server_exceptions=False) as client:
        login = client.post("/api/v1/auth/login", json={"password": PASSWORD})
        assert login.status_code == 200
        csrf = login.json()["csrf_token"]
        writes = [w for w in _private(Access.WRITE) if w != ("POST", "/api/v1/auth/logout")]
        assert len(writes) >= 8
        for method, path in writes:
            for headers in ({}, {"X-CSRF-Token": "forged"}, {"X-CSRF-Token": csrf + "x"}):
                response = client.request(method, _url(path), headers=headers)
                assert response.status_code == 403, f"{method} {path} {headers}"
                assert response.json()["error"]["code"] == "CSRF_FAILED"
            response = client.request(method, _url(path), headers={"X-CSRF-Token": csrf})
            assert response.status_code not in (401, 403), f"{method} {path}"


@pytest.mark.parametrize(
    ("host", "identity"),
    [
        ("203.0.113.7", "203.0.113.7"),
        ("::ffff:203.0.113.7", "203.0.113.7"),
        ("2001:db8:1:2:aaaa::1", "2001:db8:1:2::/64"),
        ("2001:db8:1:2:ffff:ffff:ffff:ffff", "2001:db8:1:2::/64"),
        ("testclient", "testclient"),
    ],
)
def test_client_identity_groups_an_ipv6_prefix(host: str, identity: str) -> None:
    """One host usually owns a whole IPv6 /64: each address must not get its own quota."""
    assert client_ip({"client": (host, 1)}) == identity


def test_client_identity_without_a_connection_address() -> None:
    assert client_ip({"client": None}) == "unknown"


def test_match_analysis_routes_are_behind_the_same_gate() -> None:
    """Spec 004 (I03): the routes from the Sebastian branch are private; the refresh spends
    credits, so it is a write (session + CSRF, or X-API-Key)."""
    reads = {
        ("GET", "/api/v1/teams/search"),
        ("GET", "/api/v1/analysis/fixture"),
        ("GET", "/api/v1/analysis"),
        ("GET", "/api/v1/analysis/{match_id}/odds/estimate"),
        ("GET", "/api/v1/markets/calibration"),
    }
    assert reads <= set(_private(Access.READ))
    assert ("POST", "/api/v1/analysis/{match_id}/odds/refresh") in _private(Access.WRITE)
