"""Common helpers for `ProbabilisticModel` implementations."""

from __future__ import annotations

import numpy as np
import pandas as pd

from betting_ml.ml.features.pipeline import TARGET

EPS = 1e-12


class BaseProbabilisticModel:
    """Default implementations shared by all models (see domain.ports.ProbabilisticModel)."""

    name: str = "base"
    uses_odds: bool = False

    def fit(self, train: pd.DataFrame) -> BaseProbabilisticModel:  # pragma: no cover
        raise NotImplementedError

    def predict_proba(self, matches: pd.DataFrame) -> np.ndarray:  # pragma: no cover
        raise NotImplementedError

    def predict_goal_matrix(self, matches: pd.DataFrame) -> np.ndarray | None:
        return None

    def describe(self) -> dict[str, object]:
        return {"name": self.name, "uses_odds": self.uses_odds}


def played(frame: pd.DataFrame) -> pd.DataFrame:
    """Rows with a known result."""
    return frame[frame[TARGET].notna()] if TARGET in frame else frame.dropna(subset=["home_goals"])


def targets(frame: pd.DataFrame) -> np.ndarray:
    return frame[TARGET].to_numpy(dtype=int)


def normalize_rows(proba: np.ndarray) -> np.ndarray:
    proba = np.clip(np.asarray(proba, dtype=float), EPS, None)
    return proba / proba.sum(axis=1, keepdims=True)
