"""Spec 003, T006: pure session rules (expiry, keyed digests, password fingerprint)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from betting_ml.domain.security import Session, keyed_digest

NOW = datetime(2026, 10, 22, 12, 0, tzinfo=UTC)
IDLE = timedelta(minutes=30)


def _session(**overrides: object) -> Session:
    values: dict[str, object] = {
        "token_hash": "h",
        "csrf_token": "c",
        "created_at": NOW,
        "last_seen_at": NOW,
        "expires_at": NOW + timedelta(hours=12),
        "password_fingerprint": "fp",
    }
    values.update(overrides)
    return Session(**values)  # type: ignore[arg-type]


def test_active_session() -> None:
    assert _session().is_active(NOW + timedelta(minutes=29), IDLE, "fp")


def test_idle_session_expires() -> None:
    assert not _session().is_active(NOW + IDLE, IDLE, "fp")


def test_absolute_expiry_wins_over_activity() -> None:
    session = _session(last_seen_at=NOW + timedelta(hours=11, minutes=59))
    assert not session.is_active(NOW + timedelta(hours=12), IDLE, "fp")


def test_password_change_invalidates() -> None:
    assert not _session().is_active(NOW, IDLE, "other-fingerprint")


def test_keyed_digest_is_deterministic_and_depends_on_the_key() -> None:
    assert keyed_digest(b"k1", "token") == keyed_digest(b"k1", "token")
    assert keyed_digest(b"k1", "token") != keyed_digest(b"k2", "token")
    assert keyed_digest(b"k1", "token") != keyed_digest(b"k1", "token2")
    assert len(keyed_digest(b"k1", "token")) == 64
    assert "token" not in keyed_digest(b"k1", "token")
