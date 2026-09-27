"""Maps application results to response schemas (no business logic)."""

from __future__ import annotations

from betting_ml.api.schemas import Market, MatchOut, Triple, ValueBetOut
from betting_ml.application.predict_matches import MatchPrediction
from betting_ml.domain.entities import OddsTriple, Probabilities


def _triple(
    values: OddsTriple | Probabilities | tuple[float, float, float] | None,
) -> Triple | None:
    if values is None:
        return None
    home, draw, away = values if isinstance(values, tuple) else values.as_tuple()
    return Triple(home=home, draw=draw, away=away)


def match_out(prediction: MatchPrediction) -> dict[str, object]:
    market = None
    if prediction.market is not None:
        market = Market(
            source=prediction.market.source,
            average_odds=_triple(prediction.market.average_odds),
            best_odds=_triple(prediction.market.best_odds),
            implied_probabilities=_triple(prediction.market.implied_probabilities),
        )
    out = MatchOut(
        match_id=prediction.match_id,
        league=prediction.league,
        kickoff=prediction.kickoff,
        home_team=prediction.home_team,
        away_team=prediction.away_team,
        probabilities=_triple(prediction.probabilities),  # type: ignore[arg-type]
        fair_odds=_triple(prediction.fair_odds),  # type: ignore[arg-type]
        market=market,
        value_bets=[
            ValueBetOut(
                outcome=bet.outcome.label,  # type: ignore[arg-type]
                odds=round(bet.odds, 2),
                model_probability=round(bet.model_probability, 4),
                expected_value=round(bet.expected_value, 4),
                kelly_fraction=round(bet.kelly_fraction, 4),
            )
            for bet in prediction.value_bets
        ],
    )
    return out.model_dump()
