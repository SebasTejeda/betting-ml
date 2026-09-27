"""Pinnacle-reference strategy (spec 002, US1).

Decision: fair probability = Shin over Pinnacle PRE-closing odds (``ps_odds_*``). Bet the
outcome with the highest EV if ``odds × p_fair − 1 > threshold`` using the odds of a scenario
(``max`` best price, ``b365`` single soft book, ``avg`` control). Pinnacle closing odds
(``psc_odds_*``) are only used afterwards to measure CLV — never to decide.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from typing import Literal

import numpy as np
import pandas as pd

from betting_ml.domain.odds import kelly_fraction, normalize_shin
from betting_ml.ml.betting import bootstrap_roi, max_drawdown

Scenario = Literal["max", "b365", "avg"]
Variant = Literal["none", "champion", "champion_no_odds"]
SCENARIOS: tuple[Scenario, ...] = ("max", "b365", "avg")
VARIANTS: tuple[Variant, ...] = ("none", "champion", "champion_no_odds")
THRESHOLDS = (0.01, 0.02, 0.03, 0.05)
MIN_BETS_FOR_THRESHOLD = 300
ODDS_BINS = (1.0, 2.0, 3.0, 5.0, np.inf)
ODDS_BIN_LABELS = ("[1, 2)", "[2, 3)", "[3, 5)", "≥ 5")
SIDES = ("h", "d", "a")


def odds(frame: pd.DataFrame, prefix: str) -> np.ndarray:
    return frame[[f"{prefix}_odds_{s}" for s in SIDES]].to_numpy(dtype=float)


def reference_probabilities(frame: pd.DataFrame) -> np.ndarray:
    """Shin probabilities of Pinnacle pre-closing odds (NaN rows where missing)."""
    return normalize_shin(odds(frame, "ps"))


def closing_probabilities(frame: pd.DataFrame) -> np.ndarray:
    probs = normalize_shin(odds(frame, "psc"))
    if "closing_odds_invalid" in frame:
        probs[frame["closing_odds_invalid"].to_numpy(dtype=bool)] = np.nan
    return probs


def select_bets(
    frame: pd.DataFrame,
    threshold: float,
    scenario: Scenario,
    model_proba: np.ndarray | None = None,
) -> pd.DataFrame:
    """At most one bet per match: highest EV among outcomes over the threshold (and, with a
    model filter, only outcomes where ``p_model ≥ p_fair``)."""
    p_fair = reference_probabilities(frame)
    price = odds(frame, scenario)
    ev = price * p_fair - 1.0
    eligible = np.isfinite(ev) & (ev > threshold)
    if model_proba is not None:
        eligible &= model_proba >= p_fair
    masked = np.where(eligible, ev, -np.inf)
    best = masked.argmax(axis=1)
    rows = np.arange(len(frame))
    chosen = np.isfinite(masked[rows, best])
    idx = rows[chosen]
    outcome = best[chosen]
    p_close = closing_probabilities(frame)[idx, outcome]
    taken = price[idx, outcome]
    bets = pd.DataFrame(
        {
            "match_id": frame["match_id"].to_numpy()[idx],
            "date": frame["date"].to_numpy()[idx],
            "league": frame["league"].to_numpy()[idx],
            "season": frame["season"].to_numpy()[idx],
            "outcome": outcome,
            "odds": taken,
            "p_fair": p_fair[idx, outcome],
            "ev": ev[idx, outcome],
            "won": frame["target"].to_numpy(dtype=float)[idx] == outcome,
            "clv": taken * p_close - 1.0,
            "ps_odds": odds(frame, "ps")[idx, outcome],
            "psc_odds": odds(frame, "psc")[idx, outcome],
            "p_close": p_close,
            "p_model": model_proba[idx, outcome] if model_proba is not None else np.nan,
            "kelly_fraction": kelly_fraction(p_fair[idx, outcome], taken),
        }
    )
    return bets.sort_values("date", kind="mergesort").reset_index(drop=True)


def placebo_clv(frame: pd.DataFrame, scenario: Scenario, min_odds: float = 1.0) -> dict[str, float]:
    """CLV of backing EVERY outcome at the scenario price (no selection): how much CLV the
    price source has by itself, to separate it from the effect of the selection rule."""
    price = odds(frame, scenario)
    clv = price * closing_probabilities(frame) - 1.0
    ok = np.isfinite(clv) & (price >= min_odds)
    values = clv[ok]
    return {
        "n": int(values.size),
        "clv_mean": float(values.mean()) if values.size else float("nan"),
    }


@dataclass
class StrategyResult:
    scenario: str
    variant: str
    threshold: float
    n_bets: int
    hit_rate: float
    roi_flat: float
    roi_ci_low: float
    roi_ci_high: float
    clv_mean: float
    clv_ci_low: float
    clv_ci_high: float
    clv_positive_rate: float
    clv_n: int
    max_drawdown_flat: float
    roi_kelly: float
    final_bankroll_kelly: float
    by_league: dict[str, dict[str, float]] = field(default_factory=dict)
    by_odds_range: dict[str, dict[str, float]] = field(default_factory=dict)
    by_season: dict[str, dict[str, float]] = field(default_factory=dict)
    cumulative_profit: list[float] = field(default_factory=list, repr=False)

    def summary(self) -> dict[str, object]:
        data = asdict(self)
        data.pop("cumulative_profit")
        return data


def _bootstrap_mean(values: np.ndarray, n: int = 2000, seed: int = 42) -> tuple[float, float]:
    if len(values) == 0:
        return float("nan"), float("nan")
    rng = np.random.default_rng(seed)
    means = values[rng.integers(0, len(values), size=(n, len(values)))].mean(axis=1)
    return float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))


def _group(bets: pd.DataFrame, key: pd.Series) -> dict[str, dict[str, float]]:
    out = {}
    profit = np.where(bets["won"], bets["odds"] - 1.0, -1.0)
    for name, idx in bets.groupby(key, observed=True).groups.items():
        rows = bets.index.get_indexer(idx)
        clv = bets["clv"].to_numpy()[rows]
        clv = clv[np.isfinite(clv)]
        out[str(name)] = {
            "n_bets": len(rows),
            "roi": float(profit[rows].mean()),
            "clv_mean": float(clv.mean()) if len(clv) else float("nan"),
        }
    return out


def kelly_path(
    bets: pd.DataFrame, fraction: float = 0.25, cap: float = 0.02
) -> tuple[float, float]:
    """Sequential Kelly on the fair probability (bankroll 1). Returns (ROI, final bankroll)."""
    bankroll, staked, profit = 1.0, 0.0, 0.0
    for row in bets.itertuples():
        stake = float(kelly_fraction(row.p_fair, row.odds, fraction, cap)) * bankroll
        gain = stake * (row.odds - 1.0) if row.won else -stake
        bankroll += gain
        staked += stake
        profit += gain
    return (profit / staked if staked > 0 else float("nan")), bankroll


def evaluate(
    frame: pd.DataFrame,
    threshold: float,
    scenario: Scenario,
    variant: Variant = "none",
    model_proba: np.ndarray | None = None,
    n_bootstrap: int = 2000,
) -> StrategyResult:
    bets = select_bets(frame, threshold, scenario, model_proba)
    n = len(bets)
    nan = float("nan")
    if n == 0:
        return StrategyResult(
            scenario,
            variant,
            threshold,
            0,
            nan,
            nan,
            nan,
            nan,
            nan,
            nan,
            nan,
            nan,
            0,
            0.0,
            nan,
            1.0,
        )
    profit = np.where(bets["won"], bets["odds"] - 1.0, -1.0)
    low, high = bootstrap_roi(profit, np.ones(n), n_bootstrap)
    clv = bets["clv"].to_numpy()
    clv = clv[np.isfinite(clv)]
    clv_low, clv_high = _bootstrap_mean(clv, n_bootstrap)
    roi_kelly, bankroll = kelly_path(bets)
    ranges = pd.cut(bets["odds"], ODDS_BINS, right=False, labels=ODDS_BIN_LABELS)
    return StrategyResult(
        scenario=scenario,
        variant=variant,
        threshold=threshold,
        n_bets=n,
        hit_rate=float(bets["won"].mean()),
        roi_flat=float(profit.mean()),
        roi_ci_low=low,
        roi_ci_high=high,
        clv_mean=float(clv.mean()) if len(clv) else nan,
        clv_ci_low=clv_low,
        clv_ci_high=clv_high,
        clv_positive_rate=float((clv > 0).mean()) if len(clv) else nan,
        clv_n=len(clv),
        max_drawdown_flat=max_drawdown(np.cumsum(profit)),
        roi_kelly=roi_kelly,
        final_bankroll_kelly=bankroll,
        by_league=_group(bets, bets["league"]),
        by_odds_range=_group(bets, ranges),
        by_season=_group(bets, bets["season"]),
        cumulative_profit=np.cumsum(profit).tolist(),
    )


def threshold_is_default(
    frame: pd.DataFrame,
    scenario: Scenario,
    model_proba: np.ndarray | None = None,
    thresholds: Sequence[float] = THRESHOLDS,
    min_bets: int = MIN_BETS_FOR_THRESHOLD,
) -> bool:
    """True when no threshold reaches ``min_bets`` (the lowest one is used by default)."""
    return all(len(select_bets(frame, t, scenario, model_proba)) < min_bets for t in thresholds)


def choose_threshold(
    frame: pd.DataFrame,
    scenario: Scenario,
    model_proba: np.ndarray | None = None,
    thresholds: Sequence[float] = THRESHOLDS,
    min_bets: int = MIN_BETS_FOR_THRESHOLD,
) -> float:
    """Threshold with the highest mean CLV on F1–F3 among those with ≥ ``min_bets`` bets;
    ties (and the case where none qualifies) go to the lowest threshold (more bets)."""
    best, best_clv = min(thresholds), -np.inf
    for threshold in sorted(thresholds):
        bets = select_bets(frame, threshold, scenario, model_proba)
        clv = bets["clv"].to_numpy()
        clv = clv[np.isfinite(clv)]
        if len(bets) >= min_bets and len(clv) and clv.mean() > best_clv + 1e-12:
            best, best_clv = threshold, float(clv.mean())
    return best
