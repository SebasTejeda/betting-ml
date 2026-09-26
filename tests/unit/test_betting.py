from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from betting_ml.ml.betting import (
    bootstrap_roi,
    choose_threshold,
    kelly_path,
    max_drawdown,
    select_bets,
    simulate,
)
from betting_ml.ml.plots import calibration_plot, roi_plot


def _frame(results: list[int], odds: list[tuple[float, float, float]]) -> pd.DataFrame:
    n = len(results)
    frame = pd.DataFrame(
        {
            "match_id": [f"m{i}" for i in range(n)],
            "date": pd.date_range("2022-08-01", periods=n, freq="D"),
            "league": "E0",
            "target": results,
        }
    )
    arr = np.array(odds, dtype=float)
    for prefix in ("avg", "max", "psc"):
        for i, s in enumerate("hda"):
            frame[f"{prefix}_odds_{s}"] = arr[:, i]
    return frame


def test_select_one_bet_per_match_with_highest_ev() -> None:
    frame = _frame([0, 2], [(2.0, 3.5, 4.0), (2.0, 3.5, 4.0)])
    proba = np.array([[0.56, 0.24, 0.20], [0.40, 0.25, 0.35]])
    bets = select_bets(frame, proba, threshold=0.05)
    # match 0: EV home 0.12 > away -0.2; match 1: EV away 0.40 is the best.
    assert list(bets["outcome"]) == [0, 2]
    assert list(bets["won"]) == [True, True]
    assert bets.loc[1, "ev"] == pytest.approx(0.40)
    assert select_bets(frame, proba, threshold=0.5).empty


def test_simulate_flat_roi_and_clv() -> None:
    frame = _frame([0, 1, 2, 0], [(2.0, 3.5, 4.0)] * 4)
    proba = np.tile([0.6, 0.2, 0.2], (4, 1))  # always bet home at 2.0 (EV 0.2)
    result = simulate(frame, proba, threshold=0.05, n_bootstrap=200)
    assert result.n_bets == 4
    assert result.hit_rate == 0.5
    assert result.roi_flat == pytest.approx((1 + 1 - 1 - 1) / 4)
    # Closing fair odds of home (Shin on 2.0/3.5/4.0) > 2.0 -> negative CLV
    assert result.clv_mean < 0
    assert result.roi_ci_low <= result.roi_flat <= result.roi_ci_high
    assert result.summary()["n_bets"] == 4
    assert "cumulative_profit" not in result.summary()


def test_simulate_without_bets() -> None:
    frame = _frame([0], [(2.0, 3.5, 4.0)])
    result = simulate(frame, np.array([[0.3, 0.3, 0.4]]), threshold=1.0)
    assert result.n_bets == 0 and np.isnan(result.roi_flat)


def test_missing_odds_and_invalid_closing() -> None:
    frame = _frame([0, 0], [(2.0, 3.5, 4.0), (2.0, 3.5, 4.0)])
    frame.loc[0, "avg_odds_h"] = np.nan
    frame["closing_odds_invalid"] = [False, True]
    bets = select_bets(frame, np.tile([0.6, 0.2, 0.2], (2, 1)), 0.05)
    assert len(bets) == 1 and bets.loc[0, "match_id"] == "m1"
    assert np.isnan(bets.loc[0, "closing_fair_odds"])


def test_bootstrap_and_drawdown() -> None:
    profits = np.array([1.0, -1.0, 1.0, -1.0] * 50)
    low, high = bootstrap_roi(profits, np.ones_like(profits), n=500)
    assert low < 0 < high
    assert np.isnan(bootstrap_roi(np.array([]), np.array([]))[0])
    assert max_drawdown(np.array([1.0, 3.0, 0.0, 2.0, -1.0])) == 4.0
    assert max_drawdown(np.array([])) == 0.0
    assert max_drawdown(np.array([-2.0])) == 2.0


def test_kelly_path_is_capped() -> None:
    bets = pd.DataFrame({"p_model": [0.9, 0.48], "odds": [3.0, 2.2], "won": [True, False]})
    path = kelly_path(bets)
    assert path.loc[0, "stake"] == pytest.approx(0.02)  # capped at 2 %
    assert path.loc[0, "bankroll"] == pytest.approx(1.04)
    assert path.loc[1, "stake"] == pytest.approx(0.25 * (0.48 * 2.2 - 1) / 1.2 * 1.04)


def test_choose_threshold_prefers_best_roi_with_enough_bets() -> None:
    rng = np.random.default_rng(3)
    n = 600
    frame = _frame(list(rng.integers(0, 3, n)), [(2.2, 3.4, 3.4)] * n)
    proba = np.tile([0.5, 0.25, 0.25], (n, 1))
    proba[:, 0] += rng.uniform(-0.05, 0.05, n)
    proba /= proba.sum(axis=1, keepdims=True)
    threshold = choose_threshold(frame, proba, min_bets=50)
    assert threshold in (0.02, 0.05, 0.08, 0.10)
    assert choose_threshold(frame, proba, min_bets=10_000) == 0.10


def test_plots_are_written(tmp_path: Path) -> None:
    rng = np.random.default_rng(0)
    proba = rng.dirichlet([3, 2, 2], size=400)
    y = np.array([rng.choice(3, p=p) for p in proba])
    assert calibration_plot(y, proba, tmp_path / "cal.png", "x").exists()
    frame = _frame(list(y), [(2.0, 3.5, 4.0)] * 400)
    results = [simulate(frame, proba, 0.05, s, n_bootstrap=10) for s in ("avg", "max")]
    results.append(simulate(frame, proba, 5.0, "avg", n_bootstrap=10))
    assert roi_plot(results, tmp_path / "roi.png", "y").exists()
