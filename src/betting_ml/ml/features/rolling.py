"""Shared machinery for per-team rolling features with a league prior.

Anti-leakage rules (plan.md §4, decisions.md T012):
- team aggregates use ``shift(1)``: only matches strictly before the current one;
- league priors use matches with ``date < d`` (kickoff times are imputed in old seasons, so
  same-day order is unknown).
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
import pandas as pd

from betting_ml.config import RollingConfig

ROLES = ("home", "away")


def team_long(matches: pd.DataFrame, stats: dict[str, tuple[str, str]]) -> pd.DataFrame:
    """One row per team and match.

    ``stats`` maps an output name to ``(column for the home team, column for the away team)``.
    """
    frames = []
    for role in ROLES:
        part = pd.DataFrame(
            {
                "_idx": matches.index,
                "league": matches["league"].to_numpy(),
                "date": matches["date"].to_numpy(),
                "team": matches[f"{role}_team"].to_numpy(),
                "is_home": role == "home",
            }
        )
        for name, (home_col, away_col) in stats.items():
            source = home_col if role == "home" else away_col
            part[name] = matches[source].to_numpy(dtype=float)
        frames.append(part)
    long = pd.concat(frames, ignore_index=True)
    return long.sort_values(["team", "date", "is_home"], kind="mergesort").reset_index(drop=True)


def league_prior(long: pd.DataFrame, cols: Sequence[str], by_venue: bool) -> pd.DataFrame:
    """Mean of each stat over all team-matches of the league with ``date < d``."""
    keys = ["league", "is_home"] if by_venue else ["league"]
    valid = long[[*keys, "date", *cols]]
    sums = valid.groupby([*keys, "date"])[list(cols)].sum(min_count=1).fillna(0.0)
    counts = valid.groupby([*keys, "date"])[list(cols)].count()
    cum_sums = sums.groupby(level=keys).cumsum() - sums
    cum_counts = counts.groupby(level=keys).cumsum() - counts
    prior = cum_sums / cum_counts.replace(0, np.nan)
    return (
        long[[*keys, "date"]]
        .merge(prior.reset_index(), on=[*keys, "date"], how="left")[list(cols)]
        .set_axis(long.index)
    )


def _shrink(values: pd.Series, n_prev: pd.Series, prior: pd.Series, min_matches: int) -> pd.Series:
    """Blend with the league prior when fewer than ``min_matches`` previous matches exist."""
    n = n_prev.clip(upper=min_matches).astype(float)
    blended = (n * values.fillna(0.0) + (min_matches - n) * prior) / min_matches
    return values.where(n_prev >= min_matches, blended)


def rolling_block(
    long: pd.DataFrame,
    cols: Sequence[str],
    config: RollingConfig,
    by_venue: bool,
    ewm: bool,
) -> pd.DataFrame:
    """Rolling means (and EWMA) of ``cols`` over each team's previous matches."""
    keys = ["team", "is_home"] if by_venue else ["team"]
    groups = [long[k] for k in keys]
    shifted = long.groupby(keys)[list(cols)].shift(1)
    n_prev = long.groupby(keys).cumcount()
    prior = league_prior(long, cols, by_venue)
    kind = "venue_" if by_venue else ""
    out: dict[str, pd.Series] = {}
    for window in config.windows:
        rolled = shifted.groupby(groups).rolling(window, min_periods=1).mean()
        rolled = rolled.reset_index(level=list(range(len(keys))), drop=True).sort_index()
        for col in cols:
            out[f"{col}|{kind}last{window}"] = _shrink(
                rolled[col], n_prev, prior[col], config.min_matches_for_prior
            )
    if ewm:
        smoothed = shifted.groupby(groups).ewm(alpha=config.ewma_alpha, ignore_na=True).mean()
        smoothed = smoothed.reset_index(level=list(range(len(keys))), drop=True).sort_index()
        for col in cols:
            out[f"{col}|{kind}ewm"] = _shrink(
                smoothed[col], n_prev, prior[col], config.min_matches_for_prior
            )
    return pd.DataFrame(out, index=long.index)


def to_match_features(
    long: pd.DataFrame, block: pd.DataFrame, matches_index: pd.Index, prefix: str
) -> pd.DataFrame:
    """Pivot team-level features back to one row per match: ``{prefix}_{stat}_{role}_{kind}``.

    Venue features of the home team are computed over its home matches and those of the away
    team over its away matches (``is_home`` is part of the rolling key)."""
    columns: dict[str, pd.Series] = {}
    for role in ROLES:
        mask = long["is_home"] == (role == "home")
        part = block[mask].set_index(long.loc[mask, "_idx"])
        for col in block.columns:
            stat, _, kind = col.partition("|")
            columns[f"{prefix}_{stat}_{role}_{kind}"] = part[col].reindex(matches_index)
    return pd.DataFrame(columns, index=matches_index)


def add_diffs(features: pd.DataFrame, prefix: str, stats: Sequence[str]) -> pd.DataFrame:
    """``{prefix}_{stat}_diff_{window}`` = home minus away for non-venue features."""
    out = features.copy()
    for col in features.columns:
        if not col.startswith(f"{prefix}_") or "_home_" not in col or "_venue" in col:
            continue
        stat = col[len(prefix) + 1 :].split("_home_")[0]
        if stat not in stats:
            continue
        away_col = col.replace("_home_", "_away_")
        if away_col in features.columns:
            window = col.split("_home_")[1]
            out[f"{prefix}_{stat}_diff_{window}"] = features[col] - features[away_col]
    return out
