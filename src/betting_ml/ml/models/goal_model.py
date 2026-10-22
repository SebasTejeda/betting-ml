"""Score matrix for any same-league fixture (spec 003, T005 · plan §4).

Facade over the spec 001 goal model that validated best: Dixon-Coles estimated on xG (E09,
mean validation log loss 0.9824 vs 0.9862 for Dixon-Coles on goals, E04). Every matrix is
walk-forward: the parameters used for a match are fitted only on matches played before the
start of its 7-day block, exactly as in spec 001. Cross-league fixtures live in
`cross_league.py` (T006).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from betting_ml.ml.models.dixon_coles import DixonColesModel

SOURCE_EXPERIMENT = "E09"
# ξ chosen by E09's inner validation (last training season) in the two latest folds (F2, F3);
# used when no fold applies (analysis of upcoming matches).
DEFAULT_XI = 0.003
REFIT_DAYS = 7
MAX_GOALS = 10


class MissingHistoryError(ValueError):
    pass


@dataclass(frozen=True)
class FoldSpec:
    name: str
    train: tuple[str, ...]
    valid: str
    xi: float


def folds_from_experiment(details: dict[str, Any]) -> list[FoldSpec]:
    """Folds and the ξ each one chose (``reports/experiments/E09.json``).

    ξ was picked with the last training season of each fold, never with its validation season,
    so reusing it adds no leakage."""
    return [
        FoldSpec(
            name=name,
            train=tuple(spec["train"]),
            valid=str(spec["valid"]),
            xi=float(details["models"][name]["best_xi"]),
        )
        for name, spec in details["folds"].items()
    ]


class ScoreMatrixModel:
    def __init__(self, xi: float = DEFAULT_XI, refit_days: int = REFIT_DAYS) -> None:
        self.xi = xi
        self.refit_days = refit_days

    def _model(self) -> DixonColesModel:
        return DixonColesModel(
            xi=self.xi, target="xg", refit_days=self.refit_days, max_goals=MAX_GOALS
        )

    def walk_forward(self, history: pd.DataFrame, targets: pd.DataFrame) -> np.ndarray:
        """Matrices ``(n, 11, 11)`` for ``targets`` (one league or several).

        Only ``history`` rows dated before the first target are given to ``fit``; later target
        rows become history block by block as their dates pass."""
        if targets.empty:
            return np.zeros((0, MAX_GOALS + 1, MAX_GOALS + 1))
        targets = targets.reset_index(drop=True)  # the model indexes rows by position
        start = targets["date"].min()
        model = self._model().fit(history[history["date"] < start])
        matrix = model.predict_goal_matrix(targets)
        return np.asarray(matrix)

    def fixture_matrix(
        self,
        history: pd.DataFrame,
        league: str,
        home_team: str,
        away_team: str,
        match_date: pd.Timestamp | str,
    ) -> np.ndarray:
        """Matrix ``(11, 11)`` of one (usually upcoming) fixture, fitted on matches before it."""
        day = pd.Timestamp(match_date).normalize()
        past = history[(history["league"] == league) & (history["date"] < day)]
        if past.empty:
            raise MissingHistoryError(f"no {league} history before {day.date()}")
        teams = set(past["home_team"]) | set(past["away_team"])
        missing = sorted({home_team, away_team} - teams)
        if missing:
            raise MissingHistoryError(f"no {league} history for {missing}")
        fixture = pd.DataFrame(
            [
                {
                    "match_id": f"{league}-{day.date()}-fixture",
                    "league": league,
                    "date": day,
                    "home_team": home_team,
                    "away_team": away_team,
                    "home_goals": np.nan,
                    "away_goals": np.nan,
                    "home_xg": np.nan,
                    "away_xg": np.nan,
                }
            ]
        )
        return self.walk_forward(past, fixture)[0]

    def expected_goals(self, matrix: np.ndarray) -> tuple[float, float]:
        goals = np.arange(matrix.shape[-1])
        return float((matrix.sum(axis=-1) * goals).sum()), float(
            (matrix.sum(axis=-2) * goals).sum()
        )


def validation_matrices(matches: pd.DataFrame, folds: list[FoldSpec]) -> pd.DataFrame:
    """Out-of-sample matrices for the validation season of every fold (F1–F3).

    Returns one row per validation match: ``match_id``, ``fold``, ``league``, ``date`` and
    ``matrix`` (an ``(11, 11)`` array)."""
    rows: list[dict[str, Any]] = []
    for fold in folds:
        train = matches[matches["season"].isin(fold.train)]
        valid = matches[matches["season"] == fold.valid].sort_values(["date", "match_id"])
        if valid.empty:
            continue
        if train["date"].max() >= valid["date"].min():
            raise ValueError(f"{fold.name}: training data overlaps the validation season")
        mats = ScoreMatrixModel(xi=fold.xi).walk_forward(train, valid)
        for (_, match), mat in zip(valid.iterrows(), mats, strict=True):
            rows.append(
                {
                    "match_id": match["match_id"],
                    "fold": fold.name,
                    "league": match["league"],
                    "date": match["date"],
                    "matrix": mat,
                }
            )
    return pd.DataFrame(rows, columns=["match_id", "fold", "league", "date", "matrix"])
