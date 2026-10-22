"""Brute-force and abuse limits (spec 003, US2) on top of the RateLimiter port.

Login: each attempt is counted *before* checking the password, so parallel guesses cannot slip
past the limit, and a success clears the count. One attempt over ``max_attempts`` in a minute
locks the client for 1, 5 and then 15 minutes (progressive); while locked, not even the right
password is checked. The lockout level is remembered for ``memory`` (24 h).
"""

from __future__ import annotations

import math
import threading
from dataclasses import dataclass
from datetime import timedelta

from betting_ml.domain.ports import RateLimiter

MINUTE = timedelta(minutes=1)
HOUR = timedelta(hours=1)
LOCKOUTS = (timedelta(minutes=1), timedelta(minutes=5), timedelta(minutes=15))


class TooManyAttemptsError(Exception):
    def __init__(self, retry_after: float) -> None:
        self.retry_after = max(1, math.ceil(retry_after))
        super().__init__(
            f"Demasiados intentos de inicio de sesión. Vuelve a intentarlo en {self.retry_after} s."
        )


@dataclass(frozen=True)
class RateLimits:
    """Request limits of the API: global per client IP and the paid odds refresh."""

    limiter: RateLimiter
    per_minute: int
    odds_refresh_per_hour: int


class LoginThrottle:
    def __init__(
        self,
        limiter: RateLimiter,
        max_attempts: int,
        lockouts: tuple[timedelta, ...] = LOCKOUTS,
        memory: timedelta = timedelta(hours=24),
    ) -> None:
        self.limiter = limiter
        self.max_attempts = max_attempts
        self.lockouts = lockouts
        self.memory = memory
        self._mutex = threading.Lock()

    def begin(self, client: str) -> None:
        """Counts an attempt of ``client``; raises TooManyAttemptsError when locked or over."""
        with self._mutex:
            left = self.limiter.locked_for(f"login-lock:{client}")
            if left is not None:
                raise TooManyAttemptsError(left)
            if self.limiter.hit(f"login-attempts:{client}", self.max_attempts, MINUTE) is None:
                return
            strikes = self.limiter.count(f"login-strikes:{client}", self.memory)
            self.limiter.hit(f"login-strikes:{client}", len(self.lockouts), self.memory)
            duration = self.lockouts[min(strikes, len(self.lockouts) - 1)]
            self.limiter.lock(f"login-lock:{client}", duration)
            self.limiter.reset(f"login-attempts:{client}")
        raise TooManyAttemptsError(duration.total_seconds())

    def succeeded(self, client: str) -> None:
        with self._mutex:
            self.limiter.reset(f"login-attempts:{client}")
            self.limiter.reset(f"login-strikes:{client}")
