import numpy as np
import pandas as pd
import pytest

from betting_ml.domain.metrics import log_loss
from betting_ml.domain.odds import normalize_proportional, normalize_shin
from betting_ml.domain.ports import ProbabilisticModel
from betting_ml.ml.features.pipeline import FeaturePipeline
from betting_ml.ml.models.baselines import FrequencyBaseline, MarketBaseline
from tests.conftest import make_synthetic_matches


@pytest.fixture(scope="module")
def frame() -> pd.DataFrame:
    matches = pd.concat(
        [make_synthetic_matches(league="E0"), make_synthetic_matches(league="SP1", seed=7)]
    )
    return FeaturePipeline().transform(matches, groups=["elo"])


def test_frequency_baseline(frame: pd.DataFrame) -> None:
    model = FrequencyBaseline().fit(frame)
    assert isinstance(model, ProbabilisticModel)
    proba = model.predict_proba(frame)
    np.testing.assert_allclose(proba.sum(axis=1), 1.0)
    e0 = frame[frame["league"] == "E0"]
    expected = np.bincount(e0["target"].astype(int), minlength=3) / len(e0)
    np.testing.assert_allclose(proba[frame["league"].to_numpy() == "E0"][0], expected)
    unseen = frame.iloc[:2].assign(league="XX")
    np.testing.assert_allclose(model.predict_proba(unseen)[0], model.overall)
    assert model.predict_goal_matrix(frame) is None


def test_market_baseline_shin_and_proportional(frame: pd.DataFrame) -> None:
    odds = frame[["avg_odds_h", "avg_odds_d", "avg_odds_a"]].to_numpy()
    shin = MarketBaseline("avg").fit(frame).predict_proba(frame)
    np.testing.assert_allclose(shin, normalize_shin(odds))
    prop = MarketBaseline("avg", "proportional").fit(frame).predict_proba(frame)
    np.testing.assert_allclose(prop, normalize_proportional(odds))
    assert MarketBaseline("psc").name == "market_psc_shin"


def test_market_baseline_falls_back_without_odds(frame: pd.DataFrame) -> None:
    partial = frame.copy()
    partial.loc[partial.index[:10], "psc_odds_h"] = np.nan
    model = MarketBaseline("psc").fit(frame)
    proba = model.predict_proba(partial)
    assert model.coverage == pytest.approx(1 - 10 / len(frame))
    np.testing.assert_allclose(proba[0], model.fallback.predict_proba(partial.iloc[:1])[0])
    np.testing.assert_allclose(proba.sum(axis=1), 1.0)
    assert model.describe()["source"] == "psc"


def test_market_beats_frequencies_on_informative_odds() -> None:
    matches = make_synthetic_matches(n_teams=10)
    frame = FeaturePipeline().transform(matches, groups=["elo"])
    y = frame["target"].astype(int).to_numpy()
    # Make the odds informative: the true result gets a boost.
    informative = frame.copy()
    probs = np.full((len(y), 3), 0.2)
    probs[np.arange(len(y)), y] = 0.6
    informative[["avg_odds_h", "avg_odds_d", "avg_odds_a"]] = 1 / (probs * 1.05)
    market = MarketBaseline("avg").fit(informative).predict_proba(informative)
    freq = FrequencyBaseline().fit(informative).predict_proba(informative)
    assert log_loss(y, market) < log_loss(y, freq)
