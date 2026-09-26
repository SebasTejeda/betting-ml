"""Elo ratings per league (plan.md §4).

Every feature row stores the ratings *before* the match is played; ratings are updated
afterwards. Between seasons ratings regress towards the league mean and promoted teams start
with the mean rating of the teams relegated the season before.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from betting_ml.config import EloConfig

ELO_COLUMNS = ["elo_home", "elo_away", "elo_diff", "elo_p_home"]


def expected_home_score(elo_home: float, elo_away: float, home_advantage: float) -> float:
    return 1.0 / (1.0 + 10.0 ** (-(elo_home + home_advantage - elo_away) / 400.0))


def margin_multiplier(goal_difference: int) -> float:
    """World Football Elo goal-difference multiplier."""
    gd = abs(goal_difference)
    if gd <= 1:
        return 1.0
    if gd == 2:
        return 1.5
    return (11.0 + gd) / 8.0


@dataclass
class LeagueElo:
    config: EloConfig
    ratings: dict[str, float] = field(default_factory=dict)
    season: str | None = None
    season_teams: set[str] = field(default_factory=set)

    def start_season(self, season: str, teams: set[str]) -> None:
        if self.season is None:
            self.ratings = dict.fromkeys(teams, self.config.initial_rating)
        else:
            relegated = self.season_teams - teams
            promoted = teams - self.season_teams
            survivors = {t: r for t, r in self.ratings.items() if t in teams}
            relegated_ratings = [self.ratings[t] for t in relegated if t in self.ratings]
            mean = float(np.mean(list(self.ratings.values()))) if self.ratings else 0.0
            shrink = self.config.season_regression
            newcomer = float(np.mean(relegated_ratings)) if relegated_ratings else mean
            self.ratings = {t: r - shrink * (r - mean) for t, r in survivors.items()}
            for team in promoted:
                # Teams returning after years away also re-enter as "promoted".
                self.ratings[team] = newcomer - shrink * (newcomer - mean)
        self.season = season
        self.season_teams = set(teams)

    def rating(self, team: str) -> float:
        return self.ratings.get(team, self.config.initial_rating)

    def update(self, home: str, away: str, home_goals: int, away_goals: int) -> None:
        rh, ra = self.rating(home), self.rating(away)
        expected = expected_home_score(rh, ra, self.config.home_advantage)
        score = 1.0 if home_goals > away_goals else 0.5 if home_goals == away_goals else 0.0
        k = self.config.k
        if self.config.margin_multiplier:
            k *= margin_multiplier(home_goals - away_goals)
        delta = k * (score - expected)
        self.ratings[home] = rh + delta
        self.ratings[away] = ra - delta


class EloRatings:
    """Computes pre-match Elo features and keeps the final state for inference."""

    def __init__(self, config: EloConfig | None = None) -> None:
        self.config = config or EloConfig()
        self.leagues: dict[str, LeagueElo] = {}

    def transform(self, matches: pd.DataFrame) -> pd.DataFrame:
        """Return ELO_COLUMNS aligned with ``matches.index``.

        Rows without goals (future fixtures) get features but do not update ratings.
        """
        self.leagues = {}
        order = matches.sort_values(["date", "kickoff_utc"], kind="mergesort").index
        teams_by_season = _teams_by_league_season(matches)
        out = np.full((len(matches), 4), np.nan)
        position = {idx: i for i, idx in enumerate(matches.index)}
        columns = ["league", "season", "home_team", "away_team", "home_goals", "away_goals"]
        rows = matches.loc[order, columns].itertuples()
        for row in rows:
            state = self.leagues.setdefault(row.league, LeagueElo(self.config))
            if state.season != row.season:
                state.start_season(row.season, teams_by_season[(row.league, row.season)])
            rh, ra = state.rating(row.home_team), state.rating(row.away_team)
            p_home = expected_home_score(rh, ra, self.config.home_advantage)
            out[position[row.Index]] = (rh, ra, rh - ra, p_home)
            if not (_missing(row.home_goals) or _missing(row.away_goals)):
                state.update(row.home_team, row.away_team, int(row.home_goals), int(row.away_goals))
        return pd.DataFrame(out, index=matches.index, columns=ELO_COLUMNS)

    def current_ratings(self, league: str) -> dict[str, float]:
        state = self.leagues.get(league)
        return dict(state.ratings) if state else {}


def _missing(value: object) -> bool:
    return value is None or (isinstance(value, float) and math.isnan(value))


def _teams_by_league_season(matches: pd.DataFrame) -> dict[tuple[str, str], set[str]]:
    teams: dict[tuple[str, str], set[str]] = {}
    for (league, season), group in matches.groupby(["league", "season"]):
        teams[(str(league), str(season))] = set(group["home_team"]) | set(group["away_team"])
    return teams
