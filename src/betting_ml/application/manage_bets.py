"""Use case (spec 002, US5 + US6): betting journal, bankroll settings and responsible limits."""

from __future__ import annotations

import logging
import re
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime, time
from decimal import Decimal
from typing import Any

from betting_ml.domain.audit import AuditInfo
from betting_ml.domain.entities import OUTCOMES, Outcome
from betting_ml.domain.journal import (
    BankrollSettings,
    Bet,
    BetFilters,
    BetKind,
    BetStatus,
    QuoteSource,
    SettingsChange,
    VersionConflictError,
)
from betting_ml.domain.limits import (
    LimitChange,
    LimitCheck,
    LimitStatus,
    SignalProgress,
    check_bet,
    effective_from_for,
    effective_monthly_limit,
    month_key,
    monthly_loss,
    overdue_pending,
    signal_progress,
)
from betting_ml.domain.ports import BetRepository, OddsRepository, SettingsRepository
from betting_ml.domain.value import reference_probabilities
from betting_ml.logging_config import security_event

MATCH_ID = re.compile(r"^(?P<league>[A-Z0-9]+)-(?P<date>\d{4}-\d{2}-\d{2})-[a-z0-9-]+$")
ROI_NOTE = "Con menos de 300 apuestas el ROI es mayormente ruido; mira el CLV."
NO_MARKET_REFERENCE_WARNING = (
    "Mercado sin cuota de referencia sharp: no hay EV de referencia. El CLV solo se calcula en "
    "Más/Menos 2.5 de partidos de liga (cierre de Pinnacle o, si falta, cierre promedio del "
    "mercado); en el resto de mercados no hay CLV. Cuenta para los límites."
)
NO_REFERENCE_WARNING = (
    "Sin cuota de referencia: el partido no tiene cuotas de la API. Cuenta para los límites, "
    "queda fuera de la señal de valor y su CLV se calculará con el cierre de Pinnacle de "
    "football-data si está disponible."
)


class LimitError(Exception):
    def __init__(self, check: LimitCheck) -> None:
        super().__init__(" ".join(check.messages))
        self.check = check


class MonthlyLimitReachedError(LimitError):
    """403: real bets blocked until next month."""


class LimitWarningError(LimitError):
    """409: warnings that need ``confirm: true``."""


class BetNotFoundError(LookupError):
    def __init__(self, bet_id: int) -> None:
        super().__init__(f"Apuesta {bet_id} no encontrada")
        self.bet_id = bet_id


class BetNotPendingError(ValueError):
    code = "BET_NOT_PENDING"


class BetStateError(BetNotPendingError):
    """The operation is not allowed at this point of the match (409)."""

    def __init__(self, message: str, code: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class NewBet:
    match_id: str
    outcome: Outcome | None
    bookmaker: str
    odds: Decimal
    stake: Decimal
    kind: BetKind
    note: str | None = None
    from_experimental_signal: bool = False
    # Spec 003: any market (default 1X2 with ``outcome``).
    market: str = "h2h"
    selection: str | None = None
    line: float | None = None


@dataclass
class Summary:
    bets: int
    settled: int
    staked: Decimal
    profit: Decimal
    roi: float | None
    clv_mean: float | None
    clv_positive_rate: float | None
    bankroll_initial: Decimal
    bankroll_current: Decimal
    bankroll_series: list[tuple[str, Decimal]]
    by_league: list[dict[str, Any]]
    by_bookmaker: list[dict[str, Any]]
    by_market: list[dict[str, Any]]
    month_limit: Decimal
    month_loss: Decimal
    month_remaining: Decimal
    signal: SignalProgress
    best_odds_uplift_mean: float | None
    note: str = ROI_NOTE
    settled_bets: list[Bet] = field(default_factory=list, repr=False)


class ManageBets:
    def __init__(
        self,
        bets: BetRepository,
        settings: SettingsRepository,
        odds: OddsRepository,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.bets = bets
        self.settings_repo = settings
        self.odds = odds
        self.clock = clock

    # ------------------------------------------------------------------ settings
    def _limit_changes(self) -> list[LimitChange]:
        return [
            LimitChange(c.changed_at, Decimal(c.old_value), Decimal(c.new_value), c.effective_from)
            for c in self.settings_repo.history("monthly_loss_limit")
        ]

    def current_limit(self, now: datetime | None = None) -> Decimal:
        settings: BankrollSettings = self.settings_repo.get()
        return effective_monthly_limit(
            settings.monthly_loss_limit, self._limit_changes(), month_key(now or self.clock())
        )

    def get_settings(self) -> BankrollSettings:
        return self.settings_repo.get()

    def update_settings(self, new: BankrollSettings, actor: str = "system") -> BankrollSettings:
        """Lowering the monthly limit applies now; raising it applies from next month (compared
        with the limit currently in force). Every change is kept in the history. ``new.version``
        is the version that was edited: if another save came first, VersionConflictError."""
        old = self.settings_repo.get()
        if new.version != old.version:
            raise VersionConflictError("settings", old.version)
        now = self.clock()
        in_force = self.current_limit(now)
        changes = []
        fields = (
            "bankroll_initial",
            "currency",
            "monthly_loss_limit",
            "max_stake_pct",
            "kelly_fraction",
            "min_edge",
        )
        for name in fields:
            before, after = getattr(old, name), getattr(new, name)
            if before == after:
                continue
            effective = month_key(now)
            if name == "monthly_loss_limit":
                effective = effective_from_for(in_force, after, now)
            changes.append(SettingsChange(now, name, str(before), str(after), effective))
        audit = AuditInfo(actor, "SETTINGS_CHANGED")
        saved: BankrollSettings = self.settings_repo.save(new, changes, audit)
        if changes:  # limits included: when a raise takes effect is part of the event
            security_event(
                "SETTINGS_CHANGED",
                logging.INFO,
                actor=actor,
                changes=[
                    f"{c.field}:{c.old_value}->{c.new_value}@{c.effective_from}" for c in changes
                ],
            )
        return saved

    # ------------------------------------------------------------------ bets
    def _match_info(self, match_id: str) -> dict[str, Any]:
        found = MATCH_ID.match(match_id)
        if found is None:
            raise ValueError(f"match_id inválido: {match_id!r}")
        quotes = self.odds.latest_quotes(match_ids=[match_id])
        info: dict[str, Any] = {
            "league": found["league"],
            "home_team": "",
            "away_team": "",
            "kickoff_utc": None,
        }
        if quotes:
            sample = quotes[0]
            info.update(
                home_team=sample.home_team,
                away_team=sample.away_team,
                kickoff_utc=sample.kickoff_utc,
            )
        return info

    def _fair(
        self, match_id: str, outcome: Outcome, odds: Decimal, kickoff: datetime | None = None
    ) -> tuple[float | None, float | None]:
        from betting_ml.domain.entities import OddsTriple

        books: dict[str, dict[Outcome, float]] = defaultdict(dict)
        cutoff = self.clock() if kickoff is None else min(self.clock(), kickoff)
        for q in self.odds.latest_quotes(
            match_ids=[match_id], before=cutoff, source=QuoteSource.API
        ):
            books[q.bookmaker][q.outcome] = q.odds
        complete = {
            k: OddsTriple(*(v[o] for o in OUTCOMES)) for k, v in books.items() if len(v) == 3
        }
        reference = reference_probabilities(complete)
        if reference is None:
            return None, None
        p = reference.probabilities.for_outcome(outcome)
        return p, p * float(odds) - 1.0

    def check(self, request: NewBet) -> LimitCheck:
        settings = self.settings_repo.get()
        now = self.clock()
        everything = self.bets.all()
        loss = monthly_loss(everything, month_key(now))
        exposure = sum(
            (
                b.stake
                for b in everything
                if b.kind is BetKind.REAL and b.status is BetStatus.PENDING
            ),
            Decimal("0.00"),
        )
        overdue = overdue_pending(everything, now)
        progress = signal_progress(everything) if request.from_experimental_signal else None
        return check_bet(
            request.stake,
            request.kind,
            loss,
            self.current_limit(now),
            settings.max_stake,
            request.from_experimental_signal,
            progress,
            pending_exposure=exposure,
            overdue=overdue,
        )

    def create(self, request: NewBet, confirm: bool = False, actor: str = "system") -> Bet:
        if request.stake <= 0 or request.odds <= 1:
            raise ValueError("stake > 0 y cuota > 1")
        info = self._match_info(request.match_id)
        result = self.check(request)
        if result.status is LimitStatus.BLOCKED:
            raise MonthlyLimitReachedError(result)
        if result.status is LimitStatus.WARNING and not confirm:
            raise LimitWarningError(result)
        if request.market == "h2h" and request.outcome is not None:
            fair, ev = self._fair(
                request.match_id, request.outcome, request.odds, info["kickoff_utc"]
            )
        else:  # no sharp reference for the other markets yet (spec 003)
            fair, ev = None, None
        warnings = result.messages
        if fair is None:
            warnings = (
                *warnings,
                NO_REFERENCE_WARNING if request.market == "h2h" else NO_MARKET_REFERENCE_WARNING,
            )
        if info["kickoff_utc"] is not None and self.clock() >= info["kickoff_utc"]:
            warnings = (
                *warnings,
                "Registrada después del inicio del partido (EV calculado con cuotas previas).",
            )
        bet = Bet(
            match_id=request.match_id,
            league=info["league"],
            outcome=request.outcome,
            bookmaker=request.bookmaker,
            odds=request.odds,
            stake=request.stake.quantize(Decimal("0.01")),
            kind=request.kind,
            created_at=self.clock(),
            home_team=info["home_team"],
            away_team=info["away_team"],
            kickoff_utc=info["kickoff_utc"],
            note=request.note,
            from_experimental_signal=request.from_experimental_signal,
            fair_probability=fair,
            ev=ev,
            warnings=warnings,
            no_reference=fair is None,
            market=request.market,
            selection=request.selection,
            line=request.line,
        )
        return self.bets.add(bet, AuditInfo(actor, "BET_CREATED"))

    def search(
        self, filters: BetFilters | None = None, page: int = 1, size: int = 50
    ) -> tuple[list[Bet], int]:
        return self.bets.search(filters, page, size)

    def get(self, bet_id: int) -> Bet:
        bet = self.bets.get(bet_id)
        if bet is None:
            raise BetNotFoundError(bet_id)
        return bet

    def update(
        self,
        bet_id: int,
        note: str | None = None,
        status: BetStatus | None = None,
        version: int | None = None,
        actor: str = "system",
    ) -> Bet:
        """``version`` is the one the client edited; the save itself is conditional too."""
        bet = self.get(bet_id)
        if version is not None and version != bet.version:
            raise VersionConflictError("bet", bet.version)
        action = "BET_UPDATED"
        if note is not None:
            bet = replace(bet, note=note)
        if status is not None and status is not bet.status:
            if bet.status is not BetStatus.PENDING:
                raise BetNotPendingError(
                    "una apuesta liquidada no se vuelve a liquidar a mano (el resultado oficial manda)"
                )
            if status is BetStatus.PENDING:
                raise BetNotPendingError("estado inválido")
            if self.clock() < _earliest_start(bet):
                raise BetStateError(
                    "el partido aún no empieza: no se puede liquidar", "MATCH_NOT_STARTED"
                )
            bet = bet.settle(status, self.clock(), source="manual")
            action = "BET_SETTLED"
        return self.bets.update(bet, AuditInfo(actor, action))

    def delete(self, bet_id: int, actor: str = "system") -> None:
        bet = self.get(bet_id)
        if bet.status is not BetStatus.PENDING:
            raise BetNotPendingError("solo se pueden borrar apuestas pendientes")
        if self.clock() >= _earliest_start(bet):
            raise BetStateError(
                "el partido ya empezó: la apuesta se liquida con el resultado, no se borra",
                "MATCH_ALREADY_STARTED",
            )
        self.bets.delete(bet_id, AuditInfo(actor, "BET_DELETED"))

    # ------------------------------------------------------------------ summary
    def summary(
        self,
        kind: BetKind | None = BetKind.REAL,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
    ) -> Summary:
        settings = self.settings_repo.get()
        everything = self.bets.all()
        bets = self.bets.all(BetFilters(kind=kind, date_from=date_from, date_to=date_to))
        settled = [b for b in bets if b.status is not BetStatus.PENDING and b.profit is not None]
        staked = sum((b.stake for b in settled), Decimal("0.00"))
        profit = sum((b.profit for b in settled if b.profit is not None), Decimal("0.00"))
        clvs = [b.clv for b in settled if b.clv is not None]
        series: list[tuple[str, Decimal]] = []
        running = settings.bankroll_initial
        for bet in sorted(settled, key=lambda b: b.settled_at or b.created_at):
            running += bet.profit or Decimal("0")
            series.append(((bet.settled_at or bet.created_at).date().isoformat(), running))
        now = self.clock()
        limit = self.current_limit(now)
        # same figure as the 403: overdue unsettled real bets count as lost until settled
        loss = monthly_loss(everything, month_key(now)) + overdue_pending(everything, now)
        return Summary(
            bets=len(bets),
            settled=len(settled),
            staked=staked,
            profit=profit,
            roi=float(profit / staked) if staked > 0 else None,
            clv_mean=sum(clvs) / len(clvs) if clvs else None,
            clv_positive_rate=sum(c > 0 for c in clvs) / len(clvs) if clvs else None,
            bankroll_initial=settings.bankroll_initial,
            bankroll_current=running,
            bankroll_series=series,
            by_league=_group(settled, lambda b: b.league, "league"),
            by_bookmaker=_group(settled, lambda b: b.bookmaker, "bookmaker"),
            by_market=by_market(bets),
            month_limit=limit,
            month_loss=loss,
            month_remaining=max(Decimal("0.00"), limit - loss),
            signal=signal_progress(everything),
            best_odds_uplift_mean=self._uplift(bets),
            settled_bets=settled,
        )

    def _uplift(self, bets: list[Bet]) -> float | None:
        """How much better the odds taken were than the market average when betting."""
        uplifts = []
        for bet in bets:
            quotes = [
                q.odds
                for q in self.odds.latest_quotes(
                    match_ids=[bet.match_id], before=bet.created_at, source=QuoteSource.API
                )
                if bet.market == "h2h" and q.outcome is bet.outcome
            ]
            if quotes:
                uplifts.append(float(bet.odds) / (sum(quotes) / len(quotes)) - 1.0)
        return sum(uplifts) / len(uplifts) if uplifts else None


def _group(bets: list[Bet], key: Callable[[Bet], str], name: str) -> list[dict[str, Any]]:
    groups: dict[str, list[Bet]] = defaultdict(list)
    for bet in bets:
        groups[key(bet)].append(bet)
    out = []
    for value, items in sorted(groups.items()):
        staked = sum((b.stake for b in items), Decimal("0"))
        profit = sum((b.profit or Decimal("0") for b in items), Decimal("0"))
        clvs = [b.clv for b in items if b.clv is not None]
        out.append(
            {
                name: value,
                "bets": len(items),
                "roi": float(profit / staked) if staked > 0 else None,
                "clv_mean": sum(clvs) / len(clvs) if clvs else None,
            }
        )
    return out


# CLV sources: Pinnacle's closing price (sharp) vs the closing market average (weaker).
PINNACLE_CLV_SOURCES = ("football_data_psc", "odds_api_pinnacle")
MARKET_AVERAGE_CLV_SOURCES = ("football_data_avgc",)
EVIDENCE_PAPER_BETS = 100  # spec 003 US6: ≥ 100 paper bets with mean CLV > 0 per market


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def by_market(bets: list[Bet]) -> list[dict[str, Any]]:
    """Spec 003 US6: bets, ROI and CLV per market, with the CLV against Pinnacle apart from the
    CLV against the closing market average, and the progress of paper bets with CLV towards
    the evidence condition (≥ 100 with mean CLV > 0)."""
    groups: dict[str, list[Bet]] = defaultdict(list)
    for bet in bets:
        groups[bet.market].append(bet)
    out = []
    for market, items in sorted(groups.items()):
        settled = [b for b in items if b.status is not BetStatus.PENDING and b.profit is not None]
        staked = sum((b.stake for b in settled), Decimal("0"))
        profit = sum((b.profit or Decimal("0") for b in settled), Decimal("0"))
        with_clv = [b for b in items if b.clv is not None]
        sharp = [b.clv for b in with_clv if b.clv_source in PINNACLE_CLV_SOURCES]
        average = [b.clv for b in with_clv if b.clv_source in MARKET_AVERAGE_CLV_SOURCES]
        other = [
            b.clv
            for b in with_clv
            if b.clv_source not in (*PINNACLE_CLV_SOURCES, *MARKET_AVERAGE_CLV_SOURCES)
        ]
        paper_clv = [b.clv for b in with_clv if b.kind is BetKind.PAPER and b.clv is not None]
        mean_paper = _mean(paper_clv)
        out.append(
            {
                "market": market,
                "bets": len(items),
                "settled": len(settled),
                "roi": float(profit / staked) if staked > 0 else None,
                "clv_mean_pinnacle": _mean([v for v in sharp if v is not None]),
                "clv_n_pinnacle": len(sharp),
                "clv_mean_market_average": _mean([v for v in average if v is not None]),
                "clv_n_market_average": len(average),
                "clv_mean_other": _mean([v for v in other if v is not None]),
                "clv_n_other": len(other),
                "paper_with_clv": len(paper_clv),
                "paper_clv_mean": mean_paper,
                "evidence_target": EVIDENCE_PAPER_BETS,
                "evidence_met": len(paper_clv) >= EVIDENCE_PAPER_BETS
                and mean_paper is not None
                and mean_paper > 0,
            }
        )
    return out


def _earliest_start(bet: Bet) -> datetime:
    """Kick-off, or the start of the match day (UTC) from the ``match_id`` when it is unknown."""
    if bet.kickoff_utc is not None:
        return bet.kickoff_utc
    found = MATCH_ID.match(bet.match_id)
    day = date.fromisoformat(found["date"]) if found else bet.created_at.date()
    return datetime.combine(day, time(0), tzinfo=UTC)
