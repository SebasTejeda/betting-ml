import numpy as np
import pytest

from betting_ml.domain.odds import (
    expected_value,
    fair_odds,
    implied_probabilities,
    kelly_fraction,
    normalize,
    normalize_proportional,
    normalize_shin,
    overround,
    shin_z,
)

ODDS = (2.0, 3.5, 4.0)
# 1/2 + 1/3.5 + 1/4 = 0.5 + 0.285714... + 0.25
EXPECTED_OVERROUND = 0.5 + 1 / 3.5 + 0.25 - 1


def test_implied_probabilities() -> None:
    np.testing.assert_allclose(implied_probabilities(ODDS), [0.5, 1 / 3.5, 0.25])


def test_overround_known_case() -> None:
    assert overround(ODDS) == pytest.approx(EXPECTED_OVERROUND, abs=1e-12)
    assert overround(ODDS) == pytest.approx(0.035714285714, abs=1e-9)


def test_overround_vectorised() -> None:
    result = overround([ODDS, (3.0, 3.0, 3.0)])
    np.testing.assert_allclose(result, [EXPECTED_OVERROUND, 0.0], atol=1e-12)


def test_proportional_sums_to_one() -> None:
    probs = normalize_proportional(ODDS)
    assert probs.sum() == pytest.approx(1.0)
    np.testing.assert_allclose(probs, np.array([0.5, 1 / 3.5, 0.25]) / (1 + EXPECTED_OVERROUND))


def test_shin_sums_to_one_and_z_positive() -> None:
    probs = normalize_shin(ODDS)
    assert probs.sum() == pytest.approx(1.0, abs=1e-12)
    z = shin_z(ODDS)
    assert 0 < z < 0.1


def test_shin_matches_closed_form() -> None:
    odds = np.array(ODDS)
    z = shin_z(odds)
    implied = 1 / odds
    total = implied.sum()
    expected = (np.sqrt(z**2 + 4 * (1 - z) * implied**2 / total) - z) / (2 * (1 - z))
    np.testing.assert_allclose(normalize_shin(odds), expected / expected.sum(), atol=1e-10)
    assert expected.sum() == pytest.approx(1.0, abs=1e-9)


def test_shin_favourite_longshot_correction() -> None:
    """Shin moves more probability away from the longshot than proportional does."""
    odds = (1.3, 5.5, 11.0)
    shin = normalize_shin(odds)
    prop = normalize_proportional(odds)
    assert shin[0] > prop[0]
    assert shin[2] < prop[2]


def test_shin_without_margin_equals_proportional() -> None:
    odds = (2.0, 4.0, 4.0)  # exactly fair
    np.testing.assert_allclose(normalize_shin(odds), [0.5, 0.25, 0.25], atol=1e-12)
    assert shin_z(odds) == 0.0


def test_shin_vectorised_with_missing_rows() -> None:
    odds = np.array([ODDS, (np.nan, 3.0, 3.0), (1.5, 4.0, 6.5)])
    probs = normalize_shin(odds)
    assert probs.shape == (3, 3)
    assert np.isnan(probs[1]).all()
    np.testing.assert_allclose(probs[[0, 2]].sum(axis=1), 1.0)
    np.testing.assert_allclose(probs[0], normalize_shin(ODDS))


def test_normalize_dispatch() -> None:
    np.testing.assert_allclose(normalize(ODDS, "proportional"), normalize_proportional(ODDS))
    np.testing.assert_allclose(normalize(ODDS), normalize_shin(ODDS))
    with pytest.raises(ValueError):
        normalize(ODDS, "power")  # type: ignore[arg-type]


def test_invalid_shape() -> None:
    with pytest.raises(ValueError):
        overround([[2.0]])


def test_fair_odds() -> None:
    np.testing.assert_allclose(fair_odds([0.5, 0.25, 0.25]), [2.0, 4.0, 4.0])
    assert np.isinf(fair_odds([0.0]))[0]


def test_expected_value() -> None:
    assert expected_value(0.5, 2.1) == pytest.approx(0.05)
    np.testing.assert_allclose(expected_value([0.2333], [4.5]), [0.04985])


def test_kelly_fraction() -> None:
    # full Kelly = (0.5*2.1 - 1) / 1.1 = 0.04545; 25 % = 0.01136
    assert kelly_fraction(0.5, 2.1) == pytest.approx(0.25 * 0.05 / 1.1)
    # negative edge -> no stake
    assert kelly_fraction(0.4, 2.0) == 0.0
    # large edge -> capped at 2 %
    assert kelly_fraction(0.8, 3.0) == pytest.approx(0.02)
    # contract example: p=0.2333, odds=4.5 -> ~0.0036
    assert kelly_fraction(0.2333, 4.5) == pytest.approx(0.00356, abs=1e-4)
    # invalid odds -> 0
    assert kelly_fraction(0.5, 1.0) == 0.0


def test_kelly_parameter_validation() -> None:
    with pytest.raises(ValueError):
        kelly_fraction(0.5, 2.0, fraction=0)
    with pytest.raises(ValueError):
        kelly_fraction(0.5, 2.0, cap=0)
