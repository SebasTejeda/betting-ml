"""Ports (interfaces) implemented by adapters and models.

Tabular data travels as pandas DataFrames following the canonical schema of plan.md §3.2;
the domain only references the type (no IO).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from pathlib import Path

    import numpy as np
    import pandas as pd

    from betting_ml.domain.entities import Fixture


class OddsSourceNotConfiguredError(ValueError):
    """The paid odds source has no key (ODDS_API_KEY): it cannot be called at all."""


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


class ModelHashes(Protocol):
    """SHA-256 of each saved model artifact and the one recorded in its metadata."""

    def list_versions(self) -> list[str]: ...

    def artifact_sha256(self, version: str) -> str: ...

    def recorded_sha256(self, version: str) -> str | None: ...

    def record_sha256(self, version: str, digest: str) -> None: ...


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

    def save_snapshot(self, snapshot: Any, audit: Any = ...) -> int: ...

    def latest_quotes(
        self,
        match_ids: Any = None,
        kickoff_from: Any = None,
        kickoff_to: Any = None,
        before: Any = None,
        source: Any = None,
    ) -> list[Any]: ...

    def latest_snapshot(self, source: Any = ...) -> Any: ...

    def snapshots_since(self, since: datetime, source: Any = ...) -> list[Any]: ...

    def history(self, match_id: str, bookmaker: str) -> list[Any]: ...


@runtime_checkable
class BetRepository(Protocol):
    """Betting journal (spec 002)."""

    def add(self, bet: Any, audit: Any = ...) -> Any: ...

    def get(self, bet_id: int) -> Any: ...

    def update(self, bet: Any, audit: Any = ...) -> Any: ...

    def delete(self, bet_id: int, audit: Any = ...) -> bool: ...

    def search(
        self, filters: Any = None, page: int = 1, size: int = 50
    ) -> tuple[list[Any], int]: ...

    def all(self, filters: Any = None) -> list[Any]: ...


@runtime_checkable
class SettingsRepository(Protocol):
    def get(self) -> Any: ...

    def save(self, settings: Any, changes: Any = (), audit: Any = ...) -> Any: ...

    def history(self, field: str | None = None) -> list[Any]: ...


@runtime_checkable
class Clock(Protocol):
    def now(self) -> datetime: ...

    def today(self) -> date: ...


@runtime_checkable
class ReportStore(Protocol):
    """Generated reports (JSON) read by the API, e.g. the spec-002 backtest."""

    def read_json(self, name: str) -> dict[str, Any] | None: ...


@runtime_checkable
class SessionStore(Protocol):
    """Owner sessions (spec 003), looked up by the keyed digest of their token."""

    def add(self, session: Any, audit: Any = ...) -> None: ...

    def get(self, token_hash: str) -> Any | None: ...

    def touch(self, token_hash: str, last_seen_at: datetime) -> None: ...

    def delete(self, token_hash: str, audit: Any = None) -> None: ...

    def purge(self, now: datetime, idle_cutoff: datetime) -> int: ...


@runtime_checkable
class PasswordHasher(Protocol):
    def hash(self, password: str) -> str: ...

    def verify(self, password_hash: str, password: str) -> bool: ...


@runtime_checkable
class RateLimiter(Protocol):
    """Sliding-window counters and lockouts by opaque key (spec 003, US2). Thread-safe."""

    def hit(self, key: str, limit: int, window: timedelta) -> float | None:
        """Atomically counts one event for ``key`` unless ``limit`` events already fall in the
        last ``window``: None when counted, else the seconds until one is allowed again."""

    def count(self, key: str, window: timedelta) -> int: ...

    def lock(self, key: str, duration: timedelta) -> None: ...

    def locked_for(self, key: str) -> float | None:
        """Seconds left of the lock on ``key``, or None if it is not locked."""

    def reset(self, key: str) -> None: ...


@runtime_checkable
class AuditLog(Protocol):
    """Append-only, hash-chained log (spec 003, US5). Changes to data append their event in
    their own transaction (the repositories); this port is for standalone events."""

    def append(
        self, info: Any, entity: str, entity_id: str | None = None, after: Any = None
    ) -> Any: ...

    def records(self) -> list[Any]: ...


@runtime_checkable
class IntegritySource(Protocol):
    """What ``verify-integrity`` checks: the database itself, the chain and current rows."""

    def pragma_problems(self) -> list[str]: ...

    def records(self) -> list[Any]: ...

    def current_states(self, entity: str) -> dict[str, dict[str, Any]]: ...


@runtime_checkable
class DatabaseFiles(Protocol):
    """Copies of the live database (spec 003, US6): hot backup, verification, restore."""

    def exists(self) -> bool: ...

    def copy_to(self, target: Path) -> list[str]: ...

    def copy_raw(self, target: Path) -> Path: ...

    def restore_from(self, candidate: Path, replace_file: bool = False) -> None: ...

    def after_restore(self, info: Any) -> None: ...

    def sha256(self, path: Path) -> str: ...

    def check(self, path: Path) -> list[str]: ...

    def has_audit(self, path: Path) -> bool: ...

    def integrity_source(self, path: Path) -> IntegritySource: ...


# --- spec 004 (match analysis, from the Sebastian branch)


@runtime_checkable
class RatingsSource(Protocol):
    """Club strength ratings by date that compare clubs across leagues (e.g. ClubElo)."""

    def ratings_on(self, day: date) -> pd.DataFrame: ...

    def ratings_before(self, match_date: date) -> pd.DataFrame: ...


@runtime_checkable
class InternationalResultsSource(Protocol):
    """Historical results of European club competitions (e.g. openfootball)."""

    def fetch_season(self, competition: str, season: str) -> pd.DataFrame: ...

    def fetch_league(self, folder: str, file: str, country: str, season: str) -> pd.DataFrame: ...


@runtime_checkable
class EuropeTeamNames(Protocol):
    """Resolves clubs of European competitions and their ClubElo names."""

    def from_openfootball(self, name: str, country: str) -> Any: ...

    def unknown_openfootball(self, frame: pd.DataFrame) -> Exception | None: ...

    def clubelo_name(self, team: Any, ratings: pd.DataFrame) -> str | None: ...

    def unify_foreign(self, name: str, country: str, league_names: set[str]) -> str: ...

    def canonical_foreign(self, name: str, country: str) -> str: ...
