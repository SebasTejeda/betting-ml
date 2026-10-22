"""Spec 003, T008: login lockout, global rate limit, odds refresh quota and body size limit."""

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
from betting_ml.application.throttle import LoginThrottle, RateLimits

PASSWORD = "owner-password-for-limit-tests"
KEY = "machine-key-for-limit-tests-0123456789"
LOGIN = "/api/v1/auth/login"
ME = "/api/v1/auth/me"


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


class SpyHasher(Argon2Hasher):
    def __init__(self) -> None:
        super().__init__(time_cost=1, memory_cost=1024, parallelism=1)
        self.verified = 0

    def verify(self, password_hash: str, password: str) -> bool:
        self.verified += 1
        return super().verify(password_hash, password)


def _services(
    clock: Clock, per_minute: int = 1000, refresh_per_hour: int = 6, max_body: int = 65_536
) -> Any:
    limiter = MemoryRateLimiter(clock=clock)
    hasher = SpyHasher()
    refreshed: list[Any] = []
    refresh_odds = SimpleNamespace(
        refresh=lambda leagues: (
            refreshed.append(leagues)
            or SimpleNamespace(
                snapshot_id=1,
                leagues=["E0"],
                events=0,
                credits_used=1,
                credits_remaining=400,
                unmapped_teams=[],
                stopped_by_budget=False,
            )
        )
    )
    return SimpleNamespace(
        predictor=SimpleNamespace(state=lambda: None),
        app_api_key=KEY,
        journal=SimpleNamespace(refresh_odds=refresh_odds),
        auth=Authenticate(
            sessions=SqlSessionStore(session_factory(prepare("sqlite:///:memory:"))),
            hasher=hasher,
            password_hash=hasher.hash(PASSWORD),
            secret=b"limit-tests-secret-0123456789abcdef",
            idle=timedelta(minutes=30),
            max_age=timedelta(hours=12),
            throttle=LoginThrottle(limiter, max_attempts=5),
        ),
        secure_cookies=False,
        rate_limits=RateLimits(limiter, per_minute, refresh_per_hour),
        max_body_bytes=max_body,
        hasher=hasher,
        refreshed=refreshed,
    )


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def services(clock: Clock) -> Any:
    return _services(clock)


@pytest.fixture
def client(services: Any) -> Iterator[TestClient]:
    with TestClient(create_app(services)) as test_client:
        yield test_client


def _code(response: Any) -> str:
    return str(response.json()["error"]["code"])


def test_sixth_login_attempt_is_429_with_retry_after_and_skips_argon2(
    client: TestClient, services: Any
) -> None:
    for _ in range(5):
        assert client.post(LOGIN, json={"password": "guess"}).status_code == 401
    assert services.hasher.verified == 5
    response = client.post(LOGIN, json={"password": "guess"})
    assert response.status_code == 429
    assert _code(response) == "TOO_MANY_ATTEMPTS"
    assert response.headers["Retry-After"] == "60"
    assert response.json()["error"]["details"] == {"retry_after": 60}
    assert services.hasher.verified == 5  # a locked client costs no Argon2 work


def test_the_right_password_does_not_open_a_locked_client(client: TestClient, clock: Clock) -> None:
    for _ in range(6):
        client.post(LOGIN, json={"password": "guess"})
    locked = client.post(LOGIN, json={"password": PASSWORD})
    assert locked.status_code == 429
    assert "set-cookie" not in locked.headers
    clock.now += 61
    assert client.post(LOGIN, json={"password": PASSWORD}).status_code == 200


def test_lockout_grows_and_is_per_ip(services: Any, clock: Clock) -> None:
    app = create_app(services)
    with (
        TestClient(app, client=("203.0.113.9", 1)) as attacker,
        TestClient(app, client=("192.168.1.10", 1)) as owner,
    ):
        for expected in ("60", "300"):
            for _ in range(5):
                attacker.post(LOGIN, json={"password": "guess"})
            response = attacker.post(LOGIN, json={"password": "guess"})
            assert response.headers["Retry-After"] == expected
            clock.now += int(expected) + 1
        assert owner.post(LOGIN, json={"password": PASSWORD}).status_code == 200


def test_global_limit_per_ip_is_429_rate_limited(clock: Clock) -> None:
    app = create_app(_services(clock, per_minute=3))
    with (
        TestClient(app, client=("198.51.100.1", 1)) as first,
        TestClient(app, client=("198.51.100.2", 1)) as second,
    ):
        for _ in range(3):
            assert first.get(ME).status_code == 401  # counted even without credentials
        limited = first.get("/api/v1/bets", headers={"X-API-Key": KEY})
        assert limited.status_code == 429
        assert _code(limited) == "RATE_LIMITED"
        assert limited.headers["Retry-After"] == "60"
        assert second.get(ME).status_code == 401  # another client keeps its quota
        clock.now += 60
        assert first.get(ME).status_code == 401


def test_forged_session_cookies_do_not_buy_extra_quota(clock: Clock) -> None:
    with TestClient(create_app(_services(clock, per_minute=2))) as client:
        statuses = []
        for i in range(4):
            client.cookies.set("bml_session", f"forged-{i}")
            statuses.append(client.get(ME).status_code)
        assert statuses == [401, 401, 429, 429]


def test_odds_refresh_quota_per_hour(clock: Clock) -> None:
    services = _services(clock, refresh_per_hour=2)
    with TestClient(create_app(services)) as client:
        # anonymous calls are rejected before they can spend the owner's quota
        for _ in range(3):
            assert client.post("/api/v1/odds/refresh").status_code == 401
        headers = {"X-API-Key": KEY}
        assert client.post("/api/v1/odds/refresh", headers=headers).status_code == 202
        clock.now += 1200
        assert client.post("/api/v1/odds/refresh", headers=headers).status_code == 202
        clock.now += 600
        limited = client.post("/api/v1/odds/refresh", headers=headers)
        assert limited.status_code == 429
        assert _code(limited) == "RATE_LIMITED"
        assert limited.headers["Retry-After"] == "1800"  # the first refresh leaves the hour
        assert len(services.refreshed) == 2
        clock.now += 1800
        assert client.post("/api/v1/odds/refresh", headers=headers).status_code == 202


def test_without_rate_limits_nothing_is_limited(clock: Clock) -> None:
    services = _services(clock)
    services.rate_limits = None
    with TestClient(create_app(services)) as client:
        for _ in range(10):
            assert (
                client.post("/api/v1/odds/refresh", headers={"X-API-Key": KEY}).status_code == 202
            )


def test_body_over_the_limit_is_413(clock: Clock) -> None:
    with TestClient(create_app(_services(clock, max_body=100))) as client:
        big = '{"password": "' + "x" * 200 + '"}'
        response = client.post(LOGIN, content=big, headers={"Content-Type": "application/json"})
        assert response.status_code == 413
        assert _code(response) == "PAYLOAD_TOO_LARGE"
        assert "100 bytes" in response.json()["error"]["message"]
        # at the limit it goes through to validation (wrong password → 401)
        ok = '{"password": "' + "x" * (100 - 16) + '"}'
        assert len(ok) == 100
        response = client.post(LOGIN, content=ok, headers={"Content-Type": "application/json"})
        assert response.status_code == 401


def test_chunked_body_without_content_length_is_cut(clock: Clock) -> None:
    def chunks() -> Iterator[bytes]:
        yield b'{"password": "'
        for _ in range(10):
            yield b"x" * 50
        yield b'"}'

    with TestClient(create_app(_services(clock, max_body=100))) as client:
        response = client.post(
            LOGIN, content=chunks(), headers={"Content-Type": "application/json"}
        )
        assert "content-length" not in {k.lower() for k in response.request.headers}
        assert response.status_code == 413
        assert _code(response) == "PAYLOAD_TOO_LARGE"


def test_default_body_limit_applies_without_configuration() -> None:
    services = SimpleNamespace(
        predictor=SimpleNamespace(state=lambda: None),
        app_api_key=KEY,
        journal=None,
        auth=None,
        secure_cookies=False,
    )
    with TestClient(create_app(services)) as client:
        response = client.post(LOGIN, content=b"x" * 70_000)
        assert response.status_code == 413
