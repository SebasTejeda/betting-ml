"""Baselines (E01): league frequencies and margin-free market probabilities."""

from __future__ import annotations

from typing import Literal

import numpy as np
import pandas as pd

from betting_ml.domain.odds import NormalizationMethod, normalize
from betting_ml.ml.models.base import BaseProbabilisticModel, played, targets

MarketSource = Literal["avg", "ps", "psc", "avgc", "b365"]


class FrequencyBaseline(BaseProbabilisticModel):
    """Historical H/D/A frequencies per league (global frequencies for unseen leagues)."""

    uses_odds = False

    def __init__(self) -> None:
        self.name = "frequencies"
        self.by_league: dict[str, np.ndarray] = {}
        self.overall = np.full(3, 1 / 3)

    def fit(self, train: pd.DataFrame) -> FrequencyBaseline:
        data = played(train)
        self.overall = np.bincount(targets(data), minlength=3) / len(data)
        self.by_league = {
            str(league): np.bincount(targets(group), minlength=3) / len(group)
            for league, group in data.groupby("league")
        }
        return self

    def predict_proba(self, matches: pd.DataFrame) -> np.ndarray:
        return np.vstack([self.by_league.get(lg, self.overall) for lg in matches["league"]])


class MarketBaseline(BaseProbabilisticModel):
    """Implied probabilities of an odds source after removing the margin.

    Pre-closing (`avg`) is the realistic benchmark; Pinnacle closing (`psc`) the sharpest one.
    Closing odds are only used here as an evaluation reference, never as model features.
    Rows without odds fall back to league frequencies; `coverage` reports the share with odds.
    """

    uses_odds = True

    def __init__(self, source: MarketSource = "avg", method: NormalizationMethod = "shin") -> None:
        self.source = source
        self.method = method
        self.name = f"market_{source}_{method}"
        self.fallback = FrequencyBaseline()
        self.coverage: float = float("nan")

    @property
    def odds_columns(self) -> list[str]:
        return [f"{self.source}_odds_{s}" for s in ("h", "d", "a")]

    def fit(self, train: pd.DataFrame) -> MarketBaseline:
        self.fallback.fit(train)
        return self

    def available(self, matches: pd.DataFrame) -> np.ndarray:
        return matches[self.odds_columns].notna().all(axis=1).to_numpy()

    def predict_proba(self, matches: pd.DataFrame) -> np.ndarray:
        probs = normalize(matches[self.odds_columns].to_numpy(dtype=float), self.method)
        ok = self.available(matches)
        self.coverage = float(ok.mean()) if len(ok) else float("nan")
        if not ok.all():
            probs[~ok] = self.fallback.predict_proba(matches.loc[~ok])
        return probs

    def describe(self) -> dict[str, object]:
        return {**super().describe(), "source": self.source, "method": self.method}
