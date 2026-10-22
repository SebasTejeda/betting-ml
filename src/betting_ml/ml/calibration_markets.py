"""Calibration of the derived goal markets and Over/Under 2.5 value backtest (spec 003, US1).

Every probability comes from an out-of-sample score matrix (`goal_model.validation_matrices`).
A *group* is what gets one confidence level: a market at one line (``totals:2.5``), one team
of ``team_totals`` at one line (``team_totals:home:1.5``) or a market without lines (``h2h``).

Calibration metrics are binary and pooled over the selections of a group (every selection is a
yes/no event): log loss, Brier and ECE with 10 equal-width bins. The baseline is the frequency
of each selection in the same league during the fold's training seasons. Draw no bet is
evaluated on decided matches only (a draw returns the stake), with p = P(win) / (1 − P(draw)).

Confidence (spec US1): ``alta`` if ECE < 0.02 and the model beats the baseline (log loss and
Brier), ``media`` if ECE < 0.04, ``baja`` otherwise.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

import numpy as np
import pandas as pd

from betting_ml.domain.markets import (
    SELECTIONS,
    TOP_CORRECT_SCORES,
    Market,
    MarketSpec,
    selection_mask,
)
from betting_ml.domain.odds import normalize_shin
from betting_ml.ml.betting import bootstrap_roi, max_drawdown

N_BINS = 10
HIGH_ECE = 0.02
MEDIUM_ECE = 0.04
MIN_CURVE_BIN = 10
EPS = 1e-12
GRID = 11

Confidence = Literal["alta", "media", "baja"]


@dataclass(frozen=True)
class Group:
    market: Market
    line: float | None = None
    team: str | None = None  # "home" / "away" for team_totals

    @property
    def key(self) -> str:
        parts = [self.market.value]
        if self.team:
            parts.append(self.team)
        if self.line is not None:
            parts.append(f"{self.line:g}")
        return ":".join(parts)

    @property
    def selections(self) -> tuple[str, ...]:
        if self.market is Market.CORRECT_SCORE:
            return ()
        options = SELECTIONS[self.market]
        assert options is not None
        if self.team:
            return tuple(s for s in options if s.startswith(f"{self.team}_"))
        return options


def groups_for(specs: Iterable[MarketSpec]) -> list[Group]:
    out: list[Group] = []
    for spec in specs:
        if spec.market is Market.TEAM_TOTALS:
            out += [
                Group(spec.market, line, team) for team in ("home", "away") for line in spec.lines
            ]
        elif spec.lines:
            out += [Group(spec.market, line) for line in spec.lines]
        else:
            out.append(Group(spec.market))
    return out


def _goals(frame: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    home = np.clip(frame["home_goals"].to_numpy(dtype=int), 0, GRID - 1)
    away = np.clip(frame["away_goals"].to_numpy(dtype=int), 0, GRID - 1)
    return home, away


def selection_records(scored: pd.DataFrame, groups: Sequence[Group]) -> pd.DataFrame:
    """One row per (match, selection): model probability ``p`` and outcome ``y`` (1/0).

    ``scored`` has ``match_id``, ``fold``, ``league``, ``home_goals``, ``away_goals`` and
    ``matrix``. Voided bets (draw no bet on a draw) are dropped."""
    if scored.empty:
        return pd.DataFrame(columns=["match_id", "fold", "league", "group", "selection", "p", "y"])
    mats = np.stack(scored["matrix"].to_numpy())
    home, away = _goals(scored)
    base = scored[["match_id", "fold", "league"]].reset_index(drop=True)
    parts: list[pd.DataFrame] = []
    for group in groups:
        if group.market is Market.CORRECT_SCORE:
            flat = mats.reshape(len(mats), -1)
            order = np.argsort(-flat, axis=1, kind="stable")[:, :TOP_CORRECT_SCORES]
            for rank in range(TOP_CORRECT_SCORES):
                cell = order[:, rank]
                r, c = np.divmod(cell, GRID)
                parts.append(
                    base.assign(
                        group=group.key,
                        selection=[f"{a}-{b}" for a, b in zip(r, c, strict=True)],
                        p=flat[np.arange(len(flat)), cell],
                        y=((home == r) & (away == c)).astype(float),
                    )
                )
            continue
        for sel in group.selections:
            won, void = selection_mask(group.market, sel, group.line, GRID)
            p_win = (mats * won).sum(axis=(1, 2))
            p_void = (mats * void).sum(axis=(1, 2))
            decided = ~void[home, away]
            p = p_win / np.clip(1.0 - p_void, EPS, None)
            part = base.assign(group=group.key, selection=sel, p=p, y=won[home, away].astype(float))
            parts.append(part[decided])
    return pd.concat(parts, ignore_index=True)


def _smoothed(events: np.ndarray) -> float:
    return float((events.sum() + 0.5) / (events.size + 1))


def baseline_rates(train: pd.DataFrame, groups: Sequence[Group]) -> pd.DataFrame:
    """Frequency of every selection per league in ``train`` (the naive forecast), smoothed as
    (k + 0.5) / (n + 1) so that an event never seen in training is not given probability 0.

    Correct scores: frequency of each exact score; draw no bet: among decided matches."""
    home, away = _goals(train)
    leagues = train["league"].to_numpy()
    rows: list[dict[str, Any]] = []
    for league in np.unique(leagues):
        mask = leagues == league
        h, a = home[mask], away[mask]
        for group in groups:
            if group.market is Market.CORRECT_SCORE:
                for i in range(GRID):
                    for j in range(GRID):
                        rate = _smoothed((h == i) & (a == j))
                        rows.append(
                            {
                                "league": league,
                                "group": group.key,
                                "selection": f"{i}-{j}",
                                "rate": rate,
                            }
                        )
                continue
            for sel in group.selections:
                won, void = selection_mask(group.market, sel, group.line, GRID)
                decided = ~void[h, a]
                rate = _smoothed(won[h, a][decided])
                rows.append({"league": league, "group": group.key, "selection": sel, "rate": rate})
    return pd.DataFrame(rows)


def binary_metrics(p: np.ndarray, y: np.ndarray, n_bins: int = N_BINS) -> dict[str, float]:
    p = np.clip(np.asarray(p, dtype=float), EPS, 1 - EPS)
    y = np.asarray(y, dtype=float)
    if p.size == 0:
        raise ValueError("no records")
    log_loss = float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))
    brier = float(np.mean((p - y) ** 2))
    edges = np.linspace(0.0, 1.0, n_bins + 1)
    bins = np.clip(np.digitize(p, edges[1:-1], right=True), 0, n_bins - 1)
    ece = 0.0
    for b in range(n_bins):
        mask = bins == b
        if mask.any():
            ece += mask.mean() * abs(y[mask].mean() - p[mask].mean())
    return {
        "log_loss": log_loss,
        "brier": brier,
        "ece": float(ece),
        "n": int(p.size),
        "mean_p": float(p.mean()),
        "rate": float(y.mean()),
    }


def calibration_curve(p: np.ndarray, y: np.ndarray, n_bins: int = N_BINS) -> list[dict[str, float]]:
    edges = np.linspace(0.0, 1.0, n_bins + 1)
    bins = np.clip(np.digitize(p, edges[1:-1], right=True), 0, n_bins - 1)
    curve = []
    for b in range(n_bins):
        mask = bins == b
        if mask.sum() >= MIN_CURVE_BIN:
            curve.append(
                {"p": float(p[mask].mean()), "rate": float(y[mask].mean()), "n": int(mask.sum())}
            )
    return curve


def confidence_level(model: dict[str, float], baseline: dict[str, float]) -> Confidence:
    beats = model["log_loss"] < baseline["log_loss"] and model["brier"] < baseline["brier"]
    if model["ece"] < HIGH_ECE and beats:
        return "alta"
    if model["ece"] < MEDIUM_ECE:
        return "media"
    return "baja"


@dataclass
class GroupCalibration:
    group: str
    market: str
    line: float | None
    team: str | None
    confidence: Confidence
    model: dict[str, float]
    baseline: dict[str, float]
    by_fold: dict[str, dict[str, float]] = field(default_factory=dict)
    by_league: dict[str, dict[str, float]] = field(default_factory=dict)
    curve: list[dict[str, float]] = field(default_factory=list)


def calibrate(records: pd.DataFrame, groups: Sequence[Group]) -> list[GroupCalibration]:
    """``records`` must carry ``p`` (model), ``p_base`` (baseline) and ``y``."""
    out: list[GroupCalibration] = []
    for group in groups:
        rec = records[records["group"] == group.key]
        if rec.empty:
            continue
        p, y, pb = rec["p"].to_numpy(), rec["y"].to_numpy(), rec["p_base"].to_numpy()
        model, baseline = binary_metrics(p, y), binary_metrics(pb, y)
        out.append(
            GroupCalibration(
                group=group.key,
                market=group.market.value,
                line=group.line,
                team=group.team,
                confidence=confidence_level(model, baseline),
                model=model,
                baseline=baseline,
                by_fold={
                    str(f): binary_metrics(g["p"].to_numpy(), g["y"].to_numpy())
                    for f, g in rec.groupby("fold")
                },
                by_league={
                    str(lg): binary_metrics(g["p"].to_numpy(), g["y"].to_numpy())
                    for lg, g in rec.groupby("league")
                },
                curve=calibration_curve(p, y),
            )
        )
    return out


# --------------------------------------------------------------------- Over/Under 2.5 backtest

OuScenario = Literal["b365", "avg", "max"]
OU_SCENARIOS: tuple[OuScenario, ...] = ("b365", "avg", "max")
OU_THRESHOLDS = (0.0, 0.02, 0.04, 0.06, 0.08, 0.10)
MIN_BETS_FOR_THRESHOLD = 300


def _ou_odds(frame: pd.DataFrame, prefix: str) -> np.ndarray:
    return frame[[f"{prefix}_over25", f"{prefix}_under25"]].to_numpy(dtype=float)


def closing_ou_probabilities(frame: pd.DataFrame) -> np.ndarray:
    """Shin probabilities of Pinnacle CLOSING Over/Under 2.5 (only for CLV)."""
    return normalize_shin(_ou_odds(frame, "psc"))


def select_ou_bets(frame: pd.DataFrame, threshold: float, scenario: OuScenario) -> pd.DataFrame:
    """At most one bet per match: the side (over/under) with the highest EV above the threshold.

    The decision uses only the model probability ``p_over`` and the scenario's PRE-closing
    price; Pinnacle's closing price is read afterwards to measure CLV."""
    p_over = frame["p_over"].to_numpy(dtype=float)
    probs = np.column_stack([p_over, 1.0 - p_over])
    price = _ou_odds(frame, scenario)
    ev = probs * price - 1.0
    masked = np.where(np.isfinite(ev) & (ev > threshold), ev, -np.inf)
    side = masked.argmax(axis=1)
    rows = np.arange(len(frame))
    chosen = np.isfinite(masked[rows, side])
    idx, side = rows[chosen], side[chosen]
    p_close = closing_ou_probabilities(frame)[idx, side]
    taken = price[idx, side]
    total = (frame["home_goals"] + frame["away_goals"]).to_numpy()[idx]
    won = np.where(side == 0, total > 2.5, total < 2.5)
    bets = pd.DataFrame(
        {
            "match_id": frame["match_id"].to_numpy()[idx],
            "date": frame["date"].to_numpy()[idx],
            "league": frame["league"].to_numpy()[idx],
            "season": frame["season"].to_numpy()[idx],
            "side": np.where(side == 0, "over", "under"),
            "odds": taken,
            "p_model": probs[idx, side],
            "ev": ev[idx, side],
            "won": won,
            "p_close": p_close,
            "clv": taken * p_close - 1.0,
        }
    )
    return bets.sort_values("date", kind="mergesort").reset_index(drop=True)


def _bootstrap_mean(values: np.ndarray, n: int = 2000, seed: int = 42) -> tuple[float, float]:
    if len(values) == 0:
        return float("nan"), float("nan")
    rng = np.random.default_rng(seed)
    means = values[rng.integers(0, len(values), size=(n, len(values)))].mean(axis=1)
    return float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))


def summarize_bets(bets: pd.DataFrame) -> dict[str, Any]:
    n = len(bets)
    profit = np.where(bets["won"].to_numpy(dtype=bool), bets["odds"].to_numpy() - 1.0, -1.0)
    clv = bets["clv"].to_numpy(dtype=float)
    clv = clv[np.isfinite(clv)]
    roi_low, roi_high = bootstrap_roi(profit, np.ones(n)) if n else (float("nan"), float("nan"))
    clv_low, clv_high = _bootstrap_mean(clv)
    cumulative = np.cumsum(profit)
    return {
        "n_bets": n,
        "over_share": float((bets["side"] == "over").mean()) if n else float("nan"),
        "hit_rate": float(bets["won"].mean()) if n else float("nan"),
        "roi_flat": float(profit.sum() / n) if n else float("nan"),
        "roi_ci_low": roi_low,
        "roi_ci_high": roi_high,
        "clv_mean": float(clv.mean()) if clv.size else float("nan"),
        "clv_ci_low": clv_low,
        "clv_ci_high": clv_high,
        "clv_positive_rate": float((clv > 0).mean()) if clv.size else float("nan"),
        "clv_n": int(clv.size),
        "max_drawdown_flat": float(max_drawdown(cumulative)),
        "cumulative_profit": [float(v) for v in cumulative],
    }


def placebo_ou_clv(frame: pd.DataFrame, scenario: OuScenario) -> dict[str, float]:
    """CLV of backing both sides of every match at the scenario price (no selection)."""
    clv = _ou_odds(frame, scenario) * closing_ou_probabilities(frame) - 1.0
    values = clv[np.isfinite(clv)]
    return {
        "n": int(values.size),
        "clv_mean": float(values.mean()) if values.size else float("nan"),
    }


def choose_threshold(results: dict[float, dict[str, Any]]) -> float | None:
    """Pre-registered rule (decisions.md): highest mean CLV among thresholds with at least
    ``MIN_BETS_FOR_THRESHOLD`` bets; ties → the lower threshold. ``None`` if none qualifies."""
    eligible = [
        (t, r["clv_mean"])
        for t, r in sorted(results.items())
        if r["n_bets"] >= MIN_BETS_FOR_THRESHOLD and np.isfinite(r["clv_mean"])
    ]
    if not eligible:
        return None
    return max(eligible, key=lambda item: (item[1], -item[0]))[0]
