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
class TeamNameNormalizer(Protocol):
    """Maps source-specific team names to canonical names (error if unknown)."""

    def canonicalize(self, frame: pd.DataFrame, source: Any) -> pd.DataFrame: ...

    def lookup(self, league: str, name: str) -> str | None: ...

    def teams(self, league: str) -> list[str]: ...


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

    def describe(self) -> dict[str, object]:
        """Name, parameters and fitted hyper-parameters (for reports)."""
        ...


@runtime_checkable
class ModelRegistry(Protocol):
    """Persistence of trained models and their metadata."""

    def save(self, version: str, model: Any, metadata: dict[str, Any]) -> None: ...

    def load(self, version: str) -> tuple[Any, dict[str, Any]]: ...

    def list_versions(self) -> list[str]: ...


@runtime_checkable
class ExperimentStore(Protocol):
    """Experiment results: CSV row, details, figures and fold predictions."""

    @property
    def figures_dir(self) -> Any: ...

    def upsert_row(self, row: dict[str, Any]) -> None: ...

    def save_details(self, exp_id: str, details: dict[str, Any]) -> Any: ...

    def save_predictions(self, exp_id: str, predictions: pd.DataFrame) -> Any: ...


@runtime_checkable
class TrackingStore(Protocol):
    """Served predictions and their grading (US6)."""

    def load(self) -> pd.DataFrame: ...

    def save(self, frame: pd.DataFrame) -> None: ...

    def append(self, records: pd.DataFrame) -> int: ...


@runtime_checkable
class OddsRepository(Protocol):
    """Odds snapshots and quotes (spec 002)."""

    def save_snapshot(self, snapshot: Any) -> int: ...

    def latest_quotes(
        self,
        match_ids: Any = None,
        kickoff_from: Any = None,
        kickoff_to: Any = None,
        before: Any = None,
    ) -> list[Any]: ...

    def latest_snapshot(self, source: Any = ...) -> Any: ...

    def snapshots_since(self, since: datetime, source: Any = ...) -> list[Any]: ...

    def history(self, match_id: str, bookmaker: str) -> list[Any]: ...


@runtime_checkable
class BetRepository(Protocol):
    """Betting journal (spec 002)."""

    def add(self, bet: Any) -> Any: ...

    def get(self, bet_id: int) -> Any: ...

    def update(self, bet: Any) -> Any: ...

    def delete(self, bet_id: int) -> bool: ...

    def search(
        self, filters: Any = None, page: int = 1, size: int = 50
    ) -> tuple[list[Any], int]: ...

    def all(self, filters: Any = None) -> list[Any]: ...


@runtime_checkable
class SettingsRepository(Protocol):
    def get(self) -> Any: ...

    def save(self, settings: Any, changes: Any = ()) -> None: ...

    def history(self, field: str | None = None) -> list[Any]: ...


@runtime_checkable
class Clock(Protocol):
    def now(self) -> datetime: ...

    def today(self) -> date: ...
