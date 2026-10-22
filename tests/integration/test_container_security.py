"""Spec 003, T010: the real wiring of the security controls. The functional tests inject their
own services, so without this file the container could drop the login throttle, the request
limits or the Secure cookie and the suite would stay green."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from betting_ml.adapters.argon2_hasher import Argon2Hasher
from betting_ml.adapters.memory_rate_limiter import MemoryRateLimiter
from betting_ml.application.throttle import LoginThrottle, TooManyAttemptsError
from betting_ml.config import Settings
from betting_ml.container import ApiServices, Container

ARGON2_HASH = Argon2Hasher(time_cost=1, memory_cost=1024, parallelism=1).hash("x" * 16)


def _services(tmp_path: Path, **overrides: Any) -> ApiServices:
    values: dict[str, Any] = {
        "database_url": f"sqlite:///{(tmp_path / 'app.db').as_posix()}",
        "app_password_hash": ARGON2_HASH,
        "app_api_key": "k" * 40,
        "session_secret": "s" * 40,
    }
    values.update(overrides)
    return Container(Settings(_env_file=None, **values)).api_services()


def test_container_wires_every_limit_with_the_settings(tmp_path: Path) -> None:
    services = _services(tmp_path)
    limits = services.rate_limits
    assert limits is not None
    assert (limits.per_minute, limits.odds_refresh_per_hour) == (120, 6)
    assert isinstance(limits.limiter, MemoryRateLimiter)
    assert services.max_body_bytes == 65_536
    auth = services.auth
    assert auth is not None
    assert isinstance(auth.throttle, LoginThrottle)
    assert auth.throttle.max_attempts == 5
    assert auth.throttle.limiter is limits.limiter  # one limiter for the whole API
    assert services.secure_cookies is False  # dev


def test_container_follows_custom_limits(tmp_path: Path) -> None:
    services = _services(
        tmp_path,
        rate_limit_per_minute=30,
        odds_refresh_max_per_hour=2,
        login_max_attempts_per_minute=3,
        max_body_bytes=1024,
    )
    assert services.rate_limits is not None
    assert (services.rate_limits.per_minute, services.rate_limits.odds_refresh_per_hour) == (30, 2)
    assert services.auth is not None and services.auth.throttle.max_attempts == 3
    assert services.max_body_bytes == 1024


def test_prod_cookies_are_secure(tmp_path: Path) -> None:
    services = _services(
        tmp_path,
        app_env="prod",
        allowed_hosts=["bets.example.com"],
        cors_origins=["https://bets.example.com"],
    )
    assert services.secure_cookies is True


def test_the_container_login_locks_after_the_limit(tmp_path: Path) -> None:
    auth = _services(tmp_path, login_max_attempts_per_minute=2).auth
    assert auth is not None
    for _ in range(2):
        with pytest.raises(Exception, match="Credenciales"):
            auth.login("wrong password", client="203.0.113.7")
    with pytest.raises(TooManyAttemptsError):
        auth.login("x" * 16, client="203.0.113.7")
