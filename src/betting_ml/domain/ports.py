"""Ports (interfaces) implemented by adapters and models.

Tabular data travels as pandas DataFrames following the canonical schema of plan.md §3.2;
the domain only references the type (no IO).
"""

from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    import numpy as np
    import pandas as pd

    from betting_ml.domain.entities import Fixture


@runtime_checkable
class MatchDataSource(Protocol):
    """Historical results and odds (e.g. football-data.co.uk)."""

    def fetch_season(self, league: str, season: str) -> pd.DataFrame: ...


@runtime_checkable
class XgDataSource(Protocol):
    """Per-match expected goals (e.g. Understat)."""

    def fetch_season(self, league: str, season: str) -> pd.DataFrame: ...


@runtime_checkable
class FixtureSource(Protocol):
    """Upcoming matches with odds."""

    def fetch_fixtures(self, force_refresh: bool = False) -> list[Fixture]: ...


@runtime_checkable
class MatchRepository(Protocol):
    """Persistence of processed datasets (matches / holdout / current)."""

    def save(self, name: str, frame: pd.DataFrame) -> None: ...

    def load(self, name: str) -> pd.DataFrame: ...

    def exists(self, name: str) -> bool: ...


@runtime_checkable
class ProbabilisticModel(Protocol):
    """Common interface of every 1X2 model (plan.md §6)."""

    name: str
    uses_odds: bool

    def fit(self, train: pd.DataFrame) -> ProbabilisticModel: ...

    def predict_proba(self, matches: pd.DataFrame) -> np.ndarray:
        """Shape (n, 3) with columns [H, D, A]; rows sum to 1."""
        ...

    def predict_goal_matrix(self, matches: pd.DataFrame) -> np.ndarray | None:
        """Optional (n, G, G) score matrix, used for Over/Under."""
        ...


@runtime_checkable
class ModelRegistry(Protocol):
    """Persistence of trained models and their metadata."""

    def save(self, version: str, model: Any, metadata: dict[str, Any]) -> None: ...

    def load(self, version: str) -> tuple[Any, dict[str, Any]]: ...

    def list_versions(self) -> list[str]: ...


@runtime_checkable
class Clock(Protocol):
    def now(self) -> datetime: ...

    def today(self) -> date: ...
