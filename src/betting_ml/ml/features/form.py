"""Recent form: goals, points, shots and shots on target (last N and EWMA), overall and by
venue, shrunk towards the league prior when a team has fewer than 3 previous matches."""

from __future__ import annotations

import numpy as np
import pandas as pd

from betting_ml.config import RollingConfig
from betting_ml.ml.features.rolling import add_diffs, rolling_block, team_long, to_match_features

FORM_STATS: dict[str, tuple[str, str]] = {
    "gf": ("home_goals", "away_goals"),
    "ga": ("away_goals", "home_goals"),
    "pts": ("home_points", "away_points"),
    "sh": ("home_shots", "away_shots"),
    "sha": ("away_shots", "home_shots"),
    "sot": ("home_sot", "away_sot"),
    "sota": ("away_sot", "home_sot"),
}
DIFF_STATS = ("gf", "ga", "pts", "sot")


def _with_points(matches: pd.DataFrame) -> pd.DataFrame:
    df = matches.copy()
    hg, ag = df["home_goals"].astype(float), df["away_goals"].astype(float)
    df["home_points"] = np.select([hg > ag, hg == ag], [3.0, 1.0], default=0.0)
    df["away_points"] = np.select([ag > hg, hg == ag], [3.0, 1.0], default=0.0)
    unplayed = hg.isna() | ag.isna()
    df.loc[unplayed, ["home_points", "away_points"]] = np.nan
    return df


def form_features(matches: pd.DataFrame, config: RollingConfig | None = None) -> pd.DataFrame:
    config = config or RollingConfig()
    long = team_long(_with_points(matches), FORM_STATS)
    cols = list(FORM_STATS)
    overall = rolling_block(long, cols, config, by_venue=False, ewm=True)
    venue = rolling_block(long, cols, config, by_venue=True, ewm=False)
    features = pd.concat(
        [
            to_match_features(long, overall, matches.index, "form"),
            to_match_features(long, venue, matches.index, "form"),
        ],
        axis=1,
    )
    return add_diffs(features, "form", DIFF_STATS)
