"""Use case: our cross-league club Elo (spec 003, T006; replaces ClubElo, see decisions.md).

Gathers every played match: our 5 leagues from football-data (canonical names), the medium
leagues of `configs/elo_leagues.yaml` from openfootball/europe and UCL/UEL from
openfootball/champions-league, runs `ml.models.club_elo` and saves
``data/processed/club_elo_history.parquet``. Ratings only ever use earlier matches, so reading
the played matches of 2025-26 and 2026-27 here evaluates nothing (the European 2025-26 test
keeps its own lock).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import pandas as pd

from betting_ml.domain.ports import EuropeTeamNames, InternationalResultsSource, MatchRepository
from betting_ml.ml.models.club_elo import ClubEloParams, club_key, compute_club_elo

logger = logging.getLogger(__name__)

HISTORY_NAME = "club_elo_history"
LEAGUE_DATASETS = ("matches", "holdout", "current")
COMPETITIONS = ("UCL", "UEL")


@dataclass
class ClubEloResult:
    matches: pd.DataFrame  # every input match with pre-match ratings
    history: pd.DataFrame

    def coverage(self) -> pd.DataFrame:
        return self.matches.groupby(["season", "source"]).size().unstack(fill_value=0).sort_index()


class BuildClubElo:
    def __init__(
        self,
        repository: MatchRepository,
        results: InternationalResultsSource,
        names: EuropeTeamNames,
        catalog: dict[str, Any],
        seasons: list[str],
        params: ClubEloParams | None = None,
    ) -> None:
        self.repository = repository
        self.results = results
        self.names = names
        self.catalog = catalog
        self.seasons = seasons
        self.params = params or ClubEloParams()

    def _our_leagues(self) -> pd.DataFrame:
        countries: dict[str, str] = self.catalog["domestic"]
        frames = [
            self.repository.load(name) for name in LEAGUE_DATASETS if self.repository.exists(name)
        ]
        data = pd.concat(frames, ignore_index=True).dropna(subset=["home_goals", "away_goals"])
        data = data[data["league"].isin(countries)]
        country = data["league"].map(countries)
        return pd.DataFrame(
            {
                "date": pd.to_datetime(data["date"]).dt.normalize(),
                "season": data["season"],
                "home_key": [
                    club_key(c, t) for c, t in zip(country, data["home_team"], strict=True)
                ],
                "away_key": [
                    club_key(c, t) for c, t in zip(country, data["away_team"], strict=True)
                ],
                "home_country": country,
                "away_country": country,
                "home_goals": data["home_goals"].astype(int),
                "away_goals": data["away_goals"].astype(int),
                "domestic": True,
                "source": "football_data",
            }
        )

    def _other_leagues(self) -> pd.DataFrame:
        frames = []
        for entry in self.catalog["openfootball"]:
            for season in self.seasons:
                frame = self.results.fetch_league(
                    entry["folder"], entry["file"], entry["country"], season
                )
                if not frame.empty:
                    frames.append(frame)
        if not frames:
            return pd.DataFrame()
        data = pd.concat(frames, ignore_index=True)
        return pd.DataFrame(
            {
                "date": pd.to_datetime(data["date"]),
                "season": data["season"],
                "home_key": [
                    club_key(c, t)
                    for c, t in zip(data["home_country"], data["home_team"], strict=True)
                ],
                "away_key": [
                    club_key(c, t)
                    for c, t in zip(data["away_country"], data["away_team"], strict=True)
                ],
                "home_country": data["home_country"],
                "away_country": data["away_country"],
                "home_goals": data["home_goals"].astype(int),
                "away_goals": data["away_goals"].astype(int),
                "domestic": True,
                "source": "openfootball_league",
            }
        )

    def _european(self, league_names: dict[str, set[str]]) -> pd.DataFrame:
        frames = [
            self.results.fetch_season(comp, season)
            for comp in COMPETITIONS
            for season in self.seasons
        ]
        frames = [f for f in frames if not f.empty]
        if not frames:
            return pd.DataFrame()
        data = pd.concat(frames, ignore_index=True)
        unknown = self.names.unknown_openfootball(data)
        if unknown is not None:
            raise unknown
        keys: dict[str, list[str]] = {"home": [], "away": []}
        countries: dict[str, list[str]] = {"home": [], "away": []}
        for side in ("home", "away"):
            for name, country in zip(data[f"{side}_team"], data[f"{side}_country"], strict=True):
                team = self.names.from_openfootball(name, country)
                label = team.name
                if not team.domestic:
                    label = self.names.unify_foreign(
                        team.name, team.country, league_names.get(team.country, set())
                    )
                keys[side].append(club_key(team.country, label))
                countries[side].append(team.country)
        return pd.DataFrame(
            {
                "date": pd.to_datetime(data["date"]),
                "season": data["season"],
                "home_key": keys["home"],
                "away_key": keys["away"],
                "home_country": countries["home"],
                "away_country": countries["away"],
                "home_goals": data["home_goals"].astype(int),
                "away_goals": data["away_goals"].astype(int),
                "domestic": False,
                "source": data["competition"].to_numpy(),
            }
        )

    def run(self) -> ClubEloResult:
        ours = self._our_leagues()
        others = self._other_leagues()
        league_names: dict[str, set[str]] = {}
        for frame in (ours, others):
            for side in ("home", "away"):
                if frame.empty:
                    continue
                for key in frame[f"{side}_key"]:
                    country, name = key.split("|", 1)
                    league_names.setdefault(country, set()).add(name)
        europe = self._european(league_names)
        matches = pd.concat([f for f in (ours, others, europe) if not f.empty], ignore_index=True)
        matches = matches.sort_values(["date", "source", "home_key"], kind="mergesort")
        matches = matches.reset_index(drop=True)
        pre, history = compute_club_elo(matches, self.params)
        result = ClubEloResult(pd.concat([matches, pre], axis=1), history)
        self.repository.save(HISTORY_NAME, history)
        self.repository.save("club_elo_matches", result.matches)
        logger.info("Club Elo: %d matches, %d clubs", len(matches), history["key"].nunique())
        return result
