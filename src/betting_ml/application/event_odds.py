"""Use case: odds of the additional markets of one event (spec 003, T014).

Refreshing is an explicit user action with a visible cost: the cost is estimated first
(markets × regions), the spec 002 credit reserve is respected (429 ``ODDS_BUDGET_LOW``) and a
response is cached for 30 minutes, so a second refresh within that window spends nothing. The
raw response is stored without the API key; the analysis reads the latest cached prices.
"""

from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, Protocol

from betting_ml.application.refresh_odds import OddsBudgetLowError

CACHE_MINUTES = 30
PriceKey = tuple[str, str, float | None]
MATCH_ID = re.compile(r"^[A-Z0-9]+-\d{4}-\d{2}-\d{2}-[a-z0-9-]+$")


class InvalidMatchIdError(ValueError):
    pass


class EventOddsClient(Protocol):
    regions: str

    def events(self, sport_key: str) -> list[dict[str, Any]]: ...

    def event_odds(self, sport_key: str, event_id: str, markets: list[str]) -> Any: ...


class EventNotFoundError(LookupError):
    pass


def _norm(name: str) -> str:
    text = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    return "".join(
        t for t in re.split(r"[^a-z0-9]+", text) if t not in {"fc", "cf", "sc", "ac", "afc"}
    )


def same_team(ours: str, theirs: str, aliases: Mapping[str, list[str]] | None = None) -> bool:
    """Our name vs The Odds API's (aliases from team_aliases.yaml, then normalized names)."""
    if aliases and theirs in aliases.get(ours, []):
        return True
    a, b = _norm(ours), _norm(theirs)
    return a == b or (min(len(a), len(b)) >= 4 and (a in b or b in a))


def find_event(
    events: list[dict[str, Any]],
    home: str,
    away: str,
    day: date,
    aliases: Mapping[str, list[str]] | None = None,
) -> dict[str, Any] | None:
    for event in events:
        try:
            start = datetime.fromisoformat(str(event["commence_time"]).replace("Z", "+00:00"))
        except (KeyError, ValueError):
            continue
        if abs((start.date() - day).days) > 1:
            continue
        if same_team(home, str(event.get("home_team", "")), aliases) and same_team(
            away, str(event.get("away_team", "")), aliases
        ):
            return event
    return None


@dataclass(frozen=True)
class CostEstimate:
    markets: int
    regions: int
    estimated_credits: int
    credits_remaining: int | None


@dataclass(frozen=True)
class EventRefresh:
    match_id: str
    markets: list[str]
    credits_used: int
    credits_remaining: int | None
    fetched_at: datetime
    from_cache: bool


class EventOddsService:
    def __init__(
        self,
        client: Callable[[], EventOddsClient],
        cache_dir: Path,
        markets: list[str],
        regions: str,
        sport_key: Callable[[str], str | None],
        parse: Callable[[dict[str, Any]], dict[PriceKey, tuple[float, str]]],
        credits_remaining: Callable[[], int | None],
        min_reserve: int,
        aliases: Mapping[str, list[str]] | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.client = client
        self.cache_dir = cache_dir
        self.markets = markets
        self.regions = regions
        self.sport_key = sport_key
        self.parse = parse
        self.credits_remaining = credits_remaining
        self.min_reserve = min_reserve
        self.aliases = aliases
        self.clock = clock

    def _path(self, match_id: str) -> Path:
        """Cache file of a match; the id is validated so it can never leave ``cache_dir``."""
        if not MATCH_ID.match(match_id):
            raise InvalidMatchIdError(f"match_id inválido: {match_id!r}")
        path = (self.cache_dir / f"{match_id}.json").resolve()
        if path.parent != self.cache_dir.resolve():
            raise InvalidMatchIdError(f"match_id inválido: {match_id!r}")
        return path

    def _cached(self, match_id: str) -> dict[str, Any] | None:
        path = self._path(match_id)
        if not path.exists():
            return None
        return dict(json.loads(path.read_text(encoding="utf-8")))

    def estimate(self) -> CostEstimate:
        regions = len([r for r in self.regions.split(",") if r.strip()])
        markets = len(set(self.markets))
        return CostEstimate(markets, regions, markets * regions, self._remaining())

    def _remaining(self) -> int | None:
        """Credits left: the most recent known value (snapshots of spec 002 or event odds).

        The latest one counts, never the lowest ever seen: after the monthly reset an old cache
        file must not keep blocking refreshes."""
        latest: tuple[str, int] | None = None
        for path in self.cache_dir.glob("*.json") if self.cache_dir.exists() else []:
            data = json.loads(path.read_text(encoding="utf-8"))
            value, at = data.get("credits_remaining"), str(data.get("fetched_at", ""))
            if value is not None and (latest is None or at > latest[0]):
                latest = (at, int(value))
        from_snapshots = self.credits_remaining()
        if latest is None:
            return from_snapshots
        if from_snapshots is None:
            return latest[1]
        # Both known: the snapshot repository has no timestamp here, the event cache does; the
        # event cache is newer only if it was written in the current month.
        if latest[0][:7] == self.clock().isoformat()[:7]:
            return min(latest[1], from_snapshots)
        return from_snapshots

    def refresh(
        self, match_id: str, competition: str, home: str, away: str, day: date
    ) -> EventRefresh:
        now = self.clock()
        cached = self._cached(match_id)
        if cached is not None:
            fetched = datetime.fromisoformat(cached["fetched_at"])
            if now - fetched < timedelta(minutes=CACHE_MINUTES):
                return EventRefresh(
                    match_id, cached["markets"], 0, cached.get("credits_remaining"), fetched, True
                )
        cost = self.estimate()
        if cost.credits_remaining is not None and (
            cost.credits_remaining - cost.estimated_credits < self.min_reserve
        ):
            raise OddsBudgetLowError(cost.credits_remaining, self.min_reserve)
        sport = self.sport_key(competition)
        if sport is None:
            raise EventNotFoundError(f"no odds source for competition {competition}")
        client = self.client()
        event = find_event(client.events(sport), home, away, day, self.aliases)  # free
        if event is None:
            raise EventNotFoundError(f"{home} vs {away} ({day}) not found in {sport}")
        response = client.event_odds(sport, str(event["id"]), self.markets)
        credits = response.credits
        payload = {
            "match_id": match_id,
            "fetched_at": now.isoformat(),
            "markets": self.markets,
            "credits_remaining": credits.remaining,
            "credits_used": credits.last,
            "event": response.events[0],  # raw response (never contains the API key)
        }
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._path(match_id).write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        used = credits.last if credits.last is not None else cost.estimated_credits
        return EventRefresh(match_id, self.markets, used, credits.remaining, now, False)

    def prices(self, match_id: str) -> tuple[dict[PriceKey, tuple[float, str]], datetime | None]:
        """Latest cached prices of the event (any age; the analysis shows when they are from).
        An invalid id has no prices."""
        try:
            cached = self._cached(match_id)
        except InvalidMatchIdError:
            return {}, None
        if cached is None:
            return {}, None
        return self.parse(cached["event"]), datetime.fromisoformat(cached["fetched_at"])
