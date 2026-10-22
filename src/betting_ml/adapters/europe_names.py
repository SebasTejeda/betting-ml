"""Team names for European competitions (spec 003, T003).

Clubs of our five leagues must resolve through `configs/team_aliases.yaml` (``openfootball`` and
``clubelo`` aliases): a missing one is an error, as for the other sources. Clubs from other
countries only appear in UCL/UEL matches; they keep their openfootball name and are matched to
ClubElo by a normalized name within their country, with manual fixes in
`configs/europe_aliases.yaml`. Unmatched foreign clubs are reported, never guessed.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

import pandas as pd

from betting_ml.adapters.team_names import TeamNameResolver, UnknownTeamError

LEAGUE_COUNTRY = {"E0": "ENG", "SP1": "ESP", "D1": "GER", "I1": "ITA", "F1": "FRA"}
COUNTRY_LEAGUE = {country: league for league, country in LEAGUE_COUNTRY.items()}
# openfootball country code → country of the league the club plays in (ClubElo's code).
OPENFOOTBALL_COUNTRY_FIX = {"MCO": "FRA"}

_DROP_TOKENS = {
    "ac", "afc", "as", "bc", "bk", "cf", "cd", "club", "de", "do", "fc", "fk", "if", "kv", "nk",
    "pfc", "rc", "rcd", "sc", "sk", "sl", "sv", "ssc", "ss", "us", "vfb", "vfl", "1", "04",
    "1899", "1909", "e", "da", "del", "la", "of", "the",
}  # fmt: skip


def normalize_club(name: str) -> str:
    """Accent-, case- and suffix-insensitive key ("FC Red Bull Salzburg" → "redbullsalzburg")."""
    text = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    tokens = [t for t in re.split(r"[^a-z0-9]+", text) if t and t not in _DROP_TOKENS]
    return "".join(tokens)


@dataclass(frozen=True)
class EuropeanTeam:
    name: str  # canonical name for our leagues, openfootball name otherwise
    league: str  # league code (E0…) for our leagues, country code otherwise
    domestic: bool  # True if the club plays in one of our five leagues

    @property
    def country(self) -> str:
        return LEAGUE_COUNTRY.get(self.league, self.league)


class ClubEloNameError(ValueError):
    pass


class EuropeTeamResolver:
    def __init__(
        self, resolver: TeamNameResolver, overrides: dict[str, dict[str, str]] | None = None
    ) -> None:
        self.resolver = resolver
        self.overrides = overrides or {}

    def from_openfootball(self, name: str, country: str) -> EuropeanTeam:
        country = OPENFOOTBALL_COUNTRY_FIX.get(country, country)
        league = COUNTRY_LEAGUE.get(country)
        if league is None:
            return EuropeanTeam(name, country, domestic=False)
        return EuropeanTeam(
            self.resolver.resolve(league, "openfootball", name), league, domestic=True
        )

    def unknown_openfootball(self, frame: pd.DataFrame) -> UnknownTeamError | None:
        """Every unmapped club of our leagues in a frame of openfootball matches."""
        unknown: dict[tuple[str, str], set[str]] = {}
        for side in ("home", "away"):
            for name, country in zip(frame[f"{side}_team"], frame[f"{side}_country"], strict=True):
                league = COUNTRY_LEAGUE.get(OPENFOOTBALL_COUNTRY_FIX.get(country, country))
                if league and self.resolver.unknown_names(league, "openfootball", [name]):
                    unknown.setdefault((league, "openfootball"), set()).add(name)
        return UnknownTeamError(unknown) if unknown else None

    def clubelo_candidates(self, team: EuropeanTeam) -> list[str]:
        """ClubElo names to try, in order (aliases first, then the canonical name)."""
        if team.domestic:
            aliases = self.resolver.aliases(team.league, team.name, "clubelo")
            return [*aliases, team.name]
        override = self.overrides.get(team.country, {}).get(team.name)
        return [override] if override else []

    def clubelo_name(self, team: EuropeanTeam, ratings: pd.DataFrame) -> str | None:
        """Name of ``team`` in a ClubElo snapshot.

        Raises for clubs of our leagues (aliases must be complete); ``None`` for an unmatched
        foreign club."""
        in_country = ratings.loc[ratings["country"] == team.country, "club"]
        names = set(in_country)
        for candidate in self.clubelo_candidates(team):
            if candidate in names:
                return candidate
        if team.domestic:
            raise ClubEloNameError(
                f"{team.league}/{team.name}: not in ClubElo ({team.country}); "
                "add a `clubelo` alias in team_aliases.yaml"
            )
        key = normalize_club(team.name)
        matches = [club for club in names if normalize_club(club) == key]
        if not matches:
            matches = [
                club
                for club in names
                if len(normalize_club(club)) >= 4
                and (normalize_club(club) in key or key in normalize_club(club))
            ]
        return matches[0] if len(matches) == 1 else None
