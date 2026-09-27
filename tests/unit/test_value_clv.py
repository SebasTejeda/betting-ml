from decimal import Decimal

import numpy as np
import pytest

from betting_ml.domain.clv import bet_clv, closing_fair_probability, clv
from betting_ml.domain.entities import OddsTriple, Outcome
from betting_ml.domain.odds import (
    exchange_net_odds,
    normalize,
    normalize_power,
    normalize_proportional,
    normalize_shin,
)
from betting_ml.domain.value import (
    Verdict,
    assess,
    expected_value,
    fair_probabilities,
    kelly_stake,
    reference_probabilities,
    verdict,
)

ODDS = (2.0, 3.5, 4.0)


# ---------------------------------------------------------------- power method
def test_power_sums_to_one_and_known_case() -> None:
    probs = normalize_power(ODDS)
    assert probs.sum() == pytest.approx(1.0, abs=1e-12)
    implied = 1 / np.array(ODDS)
    # recover k from one outcome and check it explains the others
    k = np.log(probs[0]) / np.log(implied[0])
    np.testing.assert_allclose(probs, implied**k, atol=1e-9)
    assert k > 1


def test_power_shrinks_longshots_more_than_proportional() -> None:
    odds = (1.3, 5.5, 11.0)
    power, prop = normalize_power(odds), normalize_proportional(odds)
    assert power[2] < prop[2] and power[0] > prop[0]


def test_power_fair_book_and_missing_rows() -> None:
    np.testing.assert_allclose(normalize_power((2.0, 4.0, 4.0)), [0.5, 0.25, 0.25], atol=1e-9)
    out = normalize_power([ODDS, (np.nan, 3.0, 3.0)])
    assert np.isnan(out[1]).all() and out[0].sum() == pytest.approx(1.0)
    np.testing.assert_allclose(normalize(ODDS, "power"), normalize_power(ODDS))


def test_all_methods_sum_to_one_property() -> None:
    rng = np.random.default_rng(0)
    for _ in range(300):
        p = rng.dirichlet([2, 1.5, 1.5])
        margin = rng.uniform(0.0, 0.12)
        odds = 1 / (p * (1 + margin))
        odds = np.maximum(odds, 1.01)
        for method in ("shin", "power", "proportional"):
            probs = normalize(odds, method)  # type: ignore[arg-type]
            assert probs.sum() == pytest.approx(1.0, abs=1e-9)
            assert (probs > 0).all()


def test_exchange_commission() -> None:
    assert exchange_net_odds(3.0, 0.05) == pytest.approx(2.9)
    np.testing.assert_allclose(exchange_net_odds([2.0, 1.5]), [1.95, 1.475])
    with pytest.raises(ValueError):
        exchange_net_odds(2.0, 1.0)


# ---------------------------------------------------------------- value
def test_fair_probabilities_and_ev() -> None:
    fair = fair_probabilities(OddsTriple(*ODDS))
    assert sum(fair.as_tuple()) == pytest.approx(1.0, abs=1e-12)
    np.testing.assert_allclose(fair.as_tuple(), normalize_shin(ODDS), atol=1e-12)
    assert expected_value(0.25, 4.4) == pytest.approx(0.10)


def test_verdict_thresholds() -> None:
    assert verdict(0.02, 0.02) is Verdict.VALUE
    assert verdict(0.019, 0.02) is Verdict.FAIR
    assert verdict(0.0, 0.02) is Verdict.FAIR
    assert verdict(-0.001, 0.02) is Verdict.AVOID
    assert Verdict.VALUE.value == "valor"


def test_kelly_stake_hand_case() -> None:
    # p=0.5, odds=2.2: full Kelly = 0.1/1.2 = 0.08333; 25 % = 0.020833 -> capped 2 % of 500 = 10.00
    assert kelly_stake(0.5, 2.2, Decimal("500")) == Decimal("10.00")
    # p=0.25, odds=4.4: full = 0.1/3.4 = 0.029412; 25 % = 0.007353 -> 3.67 (rounded down)
    assert kelly_stake(0.25, 4.4, Decimal("500")) == Decimal("3.67")
    assert kelly_stake(0.2, 4.4, Decimal("500")) == Decimal("0.00")  # negative edge
    assert kelly_stake(0.5, 1.0, Decimal("500")) == Decimal("0.00")
    assert kelly_stake(0.5, 2.2, Decimal("0")) == Decimal("0.00")
    assert isinstance(kelly_stake(0.5, 2.2, Decimal("500")), Decimal)
    with pytest.raises(ValueError):
        kelly_stake(0.5, 2.0, Decimal("1"), fraction=0)
    with pytest.raises(ValueError):
        kelly_stake(0.5, 2.0, Decimal("1"), cap_pct=0)


def test_kelly_stake_property_bounds() -> None:
    rng = np.random.default_rng(1)
    for _ in range(500):
        p = float(rng.uniform(0, 1))
        odds = float(rng.uniform(1.01, 15))
        bankroll = Decimal(str(round(float(rng.uniform(0, 5000)), 2)))
        cap = float(rng.uniform(0.001, 0.1))
        stake = kelly_stake(p, odds, bankroll, 0.25, cap)
        assert stake >= 0
        assert stake <= bankroll * Decimal(str(cap))


def test_assess() -> None:
    value = assess(0.25, 4.4, Decimal("500"), min_edge=0.02)
    assert value.verdict is Verdict.VALUE and value.suggested_stake == Decimal("3.67")
    assert value.fair_odds == pytest.approx(4.0)
    fair = assess(0.23, 4.4, Decimal("500"), min_edge=0.02)
    assert fair.verdict is Verdict.FAIR and fair.suggested_stake == Decimal("0.00")
    assert assess(0.2, 4.4, Decimal("500"), 0.02).verdict is Verdict.AVOID


def test_reference_priority() -> None:
    pin = OddsTriple(1.95, 3.9, 4.3)
    bf = OddsTriple(2.0, 4.0, 4.5)
    ref = reference_probabilities({"pinnacle": pin, "betfair_ex_eu": bf, "betsson": bf})
    assert ref is not None and ref.source == "pinnacle"
    fallback = reference_probabilities({"betfair_ex_uk": bf}, commission=0.05)
    assert fallback is not None and fallback.source == "betfair_ex_uk"
    net = OddsTriple(*(float(x) for x in exchange_net_odds(bf.as_tuple(), 0.05)))
    assert fallback.probabilities == fair_probabilities(net)
    assert reference_probabilities({"betsson": bf}) is None
    assert ref.fair_odds[0] == pytest.approx(1 / ref.probabilities.home)


# ---------------------------------------------------------------- clv
def test_clv() -> None:
    assert clv(4.6, 0.23) == pytest.approx(0.058)
    assert clv(2.0, 0.5) == pytest.approx(0.0)
    with pytest.raises(ValueError):
        clv(1.0, 0.5)
    with pytest.raises(ValueError):
        clv(2.0, 0.0)
    closing = OddsTriple(1.95, 3.9, 4.3)
    p_away = closing_fair_probability(closing, Outcome.AWAY)
    assert bet_clv(4.6, Outcome.AWAY, closing) == pytest.approx(4.6 * p_away - 1)
    assert bet_clv(4.6, Outcome.AWAY, None) is None
