"""Spec 003, T006: owner login use case with Argon2id and server-side sessions in SQLite."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from betting_ml.adapters.argon2_hasher import Argon2Hasher
from betting_ml.adapters.sql.db import prepare, session_factory
from betting_ml.adapters.sql.repositories import SqlSessionStore
from betting_ml.application.authenticate import (
    Authenticate,
    InvalidCredentialsError,
    LoginDisabledError,
)

PASSWORD = "correct horse battery staple"
HASHER = Argon2Hasher(time_cost=1, memory_cost=1024, parallelism=1)  # cheap for tests
HASH = HASHER.hash(PASSWORD)
SECRET = b"session-secret-for-tests-0123456789"


class Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 10, 22, 12, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now


@pytest.fixture
def store() -> SqlSessionStore:
    return SqlSessionStore(session_factory(prepare("sqlite:///:memory:")))


@pytest.fixture
def clock() -> Clock:
    return Clock()


def _auth(store: SqlSessionStore, clock: Clock, **overrides: object) -> Authenticate:
    values: dict[str, object] = {
        "sessions": store,
        "hasher": HASHER,
        "password_hash": HASH,
        "secret": SECRET,
        "idle": timedelta(minutes=30),
        "max_age": timedelta(hours=12),
        "clock": clock,
    }
    values.update(overrides)
    return Authenticate(**values)  # type: ignore[arg-type]


def test_login_creates_a_session_storing_only_the_token_hash(store, clock) -> None:  # type: ignore[no-untyped-def]
    login = _auth(store, clock).login(PASSWORD)
    assert len(login.token) >= 43  # 32 random bytes, url-safe
    assert login.session.token_hash != login.token
    assert login.token not in login.session.token_hash
    assert store.get(login.session.token_hash) == login.session
    assert login.session.expires_at == clock.now + timedelta(hours=12)
    assert login.session.csrf_token and login.session.csrf_token != login.token


def test_tokens_are_unique(store, clock) -> None:  # type: ignore[no-untyped-def]
    auth = _auth(store, clock)
    tokens = {auth.login(PASSWORD).token for _ in range(5)}
    assert len(tokens) == 5


@pytest.mark.parametrize("password", ["wrong", "", PASSWORD.upper(), PASSWORD + " "])
def test_wrong_password_is_rejected(store, clock, password: str) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(InvalidCredentialsError):
        _auth(store, clock).login(password)


@pytest.mark.parametrize("password_hash", ["", "not-a-hash"])
def test_login_disabled_without_a_valid_hash(store, clock, password_hash: str) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(LoginDisabledError):
        _auth(store, clock, password_hash=password_hash).login(PASSWORD)


def test_validate_slides_the_idle_window(store, clock) -> None:  # type: ignore[no-untyped-def]
    auth = _auth(store, clock)
    token = auth.login(PASSWORD).token
    for _ in range(3):
        clock.now += timedelta(minutes=25)
        session = auth.validate(token)
        assert session is not None and session.last_seen_at == clock.now


def test_idle_session_is_rejected_and_deleted(store, clock) -> None:  # type: ignore[no-untyped-def]
    auth = _auth(store, clock)
    login = auth.login(PASSWORD)
    clock.now += timedelta(minutes=31)
    assert auth.validate(login.token) is None
    assert store.get(login.session.token_hash) is None


def test_absolute_expiry(store, clock) -> None:  # type: ignore[no-untyped-def]
    auth = _auth(store, clock)
    token = auth.login(PASSWORD).token
    expired_at = None
    for _ in range(60):  # active every 15 minutes, never idle
        clock.now += timedelta(minutes=15)
        if auth.validate(token) is None:
            expired_at = clock.now
            break
    assert expired_at == datetime(2026, 10, 23, 0, 0, tzinfo=UTC)  # exactly 12 h after login


@pytest.mark.parametrize("token", ["", "x", "forged-token-0123456789-abcdefghijklmnopqrstuv"])
def test_unknown_or_tampered_tokens(store, clock, token: str) -> None:  # type: ignore[no-untyped-def]
    auth = _auth(store, clock)
    real = auth.login(PASSWORD).token
    assert auth.validate(token) is None
    assert auth.validate(real[:-1] + ("A" if real[-1] != "A" else "B")) is None


def test_logout_invalidates(store, clock) -> None:  # type: ignore[no-untyped-def]
    auth = _auth(store, clock)
    token = auth.login(PASSWORD).token
    auth.logout(token)
    assert auth.validate(token) is None
    auth.logout("unknown")  # idempotent


def test_login_rotates_the_current_session(store, clock) -> None:  # type: ignore[no-untyped-def]
    auth = _auth(store, clock)
    first = auth.login(PASSWORD).token
    second = auth.login(PASSWORD, current_token=first).token
    assert auth.validate(first) is None
    assert auth.validate(second) is not None


def test_password_change_invalidates_existing_sessions(store, clock) -> None:  # type: ignore[no-untyped-def]
    token = _auth(store, clock).login(PASSWORD).token
    new_hash = HASHER.hash("a brand new password")
    assert _auth(store, clock, password_hash=new_hash).validate(token) is None


def test_secret_rotation_invalidates_existing_sessions(store, clock) -> None:  # type: ignore[no-untyped-def]
    token = _auth(store, clock).login(PASSWORD).token
    assert _auth(store, clock, secret=b"another-secret-0123456789abcdef").validate(token) is None


def test_purge_removes_only_expired_sessions(store, clock) -> None:  # type: ignore[no-untyped-def]
    auth = _auth(store, clock)
    old = auth.login(PASSWORD).token
    clock.now += timedelta(minutes=20)
    fresh = auth.login(PASSWORD).token
    clock.now += timedelta(minutes=15)  # old idle 35 min, fresh idle 15 min
    assert auth.purge() == 1
    assert auth.validate(old) is None
    assert auth.validate(fresh) is not None


def test_hasher_rejects_garbage_hashes() -> None:
    assert HASHER.verify(HASH, PASSWORD)
    assert not HASHER.verify("garbage", PASSWORD)
    assert not HASHER.verify("", PASSWORD)
    assert HASH.startswith("$argon2id$")
