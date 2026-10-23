"""Team name normalisation with `configs/team_aliases.yaml`.

Canonical names are football-data's (they also appear in `fixtures.csv`, which feeds the API).
Any name that does not resolve is an error: nothing is dropped silently (spec §3).
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable

import pandas as pd

from betting_ml.config import SourceName, TeamAliases
from betting_ml.domain.entities import slugify

SOURCES: tuple[SourceName, ...] = (
    "football_data",
    "understat",
    "the_odds_api",
    "clubelo",
    "openfootball",
)


class UnknownTeamError(ValueError):
    def __init__(self, unknown: dict[tuple[str, str], set[str]]) -> None:
        self.unknown = unknown
        detail = "; ".join(
            f"{league}/{source}: {sorted(names)}" for (league, source), names in unknown.items()
        )
        super().__init__(f"Unmapped team names (add them to team_aliases.yaml): {detail}")


class TeamNameResolver:
    def __init__(self, aliases: TeamAliases) -> None:
        self._exact: dict[tuple[str, str], dict[str, str]] = {}
        self._lenient: dict[str, dict[str, str]] = defaultdict(dict)
        self._teams: dict[str, list[str]] = {}
        for league, teams in aliases.teams.items():
            self._teams[league] = sorted(teams)
            for source in SOURCES:
                self._exact[(league, source)] = self._build_source_map(league, source, teams)
            for canonical, sources in teams.items():
                for name in [canonical, *[a for names in sources.values() for a in names]]:
                    self._lenient[league][slugify(name)] = canonical

    @staticmethod
    def _build_source_map(
        league: str, source: str, teams: dict[str, dict[SourceName, list[str]]]
    ) -> dict[str, str]:
        mapping: dict[str, str] = {}
        for canonical, sources in teams.items():
            for name in [canonical, *sources.get(source, [])]:  # type: ignore[call-overload]
                previous = mapping.get(name)
                if previous is not None and previous != canonical:
                    raise ValueError(
                        f"alias {name!r} maps to {previous!r} and {canonical!r} "
                        f"in {league}/{source}"
                    )
                mapping[name] = canonical
        return mapping

    @property
    def leagues(self) -> list[str]:
        return sorted(self._teams)

    def teams(self, league: str) -> list[str]:
        return list(self._teams.get(league, []))

    def resolve(self, league: str, source: SourceName, name: str) -> str:
        canonical = self._exact.get((league, source), {}).get(name)
        if canonical is None:
            raise UnknownTeamError({(league, source): {name}})
        return canonical

    def unknown_names(self, league: str, source: SourceName, names: Iterable[str]) -> set[str]:
        mapping = self._exact.get((league, source), {})
        return {name for name in names if name not in mapping}

    def canonicalize(self, frame: pd.DataFrame, source: SourceName) -> pd.DataFrame:
        """Return a copy of ``frame`` with canonical ``home_team``/``away_team``.

        Raises `UnknownTeamError` listing every unmapped name (per league)."""
        unknown: dict[tuple[str, str], set[str]] = {}
        for league, group in frame.groupby("league"):
            names = set(group["home_team"]) | set(group["away_team"])
            missing = self.unknown_names(str(league), source, names)
            if missing:
                unknown[(str(league), source)] = missing
        if unknown:
            raise UnknownTeamError(unknown)
        out = frame.copy()
        for column in ("home_team", "away_team"):
            out[column] = [
                self._exact[(league, source)][name]
                for league, name in zip(out["league"], out[column], strict=True)
            ]
        return out

    def aliases(self, league: str, canonical: str, source: SourceName) -> list[str]:
        """Aliases of a canonical team for one source (excluding the canonical name)."""
        mapping = self._exact.get((league, source), {})
        return [name for name, team in mapping.items() if team == canonical and name != canonical]

    def lookup(self, league: str, name: str) -> str | None:
        """Lenient lookup for user input (any alias, case/punctuation-insensitive)."""
        return self._lenient.get(league, {}).get(slugify(name))
