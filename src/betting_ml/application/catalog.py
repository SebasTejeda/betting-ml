"""Small read-only use cases used by the API: leagues, model information, experiments and
the data refresh orchestration."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import pandas as pd

from betting_ml.application.predict_matches import ModelNotAvailableError, PredictMatches
from betting_ml.config import LeaguesFile

logger = logging.getLogger(__name__)


@dataclass
class LeagueInfo:
    code: str
    name: str
    country: str
    teams: int


def list_leagues(leagues: LeaguesFile, predictor: PredictMatches) -> list[LeagueInfo]:
    """Teams = clubs of the current season according to the served Elo state (0 if no model)."""
    out = []
    for league in leagues.leagues:
        try:
            teams = len(predictor.team_ratings(league.code))
        except ModelNotAvailableError:
            teams = 0
        out.append(LeagueInfo(league.code, league.name, league.country, teams))
    return out


def model_info(predictor: PredictMatches) -> dict[str, Any]:
    state = predictor.state()
    meta = state.champion.metadata
    return {
        "version": state.champion.version,
        "experiment_id": meta.get("experiment_id"),
        "trained_on": meta.get("trained_on"),
        "features": meta.get("features", []),
        "validation_metrics": meta.get("validation_metrics", {}),
        "holdout_metrics": meta.get("holdout_metrics", {}),
        "success_level": meta.get("success_level"),
        "model_no_odds_version": state.no_odds.version,
    }


def list_experiments(read_rows: Callable[[], pd.DataFrame]) -> list[dict[str, Any]]:
    rows = read_rows()
    if rows.empty:
        return []
    rows = rows.sort_values("val_ll_mean", kind="mergesort")
    rows = rows.astype(object).where(rows.notna(), None)
    return [dict(r) for r in rows.to_dict(orient="records")]


class RefreshData:
    """Downloads fixtures now; rebuilds the current-season data in the background."""

    def __init__(
        self,
        refresh_fixtures: Callable[[], int],
        rebuild: Callable[[], None],
        on_done: Callable[[], None],
    ) -> None:
        self.refresh_fixtures = refresh_fixtures
        self.rebuild = rebuild
        self.on_done = on_done

    def fixtures(self) -> int:
        count = self.refresh_fixtures()
        self.on_done()
        return count

    def data(self) -> None:
        try:
            self.rebuild()
        except Exception:  # background task: log, never crash the server
            logger.exception("current-season refresh failed")
            return
        self.on_done()
