"""Domain entities. Pure Python: no IO, no frameworks."""

from __future__ import annotations

import math
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime
from enum import StrEnum
from zoneinfo import ZoneInfo


class Outcome(StrEnum):
    HOME = "H"
    DRAW = "D"
    AWAY = "A"

    @property
    def position(self) -> int:
        return OUTCOMES.index(self)

    @property
    def label(self) -> str:
        return {"H": "home", "D": "draw", "A": "away"}[self.value]

    @classmethod
    def from_goals(cls, home_goals: int, away_goals: int) -> Outcome:
        if home_goals > away_goals:
            return cls.HOME
        if home_goals < away_goals:
            return cls.AWAY
        return cls.DRAW


OUTCOMES: tuple[Outcome, Outcome, Outcome] = (Outcome.HOME, Outcome.DRAW, Outcome.AWAY)


@dataclass(frozen=True, slots=True)
class Team:
    name: str
    league: str


@dataclass(frozen=True, slots=True)
class OddsTriple:
    """Decimal odds for home / draw / away."""

    home: float
    draw: float
    away: float

    def __post_init__(self) -> None:
        for value in self.as_tuple():
            if not math.isfinite(value) or value <= 1.0:
                raise ValueError(f"decimal odds must be > 1.0, got {value}")

    def as_tuple(self) -> tuple[float, float, float]:
        return (self.home, self.draw, self.away)

    def for_outcome(self, outcome: Outcome) -> float:
        return self.as_tuple()[outcome.position]


@dataclass(frozen=True, slots=True)
class Probabilities:
    """Probabilities for home / draw / away. Must sum to 1."""

    home: float
    draw: float
    away: float

    def __post_init__(self) -> None:
        values = self.as_tuple()
        if any(v < 0 or v > 1 for v in values):
            raise ValueError(f"probabilities must be in [0, 1], got {values}")
        if not math.isclose(sum(values), 1.0, abs_tol=1e-6):
            raise ValueError(f"probabilities must sum to 1, got {sum(values)}")

    def as_tuple(self) -> tuple[float, float, float]:
        return (self.home, self.draw, self.away)

    def for_outcome(self, outcome: Outcome) -> float:
        return self.as_tuple()[outcome.position]


@dataclass(frozen=True, slots=True)
class Match:
    """A played (or scheduled) match with canonical team names."""

    match_id: str
    league: str
    season: str
    date: date
    home_team: str
    away_team: str
    kickoff_utc: datetime | None = None
    home_goals: int | None = None
    away_goals: int | None = None
    home_xg: float | None = None
    away_xg: float | None = None

    @property
    def is_played(self) -> bool:
        return self.home_goals is not None and self.away_goals is not None

    @property
    def result(self) -> Outcome | None:
        if self.home_goals is None or self.away_goals is None:
            return None
        return Outcome.from_goals(self.home_goals, self.away_goals)


@dataclass(frozen=True, slots=True)
class Fixture:
    """An upcoming match with the odds published by the source."""

    match_id: str
    league: str
    kickoff_utc: datetime
    home_team: str
    away_team: str
    average_odds: OddsTriple | None = None
    best_odds: OddsTriple | None = None


@dataclass(frozen=True, slots=True)
class ValueBet:
    outcome: Outcome
    odds: float
    model_probability: float
    expected_value: float
    kelly_fraction: float


@dataclass(frozen=True, slots=True)
class Prediction:
    match_id: str
    league: str
    home_team: str
    away_team: str
    probabilities: Probabilities
    model_version: str
    kickoff_utc: datetime | None = None
    value_bets: list[ValueBet] = field(default_factory=list)


def slugify(text: str) -> str:
    """Lowercase ASCII slug: 'Nott'm Forest' -> 'nottm-forest'."""
    normalized = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    normalized = re.sub(r"['’`.]", "", normalized.lower())
    return re.sub(r"[^a-z0-9]+", "-", normalized).strip("-")


def make_match_id(league: str, match_date: date, home_team: str, away_team: str) -> str:
    """Stable id: ``{league}-{YYYY-MM-DD}-{home}-{away}`` (see contracts/api.md)."""
    return f"{league}-{match_date.isoformat()}-{slugify(home_team)}-{slugify(away_team)}"


def fixtures_on(fixtures: list[Fixture], day: date, timezone: str) -> list[Fixture]:
    """Fixtures whose kick-off falls on ``day`` in ``timezone`` (e.g. America/Lima)."""
    tz = ZoneInfo(timezone)
    return sorted(
        (f for f in fixtures if f.kickoff_utc.astimezone(tz).date() == day),
        key=lambda f: (f.kickoff_utc, f.league, f.home_team),
    )
