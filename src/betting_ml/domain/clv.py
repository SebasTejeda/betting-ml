"""Closing line value (CLV): how much better the odds taken were than the fair closing
probability of the sharp reference (Pinnacle)."""

from __future__ import annotations

from betting_ml.domain.entities import OddsTriple, Outcome
from betting_ml.domain.odds import NormalizationMethod
from betting_ml.domain.value import fair_probabilities


def clv(taken_odds: float, closing_fair_probability: float) -> float:
    """``taken_odds × closing_fair_probability − 1`` (positive = beat the close)."""
    if taken_odds <= 1:
        raise ValueError("taken_odds must be > 1")
    if not 0 < closing_fair_probability <= 1:
        raise ValueError("closing_fair_probability must be in (0, 1]")
    return taken_odds * closing_fair_probability - 1.0


def closing_fair_probability(
    closing_odds: OddsTriple, outcome: Outcome, method: NormalizationMethod = "shin"
) -> float:
    return fair_probabilities(closing_odds, method).for_outcome(outcome)


def bet_clv(
    taken_odds: float,
    outcome: Outcome,
    closing_odds: OddsTriple | None,
    method: NormalizationMethod = "shin",
) -> float | None:
    """CLV of a bet, or None when there is no closing reference."""
    if closing_odds is None:
        return None
    return clv(taken_odds, closing_fair_probability(closing_odds, outcome, method))
