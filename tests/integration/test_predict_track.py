from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from betting_ml.application.predict_matches import (
    ModelNotAvailableError,
    UnknownLeagueError,
    UnknownTeamError,
    value_bets,
)
from betting_ml.domain.entities import OddsTriple, Outcome, Probabilities
from tests.serving import FIXTURE_DAY, FakeResults, ServingEnv, build_serving_env


@pytest.fixture
def env(tmp_path: Path) -> ServingEnv:
    return build_serving_env(tmp_path)


def test_daily_predictions(env: ServingEnv) -> None:
    daily = env.predictor.for_date(FIXTURE_DAY, min_edge=0.0)
    assert daily.date == FIXTURE_DAY
    assert [m.home_team for m in daily.matches] == ["Team 00", "Team 02", "Team 04"]
    for match in daily.matches:
        assert sum(match.probabilities.as_tuple()) == pytest.approx(1.0, abs=1e-9)
    with_odds, _, without = daily.matches
    assert with_odds.model_variant == "with_odds"
    assert with_odds.model_version == "E12-logistic-2022-09-01"
    assert with_odds.market is not None and with_odds.market.implied_probabilities is not None
    assert without.model_variant == "without_odds" and without.market is None
    assert without.value_bets == []
    for bet in with_odds.value_bets:
        assert bet.odds == with_odds.market.best_odds.for_outcome(bet.outcome)  # type: ignore[union-attr]
        assert bet.expected_value == pytest.approx(bet.model_probability * bet.odds - 1)
    assert with_odds.fair_odds[0] == pytest.approx(1 / with_odds.probabilities.home, abs=0.01)


def test_default_date_empty_day_and_filters(env: ServingEnv) -> None:
    today = env.predictor.for_date()  # clock: 2022-09-03 12:00 UTC -> 07:00 in Lima
    assert today.date == FIXTURE_DAY and len(today.matches) == 3
    empty = env.predictor.for_date(date(2022, 9, 10))
    assert empty.matches == [] and "No hay partidos" in (empty.message or "")
    assert env.predictor.for_date(FIXTURE_DAY, league="SP1").matches == []
    only = env.predictor.for_date(FIXTURE_DAY, only_value=True, min_edge=0.5)
    assert all(m.value_bets for m in only.matches)
    with pytest.raises(UnknownLeagueError):
        env.predictor.for_date(FIXTURE_DAY, league="XX")


def test_features_are_cached(env: ServingEnv) -> None:
    env.predictor.for_date(FIXTURE_DAY)
    cached = len(env.predictor._cache)
    env.predictor.for_date(FIXTURE_DAY)
    assert len(env.predictor._cache) == cached
    env.predictor.reset()
    assert env.predictor._cache == {}


def test_predict_one(env: ServingEnv) -> None:
    with_odds = env.predictor.predict_one(
        "E0", "team 00", "Team 01 FC", FIXTURE_DAY, OddsTriple(2.0, 3.5, 4.0)
    )
    assert with_odds.home_team == "Team 00" and with_odds.away_team == "Team 01"
    assert with_odds.model_variant == "with_odds"
    without = env.predictor.predict_one("E0", "Team 00", "Team 01")
    assert without.model_variant == "without_odds" and without.market is None
    with pytest.raises(UnknownTeamError, match="Man Utd FC"):
        env.predictor.predict_one("E0", "Man Utd FC", "Team 01")
    with pytest.raises(UnknownTeamError):
        env.predictor.predict_one("E0", "Team 00", "Nobody")
    with pytest.raises(UnknownLeagueError):
        env.predictor.predict_one("XX", "Team 00", "Team 01")


def test_ratings_and_status(env: ServingEnv) -> None:
    ratings = env.predictor.team_ratings("E0")
    assert len(ratings) == 8 and all(1300 < r < 1700 for r in ratings.values())
    assert env.predictor.model_loaded
    assert env.predictor.data_last_update() is not None


def test_missing_models(env: ServingEnv) -> None:
    env.predictor.production_versions = lambda: {"champion": "nope", "champion_no_odds": "nope"}
    env.predictor.reset()
    assert not env.predictor.model_loaded
    with pytest.raises(ModelNotAvailableError):
        env.predictor.for_date(FIXTURE_DAY)


def test_value_bets_helper() -> None:
    probs = Probabilities(0.5, 0.3, 0.2)
    bets = value_bets(probs, OddsTriple(2.2, 3.0, 6.0), min_edge=0.05)
    assert [b.outcome for b in bets] == [Outcome.AWAY, Outcome.HOME]
    assert value_bets(probs, None, 0.05) == []


def test_tracking_records_idempotently_and_grades(env: ServingEnv) -> None:
    env.predictor.for_date(FIXTURE_DAY)
    env.predictor.for_date(FIXTURE_DAY)
    tracked = env.tracking.store.load()
    assert len(tracked) == 3  # idempotent by match + model version
    summary = env.tracking.summary()
    assert summary.predictions == 3 and summary.graded == 0 and summary.log_loss is None
    results = pd.DataFrame(
        {
            "league": ["E0", "E0"],
            "date": pd.to_datetime([FIXTURE_DAY, FIXTURE_DAY]),
            "home_team": ["Team 00", "Team 02"],
            "away_team": ["Team 01", "Team 03"],
            "home_goals": [2.0, 0.0],
            "away_goals": [0.0, 0.0],
        }
    )
    env.tracking.results = FakeResults(results)
    assert env.tracking.update() == 2
    assert env.tracking.update() == 0
    summary = env.tracking.summary().to_dict()
    assert summary["graded"] == 2
    assert np.isfinite(summary["log_loss"]) and 0 <= summary["accuracy"] <= 1


def test_tracking_empty(tmp_path: Path) -> None:
    env = build_serving_env(tmp_path)
    assert env.tracking.summary().predictions == 0
    assert env.tracking.update() == 0
    assert env.tracking.record([], []) == 0
