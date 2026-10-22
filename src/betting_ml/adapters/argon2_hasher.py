"""Argon2id password hashing (PasswordHasher port), OWASP-recommended parameters by default."""

from __future__ import annotations

from argon2 import PasswordHasher as _Argon2
from argon2 import Type
from argon2.exceptions import InvalidHashError, VerificationError


class Argon2Hasher:
    def __init__(self, time_cost: int = 3, memory_cost: int = 65_536, parallelism: int = 4) -> None:
        self._hasher = _Argon2(
            time_cost=time_cost, memory_cost=memory_cost, parallelism=parallelism, type=Type.ID
        )

    def hash(self, password: str) -> str:
        return self._hasher.hash(password)

    def verify(self, password_hash: str, password: str) -> bool:
        """False on mismatch and on malformed hashes: never raises for bad input."""
        try:
            return self._hasher.verify(password_hash, password)
        except (VerificationError, InvalidHashError):
            return False
