"""Feature pipeline: builds every feature group of `features.yaml` for a set of matches.

Input: matches sorted or not, with the canonical schema. Output: the match metadata needed
for evaluation (never used as features), the target and the feature columns.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
import pandas as pd

from betting_ml.config import FeaturesFile, load_features
from betting_ml.ml.features.elo import EloRatings
from betting_ml.ml.features.form import form_features
from betting_ml.ml.features.market import market_features
from betting_ml.ml.features.schedule import schedule_features
from betting_ml.ml.features.xg import xg_features

TARGET = "target"
RESULT_TO_TARGET = {"H": 0, "D": 1, "A": 2}
META_COLUMNS = [
    "match_id",
    "league",
    "season",
    "date",
    "kickoff_utc",
    "home_team",
    "away_team",
    "result",
    "home_goals",
    "away_goals",
    "home_xg",
    "away_xg",
    "result_awarded",
    "closing_odds_invalid",
]
ODDS_PREFIXES = ("avg", "max", "ps", "b365", "psc", "avgc", "maxc", "b365c")
FORBIDDEN_FEATURE_PATTERNS = (
    "psc_",
    "avgc_",
    "maxc_",
    "b365c_",
    "home_goals",
    "away_goals",
    "home_xg",
    "away_xg",
    "result",
    "target",
)
ALL_GROUPS = ("elo", "form", "xg", "schedule", "market")


class FeaturePipeline:
    def __init__(self, config: FeaturesFile | None = None) -> None:
        self.config = config or load_features()
        self.elo = EloRatings(self.config.elo)

    def transform(self, matches: pd.DataFrame, groups: Sequence[str] = ALL_GROUPS) -> pd.DataFrame:
        unknown = set(groups) - set(ALL_GROUPS)
        if unknown:
            raise ValueError(f"unknown feature groups {sorted(unknown)}")
        df = matches.sort_values(["date", "kickoff_utc", "league", "home_team"], kind="mergesort")
        df = df.reset_index(drop=True)
        parts = [self._meta(df)]
        builders = {
            "elo": lambda: self.elo.transform(df),
            "form": lambda: form_features(df, self.config.form),
            "xg": lambda: xg_features(df, self.config.xg),
            "schedule": lambda: schedule_features(df, self.config.schedule),
            "market": lambda: market_features(df, self.config.market),
        }
        parts += [builders[group]() for group in groups]
        return pd.concat(parts, axis=1)

    @staticmethod
    def _meta(df: pd.DataFrame) -> pd.DataFrame:
        meta = pd.DataFrame(index=df.index)
        for col in META_COLUMNS:
            meta[col] = df[col] if col in df.columns else np.nan
        meta["result_awarded"] = meta["result_awarded"].fillna(False).astype(bool)
        meta["closing_odds_invalid"] = meta["closing_odds_invalid"].fillna(False).astype(bool)
        odds = [c for c in df.columns if c.startswith(tuple(f"{p}_odds_" for p in ODDS_PREFIXES))]
        odds += [c for c in df.columns if c.endswith(("over25", "under25"))]
        meta = pd.concat([meta, df[odds]], axis=1)
        meta[TARGET] = df["result"].map(RESULT_TO_TARGET).astype("Int64")
        return meta

    def feature_columns(self, frame: pd.DataFrame, groups: Sequence[str]) -> list[str]:
        """Feature columns for ``groups`` according to the prefixes in features.yaml."""
        return select_feature_columns(frame.columns, groups, self.config)


def select_feature_columns(
    columns: Sequence[str] | pd.Index, groups: Sequence[str], config: FeaturesFile
) -> list[str]:
    selected: list[str] = []
    for group in groups:
        prefixes = config.groups.get(group)
        if prefixes is None:
            raise ValueError(f"group {group!r} not defined in features.yaml")
        for col in columns:
            if col in selected:
                continue
            if any(col == p or (p.endswith("_") and col.startswith(p)) for p in prefixes):
                selected.append(col)
    bad = [c for c in selected if any(pattern in c for pattern in FORBIDDEN_FEATURE_PATTERNS)]
    if bad:
        raise ValueError(f"forbidden (leaky) feature columns selected: {bad}")
    return selected
