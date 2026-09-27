"""The Odds API adapter (spec 002, US2): client with credit accounting and mapping of events
to canonical match ids. The API key only lives in memory (never logged or stored)."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import httpx
import pandas as pd

from betting_ml.adapters.team_names import TeamNameResolver
from betting_ml.domain.entities import Outcome, make_match_id
from betting_ml.domain.journal import OddsQuote

logger = logging.getLogger(__name__)
BASE_URL = "https://api.the-odds-api.com/v4"
SOURCE = "the_odds_api"


class OddsApiError(RuntimeError):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(f"The Odds API {status}: {message}")
        self.status = status


@dataclass(frozen=True)
class Credits:
    remaining: int | None
    used: int | None
    last: int | None

    @classmethod
    def from_headers(cls, headers: httpx.Headers | dict[str, str]) -> Credits:
        def number(name: str) -> int | None:
            value = headers.get(name)
            try:
                return int(float(value)) if value is not None else None
            except ValueError:
                return None

        return cls(
            number("x-requests-remaining"), number("x-requests-used"), number("x-requests-last")
        )


@dataclass
class OddsResponse:
    events: list[dict[str, Any]]
    credits: Credits


class TheOddsApiClient:
    """Retries only on 5xx / network errors; never on 4xx (they would waste credits)."""

    def __init__(
        self,
        api_key: str,
        regions: str = "eu,uk",
        http: httpx.Client | None = None,
        retries: int = 3,
        backoff_seconds: float = 2.0,
        sleep: Callable[[float], None] = time.sleep,
        base_url: str = BASE_URL,
    ) -> None:
        if not api_key:
            raise ValueError("ODDS_API_KEY is not configured")
        self._api_key = api_key
        self.regions = regions
        self.http = http or httpx.Client(timeout=20.0)
        self.retries = retries
        self.backoff_seconds = backoff_seconds
        self._sleep = sleep
        self.base_url = base_url
        self.last_credits: Credits | None = None

    def __repr__(self) -> str:  # never expose the key
        return f"TheOddsApiClient(regions={self.regions!r})"

    def _get(self, path: str, params: dict[str, str]) -> httpx.Response:
        url = f"{self.base_url}{path}"
        query = {**params, "apiKey": self._api_key}
        last_error: Exception | None = None
        for attempt in range(1, self.retries + 1):
            try:
                response = self.http.get(url, params=query)
            except httpx.HTTPError as exc:  # network / timeout
                last_error = exc
            else:
                self.last_credits = Credits.from_headers(response.headers)
                if response.status_code < 400:
                    return response
                if response.status_code < 500:
                    raise OddsApiError(response.status_code, self._redact(_message(response)))
                last_error = OddsApiError(response.status_code, self._redact(_message(response)))
            logger.warning(
                "The Odds API %s failed (attempt %d): %s", path, attempt, type(last_error).__name__
            )
            if attempt < self.retries:
                self._sleep(self.backoff_seconds * attempt)
        raise OddsApiError(
            503, self._redact(f"{path} failed after {self.retries} attempts: {last_error}")
        )

    def _redact(self, text: str) -> str:
        return text.replace(self._api_key, "***")

    def sports(self) -> list[dict[str, Any]]:
        """List of sports (does not consume credits)."""
        return list(self._get("/sports", {"all": "true"}).json())

    def odds(self, sport_key: str, markets: str = "h2h") -> OddsResponse:
        """Odds of a sport. Costs markets × regions credits."""
        response = self._get(
            f"/sports/{sport_key}/odds",
            {
                "regions": self.regions,
                "markets": markets,
                "oddsFormat": "decimal",
                "dateFormat": "iso",
            },
        )
        return OddsResponse(list(response.json()), Credits.from_headers(response.headers))


def _message(response: httpx.Response) -> str:
    try:
        return str(response.json().get("message", response.text))[:200]
    except ValueError:
        return response.text[:200]


# ---------------------------------------------------------------------- mapping
@dataclass
class MappedOdds:
    quotes: list[OddsQuote] = field(default_factory=list)
    events: int = 0
    unmapped_teams: set[str] = field(default_factory=set)
    unknown_bookmakers: set[str] = field(default_factory=set)


def uk_date(commence: datetime) -> Any:
    """football-data dates are UK local dates: the match id uses the same convention."""
    return pd.Timestamp(commence).tz_convert("Europe/London").date()


def resolve_team(resolver: TeamNameResolver, league: str, name: str) -> str | None:
    """Exact `the_odds_api` alias first, then the lenient lookup across every alias."""
    try:
        return resolver.resolve(league, SOURCE, name)  # type: ignore[arg-type]
    except (ValueError, KeyError):
        return resolver.lookup(league, name)


def map_events(
    events: Iterable[dict[str, Any]],
    league: str,
    resolver: TeamNameResolver,
    known_bookmakers: set[str] | None = None,
) -> MappedOdds:
    """Convert h2h events to canonical quotes. Unmapped teams are reported, never hidden."""
    mapped = MappedOdds()
    for event in events:
        mapped.events += 1
        home_raw, away_raw = event["home_team"], event["away_team"]
        home = resolve_team(resolver, league, home_raw)
        away = resolve_team(resolver, league, away_raw)
        if home is None or away is None:
            mapped.unmapped_teams |= {
                f"{league}/{n}" for n, t in ((home_raw, home), (away_raw, away)) if t is None
            }
            continue
        kickoff = datetime.fromisoformat(event["commence_time"].replace("Z", "+00:00")).astimezone(
            UTC
        )
        match_id = make_match_id(league, uk_date(kickoff), home, away)
        for book in event.get("bookmakers", []):
            key = book["key"]
            if known_bookmakers is not None and key not in known_bookmakers:
                mapped.unknown_bookmakers.add(key)
                continue
            for market in book.get("markets", []):
                if market.get("key") != "h2h":
                    continue
                last_update = market.get("last_update") or book.get("last_update")
                updated = (
                    datetime.fromisoformat(last_update.replace("Z", "+00:00")).astimezone(UTC)
                    if last_update
                    else None
                )
                for outcome in market.get("outcomes", []):
                    name = outcome["name"]
                    code = (
                        Outcome.DRAW
                        if name == "Draw"
                        else Outcome.HOME
                        if name == home_raw
                        else Outcome.AWAY
                        if name == away_raw
                        else None
                    )
                    if code is None:
                        continue
                    mapped.quotes.append(
                        OddsQuote(
                            match_id=match_id,
                            league=league,
                            bookmaker=key,
                            outcome=code,
                            odds=float(outcome["price"]),
                            kickoff_utc=kickoff,
                            home_team=home,
                            away_team=away,
                            last_update=updated,
                        )
                    )
    return mapped
