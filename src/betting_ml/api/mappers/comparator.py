"""Spec-002 comparator and calculator results -> response schemas (no business logic)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from betting_ml.api.schemas_002 import (
    BestOut,
    BookQuoteOut,
    CalculatorOut,
    ComparatorDetailOut,
    FairOut,
    HistoryPointOut,
    MarginsOut,
    ModelOut,
    SignalBetOut,
    SignalOut,
    Triple,
)
from betting_ml.application.compare_matches import (
    EXPERIMENTAL_LABEL,
    ManualEvaluation,
    MatchComparison,
)
from betting_ml.domain.entities import OUTCOMES, Outcome


def triple(values: dict[Outcome, float] | tuple[float, float, float] | None) -> Triple:
    if values is None:
        return Triple()
    if isinstance(values, tuple):
        return Triple(home=values[0], draw=values[1], away=values[2])
    return Triple(**{o.label: round(values[o], 4) for o in OUTCOMES if o in values})


def match_out(m: MatchComparison) -> dict[str, Any]:
    fair = None
    if m.reference is not None:
        probs = m.reference.probabilities
        fair = FairOut(
            source=m.reference.source,
            probabilities=Triple(
                home=round(probs.home, 4), draw=round(probs.draw, 4), away=round(probs.away, 4)
            ),
            odds=Triple(
                **{
                    o.label: round(v, 2)
                    for o, v in zip(OUTCOMES, m.reference.fair_odds, strict=True)
                }
            ),
        )
    model = None
    if m.model is not None:
        model = ModelOut(
            probabilities=Triple(home=m.model.home, draw=m.model.draw, away=m.model.away),
            version=m.model_version,
        )
    signal = None
    if m.signal is not None:
        signal = SignalOut(
            label=EXPERIMENTAL_LABEL,
            bets=[
                SignalBetOut(
                    outcome=s.outcome.label,  # type: ignore[arg-type]
                    bookmaker=s.bookmaker,
                    odds=s.odds,
                    ev=round(s.ev, 4),
                    model_agrees=s.model_agrees,
                    suggested_stake=s.suggested_stake,
                )
                for s in m.signal
            ],
        )
    return {
        "match_id": m.match_id,
        "league": m.league,
        "kickoff": m.kickoff,
        "home_team": m.home_team,
        "away_team": m.away_team,
        "fair": fair,
        "model": model,
        "best": {
            o.label: BestOut(
                bookmaker=b.bookmaker, odds=b.odds, ev=None if b.ev is None else round(b.ev, 4)
            )
            for o, b in m.best.items()
        },
        "margins": MarginsOut(
            best_combined=m.margins.best_combined,
            average=m.margins.average,
            best_vs_average_uplift=m.margins.best_vs_average_uplift,
        ),
        "experimental_signal": signal,
        "warning": m.warning,
    }


def detail_out(
    comparison: MatchComparison, history: list[tuple[datetime, dict[Outcome, float]]]
) -> ComparatorDetailOut:
    return ComparatorDetailOut(
        **match_out(comparison),
        bookmakers=[
            BookQuoteOut(
                key=b.key,
                accessible=b.accessible,
                odds=triple(b.odds),
                margin=b.margin,
                updated_at=b.updated_at,
            )
            for b in comparison.books
        ],
        reference_history=[HistoryPointOut(at=at, odds=triple(odds)) for at, odds in history],
    )


def calculator_out(result: ManualEvaluation) -> CalculatorOut:
    a = result.assessment
    best = result.best_available
    return CalculatorOut(
        fair_probability=round(a.fair_probability, 4),
        fair_odds=round(a.fair_odds, 2),
        ev=round(a.ev, 4),
        verdict=a.verdict.value,  # type: ignore[arg-type]
        experimental=True,
        label=EXPERIMENTAL_LABEL,
        suggested_stake=a.suggested_stake,
        model_probability=result.model_probability,
        model_agrees=result.model_agrees,
        reference=result.reference_source,
        best_available=None
        if best is None
        else BestOut(bookmaker=best.bookmaker, odds=best.odds, ev=best.ev),
    )
