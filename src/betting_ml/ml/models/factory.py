"""Builds models from the `model:` block of an experiment YAML."""

from __future__ import annotations

import copy
from collections.abc import Sequence
from typing import Any

import numpy as np
import pandas as pd

from betting_ml.config import FeaturesFile
from betting_ml.domain.metrics import log_loss
from betting_ml.domain.ports import ProbabilisticModel
from betting_ml.ml.models.base import BaseProbabilisticModel, played, targets
from betting_ml.ml.models.baselines import FrequencyBaseline, MarketBaseline
from betting_ml.ml.models.calibration import CalibratedModel
from betting_ml.ml.models.ensemble import BlendModel, StackingModel
from betting_ml.ml.models.poisson import GoalModel
from betting_ml.ml.models.sklearn_models import OptunaLightGBM, SklearnModel, inner_split


class XiTunedGoalModel(BaseProbabilisticModel):
    """Goal model whose decay ξ is chosen on the internal validation season of each fold."""

    uses_odds = False

    def __init__(self, xi_grid: Sequence[float], **goal_kwargs: Any) -> None:
        self.xi_grid = list(xi_grid)
        self.goal_kwargs = goal_kwargs
        kind = "dixon_coles" if goal_kwargs.get("dixon_coles") else "poisson"
        self.name = f"{kind}_{goal_kwargs.get('target', 'goals')}_xi_tuned"
        self.inner_scores: dict[float, float] = {}
        self.best_xi: float | None = None
        self.model: GoalModel | None = None

    def fit(self, train: pd.DataFrame) -> XiTunedGoalModel:
        data = played(train)
        inner_train, inner_valid = inner_split(data)
        y = targets(inner_valid)
        self.inner_scores = {}
        for xi in self.xi_grid:
            model = GoalModel(xi=xi, **self.goal_kwargs).fit(inner_train)
            self.inner_scores[xi] = log_loss(y, model.predict_proba(inner_valid))
        self.best_xi = min(self.inner_scores, key=lambda xi: self.inner_scores[xi])
        self.model = GoalModel(xi=self.best_xi, **self.goal_kwargs).fit(data)
        return self

    def predict_proba(self, matches: pd.DataFrame) -> np.ndarray:
        if self.model is None:
            raise RuntimeError("model not fitted")
        return self.model.predict_proba(matches)

    def predict_goal_matrix(self, matches: pd.DataFrame) -> np.ndarray | None:
        if self.model is None:
            raise RuntimeError("model not fitted")
        return self.model.predict_goal_matrix(matches)

    def describe(self) -> dict[str, object]:
        return {
            **super().describe(),
            "xi_grid": self.xi_grid,
            "inner_log_loss": self.inner_scores,
            "best_xi": self.best_xi,
            **self.goal_kwargs,
        }


def build_model(
    spec: dict[str, Any], features_config: FeaturesFile | None = None
) -> ProbabilisticModel:
    spec = copy.deepcopy(spec)
    kind = spec.pop("type")
    name = spec.pop("name", None)
    model: ProbabilisticModel
    if kind == "frequencies":
        model = FrequencyBaseline()
    elif kind == "market":
        model = MarketBaseline(spec.get("source", "avg"), spec.get("method", "shin"))
    elif kind in ("poisson", "dixon_coles"):
        goal_kwargs = {
            "dixon_coles": kind == "dixon_coles",
            "target": spec.get("target", "goals"),
            "refit_days": spec.get("refit_days", 7),
            "l2": spec.get("l2", 0.5),
        }
        if "xi_grid" in spec:
            model = XiTunedGoalModel(spec["xi_grid"], **goal_kwargs)
        else:
            model = GoalModel(xi=spec.get("xi", 0.0019), **goal_kwargs)
    elif kind == "sklearn":
        model = SklearnModel(
            spec["kind"], spec["groups"], params=spec.get("params"), features_config=features_config
        )
    elif kind == "optuna_lightgbm":
        model = OptunaLightGBM(
            spec["groups"],
            n_trials=spec.get("n_trials", 40),
            params=spec.get("params"),
            features_config=features_config,
        )
    elif kind == "calibrated":
        model = CalibratedModel(
            build_model(spec["base"], features_config), spec.get("method", "temperature")
        )
    elif kind == "blend":
        members = [build_model(m, features_config) for m in spec["members"]]
        model = BlendModel(members, spec.get("weights"))
    elif kind == "stacking":
        members = [build_model(m, features_config) for m in spec["members"]]
        model = StackingModel(members, C=spec.get("C", 1.0))
    else:
        raise ValueError(f"unknown model type {kind!r}")
    if name:
        model.name = name
    return model


def feature_groups(spec: dict[str, Any]) -> list[str]:
    """Every feature group a model spec needs (recursively)."""
    groups: list[str] = list(spec.get("groups", []))
    for key in ("base",):
        if key in spec:
            groups += feature_groups(spec[key])
    for member in spec.get("members", []):
        groups += feature_groups(member)
    return list(dict.fromkeys(groups))
