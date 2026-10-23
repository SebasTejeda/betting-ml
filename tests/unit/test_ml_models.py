import numpy as np
import pandas as pd
import pytest

from betting_ml.domain.metrics import expected_calibration_error, log_loss
from betting_ml.ml.features.pipeline import FeaturePipeline
from betting_ml.ml.models.baselines import FrequencyBaseline, MarketBaseline
from betting_ml.ml.models.calibration import (
    CalibratedModel,
    IsotonicCalibrator,
    TemperatureScaler,
)
from betting_ml.ml.models.ensemble import BlendModel, StackingModel, optimal_blend_weights
from betting_ml.ml.models.factory import XiTunedGoalModel
from betting_ml.ml.models.poisson import PoissonModel
from betting_ml.ml.models.sklearn_models import (
    OptunaLightGBM,
    SklearnModel,
    build_estimator,
    inner_split,
)
from tests.conftest import make_synthetic_matches

SEASONS = ("2017-18", "2018-19", "2019-20", "2020-21", "2021-22")


@pytest.fixture(scope="module")
def frame() -> pd.DataFrame:
    matches = make_synthetic_matches(n_teams=10, seasons=SEASONS, seed=11)
    return FeaturePipeline().transform(matches)


def _split(frame: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    return frame[frame["season"] < "2021-22"], frame[frame["season"] == "2021-22"]


@pytest.mark.parametrize("kind", ["logistic", "xgboost", "lightgbm"])
def test_sklearn_models_fit_predict(frame: pd.DataFrame, kind: str) -> None:
    train, valid = _split(frame)
    model = SklearnModel(
        kind, ["elo", "form"], params={"n_estimators": 30} if kind != "logistic" else {}
    )  # type: ignore[arg-type]
    proba = model.fit(train).predict_proba(valid)
    assert proba.shape == (len(valid), 3)
    np.testing.assert_allclose(proba.sum(axis=1), 1.0)
    assert not model.uses_odds
    assert model.describe()["n_features"] == len(model.feature_names)
    assert all(c.startswith(("elo_", "form_")) for c in model.feature_names)


def test_market_group_marks_uses_odds(frame: pd.DataFrame) -> None:
    model = SklearnModel("logistic", ["elo", "market"])
    assert model.uses_odds
    model.fit(frame)
    assert any(c.startswith("mkt_") for c in model.feature_names)


def test_errors(frame: pd.DataFrame) -> None:
    with pytest.raises(ValueError):
        build_estimator("svm")  # type: ignore[arg-type]
    with pytest.raises(RuntimeError):
        SklearnModel("logistic", ["elo"]).predict_proba(frame)
    with pytest.raises(ValueError, match="two seasons"):
        inner_split(frame[frame["season"] == "2017-18"])


def test_elo_logistic_beats_frequencies() -> None:
    matches = make_synthetic_matches(n_teams=18, seasons=SEASONS, seed=5)
    train, valid = _split(FeaturePipeline().transform(matches, groups=["elo"]))
    y = valid["target"].astype(int).to_numpy()
    elo = SklearnModel("logistic", ["elo"]).fit(train).predict_proba(valid)
    freq = FrequencyBaseline().fit(train).predict_proba(valid)
    assert log_loss(y, elo) < log_loss(y, freq)


def test_optuna_lightgbm_uses_inner_validation(frame: pd.DataFrame) -> None:
    train, valid = _split(frame)
    model = OptunaLightGBM(["elo"], n_trials=3).fit(train)
    assert model.best_params and np.isfinite(model.inner_log_loss)
    assert model.predict_proba(valid).shape == (len(valid), 3)
    assert model.describe()["n_trials"] == 3


def test_temperature_scaling_fixes_overconfidence() -> None:
    rng = np.random.default_rng(0)
    true = rng.dirichlet([3, 2, 2], size=3000)
    y = np.array([rng.choice(3, p=p) for p in true])
    overconfident = np.exp(np.log(true) * 2.5)
    overconfident /= overconfident.sum(axis=1, keepdims=True)
    scaler = TemperatureScaler().fit(overconfident, y)
    assert scaler.temperature == pytest.approx(2.5, rel=0.15)
    assert log_loss(y, scaler.transform(overconfident)) < log_loss(y, overconfident)
    iso = IsotonicCalibrator().fit(overconfident, y)
    calibrated = iso.transform(overconfident)
    assert expected_calibration_error(y, calibrated) < expected_calibration_error(y, overconfident)


@pytest.mark.parametrize("method", ["temperature", "isotonic"])
def test_calibrated_model(frame: pd.DataFrame, method: str) -> None:
    train, valid = _split(frame)
    model = CalibratedModel(SklearnModel("logistic", ["elo"]), method).fit(train)  # type: ignore[arg-type]
    proba = model.predict_proba(valid)
    np.testing.assert_allclose(proba.sum(axis=1), 1.0)
    assert model.predict_goal_matrix(valid) is None
    assert model.describe()["method"] == method
    with pytest.raises(RuntimeError):
        CalibratedModel(SklearnModel("logistic", ["elo"])).predict_proba(valid)


def test_blend_weights_prefer_better_model() -> None:
    rng = np.random.default_rng(1)
    true = rng.dirichlet([3, 2, 2], size=4000)
    y = np.array([rng.choice(3, p=p) for p in true])
    noise = rng.dirichlet([1, 1, 1], size=4000)
    w = optimal_blend_weights([true, noise], y)
    assert w[0] > 0.9 and w.sum() == pytest.approx(1.0)


def test_blend_and_stacking_models(frame: pd.DataFrame) -> None:
    train, valid = _split(frame)
    members = [SklearnModel("logistic", ["elo"]), PoissonModel(xi=0.002)]
    blend = BlendModel(members).fit(train)
    proba = blend.predict_proba(valid)
    np.testing.assert_allclose(proba.sum(axis=1), 1.0)
    assert blend.weights is not None and blend.weights.sum() == pytest.approx(1.0)
    assert not blend.uses_odds
    fixed = BlendModel(members, weights=[0.5, 0.5]).fit(train)
    assert fixed.describe()["weights"] == [0.5, 0.5]
    stack = StackingModel([SklearnModel("logistic", ["elo"]), MarketBaseline("avg")]).fit(train)
    assert stack.uses_odds
    np.testing.assert_allclose(stack.predict_proba(valid).sum(axis=1), 1.0)
    assert len(stack.describe()["members"]) == 2  # type: ignore[arg-type]


def test_unfitted_models_refuse_to_predict_even_without_asserts() -> None:
    """Explicit checks (not ``assert``): they hold under ``python -O`` too (spec 003, T019)."""
    frame = pd.DataFrame()
    with pytest.raises(RuntimeError, match="not fitted"):
        BlendModel([FrequencyBaseline()]).predict_proba(frame)
    tuned = XiTunedGoalModel(xi_grid=[0.0])
    for predict in (tuned.predict_proba, tuned.predict_goal_matrix):
        with pytest.raises(RuntimeError, match="not fitted"):
            predict(frame)
