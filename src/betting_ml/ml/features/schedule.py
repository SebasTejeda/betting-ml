"""Schedule features: rest days, matchday and congestion (league matches only)."""

from __future__ import annotations

import pandas as pd

from betting_ml.config import ScheduleConfig
from betting_ml.ml.features.rolling import ROLES

MAX_REST_DAYS = 21.0


def schedule_features(matches: pd.DataFrame, config: ScheduleConfig | None = None) -> pd.DataFrame:
    """Only uses dates of the schedule (known in advance), never results."""
    config = config or ScheduleConfig()
    frames = []
    for role in ROLES:
        frames.append(
            pd.DataFrame(
                {
                    "_idx": matches.index,
                    "team": matches[f"{role}_team"].to_numpy(),
                    "season": matches["season"].to_numpy(),
                    "date": matches["date"].to_numpy(),
                    "role": role,
                }
            )
        )
    long = pd.concat(frames, ignore_index=True).sort_values(["team", "date"], kind="mergesort")
    by_team = long.groupby("team")["date"]
    rest = (long["date"] - by_team.shift(1)).dt.days.astype(float)
    long["rest"] = rest.clip(upper=MAX_REST_DAYS).fillna(MAX_REST_DAYS)
    long["matchday"] = long.groupby(["team", "season"]).cumcount() + 1
    window = pd.Timedelta(days=config.congestion_days)
    counts = []
    for _, group in long.groupby("team", sort=False):
        dates = group["date"].to_numpy()
        starts = dates - window.to_timedelta64()
        left = dates.searchsorted(starts, side="left")
        right = dates.searchsorted(dates, side="left")  # excludes the current match
        counts.append(pd.Series(right - left, index=group.index))
    long["congestion"] = pd.concat(counts)
    out = pd.DataFrame(index=matches.index)
    for role in ROLES:
        part = long[long["role"] == role].set_index("_idx")
        out[f"sched_rest_{role}"] = part["rest"].reindex(matches.index)
        out[f"sched_matchday_{role}"] = part["matchday"].reindex(matches.index).astype(float)
        out[f"sched_n{config.congestion_days}_{role}"] = (
            part["congestion"].reindex(matches.index).astype(float)
        )
    out["sched_rest_diff"] = out["sched_rest_home"] - out["sched_rest_away"]
    return out
