"""Security concepts of the domain (spec 003). Pure: no HTTP, cookies or framework types."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class PrincipalKind(StrEnum):
    API_KEY = "api_key"  # machine clients: Postman, CLI, scripts


@dataclass(frozen=True)
class Principal:
    """Who is making an authenticated request."""

    kind: PrincipalKind
