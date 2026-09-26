"""Generic wrapper for scikit-learn compatible classifiers (logistic, XGBoost, LightGBM)
with feature selection by groups, plus an Optuna-tuned LightGBM (E08)."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any, Literal

import numpy as np
import pandas as pd
from sklearn.base import ClassifierMixin
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from betting_ml.config import FeaturesFile, load_features
from betting_ml.domain.metrics import log_loss
from betting_ml.ml.features.pipeline import select_feature_columns
from betting_ml.ml.models.base import BaseProbabilisticModel, normalize_rows, played, targets

logger = logging.getLogger(__name__)

EstimatorKind = Literal["logistic", "xgboost", "lightgbm"]
SEED = 42


def build_estimator(
    kind: EstimatorKind, params: dict[str, Any] | None = None, seed: int = SEED
) -> ClassifierMixin:
    params = dict(params or {})
    if kind == "logistic":
        return LogisticRegression(max_iter=2000, **{"C": 1.0, **params})
    if kind == "xgboost":
        from xgboost import XGBClassifier

        defaults = {
            "n_estimators": 300,
            "learning_rate": 0.03,
            "max_depth": 3,
            "subsample": 0.8,
            "colsample_bytree": 0.8,
            "min_child_weight": 5,
            "reg_lambda": 1.0,
        }
        return XGBClassifier(
            objective="multi:softprob",
            eval_metric="mlogloss",
            random_state=seed,
            n_jobs=4,
            **{**defaults, **params},
        )
    if kind == "lightgbm":
        from lightgbm import LGBMClassifier

        defaults = {
            "n_estimators": 300,
            "learning_rate": 0.03,
            "num_leaves": 15,
            "min_child_samples": 50,
            "subsample": 0.8,
            "subsample_freq": 1,
            "colsample_bytree": 0.8,
            "reg_lambda": 1.0,
        }
        return LGBMClassifier(
            objective="multiclass",
            random_state=seed,
            n_jobs=4,
            verbose=-1,
            **{**defaults, **params},
        )
    raise ValueError(f"unknown estimator kind {kind!r}")


class SklearnModel(BaseProbabilisticModel):
    """Imputation (+ scaling for linear models) + classifier over the selected feature groups."""

    def __init__(
        self,
        kind: EstimatorKind,
        groups: Sequence[str],
        params: dict[str, Any] | None = None,
        name: str | None = None,
        features_config: FeaturesFile | None = None,
        seed: int = SEED,
    ) -> None:
        self.kind = kind
        self.groups = list(groups)
        self.params = dict(params or {})
        self.seed = seed
        self.features_config = features_config or load_features()
        self.uses_odds = "market" in self.groups
        self.name = name or f"{kind}[{'+'.join(self.groups)}]"
        self.feature_names: list[str] = []
        self.pipeline: Pipeline | None = None

    def _make_pipeline(self, params: dict[str, Any] | None = None) -> Pipeline:
        steps: list[tuple[str, Any]] = [("impute", SimpleImputer(strategy="median"))]
        if self.kind == "logistic":
            steps.append(("scale", StandardScaler()))
        steps.append(("model", build_estimator(self.kind, params or self.params, self.seed)))
        return Pipeline(steps)

    def select(self, frame: pd.DataFrame) -> list[str]:
        return select_feature_columns(frame.columns, self.groups, self.features_config)

    def fit(self, train: pd.DataFrame) -> SklearnModel:
        data = played(train)
        self.feature_names = self.select(data)
        if not self.feature_names:
            raise ValueError(f"no features selected for groups {self.groups}")
        self.pipeline = self._make_pipeline()
        self.pipeline.fit(data[self.feature_names], targets(data))
        return self

    def predict_proba(self, matches: pd.DataFrame) -> np.ndarray:
        if self.pipeline is None:
            raise RuntimeError("model not fitted")
        raw = self.pipeline.predict_proba(matches[self.feature_names])
        classes = list(self.pipeline.classes_)
        proba = np.zeros((len(matches), 3))
        for i, cls in enumerate(classes):
            proba[:, int(cls)] = raw[:, i]
        return normalize_rows(proba)

    def describe(self) -> dict[str, object]:
        return {
            **super().describe(),
            "kind": self.kind,
            "groups": self.groups,
            "params": self.params,
            "n_features": len(self.feature_names),
        }


def inner_split(train: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Last training season as internal validation (plan.md §5)."""
    seasons = sorted(train["season"].unique())
    if len(seasons) < 2:
        raise ValueError("need at least two seasons for internal validation")
    return train[train["season"].isin(seasons[:-1])], train[train["season"] == seasons[-1]]


class OptunaLightGBM(SklearnModel):
    """LightGBM whose hyperparameters are tuned with Optuna on the internal validation
    season of each fold (never on the fold's validation data)."""

    def __init__(
        self, groups: Sequence[str], n_trials: int = 40, name: str | None = None, **kwargs: Any
    ) -> None:
        super().__init__(
            "lightgbm", groups, name=name or f"lightgbm_optuna[{'+'.join(groups)}]", **kwargs
        )
        self.n_trials = n_trials
        self.best_params: dict[str, Any] = {}
        self.inner_log_loss: float = float("nan")

    def _suggest(self, trial: Any) -> dict[str, Any]:
        return {
            "learning_rate": trial.suggest_float("learning_rate", 0.01, 0.1, log=True),
            "num_leaves": trial.suggest_int("num_leaves", 4, 48),
            "min_child_samples": trial.suggest_int("min_child_samples", 20, 300, log=True),
            "subsample": trial.suggest_float("subsample", 0.5, 1.0),
            "colsample_bytree": trial.suggest_float("colsample_bytree", 0.3, 1.0),
            "reg_lambda": trial.suggest_float("reg_lambda", 1e-3, 30.0, log=True),
            "reg_alpha": trial.suggest_float("reg_alpha", 1e-3, 10.0, log=True),
            "n_estimators": trial.suggest_int("n_estimators", 100, 1200, log=True),
        }

    def fit(self, train: pd.DataFrame) -> OptunaLightGBM:
        import optuna

        optuna.logging.set_verbosity(optuna.logging.WARNING)
        data = played(train)
        self.feature_names = self.select(data)
        inner_train, inner_valid = inner_split(data)
        x_tr, y_tr = inner_train[self.feature_names], targets(inner_train)
        x_va, y_va = inner_valid[self.feature_names], targets(inner_valid)

        def objective(trial: Any) -> float:
            pipeline = self._make_pipeline({**self.params, **self._suggest(trial)})
            pipeline.fit(x_tr, y_tr)
            return log_loss(y_va, pipeline.predict_proba(x_va))

        study = optuna.create_study(
            direction="minimize", sampler=optuna.samplers.TPESampler(seed=self.seed)
        )
        study.optimize(objective, n_trials=self.n_trials)
        self.best_params = {**self.params, **study.best_params}
        self.inner_log_loss = float(study.best_value)
        logger.info("Optuna best inner log loss %.4f with %s", study.best_value, study.best_params)
        self.pipeline = self._make_pipeline(self.best_params)
        self.pipeline.fit(data[self.feature_names], targets(data))
        return self

    def describe(self) -> dict[str, object]:
        return {**super().describe(), "n_trials": self.n_trials, "best_params": self.best_params}
