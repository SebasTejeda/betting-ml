"""Cross-league club Elo (spec 003, T006): our replacement for ClubElo (see decisions.md).

One rating per club for every league and European competition, processed in date order with
the spec 001 parameters (K = 20, home advantage 60, World Football Elo margin multiplier).
Leagues only learn their relative strength through European matches. Each league season has
a fixed *base*, computed once at its first match: the mean rating of the clubs of that country
active in the previous ``active_days`` (or, after a gap without data, of every club of that
country that ever played its league). Between seasons a club regresses 1/3 towards that base
(not towards 1500, which would erase the gap between leagues); a club new to a league starts at
base − 50 (promoted). A league seen for the first time has no base: its new clubs all start at
the same initial rating (no cascade inside the first matchday).

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
# Extra columns of our snapshots (not in ClubElo): rated matches in the previous
# ``recent_days``, date of the last rated match and of the last LEAGUE match (a club whose
# league file stops keeps playing in Europe with a frozen league component), for T006.
EXTRA_COLUMNS = ["recent", "last_match", "last_league_match"]
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
    active_days: int = 400  # clubs counted in a league's base at the start of its season
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
    season_base: dict[tuple[str, str], float | None] = {}
    recent: dict[str, deque[pd.Timestamp]] = defaultdict(deque)
    pre = pd.DataFrame(
        index=matches.index,
        columns=["home_elo", "away_elo", "home_recent", "away_recent"],
        dtype=float,
    )
    history: list[tuple[pd.Timestamp, str, str, str, float, bool]] = []

    def base_of(country: str, season: str, day: pd.Timestamp) -> float | None:
        """Fixed for the whole league season (computed at its first match)."""
        if (country, season) not in season_base:
            horizon = day - pd.Timedelta(days=p.active_days)
            league = [k for k in last_league_day if country_of[k] == country]
            active = [rating[k] for k in league if last_league_day[k] >= horizon]
            members = active or [rating[k] for k in league]
            season_base[(country, season)] = float(np.mean(members)) if members else None
        return season_base[(country, season)]

    def enter_league(key: str, country: str, season: str, day: pd.Timestamp) -> None:
        if last_season.get(key) == season:
            return
        base = base_of(country, season, day)
        if key not in rating:
            rating[key] = p.initial if base is None else base - p.promoted_offset
        elif base is not None:
            rating[key] += p.season_regression * (base - rating[key])
        last_season[key] = season

    for idx in order:
        row = matches.loc[idx]
        day = pd.Timestamp(row["date"])
        home, away = str(row["home_key"]), str(row["away_key"])
        country_of[home] = str(row["home_country"])
        country_of[away] = str(row["away_country"])
        season = str(row["season"])
        if bool(row["domestic"]):
            base_of(country_of[home], season, day)  # fixed before any club of the match enters
            for key in (home, away):
                enter_league(key, country_of[key], season, day)
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
            history.append((day, key, country_of[key], season, rating[key], bool(row["domestic"])))

    hist = pd.DataFrame(history, columns=["date", "key", "country", "season", "elo", "domestic"])
    return pre, hist


def snapshot(
    history: pd.DataFrame, day: pd.Timestamp | str, recent_days: int = 365
) -> pd.DataFrame:
    """Ratings valid on ``day`` (matches strictly before it), in ClubElo's schema plus
    `EXTRA_COLUMNS`.

    ``level`` is 1 for the clubs of the latest league season of their country seen before
    ``day`` (every league in the catalog is a top flight; relegated clubs drop out as soon as
    the new season starts), missing otherwise."""
    day = pd.Timestamp(day).normalize()
    past = history[history["date"] < day]
    if past.empty:
        return pd.DataFrame(columns=SNAPSHOT_COLUMNS + EXTRA_COLUMNS)
    last = past.groupby("key", sort=True).last()
    league = past[past["domestic"]]
    latest = league.groupby("country")["season"].max()
    in_latest = league[league["season"] == league["country"].map(latest)]
    active = set(in_latest["key"])
    window = past[past["date"] >= day - pd.Timedelta(days=recent_days)]
    recent = window.groupby("key").size()
    last_match = past.groupby("key")["date"].max()
    last_league_match = league.groupby("key")["date"].max()
    out = pd.DataFrame(
        {
            "club": [k.split("|", 1)[1] for k in last.index],
            "country": last["country"].to_numpy(),
            "level": pd.array([1 if k in active else pd.NA for k in last.index], dtype="Int64"),
            "elo": last["elo"].to_numpy(dtype=float),
            "valid_from": pd.NaT,
            "valid_to": pd.NaT,
            "recent": recent.reindex(last.index, fill_value=0).to_numpy(dtype=int),
            "last_match": last_match.reindex(last.index).to_numpy(),
            "last_league_match": last_league_match.reindex(last.index).to_numpy(),
        },
        columns=SNAPSHOT_COLUMNS + EXTRA_COLUMNS,
    )
    return out.reset_index(drop=True)
