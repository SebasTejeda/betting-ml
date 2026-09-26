"""Expected-goals form: xG for/against, xG difference and "luck" (goals − xG), last N and
EWMA, with league prior for teams with little history."""

from __future__ import annotations

import pandas as pd

from betting_ml.config import RollingConfig
from betting_ml.ml.features.rolling import add_diffs, rolling_block, team_long, to_match_features

XG_STATS: dict[str, tuple[str, str]] = {
    "xgf": ("home_xg", "away_xg"),
    "xga": ("away_xg", "home_xg"),
    "xgd": ("home_xgd", "away_xgd"),
    "luck": ("home_luck", "away_luck"),
}


def _with_derived(matches: pd.DataFrame) -> pd.DataFrame:
    df = matches.copy()
    df["home_xgd"] = df["home_xg"] - df["away_xg"]
    df["away_xgd"] = -df["home_xgd"]
    df["home_luck"] = df["home_goals"] - df["home_xg"]
    df["away_luck"] = df["away_goals"] - df["away_xg"]
    return df


def xg_features(matches: pd.DataFrame, config: RollingConfig | None = None) -> pd.DataFrame:
    config = config or RollingConfig()
    long = team_long(_with_derived(matches), XG_STATS)
    cols = list(XG_STATS)
    overall = rolling_block(long, cols, config, by_venue=False, ewm=True)
    venue = rolling_block(long, ["xgf", "xga"], config, by_venue=True, ewm=False)
    features = pd.concat(
        [
            to_match_features(long, overall, matches.index, "xg"),
            to_match_features(long, venue, matches.index, "xg"),
        ],
        axis=1,
    )
    return add_diffs(features, "xg", ("xgf", "xga", "xgd"))
