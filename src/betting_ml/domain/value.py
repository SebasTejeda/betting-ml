"""Value assessment against a sharp reference (spec 002, US3/US4): fair probabilities,
expected value, verdict and a capped fractional-Kelly stake. Money is always `Decimal`."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_DOWN, Decimal
from enum import StrEnum

from betting_ml.domain.entities import OddsTriple, Probabilities
from betting_ml.domain.odds import NormalizationMethod, exchange_net_odds, normalize

CENT = Decimal("0.01")
REFERENCE_BOOKMAKER = "pinnacle"
EXCHANGE_BOOKMAKERS = ("betfair_ex_eu", "betfair_ex_uk")


class Verdict(StrEnum):
    VALUE = "valor"
    FAIR = "justo"
    AVOID = "evitar"


def fair_probabilities(odds: OddsTriple, method: NormalizationMethod = "shin") -> Probabilities:
    """Margin-free probabilities of a 1X2 triple (always sum to 1)."""
    probs = normalize(odds.as_tuple(), method)
    total = float(probs.sum())
    home, draw = float(probs[0]) / total, float(probs[1]) / total
    return Probabilities(home, draw, 1.0 - home - draw)


def expected_value(probability: float, odds: float) -> float:
    return probability * odds - 1.0


def verdict(ev: float, min_edge: float) -> Verdict:
    """``valor`` if ev ≥ min_edge; ``justo`` if 0 ≤ ev < min_edge; ``evitar`` if ev < 0."""
    if ev >= min_edge:
        return Verdict.VALUE
    if ev >= 0:
        return Verdict.FAIR
    return Verdict.AVOID


def kelly_stake(
    probability: float,
    odds: float,
    bankroll: Decimal,
    fraction: float = 0.25,
    cap_pct: float = 0.02,
) -> Decimal:
    """Fractional Kelly stake in money, rounded down to cents.

    Never negative and never above ``cap_pct`` of the bankroll."""
    if not 0 < fraction <= 1:
        raise ValueError("fraction must be in (0, 1]")
    if not 0 < cap_pct <= 1:
        raise ValueError("cap_pct must be in (0, 1]")
    if bankroll <= 0 or odds <= 1 or not 0 <= probability <= 1:
        return Decimal("0.00")
    full = (probability * odds - 1.0) / (odds - 1.0)
    share = min(max(full * fraction, 0.0), cap_pct)
    stake = (bankroll * Decimal(str(share))).quantize(CENT, rounding=ROUND_DOWN)
    cap = (bankroll * Decimal(str(cap_pct))).quantize(CENT, rounding=ROUND_DOWN)
    return max(Decimal("0.00"), min(stake, cap))


@dataclass(frozen=True)
class Reference:
    source: str
    probabilities: Probabilities

    @property
    def fair_odds(self) -> tuple[float, float, float]:
        return tuple(1.0 / p if p > 0 else float("inf") for p in self.probabilities.as_tuple())  # type: ignore[return-value]


def reference_probabilities(
    quotes: dict[str, OddsTriple],
    commission: float = 0.05,
    method: NormalizationMethod = "shin",
) -> Reference | None:
    """Pinnacle without margin; else Betfair Exchange net of commission; else None."""
    if REFERENCE_BOOKMAKER in quotes:
        return Reference(
            REFERENCE_BOOKMAKER, fair_probabilities(quotes[REFERENCE_BOOKMAKER], method)
        )
    for key in EXCHANGE_BOOKMAKERS:
        if key in quotes:
            net = exchange_net_odds(quotes[key].as_tuple(), commission)
            return Reference(key, fair_probabilities(OddsTriple(*(float(x) for x in net)), method))
    return None


@dataclass(frozen=True)
class ValueAssessment:
    fair_probability: float
    fair_odds: float
    ev: float
    verdict: Verdict
    suggested_stake: Decimal


def assess(
    fair_probability: float,
    odds: float,
    bankroll: Decimal,
    min_edge: float,
    kelly_fraction: float = 0.25,
    cap_pct: float = 0.02,
) -> ValueAssessment:
    """Evaluate a quote. A stake is only suggested for a ``valor`` verdict."""
    ev = expected_value(fair_probability, odds)
    result = verdict(ev, min_edge)
    stake = (
        kelly_stake(fair_probability, odds, bankroll, kelly_fraction, cap_pct)
        if result is Verdict.VALUE
        else Decimal("0.00")
    )
    fair = 1.0 / fair_probability if fair_probability > 0 else float("inf")
    return ValueAssessment(fair_probability, fair, ev, result, stake)
