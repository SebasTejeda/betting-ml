"""Use case (US6): store every prediction served by /matches and grade it once the real
result is known, to measure the model out of sample over time."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any

import numpy as np
import pandas as pd

from betting_ml.domain.entities import Fixture, make_match_id
from betting_ml.domain.metrics import accuracy, log_loss
from betting_ml.domain.ports import MatchDataSource, TeamNameNormalizer, TrackingStore

logger = logging.getLogger(__name__)
RESULT_INDEX = {"H": 0, "D": 1, "A": 2}


@dataclass
class TrackingSummary:
    predictions: int
    graded: int
    log_loss: float | None
    accuracy: float | None
    value_bets: int
    roi: float | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class TrackPredictions:
    def __init__(
        self,
        store: TrackingStore,
        results: MatchDataSource,
        team_names: TeamNameNormalizer,
        leagues: list[str],
        current_season: str,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.store = store
        self.results = results
        self.team_names = team_names
        self.leagues = leagues
        self.current_season = current_season
        self.clock = clock

    def record(self, predictions: list[Any], fixtures: list[Fixture]) -> int:
        """Called with the predictions served by /matches (MatchPrediction objects)."""
        by_id = {f.match_id: f for f in fixtures}
        now = self.clock().isoformat(timespec="seconds")
        rows = []
        for p in predictions:
            fixture = by_id.get(p.match_id)
            best = p.value_bets[0] if p.value_bets else None
            rows.append(
                {
                    "match_id": p.match_id,
                    "model_version": p.model_version,
                    "model_variant": p.model_variant,
                    "league": p.league,
                    "kickoff_utc": p.kickoff,
                    "home_team": p.home_team,
                    "away_team": p.away_team,
                    "p_home": p.probabilities.home,
                    "p_draw": p.probabilities.draw,
                    "p_away": p.probabilities.away,
                    "avg_odds": _odds(fixture.average_odds if fixture else None),
                    "value_outcome": best.outcome.value if best else None,
                    "value_odds": best.odds if best else np.nan,
                    "value_ev": best.expected_value if best else np.nan,
                    "predicted_at": now,
                    "result": None,
                    "graded_at": None,
                }
            )
        if not rows:
            return 0
        return self.store.append(pd.DataFrame(rows))

    def update(self) -> int:
        """Grade pending predictions with the results of the current season."""
        tracked = self.store.load()
        if tracked.empty:
            return 0
        frames = []
        for league in self.leagues:
            try:
                frames.append(self.results.fetch_season(league, self.current_season))
            except Exception as exc:  # keep grading the other leagues
                logger.error("results for %s unavailable: %s", league, exc)
        if not frames:
            return 0
        results = self.team_names.canonicalize(
            pd.concat(frames, ignore_index=True), "football_data"
        )
        played = results.dropna(subset=["home_goals", "away_goals"])
        outcome = {}
        for row in played.itertuples():
            match_id = make_match_id(row.league, row.date.date(), row.home_team, row.away_team)
            hg, ag = int(row.home_goals), int(row.away_goals)
            outcome[match_id] = "H" if hg > ag else "A" if hg < ag else "D"
        pending = tracked["result"].isna() & tracked["match_id"].isin(outcome)
        tracked.loc[pending, "result"] = tracked.loc[pending, "match_id"].map(outcome)
        tracked.loc[pending, "graded_at"] = self.clock().isoformat(timespec="seconds")
        self.store.save(tracked)
        return int(pending.sum())

    def summary(self) -> TrackingSummary:
        tracked = self.store.load()
        if tracked.empty:
            return TrackingSummary(0, 0, None, None, 0, None)
        graded = tracked[tracked["result"].notna()]
        if graded.empty:
            return TrackingSummary(len(tracked), 0, None, None, 0, None)
        y = graded["result"].map(RESULT_INDEX).to_numpy(dtype=int)
        proba = graded[["p_home", "p_draw", "p_away"]].to_numpy(dtype=float)
        bets = graded[graded["value_outcome"].notna()]
        roi = None
        if len(bets):
            won = bets["value_outcome"] == bets["result"]
            roi = float(np.where(won, bets["value_odds"] - 1.0, -1.0).mean())
        return TrackingSummary(
            predictions=len(tracked),
            graded=len(graded),
            log_loss=round(log_loss(y, proba), 4),
            accuracy=round(accuracy(y, proba), 4),
            value_bets=len(bets),
            roi=None if roi is None else round(roi, 4),
        )


def _odds(odds: Any) -> str | None:
    return None if odds is None else ",".join(f"{v:.2f}" for v in odds.as_tuple())
