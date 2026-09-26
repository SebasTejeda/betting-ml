from datetime import UTC, date, datetime

import pytest

from betting_ml.domain.entities import (
    OUTCOMES,
    Fixture,
    Match,
    OddsTriple,
    Outcome,
    Prediction,
    Probabilities,
    ValueBet,
)
from betting_ml.domain.ports import Clock, MatchRepository


def test_outcome_from_goals() -> None:
    assert Outcome.from_goals(2, 1) is Outcome.HOME
    assert Outcome.from_goals(1, 1) is Outcome.DRAW
    assert Outcome.from_goals(0, 3) is Outcome.AWAY
    assert [o.position for o in OUTCOMES] == [0, 1, 2]
    assert Outcome.AWAY.label == "away"


def test_odds_triple_validation() -> None:
    odds = OddsTriple(2.0, 3.5, 4.0)
    assert odds.for_outcome(Outcome.DRAW) == 3.5
    with pytest.raises(ValueError):
        OddsTriple(1.0, 3.5, 4.0)
    with pytest.raises(ValueError):
        OddsTriple(float("nan"), 3.5, 4.0)


def test_probabilities_validation() -> None:
    probs = Probabilities(0.5, 0.3, 0.2)
    assert probs.for_outcome(Outcome.AWAY) == 0.2
    with pytest.raises(ValueError):
        Probabilities(0.5, 0.3, 0.3)
    with pytest.raises(ValueError):
        Probabilities(1.2, -0.1, -0.1)


def test_match_result() -> None:
    match = Match("m1", "E0", "2024-25", date(2024, 8, 17), "Arsenal", "Wolves", None, 2, 0)
    assert match.is_played
    assert match.result is Outcome.HOME
    upcoming = Match("m2", "E0", "2024-25", date(2024, 8, 17), "Arsenal", "Wolves")
    assert not upcoming.is_played
    assert upcoming.result is None


def test_prediction_and_fixture_construct() -> None:
    kickoff = datetime(2026, 9, 27, 14, tzinfo=UTC)
    fixture = Fixture("f1", "E0", kickoff, "Arsenal", "Chelsea", OddsTriple(1.9, 3.7, 4.2))
    bet = ValueBet(Outcome.AWAY, 4.5, 0.2333, 0.0499, 0.0036)
    pred = Prediction(
        "f1", "E0", "Arsenal", "Chelsea", Probabilities(0.5, 0.25, 0.25), "v1", kickoff, [bet]
    )
    assert fixture.average_odds is not None
    assert pred.value_bets[0].outcome is Outcome.AWAY


def test_ports_are_structural() -> None:
    class FixedClock:
        def now(self) -> datetime:
            return datetime(2026, 1, 1, tzinfo=UTC)

        def today(self) -> date:
            return date(2026, 1, 1)

    assert isinstance(FixedClock(), Clock)
    assert not isinstance(FixedClock(), MatchRepository)
