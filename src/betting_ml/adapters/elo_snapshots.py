"""`RatingsSource` over our own cross-league Elo (spec 003, T006; replaces ClubElo)."""

from __future__ import annotations

from datetime import date

import pandas as pd

from betting_ml.domain.ports import MatchRepository
from betting_ml.domain.ratings import snapshot_date
from betting_ml.ml.models.club_elo import snapshot

HISTORY_NAME = "club_elo_history"


class EloSnapshotSource:
    """Snapshots of ``data/processed/club_elo_history.parquet`` with ClubElo's schema."""

    def __init__(self, repository: MatchRepository, recent_days: int = 365) -> None:
        self.repository = repository
        self.recent_days = recent_days
        self._history: pd.DataFrame | None = None

    @property
    def history(self) -> pd.DataFrame:
        if self._history is None:
            self._history = self.repository.load(HISTORY_NAME)
        return self._history

    def ratings_on(self, day: date) -> pd.DataFrame:
        return snapshot(self.history, pd.Timestamp(day), self.recent_days)

    def ratings_before(self, match_date: date) -> pd.DataFrame:
        return self.ratings_on(snapshot_date(match_date))
