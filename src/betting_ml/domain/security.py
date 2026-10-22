"""Security concepts of the domain (spec 003). Pure: no HTTP, cookies or framework types."""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum


class PrincipalKind(StrEnum):
    API_KEY = "api_key"  # machine clients: Postman, CLI, scripts
    SESSION = "session"  # the owner in the browser


@dataclass(frozen=True)
class Session:
    """Server-side owner session. Only a keyed digest of the token is stored, never the token."""

    token_hash: str
    csrf_token: str
    created_at: datetime
    last_seen_at: datetime
    expires_at: datetime  # absolute limit (SESSION_MAX_HOURS), activity does not extend it
    password_fingerprint: str  # changes with APP_PASSWORD_HASH: old sessions stop working

    def is_active(self, now: datetime, idle: timedelta, password_fingerprint: str) -> bool:
        return (
            now < self.expires_at
            and now - self.last_seen_at < idle
            and hmac.compare_digest(self.password_fingerprint, password_fingerprint)
        )


@dataclass(frozen=True)
class Principal:
    """Who is making an authenticated request."""

    kind: PrincipalKind
    session: Session | None = None


def keyed_digest(key: bytes, value: str) -> str:
    """HMAC-SHA256 hex digest: tokens and fingerprints are stored keyed by SESSION_SECRET."""
    return hmac.new(key, value.encode("utf-8"), hashlib.sha256).hexdigest()
