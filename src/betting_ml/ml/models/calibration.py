"""Post-hoc calibration fitted on the internal validation season (never on the fold's
validation data): isotonic (one-vs-rest) or temperature scaling."""

from __future__ import annotations

import copy
from typing import Literal

import numpy as np
import pandas as pd
from scipy.optimize import minimize_scalar
from sklearn.isotonic import IsotonicRegression

from betting_ml.domain.metrics import log_loss
from betting_ml.domain.ports import ProbabilisticModel
from betting_ml.ml.models.base import BaseProbabilisticModel, normalize_rows, played, targets
from betting_ml.ml.models.sklearn_models import inner_split

CalibrationMethod = Literal["isotonic", "temperature"]


class TemperatureScaler:
    def __init__(self) -> None:
        self.temperature = 1.0

    def fit(self, proba: np.ndarray, y: np.ndarray) -> TemperatureScaler:
        logp = np.log(normalize_rows(proba))
        result = minimize_scalar(
            lambda t: log_loss(y, self._apply(logp, t)), bounds=(0.3, 5.0), method="bounded"
        )
        self.temperature = float(result.x)
        return self

    @staticmethod
    def _apply(logp: np.ndarray, temperature: float) -> np.ndarray:
        scaled = logp / temperature
        scaled -= scaled.max(axis=1, keepdims=True)
        return normalize_rows(np.exp(scaled))

    def transform(self, proba: np.ndarray) -> np.ndarray:
        return self._apply(np.log(normalize_rows(proba)), self.temperature)


class IsotonicCalibrator:
    def __init__(self) -> None:
        self.models: list[IsotonicRegression] = []

    def fit(self, proba: np.ndarray, y: np.ndarray) -> IsotonicCalibrator:
        self.models = []
        for k in range(proba.shape[1]):
            iso = IsotonicRegression(y_min=1e-4, y_max=1 - 1e-4, out_of_bounds="clip")
            iso.fit(proba[:, k], (y == k).astype(float))
            self.models.append(iso)
        return self

    def transform(self, proba: np.ndarray) -> np.ndarray:
        cols = [m.predict(proba[:, k]) for k, m in enumerate(self.models)]
        return normalize_rows(np.column_stack(cols))


class CalibratedModel(BaseProbabilisticModel):
    def __init__(self, base: ProbabilisticModel, method: CalibrationMethod = "temperature") -> None:
        self.template = base
        self.method = method
        self.name = f"{base.name}+{method}"
        self.uses_odds = base.uses_odds
        self.base: ProbabilisticModel | None = None
        self.calibrator: TemperatureScaler | IsotonicCalibrator = (
            TemperatureScaler() if method == "temperature" else IsotonicCalibrator()
        )

    def fit(self, train: pd.DataFrame) -> CalibratedModel:
        data = played(train)
        inner_train, inner_valid = inner_split(data)
        inner_model = copy.deepcopy(self.template).fit(inner_train)
        self.calibrator.fit(inner_model.predict_proba(inner_valid), targets(inner_valid))
        self.base = copy.deepcopy(self.template).fit(data)
        return self

    def predict_proba(self, matches: pd.DataFrame) -> np.ndarray:
        if self.base is None:
            raise RuntimeError("model not fitted")
        return self.calibrator.transform(self.base.predict_proba(matches))

    def predict_goal_matrix(self, matches: pd.DataFrame) -> np.ndarray | None:
        return None

    def describe(self) -> dict[str, object]:
        extra: dict[str, object] = {"base": self.template.name, "method": self.method}
        if isinstance(self.calibrator, TemperatureScaler):
            extra["temperature"] = self.calibrator.temperature
        return {**super().describe(), **extra}
