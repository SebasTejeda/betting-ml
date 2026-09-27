"""Use case (spec 002, US2): download odds snapshots within the credit budget of The Odds API."""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol
from zoneinfo import ZoneInfo

from betting_ml.config import LeaguesFile
from betting_ml.domain.journal import OddsSnapshot, QuoteSource
from betting_ml.domain.ports import OddsRepository

logger = logging.getLogger(__name__)
LIMA = ZoneInfo("America/Lima")


class OddsClient(Protocol):
    regions: str
    last_credits: Any

    def odds(self, sport_key: str, markets: str = "h2h") -> Any: ...

    def sports(self) -> list[dict[str, Any]]: ...


class OddsBudgetLowError(RuntimeError):
    def __init__(self, remaining: int, reserve: int) -> None:
        super().__init__(
            f"Quedan {remaining} créditos (mínimo {reserve}). Refresco bloqueado hasta el próximo ciclo."
        )
        self.remaining = remaining
        self.reserve = reserve


@dataclass
class Budget:
    credits_remaining: int | None
    credits_used_month: int
    min_reserve: int
    last_refresh: datetime | None

    @property
    def low(self) -> bool:
        return self.credits_remaining is not None and self.credits_remaining < self.min_reserve


@dataclass
class RefreshResult:
    snapshot_id: int | None
    leagues: list[str]
    events: int
    credits_used: int
    credits_remaining: int | None
    unmapped_teams: list[str] = field(default_factory=list)
    unknown_bookmakers: list[str] = field(default_factory=list)
    stopped_by_budget: bool = False


def month_start_lima(now: datetime) -> datetime:
    local = now.astimezone(LIMA)
    return local.replace(day=1, hour=0, minute=0, second=0, microsecond=0).astimezone(UTC)


class RefreshOdds:
    def __init__(
        self,
        client_factory: Callable[[], OddsClient],
        repository: OddsRepository,
        leagues: LeaguesFile,
        mapper: Callable[[list[dict[str, Any]], str], Any],
        min_reserve: int = 50,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.client_factory = client_factory
        self.repository = repository
        self.leagues = leagues
        self.mapper = mapper
        self.min_reserve = min_reserve
        self.clock = clock

    def budget(self) -> Budget:
        latest = self.repository.latest_snapshot(QuoteSource.API)
        month = self.repository.snapshots_since(month_start_lima(self.clock()), QuoteSource.API)
        return Budget(
            credits_remaining=None if latest is None else latest.credits_remaining,
            credits_used_month=sum(s.credits_used or 0 for s in month),
            min_reserve=self.min_reserve,
            last_refresh=None if latest is None else latest.fetched_at,
        )

    def refresh(self, leagues: Sequence[str] | None = None) -> RefreshResult:
        codes = list(leagues) if leagues else self.leagues.codes
        unknown = [c for c in codes if c not in self.leagues.codes]
        if unknown:
            raise KeyError(f"unknown leagues {unknown}")
        budget = self.budget()
        client = self.client_factory()
        cost = len([r for r in client.regions.split(",") if r.strip()])  # h2h: 1 market x regions
        remaining = budget.credits_remaining
        if remaining is not None and remaining - cost < self.min_reserve:
            # The stored balance may be stale (credits reset monthly): ask the API for free.
            remaining = self._probe(client, remaining)
            if remaining is not None and remaining - cost < self.min_reserve:
                raise OddsBudgetLowError(remaining, self.min_reserve)
        now = self.clock()
        snapshot = OddsSnapshot(fetched_at=now, source=QuoteSource.API)
        used, events = 0, 0
        unmapped: set[str] = set()
        unknown_books: set[str] = set()
        stopped = False
        try:
            for code in codes:
                if remaining is not None and remaining - cost < self.min_reserve:
                    stopped = True
                    logger.warning("credit reserve reached: refresh stopped before %s", code)
                    break
                sport = self.leagues.league(code).odds_api
                if not sport:
                    continue
                response = client.odds(sport)
                used += response.credits.last or 0
                remaining = response.credits.remaining
                upcoming = [e for e in response.events if _starts_after(e, now)]  # no in-play odds
                mapped = self.mapper(upcoming, code)
                events += mapped.events
                unmapped |= mapped.unmapped_teams
                unknown_books |= mapped.unknown_bookmakers
                snapshot.quotes.extend(mapped.quotes)
                snapshot.leagues.append(code)
        finally:
            # Whatever was paid for is stored, even if a later league fails.
            snapshot.credits_used = used
            snapshot.credits_remaining = remaining
            snapshot_id = (
                self.repository.save_snapshot(snapshot) if (snapshot.leagues or used) else None
            )
        if unmapped:
            logger.error(
                "unmapped The Odds API teams (add them to team_aliases.yaml): %s", sorted(unmapped)
            )
        return RefreshResult(
            snapshot_id=snapshot_id,
            leagues=snapshot.leagues,
            events=events,
            credits_used=used,
            credits_remaining=remaining,
            unmapped_teams=sorted(unmapped),
            unknown_bookmakers=sorted(unknown_books),
            stopped_by_budget=stopped,
        )

    def _probe(self, client: OddsClient, stored: int | None) -> int | None:
        """Read the current balance with GET /v4/sports (costs no credits) and store it."""
        try:
            client.sports()
        except Exception:  # keep the stored value if the probe fails
            logger.exception("credit probe failed")
            return stored
        credits = client.last_credits
        remaining = None if credits is None else credits.remaining
        if remaining is not None:
            self.repository.save_snapshot(
                OddsSnapshot(
                    self.clock(), QuoteSource.API, credits_remaining=remaining, credits_used=0
                )
            )
        if remaining is None:
            # No balance header: a new month (Lima) means the provider renewed the credits.
            this_month = self.repository.snapshots_since(
                month_start_lima(self.clock()), QuoteSource.API
            )
            return None if not this_month else stored
        return remaining

    def should_auto_refresh(self, now: datetime | None = None) -> bool:
        """Automatic refresh only on days with matches of the configured leagues (in Lima),
        judging by the latest snapshot; the first refresh is always allowed."""
        now = now or self.clock()
        if self.budget().low:
            return False
        today = now.astimezone(LIMA).date()
        quotes = self.repository.latest_quotes()
        if not quotes:
            return True
        return any(
            q.kickoff_utc is not None and q.kickoff_utc.astimezone(LIMA).date() == today
            for q in quotes
        )


def _starts_after(event: dict[str, Any], now: datetime) -> bool:
    commence = event.get("commence_time")
    if not commence:
        return True
    return datetime.fromisoformat(str(commence).replace("Z", "+00:00")) > now
