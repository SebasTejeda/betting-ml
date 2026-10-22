"""Cross-league club Elo (spec 003, T006): our replacement for ClubElo (see decisions.md).

One rating per club for every league and European competition, processed in date order with
the spec 001 parameters (K = 20, home advantage 60, World Football Elo margin multiplier).
Leagues only learn their relative strength through European matches. Between seasons a club
regresses 1/3 towards the mean of **its own league** (not towards 1500, which would erase the
gap between leagues); a club new to a league starts at that league's mean − 50 (promoted).

No leakage by construction: ``pre`` holds the ratings before each match, and a snapshot of
day ``d`` only contains matches dated strictly before ``d``.
"""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass

import numpy as np
import pandas as pd

from betting_ml.ml.features.elo import expected_home_score, margin_multiplier

SNAPSHOT_COLUMNS = ["club", "country", "level", "elo", "valid_from", "valid_to"]
INPUT_COLUMNS = [
    "date",
    "season",
    "home_key",
    "away_key",
    "home_country",
    "away_country",
    "home_goals",
    "away_goals",
    "domestic",
]


@dataclass(frozen=True)
class ClubEloParams:
    initial: float = 1500.0
    k: float = 20.0
    home_advantage: float = 60.0
    margin: bool = True
    season_regression: float = 1 / 3
    promoted_offset: float = 50.0
    active_days: int = 400  # a club is "level 1" if it played a league match this recently
    recent_days: int = 365  # window to count each club's rated matches


def club_key(country: str, name: str) -> str:
    return f"{country}|{name}"


def compute_club_elo(
    matches: pd.DataFrame, params: ClubEloParams | None = None
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Run the Elo over every match.

    ``matches`` needs `INPUT_COLUMNS` (``domestic`` = league match of the club's own country).
    Returns ``pre`` (aligned with ``matches``: ``home_elo``, ``away_elo`` before the match and
    ``home_recent``/``away_recent``, the rated matches of each club in the previous
    ``recent_days``) and ``history`` (one row per club and match: rating after it)."""
    p = params or ClubEloParams()
    missing = set(INPUT_COLUMNS) - set(matches.columns)
    if missing:
        raise ValueError(f"missing columns {sorted(missing)}")
    order = matches.sort_values("date", kind="mergesort").index
    rating: dict[str, float] = {}
    country_of: dict[str, str] = {}
    last_season: dict[str, str] = {}
    last_league_day: dict[str, pd.Timestamp] = {}
    recent: dict[str, deque[pd.Timestamp]] = defaultdict(deque)
    pre = pd.DataFrame(
        index=matches.index,
        columns=["home_elo", "away_elo", "home_recent", "away_recent"],
        dtype=float,
    )
    history: list[tuple[pd.Timestamp, str, str, float, bool]] = []

    def league_mean(country: str, day: pd.Timestamp) -> float | None:
        horizon = day - pd.Timedelta(days=p.active_days)
        members = [
            rating[k]
            for k, last in last_league_day.items()
            if country_of[k] == country and last >= horizon and k in rating
        ]
        return float(np.mean(members)) if members else None

    def enter_league(key: str, country: str, season: str, day: pd.Timestamp) -> None:
        if last_season.get(key) == season:
            return
        mean = league_mean(country, day)
        if key not in rating:
            rating[key] = p.initial if mean is None else mean - p.promoted_offset
        elif mean is not None:
            rating[key] += p.season_regression * (mean - rating[key])
        last_season[key] = season

    for idx in order:
        row = matches.loc[idx]
        day = pd.Timestamp(row["date"])
        home, away = str(row["home_key"]), str(row["away_key"])
        country_of[home] = str(row["home_country"])
        country_of[away] = str(row["away_country"])
        if bool(row["domestic"]):
            for key in (home, away):
                enter_league(key, country_of[key], str(row["season"]), day)
        for key in (home, away):
            rating.setdefault(key, p.initial)
            window = recent[key]
            while window and window[0] < day - pd.Timedelta(days=p.recent_days):
                window.popleft()
        rh, ra = rating[home], rating[away]
        pre.loc[idx] = [rh, ra, len(recent[home]), len(recent[away])]

        hg, ag = int(row["home_goals"]), int(row["away_goals"])
        actual = 1.0 if hg > ag else 0.5 if hg == ag else 0.0
        expected = expected_home_score(rh, ra, p.home_advantage)
        k = p.k * (margin_multiplier(hg - ag) if p.margin else 1.0)
        delta = k * (actual - expected)
        rating[home], rating[away] = rh + delta, ra - delta
        for key in (home, away):
            recent[key].append(day)
            if bool(row["domestic"]):
                last_league_day[key] = day
            history.append((day, key, country_of[key], rating[key], bool(row["domestic"])))

    hist = pd.DataFrame(history, columns=["date", "key", "country", "elo", "domestic"])
    return pre, hist


def snapshot(
    history: pd.DataFrame, day: pd.Timestamp | str, active_days: int = 400
) -> pd.DataFrame:
    """Ratings valid on ``day`` (matches strictly before it), in ClubElo's schema.

    ``level`` is 1 for clubs that played a league match in the previous ``active_days``
    (every league in the catalog is a top flight), missing otherwise."""
    day = pd.Timestamp(day).normalize()
    past = history[history["date"] < day]
    if past.empty:
        return pd.DataFrame(columns=SNAPSHOT_COLUMNS)
    last = past.groupby("key", sort=True).last()
    league_days = past[past["domestic"]].groupby("key")["date"].max()
    active = league_days[league_days >= day - pd.Timedelta(days=active_days)].index
    out = pd.DataFrame(
        {
            "club": [k.split("|", 1)[1] for k in last.index],
            "country": last["country"].to_numpy(),
            "level": pd.array([1 if k in active else pd.NA for k in last.index], dtype="Int64"),
            "elo": last["elo"].to_numpy(dtype=float),
            "valid_from": pd.NaT,
            "valid_to": pd.NaT,
        },
        columns=SNAPSHOT_COLUMNS,
    )
    return out.reset_index(drop=True)
