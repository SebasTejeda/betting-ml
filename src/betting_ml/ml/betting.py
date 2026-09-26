"""Betting simulation (experiments.md §5): value bets with EV > threshold, at most one bet per
match, flat and capped fractional-Kelly stakes, bootstrap CI of ROI, drawdown and CLV."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from typing import Literal

import numpy as np
import pandas as pd

from betting_ml.domain.odds import expected_value, kelly_fraction, normalize_shin

THRESHOLDS = (0.02, 0.05, 0.08, 0.10)
OddsScenario = Literal["avg", "max"]
N_BOOTSTRAP = 2000
MIN_BETS_FOR_THRESHOLD = 100
SEED = 42


def odds_matrix(frame: pd.DataFrame, source: str) -> np.ndarray:
    return frame[[f"{source}_odds_{s}" for s in ("h", "d", "a")]].to_numpy(dtype=float)


def select_bets(
    frame: pd.DataFrame, proba: np.ndarray, threshold: float, scenario: OddsScenario = "avg"
) -> pd.DataFrame:
    """One bet per match: the outcome with the highest EV, if EV > threshold."""
    odds = odds_matrix(frame, scenario)
    ev = expected_value(proba, odds)
    ev = np.where(np.isfinite(ev), ev, -np.inf)
    best = ev.argmax(axis=1)
    rows = np.arange(len(frame))
    best_ev = ev[rows, best]
    chosen = best_ev > threshold
    bets = pd.DataFrame(
        {
            "match_id": frame["match_id"].to_numpy()[chosen],
            "date": frame["date"].to_numpy()[chosen],
            "league": frame["league"].to_numpy()[chosen],
            "outcome": best[chosen],
            "odds": odds[rows, best][chosen],
            "p_model": proba[rows, best][chosen],
            "ev": best_ev[chosen],
            "won": (frame["target"].to_numpy(dtype=float)[chosen] == best[chosen]),
        }
    )
    closing = _closing_fair_odds(frame)[chosen]
    bets["closing_fair_odds"] = closing[np.arange(len(bets)), bets["outcome"].to_numpy()]
    return bets.sort_values("date", kind="mergesort").reset_index(drop=True)


def _closing_fair_odds(frame: pd.DataFrame) -> np.ndarray:
    """Pinnacle closing odds without margin (Shin); NaN where unavailable/invalid."""
    closing = odds_matrix(frame, "psc")
    probs = normalize_shin(closing)
    if "closing_odds_invalid" in frame:
        probs[frame["closing_odds_invalid"].to_numpy(dtype=bool)] = np.nan
    with np.errstate(divide="ignore", invalid="ignore"):
        return 1.0 / probs


def bootstrap_roi(
    profits: np.ndarray, stakes: np.ndarray, n: int = N_BOOTSTRAP, seed: int = SEED
) -> tuple[float, float]:
    if len(profits) == 0:
        return (float("nan"), float("nan"))
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(profits), size=(n, len(profits)))
    rois = profits[idx].sum(axis=1) / stakes[idx].sum(axis=1)
    return float(np.percentile(rois, 2.5)), float(np.percentile(rois, 97.5))


def max_drawdown(cumulative: np.ndarray) -> float:
    """Largest peak-to-trough fall of a cumulative profit (or bankroll) curve."""
    if len(cumulative) == 0:
        return 0.0
    curve = np.concatenate([[0.0], cumulative])
    return float(np.max(np.maximum.accumulate(curve) - curve))


def kelly_path(bets: pd.DataFrame, fraction: float = 0.25, cap: float = 0.02) -> pd.DataFrame:
    """Sequential Kelly staking on a bankroll starting at 1 (bets ordered by date)."""
    bankroll = 1.0
    stakes, profits, curve = [], [], []
    for row in bets.itertuples():
        stake = float(kelly_fraction(row.p_model, row.odds, fraction, cap)) * bankroll
        profit = stake * (row.odds - 1.0) if row.won else -stake
        bankroll += profit
        stakes.append(stake)
        profits.append(profit)
        curve.append(bankroll)
    return pd.DataFrame({"stake": stakes, "profit": profits, "bankroll": curve})


@dataclass
class BetResult:
    scenario: str
    threshold: float
    n_bets: int
    hit_rate: float
    roi_flat: float
    roi_ci_low: float
    roi_ci_high: float
    max_drawdown_flat: float
    clv_mean: float
    clv_n: int
    roi_kelly: float
    final_bankroll_kelly: float
    max_drawdown_kelly: float
    cumulative_profit: list[float] = field(default_factory=list, repr=False)

    def summary(self) -> dict[str, float | int | str]:
        data = asdict(self)
        data.pop("cumulative_profit")
        return data


def simulate(
    frame: pd.DataFrame,
    proba: np.ndarray,
    threshold: float,
    scenario: OddsScenario = "avg",
    n_bootstrap: int = N_BOOTSTRAP,
) -> BetResult:
    bets = select_bets(frame, proba, threshold, scenario)
    n = len(bets)
    if n == 0:
        nan = float("nan")
        return BetResult(scenario, threshold, 0, nan, nan, nan, nan, 0.0, nan, 0, nan, 1.0, 0.0)
    profits = np.where(bets["won"], bets["odds"] - 1.0, -1.0)
    stakes = np.ones(n)
    low, high = bootstrap_roi(profits, stakes, n_bootstrap)
    cumulative = np.cumsum(profits)
    clv = bets["odds"] / bets["closing_fair_odds"] - 1.0
    clv = clv[np.isfinite(clv)]
    kelly = kelly_path(bets)
    kelly_staked = kelly["stake"].sum()
    return BetResult(
        scenario=scenario,
        threshold=threshold,
        n_bets=n,
        hit_rate=float(bets["won"].mean()),
        roi_flat=float(profits.sum() / n),
        roi_ci_low=low,
        roi_ci_high=high,
        max_drawdown_flat=max_drawdown(cumulative),
        clv_mean=float(clv.mean()) if len(clv) else float("nan"),
        clv_n=len(clv),
        roi_kelly=float(kelly["profit"].sum() / kelly_staked) if kelly_staked > 0 else float("nan"),
        final_bankroll_kelly=float(kelly["bankroll"].iloc[-1]),
        max_drawdown_kelly=max_drawdown(kelly["bankroll"].to_numpy() - 1.0),
        cumulative_profit=cumulative.tolist(),
    )


def choose_threshold(
    frame: pd.DataFrame,
    proba: np.ndarray,
    thresholds: Sequence[float] = THRESHOLDS,
    min_bets: int = MIN_BETS_FOR_THRESHOLD,
) -> float:
    """Threshold with the best realistic flat ROI over the validation folds (F1–F3 pooled),
    requiring at least ``min_bets`` bets; ties go to the higher (more conservative) one."""
    best, best_roi = max(thresholds), -np.inf
    for threshold in sorted(thresholds):
        result = simulate(frame, proba, threshold, "avg", n_bootstrap=1)
        if result.n_bets >= min_bets and result.roi_flat >= best_roi:
            best, best_roi = threshold, result.roi_flat
    return best
