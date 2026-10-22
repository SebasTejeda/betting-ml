"""Upcoming matches from football-data's fixtures.csv (updated ~twice a week), cached for
``cache_hours``. Kick-off times are UK local time in the source and converted to UTC."""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from betting_ml.adapters.football_data import _kickoff_utc, _parse_dates, _read_frame
from betting_ml.adapters.http import HttpClient
from betting_ml.adapters.team_names import TeamNameResolver
from betting_ml.domain.entities import Fixture, OddsTriple, fixtures_on, make_match_id

__all__ = ["FootballDataFixtures", "fixtures_on", "parse_fixtures"]

logger = logging.getLogger(__name__)

FIXTURES_URL = "https://www.football-data.co.uk/fixtures.csv"
TIMESTAMP_FORMAT = "%Y%m%dT%H%M%S"


def _odds(row: pd.Series, prefix: str) -> OddsTriple | None:
    values = [row.get(f"{prefix}{side}") for side in ("H", "D", "A")]
    try:
        numbers = [float(v) for v in values]
    except (TypeError, ValueError):
        return None
    if any(np.isnan(n) or n <= 1.01 for n in numbers):
        return None
    return OddsTriple(*numbers)


def parse_fixtures(
    content: bytes, league_codes: dict[str, str], resolver: TeamNameResolver
) -> tuple[list[Fixture], set[str]]:
    """Return the fixtures of the supported leagues and the team names that did not resolve.

    ``league_codes`` maps football-data division codes to our league codes."""
    raw = _read_frame(content)
    raw = raw[raw["Div"].isin(league_codes)].reset_index(drop=True)
    if raw.empty:
        return [], set()
    dates = _parse_dates(raw["Date"])
    kickoffs, _ = _kickoff_utc(dates, raw.get("Time"))
    fixtures, unknown = [], set()
    for i, row in raw.iterrows():
        league = league_codes[row["Div"]]
        home = resolver.unknown_names(league, "football_data", [row["HomeTeam"]])
        away = resolver.unknown_names(league, "football_data", [row["AwayTeam"]])
        if home or away:
            unknown |= {f"{league}/{name}" for name in home | away}
            continue
        home_team = resolver.resolve(league, "football_data", row["HomeTeam"])
        away_team = resolver.resolve(league, "football_data", row["AwayTeam"])
        fixtures.append(
            Fixture(
                match_id=make_match_id(league, dates[i].date(), home_team, away_team),
                league=league,
                kickoff_utc=kickoffs[i].to_pydatetime(),
                home_team=home_team,
                away_team=away_team,
                average_odds=_odds(row, "Avg"),
                best_odds=_odds(row, "Max"),
            )
        )
    if unknown:
        logger.warning("Fixtures with unmapped teams (add them to team_aliases.yaml): %s", unknown)
    return fixtures, unknown


class FootballDataFixtures:
    """Implements `FixtureSource` with a time-based cache in data/raw/fixtures/."""

    def __init__(
        self,
        raw_dir: Path,
        resolver: TeamNameResolver,
        league_codes: dict[str, str],
        cache_hours: float = 6.0,
        http: HttpClient | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        url: str = FIXTURES_URL,
    ) -> None:
        self.dir = raw_dir / "fixtures"
        self.resolver = resolver
        self.league_codes = league_codes
        self.cache_hours = cache_hours
        self.http = http or HttpClient()
        self.clock = clock
        self.url = url
        self.unknown_teams: set[str] = set()
        self.last_update: datetime | None = None

    def _cached(self) -> tuple[Path, datetime] | None:
        files = sorted(self.dir.glob("fixtures_*.csv"))
        if not files:
            return None
        latest = files[-1]
        stamp = datetime.strptime(latest.stem.removeprefix("fixtures_"), TIMESTAMP_FORMAT)
        return latest, stamp.replace(tzinfo=UTC)

    def _download(self) -> Path:
        now = self.clock()
        content = self.http.get(self.url).content
        self.dir.mkdir(parents=True, exist_ok=True)
        path = self.dir / f"fixtures_{now.strftime(TIMESTAMP_FORMAT)}.csv"
        path.write_bytes(content)
        return path

    def fetch_fixtures(self, force_refresh: bool = False) -> list[Fixture]:
        cached = self._cached()
        fresh = cached is not None and self.clock() - cached[1] < timedelta(hours=self.cache_hours)
        if force_refresh or not fresh:
            try:
                path = self._download()
                stamp = self.clock()
            except Exception:
                if cached is None:
                    raise
                logger.exception("fixtures.csv download failed; using the cached copy")
                path, stamp = cached
        else:
            if cached is None:  # pragma: no cover - not downloading means a cached copy exists
                raise RuntimeError("fixtures.csv: no cached copy")
            path, stamp = cached
        self.last_update = stamp
        fixtures, self.unknown_teams = parse_fixtures(
            path.read_bytes(), self.league_codes, self.resolver
        )
        return fixtures
