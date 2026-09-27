"""Use case (spec 002, US5): settle pending bets with football-data results and compute CLV.

CLV source (owner's decision, decisions.md): Pinnacle closing odds of football-data
(``psc_odds_*``) when available; otherwise the last The Odds API snapshot of the reference
(Pinnacle, then Betfair Exchange net of commission) taken before kick-off."""

from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta

import numpy as np
import pandas as pd

from betting_ml.domain.clv import bet_clv
from betting_ml.domain.entities import OUTCOMES, OddsTriple, Outcome, make_match_id
from betting_ml.domain.journal import Bet, BetFilters, BetStatus, QuoteSource
from betting_ml.domain.odds import exchange_net_odds
from betting_ml.domain.ports import (
    BetRepository,
    MatchDataSource,
    OddsRepository,
    TeamNameNormalizer,
)

logger = logging.getLogger(__name__)
FOOTBALL_DATA_PSC = "football_data_psc"


@dataclass
class SettleResult:
    settled: int
    clv_computed: int
    still_pending: int
    corrected: int = 0


RECONCILE_DAYS = 30


def _outcome(row: pd.Series) -> Outcome:
    hg, ag = int(row["home_goals"]), int(row["away_goals"])
    return Outcome.HOME if hg > ag else Outcome.AWAY if hg < ag else Outcome.DRAW


def season_of(day: date) -> str:
    start = day.year if day.month >= 7 else day.year - 1
    return f"{start}-{(start + 1) % 100:02d}"


class SettleBets:
    def __init__(
        self,
        bets: BetRepository,
        odds: OddsRepository,
        results: MatchDataSource,
        team_names: TeamNameNormalizer,
        exchange_commission: float = 0.05,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.bets = bets
        self.odds = odds
        self.results = results
        self.team_names = team_names
        self.exchange_commission = exchange_commission
        self.clock = clock

    def _results(self, bets: list[Bet]) -> dict[str, pd.Series]:
        needed = {(b.league, season_of(_day(b))) for b in bets}
        frames = []
        for league, season in sorted(needed):
            try:
                frames.append(self.results.fetch_season(league, season))
            except Exception as exc:  # keep settling other leagues
                logger.error("results for %s %s unavailable: %s", league, season, exc)
        frames = [f for f in frames if not f.empty]
        if not frames:
            return {}
        data = self.team_names.canonicalize(pd.concat(frames, ignore_index=True), "football_data")
        data = data.dropna(subset=["home_goals", "away_goals"])
        out = {}
        for _, row in data.iterrows():
            match_id = make_match_id(
                row["league"], pd.Timestamp(row["date"]).date(), row["home_team"], row["away_team"]
            )
            out[match_id] = row
        return out

    def _api_closing(self, bet: Bet) -> tuple[OddsTriple | None, str | None]:
        if bet.kickoff_utc is None:  # without the kick-off time there is no "closing" line
            return None, None
        books: dict[str, dict[Outcome, float]] = defaultdict(dict)
        for q in self.odds.latest_quotes(
            match_ids=[bet.match_id], before=bet.kickoff_utc, source=QuoteSource.API
        ):
            books[q.bookmaker][q.outcome] = q.odds
        if len(books.get("pinnacle", {})) == 3:
            return OddsTriple(*(books["pinnacle"][o] for o in OUTCOMES)), "odds_api_pinnacle"
        for key in ("betfair_ex_eu", "betfair_ex_uk"):
            if len(books.get(key, {})) == 3:
                net = exchange_net_odds([books[key][o] for o in OUTCOMES], self.exchange_commission)
                return OddsTriple(*(float(x) for x in net)), f"odds_api_{key}"
        return None, None

    def _closing(self, bet: Bet, row: pd.Series | None) -> tuple[OddsTriple | None, str | None]:
        if row is not None:
            values = [row.get(f"psc_odds_{s}") for s in ("h", "d", "a")]
            if all(v is not None and np.isfinite(float(v)) and float(v) > 1 for v in values):
                return OddsTriple(*(float(v) for v in values)), FOOTBALL_DATA_PSC
        return self._api_closing(bet)

    def run(self) -> SettleResult:
        pending = self.bets.all(BetFilters(status=BetStatus.PENDING))
        now = self.clock()
        recent = now - timedelta(days=RECONCILE_DAYS)
        # Manually settled bets are checked against the official result (it always wins).
        settled_recent = [
            b
            for b in self.bets.all()
            if b.status is not BetStatus.PENDING
            and (b.clv is None or (b.settled_at or now) >= recent)
        ]
        results = self._results(pending + settled_recent) if (pending or settled_recent) else {}
        settled = clv_count = corrected = 0
        for bet in settled_recent:
            row = results.get(bet.match_id)
            if row is None:
                continue
            real = bet.result_status(_outcome(row))
            if bet.status is not real:
                fixed = replace(bet.settle(real, now), clv=bet.clv, clv_source=bet.clv_source)
                fixed = replace(
                    fixed, note=((bet.note or "") + " [corregida con el resultado oficial]").strip()
                )
                self.bets.update(fixed)
                corrected += 1
        missing_clv = [
            b for b in self.bets.all() if b.status is not BetStatus.PENDING and b.clv is None
        ]
        for bet in pending:
            row = results.get(bet.match_id)
            if row is None:
                continue
            updated = bet.settle(bet.result_status(_outcome(row)), now)
            closing, source = self._closing(bet, row)
            if closing is not None:
                updated = replace(
                    updated, clv=bet_clv(float(bet.odds), bet.outcome, closing), clv_source=source
                )
                clv_count += 1
            self.bets.update(updated)
            settled += 1
        for bet in missing_clv:  # manually settled bets: add the CLV when possible
            closing, source = self._closing(bet, results.get(bet.match_id))
            if closing is not None:
                self.bets.update(
                    replace(
                        bet, clv=bet_clv(float(bet.odds), bet.outcome, closing), clv_source=source
                    )
                )
                clv_count += 1
        return SettleResult(settled, clv_count, len(pending) - settled, corrected)


def _day(bet: Bet) -> date:
    if bet.kickoff_utc is not None:
        return pd.Timestamp(bet.kickoff_utc).tz_convert("Europe/London").date()
    return date.fromisoformat(bet.match_id.split("-", 1)[1][:10])
