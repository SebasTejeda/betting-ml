"""Model combinations whose weights are learned on the internal validation season:
linear pool (blend) and stacking with a multinomial logistic meta-model."""

from __future__ import annotations

import copy
from collections.abc import Sequence

import numpy as np
import pandas as pd
from scipy.optimize import minimize
from sklearn.linear_model import LogisticRegression

from betting_ml.domain.metrics import log_loss
from betting_ml.domain.ports import ProbabilisticModel
from betting_ml.ml.models.base import BaseProbabilisticModel, normalize_rows, played, targets
from betting_ml.ml.models.sklearn_models import inner_split


def _inner_predictions(
    templates: Sequence[ProbabilisticModel], train: pd.DataFrame
) -> tuple[list[np.ndarray], np.ndarray]:
    inner_train, inner_valid = inner_split(played(train))
    preds = [copy.deepcopy(m).fit(inner_train).predict_proba(inner_valid) for m in templates]
    return preds, targets(inner_valid)


def optimal_blend_weights(preds: Sequence[np.ndarray], y: np.ndarray) -> np.ndarray:
    """Simplex weights minimising the log loss of the linear pool."""
    k = len(preds)

    def loss(z: np.ndarray) -> float:
        w = np.exp(z - z.max())
        w /= w.sum()
        return log_loss(y, sum(wi * p for wi, p in zip(w, preds, strict=True)))

    z = minimize(loss, np.zeros(k), method="Nelder-Mead", options={"xatol": 1e-4, "fatol": 1e-7}).x
    w = np.exp(z - z.max())
    return w / w.sum()


class BlendModel(BaseProbabilisticModel):
    def __init__(
        self,
        models: Sequence[ProbabilisticModel],
        weights: Sequence[float] | None = None,
        name: str | None = None,
    ) -> None:
        self.templates = list(models)
        self.fixed_weights = None if weights is None else np.asarray(weights, dtype=float)
        self.weights = self.fixed_weights
        self.uses_odds = any(m.uses_odds for m in self.templates)
        self.name = name or "blend(" + ", ".join(m.name for m in self.templates) + ")"
        self.models: list[ProbabilisticModel] = []

    def fit(self, train: pd.DataFrame) -> BlendModel:
        if self.fixed_weights is None:
            preds, y = _inner_predictions(self.templates, train)
            self.weights = optimal_blend_weights(preds, y)
        self.models = [copy.deepcopy(m).fit(train) for m in self.templates]
        return self

    def predict_proba(self, matches: pd.DataFrame) -> np.ndarray:
        assert self.weights is not None
        preds = [m.predict_proba(matches) for m in self.models]
        return normalize_rows(sum(w * p for w, p in zip(self.weights, preds, strict=True)))

    def describe(self) -> dict[str, object]:
        weights = None if self.weights is None else [round(float(w), 4) for w in self.weights]
        return {
            **super().describe(),
            "members": [m.name for m in self.templates],
            "weights": weights,
        }


class StackingModel(BaseProbabilisticModel):
    """Multinomial logistic regression over the log-probabilities of the base models."""

    def __init__(
        self, models: Sequence[ProbabilisticModel], C: float = 1.0, name: str | None = None
    ) -> None:
        self.templates = list(models)
        self.C = C
        self.uses_odds = any(m.uses_odds for m in self.templates)
        self.name = name or "stack(" + ", ".join(m.name for m in self.templates) + ")"
        self.meta = LogisticRegression(C=C, max_iter=2000)
        self.models: list[ProbabilisticModel] = []

    @staticmethod
    def _meta_features(preds: Sequence[np.ndarray]) -> np.ndarray:
        return np.hstack([np.log(normalize_rows(p)) for p in preds])

    def fit(self, train: pd.DataFrame) -> StackingModel:
        preds, y = _inner_predictions(self.templates, train)
        self.meta.fit(self._meta_features(preds), y)
        self.models = [copy.deepcopy(m).fit(train) for m in self.templates]
        return self

    def predict_proba(self, matches: pd.DataFrame) -> np.ndarray:
        preds = [m.predict_proba(matches) for m in self.models]
        raw = self.meta.predict_proba(self._meta_features(preds))
        proba = np.zeros((len(matches), 3))
        for i, cls in enumerate(self.meta.classes_):
            proba[:, int(cls)] = raw[:, i]
        return normalize_rows(proba)

    def describe(self) -> dict[str, object]:
        return {**super().describe(), "members": [m.name for m in self.templates], "C": self.C}
