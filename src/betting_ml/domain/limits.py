"""Responsible-gambling rules (spec 002, US6; constitution §IX). Pure and deterministic.

- The monthly loss is the net loss of REAL bets settled in the current calendar month in Lima.
- Once the monthly budget is exhausted, real bets are blocked until next month (paper bets are
  always allowed).
- A high stake or getting close to / over the monthly budget produces warnings that need an
  explicit confirmation.
- Lowering the monthly limit applies immediately; raising it only applies from next month.
- Real bets coming from the experimental value signal need confirmation until the signal has
  its own evidence (100 paper bets with positive mean CLV).
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from zoneinfo import ZoneInfo

from betting_ml.domain.journal import Bet, BetKind, BetStatus

LIMA = ZoneInfo("America/Lima")
NEAR_LIMIT_SHARE = Decimal("0.8")
SIGNAL_TARGET_BETS = 100


class LimitStatus(StrEnum):
    OK = "ok"
    WARNING = "warning"
    BLOCKED = "blocked"


class LimitCode(StrEnum):
    MONTHLY_LIMIT_REACHED = "MONTHLY_LIMIT_REACHED"
    LIMIT_WARNING = "LIMIT_WARNING"
    EXPERIMENTAL_SIGNAL_UNPROVEN = "EXPERIMENTAL_SIGNAL_UNPROVEN"


@dataclass(frozen=True)
class LimitCheck:
    status: LimitStatus
    code: LimitCode | None = None
    messages: tuple[str, ...] = ()


@dataclass(frozen=True)
class SignalProgress:
    paper_bets: int
    clv_mean: float | None
    target: int = SIGNAL_TARGET_BETS

    @property
    def evidence_met(self) -> bool:
        return self.paper_bets >= self.target and self.clv_mean is not None and self.clv_mean > 0


@dataclass(frozen=True)
class LimitChange:
    """A change of the monthly loss limit: ``new`` applies from month ``effective_from``."""

    changed_at: datetime
    old: Decimal
    new: Decimal
    effective_from: str
    extra: dict[str, str] = field(default_factory=dict)


def month_key(moment: datetime, tz: ZoneInfo = LIMA) -> str:
    return moment.astimezone(tz).strftime("%Y-%m")


def next_month_key(moment: datetime, tz: ZoneInfo = LIMA) -> str:
    local = moment.astimezone(tz)
    year, month = (local.year + 1, 1) if local.month == 12 else (local.year, local.month + 1)
    return f"{year:04d}-{month:02d}"


def effective_from_for(old: Decimal, new: Decimal, now: datetime) -> str:
    """Lowering applies now; raising only from next month."""
    return month_key(now) if new <= old else next_month_key(now)


def effective_monthly_limit(
    requested: Decimal, changes: Sequence[LimitChange], month: str
) -> Decimal:
    """Limit in force for ``month`` given the chronological change history."""
    if not changes:
        return requested
    ordered = sorted(changes, key=lambda c: c.changed_at)
    value = ordered[0].old
    for change in ordered:
        if change.effective_from <= month:
            value = change.new
    return value


def monthly_loss(bets: Iterable[Bet], month: str, tz: ZoneInfo = LIMA) -> Decimal:
    """Net loss (≥ 0) of real bets settled in ``month`` (Lima calendar)."""
    net = Decimal("0.00")
    for bet in bets:
        if bet.kind is not BetKind.REAL or bet.status is BetStatus.PENDING or bet.profit is None:
            continue
        if bet.settled_at is None or month_key(bet.settled_at, tz) != month:
            continue
        net += bet.profit
    return max(Decimal("0.00"), -net)


def signal_progress(bets: Iterable[Bet]) -> SignalProgress:
    """Settled paper bets from the experimental signal with a CLV."""
    clvs = [
        b.clv
        for b in bets
        if b.kind is BetKind.PAPER
        and b.from_experimental_signal
        and b.clv is not None
        and b.status is not BetStatus.PENDING
    ]
    return SignalProgress(len(clvs), sum(clvs) / len(clvs) if clvs else None)


def check_bet(
    stake: Decimal,
    kind: BetKind,
    month_loss: Decimal,
    monthly_limit: Decimal,
    max_stake: Decimal,
    from_experimental_signal: bool = False,
    progress: SignalProgress | None = None,
    pending_exposure: Decimal = Decimal("0.00"),
) -> LimitCheck:
    """ok / warning (needs confirmation) / blocked. Paper bets are never blocked.

    Warnings use the worst case: settled loss of the month + stakes of pending real bets + this
    stake. The block (403) uses the settled loss."""
    if kind is BetKind.PAPER:
        return LimitCheck(LimitStatus.OK)
    if month_loss >= monthly_limit:
        return LimitCheck(
            LimitStatus.BLOCKED,
            LimitCode.MONTHLY_LIMIT_REACHED,
            (
                f"Presupuesto mensual de pérdida superado ({month_loss} de {monthly_limit}). "
                "No se registran apuestas reales hasta el mes siguiente; las de papel siguen permitidas.",
            ),
        )
    messages: list[str] = []
    code = None
    if from_experimental_signal and (progress is None or not progress.evidence_met):
        done = 0 if progress is None else progress.paper_bets
        clv = (
            "sin datos"
            if progress is None or progress.clv_mean is None
            else f"{100 * progress.clv_mean:+.2f} %"
        )
        messages.append(
            f"Esta señal aún no tiene evidencia ({done}/{SIGNAL_TARGET_BETS} apuestas en papel, CLV actual {clv}). "
            "¿Apostar dinero real igual?"
        )
        code = LimitCode.EXPERIMENTAL_SIGNAL_UNPROVEN
    if stake > max_stake:
        messages.append(f"El stake {stake} supera el máximo por apuesta ({max_stake}).")
    worst = month_loss + pending_exposure + stake
    exposure = f"pérdida actual {month_loss} + pendientes {pending_exposure} de {monthly_limit}"
    if worst > monthly_limit:
        messages.append(f"En el peor caso superas el límite mensual ({exposure}).")
    elif worst >= monthly_limit * NEAR_LIMIT_SHARE:
        messages.append(f"Te acercas al límite mensual ({exposure}).")
    if not messages:
        return LimitCheck(LimitStatus.OK)
    return LimitCheck(LimitStatus.WARNING, code or LimitCode.LIMIT_WARNING, tuple(messages))
