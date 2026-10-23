"""Argon2id password hashing (PasswordHasher port), OWASP-recommended parameters by default.

Each verification takes ``memory_cost`` KiB (64 MiB): at most ``max_concurrent`` run at once,
so a burst of logins from many addresses cannot exhaust the memory of the API process. A check
that finds no free slot within ``busy_timeout`` seconds fails fast (PasswordCheckBusyError)
instead of holding one of the API's worker threads in a queue.
"""

from __future__ import annotations

import threading

from argon2 import PasswordHasher as _Argon2
from argon2 import Type
from argon2.exceptions import InvalidHashError, VerificationError

from betting_ml.domain.security import PasswordCheckBusyError


class Argon2Hasher:
    def __init__(
        self,
        time_cost: int = 3,
        memory_cost: int = 65_536,
        parallelism: int = 4,
        max_concurrent: int = 2,
        busy_timeout: float = 2.0,
    ) -> None:
        self._busy_timeout = busy_timeout
        self._slots = threading.BoundedSemaphore(max_concurrent)
        self._hasher = _Argon2(
            time_cost=time_cost, memory_cost=memory_cost, parallelism=parallelism, type=Type.ID
        )

    def hash(self, password: str) -> str:
        return self._hasher.hash(password)

    def verify(self, password_hash: str, password: str) -> bool:
        """False on mismatch and on malformed hashes: never raises for bad input."""
        if not self._slots.acquire(timeout=self._busy_timeout):
            raise PasswordCheckBusyError()
        try:
            return self._hasher.verify(password_hash, password)
        except (VerificationError, InvalidHashError):
            return False
        finally:
            self._slots.release()
