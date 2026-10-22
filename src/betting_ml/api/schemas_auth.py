"""Spec-003 auth schemas (contracts/api.md of spec 003)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class LoginIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Upper bound: Argon2 cost must not depend on attacker-sized input.
    password: str = Field(min_length=1, max_length=1024)


class LoginOut(BaseModel):
    csrf_token: str
    expires_at: datetime
    idle_minutes: int


class MeOut(BaseModel):
    authenticated: bool
    kind: Literal["session", "api_key"]
    csrf_token: str | None
    expires_at: datetime | None
