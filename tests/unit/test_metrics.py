import numpy as np
import pytest
from sklearn import metrics as skm

from betting_ml.domain.metrics import (
    accuracy,
    brier_score,
    evaluate,
    expected_calibration_error,
    log_loss,
    ranked_probability_score,
)


@pytest.fixture
def sample() -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(42)
    proba = rng.dirichlet([4, 2.5, 3], size=500)
    y = np.array([rng.choice(3, p=row) for row in proba])
    return y, proba


def test_log_loss_matches_sklearn(sample: tuple[np.ndarray, np.ndarray]) -> None:
    y, p = sample
    assert log_loss(y, p) == pytest.approx(skm.log_loss(y, p, labels=[0, 1, 2]), abs=1e-9)


def test_brier_matches_sklearn(sample: tuple[np.ndarray, np.ndarray]) -> None:
    y, p = sample
    expected = skm.brier_score_loss(y, p, labels=[0, 1, 2], scale_by_half=False)
    assert brier_score(y, p) == pytest.approx(expected, abs=1e-9)


def test_accuracy_matches_sklearn(sample: tuple[np.ndarray, np.ndarray]) -> None:
    y, p = sample
    assert accuracy(y, p) == pytest.approx(skm.accuracy_score(y, p.argmax(axis=1)), abs=1e-9)


def test_rps_hand_case() -> None:
    # p = [0.5, 0.3, 0.2], outcome H -> cum p = [0.5, 0.8], cum o = [1, 1]
    # RPS = ((0.5)^2 + (0.2)^2) / 2 = 0.145
    assert ranked_probability_score([0], [[0.5, 0.3, 0.2]]) == pytest.approx(0.145)
    # outcome A -> cum o = [0, 0] -> (0.25 + 0.64) / 2 = 0.445
    assert ranked_probability_score([2], [[0.5, 0.3, 0.2]]) == pytest.approx(0.445)
    # perfect forecast
    assert ranked_probability_score([1], [[0, 1, 0]]) == pytest.approx(0.0)


def test_log_loss_handles_zero_probability() -> None:
    assert np.isfinite(log_loss([1], [[1.0, 0.0, 0.0]]))


def test_ece_perfectly_calibrated_and_overconfident() -> None:
    # Confidence 0.6 in bin (0.5, 0.6]; 60 % correct -> ECE 0.
    p = np.tile([0.6, 0.2, 0.2], (10, 1))
    y = np.array([0] * 6 + [1] * 4)
    assert expected_calibration_error(y, p) == pytest.approx(0.0, abs=1e-12)
    # Same confidence but only 30 % correct -> ECE 0.3.
    y_bad = np.array([0] * 3 + [1] * 7)
    assert expected_calibration_error(y_bad, p) == pytest.approx(0.3)


def test_evaluate_bundle(sample: tuple[np.ndarray, np.ndarray]) -> None:
    y, p = sample
    result = evaluate(y, p)
    assert result.n == 500
    assert result.to_dict()["log_loss"] == pytest.approx(log_loss(y, p))
    assert 0 <= result.ece <= 1


def test_validation_errors() -> None:
    with pytest.raises(ValueError):
        log_loss([0, 1], [[0.5, 0.3, 0.2]])
    with pytest.raises(ValueError):
        log_loss([], np.empty((0, 3)))
    with pytest.raises(ValueError):
        log_loss([3], [[0.5, 0.3, 0.2]])
