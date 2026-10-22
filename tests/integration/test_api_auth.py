"""Spec 003, T006: /auth/login, /auth/me, /auth/logout, session cookie and CSRF on writes."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient

from betting_ml.adapters.argon2_hasher import Argon2Hasher
from betting_ml.adapters.memory_rate_limiter import MemoryRateLimiter
from betting_ml.adapters.sql.db import prepare, session_factory
from betting_ml.adapters.sql.repositories import SqlSessionStore
from betting_ml.api.main import create_app
from betting_ml.application.authenticate import Authenticate
from betting_ml.application.throttle import LoginThrottle

PASSWORD = "owner-password-for-tests"
KEY = "machine-key-for-auth-tests-0123456789"
HASHER = Argon2Hasher(time_cost=1, memory_cost=1024, parallelism=1)
HASH = HASHER.hash(PASSWORD)


def _services(password_hash: str = HASH, secure_cookies: bool = False) -> Any:
    auth = Authenticate(
        sessions=SqlSessionStore(session_factory(prepare("sqlite:///:memory:"))),
        hasher=HASHER,
        password_hash=password_hash,
        secret=b"api-auth-tests-secret-0123456789abcdef",
        idle=timedelta(minutes=30),
        max_age=timedelta(hours=12),
        throttle=LoginThrottle(MemoryRateLimiter(), max_attempts=1000),
    )
    return SimpleNamespace(
        predictor=SimpleNamespace(state=lambda: None),
        app_api_key=KEY,
        journal=None,
        auth=auth,
        secure_cookies=secure_cookies,
    )


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(create_app(_services())) as test_client:
        yield test_client


def _login(client: TestClient) -> dict[str, Any]:
    response = client.post("/api/v1/auth/login", json={"password": PASSWORD})
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def _error(response: Any, status: int, code: str) -> None:
    assert response.status_code == status, response.text
    assert response.json()["error"]["code"] == code


def test_login_sets_a_hardened_cookie_and_never_returns_the_token(client: TestClient) -> None:
    response = client.post("/api/v1/auth/login", json={"password": PASSWORD})
    assert response.status_code == 200
    cookie = response.headers["set-cookie"]
    token = client.cookies.get("bml_session")
    assert token and len(token) >= 43
    for attribute in ("HttpOnly", "SameSite=strict", "Path=/", "Max-Age=43200"):
        assert attribute.lower() in cookie.lower()
    assert "secure" not in cookie.lower()  # dev
    body = response.json()
    assert set(body) == {"csrf_token", "expires_at", "idle_minutes"}
    assert token not in response.text
    assert body["idle_minutes"] == 30


def test_cookie_is_secure_in_prod() -> None:
    with TestClient(create_app(_services(secure_cookies=True))) as client:
        response = client.post("/api/v1/auth/login", json={"password": PASSWORD})
        assert "secure" in response.headers["set-cookie"].lower()


@pytest.mark.parametrize("password", ["wrong", PASSWORD + "x", " " + PASSWORD])
def test_wrong_password_gives_a_generic_401_without_cookie(
    client: TestClient, password: str
) -> None:
    response = client.post("/api/v1/auth/login", json={"password": password})
    _error(response, 401, "INVALID_CREDENTIALS")
    assert "set-cookie" not in response.headers
    assert "contraseña" not in response.json()["error"]["message"].lower()


@pytest.mark.parametrize(
    "body", [{}, {"password": ""}, {"password": "x" * 1025}, {"password": PASSWORD, "extra": 1}]
)
def test_login_body_is_validated(client: TestClient, body: dict[str, Any]) -> None:
    _error(client.post("/api/v1/auth/login", json=body), 422, "VALIDATION_ERROR")


def test_login_disabled_without_password_hash() -> None:
    with TestClient(create_app(_services(password_hash=""))) as client:
        _error(
            client.post("/api/v1/auth/login", json={"password": PASSWORD}), 503, "LOGIN_DISABLED"
        )


def test_me_with_session_with_key_and_without_credentials(client: TestClient) -> None:
    _error(client.get("/api/v1/auth/me"), 401, "UNAUTHORIZED")
    login = _login(client)
    me = client.get("/api/v1/auth/me").json()
    assert me["authenticated"] is True and me["kind"] == "session"
    assert me["csrf_token"] == login["csrf_token"]
    client.cookies.clear()
    machine = client.get("/api/v1/auth/me", headers={"X-API-Key": KEY}).json()
    assert machine == {
        "authenticated": True,
        "kind": "api_key",
        "csrf_token": None,
        "expires_at": None,
    }
    _error(client.get("/api/v1/auth/me", headers={"X-API-Key": "wrong"}), 401, "UNAUTHORIZED")


def test_tampered_cookie_is_rejected(client: TestClient) -> None:
    _login(client)
    token = client.cookies.get("bml_session") or ""
    client.cookies.set("bml_session", token[:-2] + "xx")
    _error(client.get("/api/v1/auth/me"), 401, "UNAUTHORIZED")


def test_session_writes_need_the_csrf_token(client: TestClient) -> None:
    login = _login(client)
    _error(client.post("/api/v1/auth/logout"), 403, "CSRF_FAILED")
    _error(
        client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": "forged"}), 403, "CSRF_FAILED"
    )
    response = client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": login["csrf_token"]})
    assert response.status_code == 204
    assert (
        'bml_session=""' in response.headers["set-cookie"]
        or "Max-Age=0" in response.headers["set-cookie"]
    )
    _error(client.get("/api/v1/auth/me"), 401, "UNAUTHORIZED")


def test_csrf_token_of_another_session_is_rejected() -> None:
    services = _services()
    with TestClient(create_app(services)) as alice, TestClient(create_app(services)) as mallory:
        _login(alice)
        foreign = _login(mallory)["csrf_token"]
        _error(
            alice.post("/api/v1/auth/logout", headers={"X-CSRF-Token": foreign}),
            403,
            "CSRF_FAILED",
        )


def test_logout_session_cannot_be_reused(client: TestClient) -> None:
    login = _login(client)
    token = client.cookies.get("bml_session") or ""
    client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": login["csrf_token"]})
    client.cookies.set("bml_session", token)  # replay the old cookie
    _error(client.get("/api/v1/auth/me"), 401, "UNAUTHORIZED")


def test_login_rotates_the_session(client: TestClient) -> None:
    _login(client)
    first = client.cookies.get("bml_session")
    _login(client)
    second = client.cookies.get("bml_session")
    assert first != second
    client.cookies.set("bml_session", first or "")
    _error(client.get("/api/v1/auth/me"), 401, "UNAUTHORIZED")


def test_machine_key_writes_do_not_need_csrf(client: TestClient) -> None:
    response = client.post("/api/v1/auth/logout", headers={"X-API-Key": KEY})
    assert response.status_code == 204


def test_wrong_key_is_rejected_even_with_a_valid_session(client: TestClient) -> None:
    login = _login(client)
    response = client.post(
        "/api/v1/auth/logout", headers={"X-API-Key": "wrong", "X-CSRF-Token": login["csrf_token"]}
    )
    _error(response, 401, "UNAUTHORIZED")
