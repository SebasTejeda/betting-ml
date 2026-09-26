"""Use case: run one experiment over the walk-forward folds F1–F3 (never the holdout),
record its row in reports/experiments.csv, details, figures and predictions (US3)."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import numpy as np
import pandas as pd

from betting_ml.config import ExperimentConfig, FeaturesFile, LeaguesFile, with_overrides
from betting_ml.domain.metrics import evaluate
from betting_ml.domain.ports import ExperimentStore, MatchRepository
from betting_ml.ml.betting import choose_threshold, simulate
from betting_ml.ml.features.pipeline import ALL_GROUPS, TARGET, FeaturePipeline
from betting_ml.ml.models.factory import build_model, feature_groups
from betting_ml.ml.plots import calibration_plot, roi_plot
from betting_ml.ml.validation import walk_forward_folds

logger = logging.getLogger(__name__)
MATCHES = "matches"
OUTCOME_COLUMNS = ["p_home", "p_draw", "p_away"]


@dataclass
class VariantResult:
    row: dict[str, Any]
    details: dict[str, Any]
    predictions: pd.DataFrame


class RunExperiment:
    def __init__(
        self,
        repository: MatchRepository,
        store: ExperimentStore,
        leagues: LeaguesFile,
        features: FeaturesFile,
        git_commit: Callable[[], str],
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.repository = repository
        self.store = store
        self.leagues = leagues
        self.features = features
        self.git_commit = git_commit
        self.clock = clock

    def build_frame(self, config: ExperimentConfig) -> tuple[pd.DataFrame, FeaturesFile]:
        features = with_overrides(self.features, config.feature_overrides)
        matches = self.repository.load(MATCHES)  # training seasons only; never the holdout
        seasons = set(self.leagues.seasons.train)
        if not set(matches["season"].unique()) <= seasons:
            raise ValueError("matches dataset contains seasons outside the training range")
        return FeaturePipeline(features).transform(matches, ALL_GROUPS), features

    def run(self, config: ExperimentConfig) -> list[VariantResult]:
        frame, features = self.build_frame(config)
        results = []
        for row_id, spec in config.model_specs().items():
            result = self.evaluate_variant(row_id, config, spec, frame, features)
            self.store.upsert_row(result.row)
            self.store.save_details(row_id, result.details)
            self.store.save_predictions(row_id, result.predictions)
            results.append(result)
        return results

    def evaluate_variant(
        self,
        row_id: str,
        config: ExperimentConfig,
        spec: dict[str, Any],
        frame: pd.DataFrame,
        features: FeaturesFile,
    ) -> VariantResult:
        start = time.perf_counter()
        folds = walk_forward_folds(self.leagues.seasons.train)
        fold_metrics: dict[str, dict[str, float]] = {}
        fold_models: dict[str, dict[str, object]] = {}
        parts = []
        uses_odds = False
        for fold in folds:
            train, valid = fold.split(frame)
            model = build_model(spec, features)
            uses_odds = model.uses_odds
            if uses_odds and not config.uses_odds:
                raise ValueError(f"{row_id}: model uses odds but the YAML says uses_odds: false")
            logger.info(
                "%s %s: training %s on %d matches", row_id, fold.name, model.name, len(train)
            )
            model.fit(train)
            proba = model.predict_proba(valid)
            _check_probabilities(proba, len(valid))
            fold_metrics[fold.name] = evaluate(valid[TARGET].astype(int), proba).to_dict()
            fold_models[fold.name] = model.describe()
            part = valid.copy()
            part[OUTCOME_COLUMNS] = proba
            part["fold"] = fold.name
            parts.append(part)
        pooled = pd.concat(parts, ignore_index=True)
        proba = pooled[OUTCOME_COLUMNS].to_numpy()
        y = pooled[TARGET].astype(int).to_numpy()
        threshold = choose_threshold(pooled, proba)
        realistic = simulate(pooled, proba, threshold, "avg")
        optimistic = simulate(pooled, proba, threshold, "max")
        figures = self.store.figures_dir
        title = f"{row_id} — {config.name}"
        calibration_plot(y, proba, figures / f"{row_id}_calibration.png", title)
        roi_plot([realistic, optimistic], figures / f"{row_id}_roi.png", title)
        mean = {
            k: float(np.mean([m[k] for m in fold_metrics.values()])) for k in fold_metrics["F1"]
        }
        runtime = time.perf_counter() - start
        model_name = build_model(spec, features).name
        row = {
            "exp_id": row_id,
            "name": config.name,
            "hypothesis": config.hypothesis,
            "model": model_name,
            "feature_groups": "+".join(feature_groups(spec)) or "-",
            "uses_odds": uses_odds,
            "val_ll_f1": round(fold_metrics["F1"]["log_loss"], 5),
            "val_ll_f2": round(fold_metrics["F2"]["log_loss"], 5),
            "val_ll_f3": round(fold_metrics["F3"]["log_loss"], 5),
            "val_ll_mean": round(mean["log_loss"], 5),
            "val_brier": round(mean["brier"], 5),
            "val_rps": round(mean["rps"], 5),
            "val_ece": round(mean["ece"], 5),
            "val_acc": round(mean["accuracy"], 5),
            "bet_threshold": threshold,
            "n_bets": realistic.n_bets,
            "roi_flat": _round(realistic.roi_flat),
            "roi_ci_low": _round(realistic.roi_ci_low),
            "roi_ci_high": _round(realistic.roi_ci_high),
            "clv_mean": _round(realistic.clv_mean),
            "runtime_s": round(runtime, 1),
            "git_commit": self.git_commit(),
            "timestamp": self.clock().isoformat(timespec="seconds"),
            "conclusion": "",
        }
        details = {
            "exp_id": row_id,
            "config": config.model_dump(),
            "spec": spec,
            "folds": {
                f.name: {"train": list(f.train_seasons), "valid": f.valid_season} for f in folds
            },
            "fold_metrics": fold_metrics,
            "mean_metrics": mean,
            "models": fold_models,
            "betting": {"realistic": realistic.summary(), "optimistic": optimistic.summary()},
            "metrics_by_league": _metrics_by_league(pooled),
        }
        keep = ["match_id", "league", "season", "date", "fold", TARGET, *OUTCOME_COLUMNS]
        return VariantResult(row, details, pooled[keep])


def _round(value: float, digits: int = 5) -> float | str:
    return "" if value is None or not np.isfinite(value) else round(float(value), digits)


def _check_probabilities(proba: np.ndarray, n: int) -> None:
    if proba.shape != (n, 3) or not np.all(np.isfinite(proba)):
        raise ValueError(f"invalid probabilities with shape {proba.shape}")
    if not np.allclose(proba.sum(axis=1), 1.0, atol=1e-6):
        raise ValueError("probabilities do not sum to 1")


def _metrics_by_league(pooled: pd.DataFrame) -> dict[str, dict[str, float]]:
    out = {}
    for league, group in pooled.groupby("league"):
        metrics = evaluate(group[TARGET].astype(int), group[OUTCOME_COLUMNS].to_numpy())
        out[str(league)] = metrics.to_dict()
    return out
