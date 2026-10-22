"""Owner login with server-side sessions (spec 003, US1).

The browser holds a random 256-bit token in an HttpOnly cookie; the database only stores
HMAC-SHA256(SESSION_SECRET, token). Sessions expire after ``idle`` without activity and at
``max_age`` in any case; changing APP_PASSWORD_HASH or SESSION_SECRET invalidates them all.
"""

from __future__ import annotations

import secrets
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta

from betting_ml.application.throttle import LoginThrottle
from betting_ml.domain.audit import AuditInfo
from betting_ml.domain.ports import AuditLog, PasswordHasher, SessionStore
from betting_ml.domain.security import Session, keyed_digest

TOKEN_BYTES = 32  # 256 bits


class InvalidCredentialsError(Exception):
    def __init__(self) -> None:
        super().__init__("Credenciales inválidas")


class LoginDisabledError(Exception):
    def __init__(self) -> None:
        super().__init__(
            "Login deshabilitado: configura APP_PASSWORD_HASH en .env (betting-ml hash-password)"
        )


@dataclass(frozen=True)
class Login:
    token: str  # goes to the cookie only; never logged nor stored
    session: Session


class Authenticate:
    def __init__(
        self,
        sessions: SessionStore,
        hasher: PasswordHasher,
        password_hash: str,
        secret: bytes,
        idle: timedelta,
        max_age: timedelta,
        throttle: LoginThrottle,  # required: there is no login without brute-force limits
        audit_log: AuditLog | None = None,  # failed logins (successful ones go with the session)
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        token_factory: Callable[[int], str] = secrets.token_urlsafe,
    ) -> None:
        self.sessions = sessions
        self.hasher = hasher
        self.password_hash = password_hash
        self.secret = secret
        self.idle = idle
        self.max_age = max_age
        self.clock = clock
        self.token_factory = token_factory
        self.throttle = throttle
        self.audit_log = audit_log
        self.fingerprint = keyed_digest(secret, password_hash)

    @property
    def enabled(self) -> bool:
        return self.password_hash.startswith("$argon2id$")

    def login(
        self, password: str, current_token: str | None = None, client: str = "unknown"
    ) -> Login:
        if not self.enabled:
            raise LoginDisabledError()
        self.throttle.begin(client)  # before Argon2: a locked client costs no CPU
        if not self.hasher.verify(self.password_hash, password):
            if self.audit_log is not None:
                failed = AuditInfo("anonymous", "LOGIN_FAILED", {"client": client})
                self.audit_log.append(failed, "session")
            raise InvalidCredentialsError()
        self.throttle.succeeded(client)
        if current_token:  # rotation: the previous session never survives a new login
            self.logout(current_token)
        self.purge()
        now = self.clock()
        token = self.token_factory(TOKEN_BYTES)
        session = Session(
            token_hash=keyed_digest(self.secret, token),
            csrf_token=self.token_factory(TOKEN_BYTES),
            created_at=now,
            last_seen_at=now,
            expires_at=now + self.max_age,
            password_fingerprint=self.fingerprint,
        )
        self.sessions.add(session, AuditInfo("session", "LOGIN_OK", {"client": client}))
        return Login(token=token, session=session)

    def validate(self, token: str) -> Session | None:
        """The active session of ``token`` with its idle window slid to now, else None."""
        if not token:
            return None
        token_hash = keyed_digest(self.secret, token)
        session = self.sessions.get(token_hash)
        if session is None:
            return None
        now = self.clock()
        if not session.is_active(now, self.idle, self.fingerprint):
            self.sessions.delete(token_hash)
            return None
        self.sessions.touch(token_hash, now)
        return replace(session, last_seen_at=now)

    def logout(self, token: str) -> None:
        if token:
            self.sessions.delete(keyed_digest(self.secret, token), AuditInfo("session", "LOGOUT"))

    def purge(self) -> int:
        now = self.clock()
        return self.sessions.purge(now, now - self.idle)
