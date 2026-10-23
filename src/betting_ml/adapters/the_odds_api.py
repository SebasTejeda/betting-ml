"""The Odds API adapter (spec 002, US2): client with credit accounting and mapping of events
to canonical match ids. The API key only lives in memory (never logged or stored)."""

from __future__ import annotations

import json
import logging
import math
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
from betting_ml.domain.ports import OddsSourceNotConfiguredError

logger = logging.getLogger(__name__)
# httpx logs full URLs at INFO, and the API key travels in the query string.
logging.getLogger("httpx").setLevel(logging.WARNING)
BASE_URL = "https://api.the-odds-api.com/v4"
SOURCE = "the_odds_api"
# A league's odds are ~0.1-1 MB; bigger answers are refused (spec 004, integration I07).
MAX_RESPONSE_BYTES = 5 * 1024 * 1024
RESPONSE_DEADLINE_SECONDS = 60.0


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
        max_bytes: int = MAX_RESPONSE_BYTES,
        deadline_seconds: float = RESPONSE_DEADLINE_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if not api_key:
            raise OddsSourceNotConfiguredError("ODDS_API_KEY is not configured")
        self._api_key = api_key
        self.regions = regions
        self.http = http or httpx.Client(timeout=20.0)
        self.retries = retries
        self.backoff_seconds = backoff_seconds
        self._sleep = sleep
        self.base_url = base_url
        self.max_bytes = max_bytes
        self.deadline_seconds = deadline_seconds
        self._clock = clock
        self.last_credits: Credits | None = None

    def __repr__(self) -> str:  # never expose the key
        return f"TheOddsApiClient(regions={self.regions!r})"

    def _get(self, path: str, params: dict[str, str], retries: int | None = None) -> httpx.Response:
        url = f"{self.base_url}{path}"
        query = {**params, "apiKey": self._api_key}
        retries = self.retries if retries is None else retries
        last_error: Exception | None = None
        for attempt in range(1, retries + 1):
            try:
                response = self._bounded_get(path, url, query)
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
            if attempt < retries:
                self._sleep(self.backoff_seconds * attempt)
        raise OddsApiError(
            503, self._redact(f"{path} failed after {retries} attempts: {last_error}")
        )

    def _bounded_get(self, path: str, url: str, query: dict[str, str]) -> httpx.Response:
        """The whole answer, read in chunks: too large or too slow is refused, never retried
        (and never cached). ``path`` names it in errors; the URL carries the key."""
        with self.http.stream("GET", url, params=query) as streamed:
            declared = streamed.headers.get("content-length")
            if declared is not None and declared.isdigit() and int(declared) > self.max_bytes:
                raise OddsApiError(
                    502, f"{path}: {declared} bytes declared, limit {self.max_bytes}"
                )
            started = self._clock()
            body = bytearray()
            for chunk in streamed.iter_bytes():
                body += chunk
                if len(body) > self.max_bytes:
                    raise OddsApiError(502, f"{path}: more than {self.max_bytes} bytes")
                if self._clock() - started > self.deadline_seconds:
                    raise OddsApiError(
                        502, f"{path}: answer not complete after {self.deadline_seconds}s"
                    )
            # iter_bytes already decoded the body (counted decoded: a gzip bomb stops too)
            headers = [
                (name, value)
                for name, value in streamed.headers.items()
                if name.lower() not in {"content-encoding", "content-length", "transfer-encoding"}
            ]
            return httpx.Response(
                streamed.status_code,
                headers=headers,
                content=bytes(body),
                request=streamed.request,
            )

    def _redact(self, text: str) -> str:
        return text.replace(self._api_key, "***")

    def _json(self, response: httpx.Response) -> Any:
        """The body without the key, should the API ever echo it (it is cached as is)."""
        return json.loads(self._redact(response.text))

    def sports(self) -> list[dict[str, Any]]:
        """List of sports (does not consume credits)."""
        return list(self._json(self._get("/sports", {"all": "true"})))

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
        return OddsResponse(list(self._json(response)), Credits.from_headers(response.headers))

    def events(self, sport_key: str) -> list[dict[str, Any]]:
        """Upcoming events of a sport (does not consume credits; spec 003)."""
        return list(self._json(self._get(f"/sports/{sport_key}/events", {"dateFormat": "iso"})))

    def event_odds(self, sport_key: str, event_id: str, markets: list[str]) -> OddsResponse:
        """Odds of one event for several markets (spec 003). Costs `estimate_event_cost`.

        Never retried (integration I08): a failed answer may already have been charged, and a
        refresh takes a single slot of the hourly quota, so it spends at most one estimate."""
        response = self._get(
            f"/sports/{sport_key}/events/{event_id}/odds",
            {
                "regions": self.regions,
                "markets": ",".join(markets),
                "oddsFormat": "decimal",
                "dateFormat": "iso",
            },
            retries=1,
        )
        return OddsResponse([self._json(response)], Credits.from_headers(response.headers))


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
    invalid_prices: int = 0  # prices that are not odds (≤ 1, not a number): skipped


def _price(raw: Any) -> float | None:
    """Decimal odds or None: the database rejects odds ≤ 1 (spec 003, US5)."""
    try:
        price = float(raw)
    except (TypeError, ValueError):
        return None
    return price if math.isfinite(price) and price > 1 else None


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
                    price = _price(outcome.get("price"))
                    if price is None:
                        mapped.invalid_prices += 1
                        continue
                    mapped.quotes.append(
                        OddsQuote(
                            match_id=match_id,
                            league=league,
                            bookmaker=key,
                            outcome=code,
                            odds=price,
                            kickoff_utc=kickoff,
                            home_team=home,
                            away_team=away,
                            last_update=updated,
                        )
                    )
    if mapped.invalid_prices:
        logger.warning("%s: %d invalid prices skipped", league, mapped.invalid_prices)
    return mapped


# ---------------------------------------------------------------------- spec 003: event odds
# Market keys of The Odds API for the catalog markets (configs/markets.yaml). The response
# format below follows the v4 documentation; it must be checked against a recorded real
# response with the pending T004 call (decisions.md).
EVENT_SPORT_KEYS = {"UCL": "soccer_uefa_champs_league", "UEL": "soccer_uefa_europa_league"}


def estimate_event_cost(markets: list[str], regions: str) -> int:
    """Credits of one event-odds request: unique markets × regions (v4 pricing)."""
    return len(set(markets)) * len([r for r in regions.split(",") if r.strip()])


def _event_selection(
    market: str, outcome: dict[str, Any], home: str, away: str
) -> tuple[str, str, float | None] | None:
    name = str(outcome.get("name", ""))
    point = outcome.get("point")
    line = float(point) if point is not None else None
    low = name.lower()
    if market == "h2h":
        side = {home: "home", away: "away"}.get(name) or ("draw" if low == "draw" else None)
        return ("h2h", side, None) if side else None
    if market == "totals" and low in ("over", "under") and line is not None:
        return ("totals", low, line)
    if market == "btts" and low in ("yes", "no"):
        return ("btts", low, None)
    if market == "team_totals" and low in ("over", "under") and line is not None:
        team = {home: "home", away: "away"}.get(str(outcome.get("description", "")))
        return ("team_totals", f"{team}_{low}", line) if team else None
    if market == "draw_no_bet":
        side = {home: "home", away: "away"}.get(name)
        return ("draw_no_bet", side, None) if side else None
    if market == "double_chance":
        has_home, has_away, has_draw = home in name, away in name, "draw" in low
        if has_home and has_draw:
            return ("double_chance", "1X", None)
        if has_away and has_draw:
            return ("double_chance", "X2", None)
        if has_home and has_away:
            return ("double_chance", "12", None)
    return None


def parse_event_prices(
    event: dict[str, Any],
    accessible: set[str],
    commissions: dict[str, float],
) -> dict[tuple[str, str, float | None], tuple[float, str]]:
    """Best accessible price per (market, selection, line) of one event (exchanges net of
    commission). Unknown markets or outcomes are ignored."""
    home, away = str(event.get("home_team", "")), str(event.get("away_team", ""))
    best: dict[tuple[str, str, float | None], tuple[float, str]] = {}
    for book in event.get("bookmakers", []):
        key = str(book.get("key", ""))
        if key not in accessible:
            continue
        commission = commissions.get(key, 0.0)
        for market in book.get("markets", []):
            for outcome in market.get("outcomes", []):
                selection = _event_selection(str(market.get("key", "")), outcome, home, away)
                price = outcome.get("price")
                if selection is None or price is None or float(price) <= 1.0:
                    continue
                net = 1.0 + (float(price) - 1.0) * (1.0 - commission)
                if selection not in best or net > best[selection][0]:
                    best[selection] = (net, key)
    return best
