"""Bookmaker margins and the price improvement of taking the best available odds — the
evidence behind the odds comparator (spec 002, reoriented after the T008 gate)."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import numpy as np
import pandas as pd

SIDES = ("h", "d", "a")


def _odds(frame: pd.DataFrame, prefix: str) -> pd.DataFrame:
    return frame[[f"{prefix}_odds_{s}" for s in SIDES]]


def margin_summary(
    frame: pd.DataFrame, prefixes: Sequence[str] = ("avg", "b365", "ps", "max")
) -> dict[str, dict[str, Any]]:
    """Mean overround (sum of implied probabilities − 1) of each odds source."""
    out = {}
    for prefix in prefixes:
        odds = _odds(frame, prefix).dropna()
        margin = (1.0 / odds).sum(axis=1) - 1.0
        out[prefix] = {
            "n_matches": len(odds),
            "margin_mean": float(margin.mean()) if len(odds) else float("nan"),
        }
    return out


def best_price_uplift(frame: pd.DataFrame, versus: str) -> dict[str, Any]:
    """How much higher the best price is than ``versus`` for the same outcome (all outcomes)."""
    both = frame[[f"{p}_odds_{s}" for p in ("max", versus) for s in SIDES]].dropna()
    ratio = np.concatenate([both[f"max_odds_{s}"] / both[f"{versus}_odds_{s}"] for s in SIDES])
    return {
        "n_quotes": int(ratio.size),
        "uplift_mean": float(ratio.mean() - 1.0) if ratio.size else float("nan"),
        "uplift_median": float(np.median(ratio) - 1.0) if ratio.size else float("nan"),
    }


def market_report(frame: pd.DataFrame) -> dict[str, Any]:
    return {
        "margins": margin_summary(frame),
        "best_vs_avg": best_price_uplift(frame, "avg"),
        "best_vs_b365": best_price_uplift(frame, "b365"),
        "by_league": {
            str(league): {
                "avg_margin": margin_summary(group, ("avg",))["avg"]["margin_mean"],
                "best_margin": margin_summary(group, ("max",))["max"]["margin_mean"],
                "best_vs_avg": best_price_uplift(group, "avg")["uplift_mean"],
            }
            for league, group in frame.groupby("league")
        },
    }
