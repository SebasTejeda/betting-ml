"""Use case: retrain the champion and the best model without odds on everything available
(2014-15 … holdout + played matches of the current season) for serving (plan.md §5)."""

from __future__ import annotations

import copy
import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from betting_ml.config import FeaturesFile, LeaguesFile, with_overrides
from betting_ml.domain.ports import MatchRepository, ModelRegistry
from betting_ml.ml.features.pipeline import ALL_GROUPS, FeaturePipeline
from betting_ml.ml.models.factory import build_model

HISTORY = "history"
SHORT_KIND = {"optuna_lightgbm": "lightgbm", "dixon_coles": "dc", "poisson": "poisson"}


class HoldoutNotEvaluatedError(RuntimeError):
    pass


def production_spec(
    spec: dict[str, Any], holdout_describe: dict[str, Any] | None
) -> dict[str, Any]:
    """Optuna models are refitted with the hyper-parameters chosen in the final split
    (tuning again on the few played matches of the current season would be noise)."""
    if (
        spec.get("type") == "optuna_lightgbm"
        and holdout_describe
        and holdout_describe.get("best_params")
    ):
        return {
            "type": "sklearn",
            "kind": "lightgbm",
            "groups": spec["groups"],
            "params": holdout_describe["best_params"],
        }
    return copy.deepcopy(spec)


def model_version(entry: dict[str, Any], today: str) -> str:
    spec = entry["spec"]
    kind = spec.get("kind") or SHORT_KIND.get(spec["type"], spec["type"])
    return f"{entry['experiment_id']}-{kind}-{today}"


class TrainProduction:
    def __init__(
        self,
        repository: MatchRepository,
        registry: ModelRegistry,
        leagues: LeaguesFile,
        features: FeaturesFile,
        champion_path: Path,
        reports_dir: Path,
        production_path: Path,
        git_commit: Callable[[], str],
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.repository = repository
        self.registry = registry
        self.leagues = leagues
        self.features = features
        self.champion_path = champion_path
        self.reports_dir = reports_dir
        self.production_path = production_path
        self.git_commit = git_commit
        self.clock = clock

    def history(self) -> pd.DataFrame:
        frames = [self.repository.load("matches"), self.repository.load("holdout")]
        if self.repository.exists("current"):
            frames.append(self.repository.load("current"))
        data = pd.concat(frames, ignore_index=True)
        return data.drop_duplicates("match_id").sort_values(
            ["date", "kickoff_utc"], kind="mergesort"
        )

    def run(self) -> dict[str, Any]:
        lock = self.reports_dir / "HOLDOUT_USED.lock"
        if (
            not lock.exists()
            or json.loads(lock.read_text(encoding="utf-8")).get("status") != "completed"
        ):
            raise HoldoutNotEvaluatedError(
                "run the final holdout evaluation before training for production"
            )
        selection = json.loads(self.champion_path.read_text(encoding="utf-8"))
        holdout = json.loads(
            (self.reports_dir / "holdout_results.json").read_text(encoding="utf-8")
        )
        history = self.history()
        # Served predictions read this dataset (the API never opens the holdout file itself).
        self.repository.save(HISTORY, history)
        today = self.clock().date().isoformat()
        seasons = sorted(history["season"].unique())
        trained_on = f"{seasons[0]}..{seasons[-1]}"
        versions = {}
        for role, key in (("champion", "champion"), ("champion_no_odds", "champion_no_odds")):
            entry = selection[role]
            overrides = entry.get("feature_overrides", {})
            features = with_overrides(self.features, overrides)
            spec = production_spec(entry["spec"], holdout["models"][key].get("describe"))
            frame = FeaturePipeline(features).transform(history, ALL_GROUPS)
            model = build_model(spec, features).fit(frame)
            version = model_version(entry, today)
            metadata = {
                "version": version,
                "role": role,
                "experiment_id": entry["experiment_id"],
                "model": entry["model"],
                "uses_odds": entry["uses_odds"],
                "spec": spec,
                "feature_overrides": overrides,
                "features": getattr(model, "feature_names", []),
                "trained_on": trained_on,
                "n_matches": int(frame["target"].notna().sum()),
                "trained_at": self.clock().isoformat(timespec="seconds"),
                "data_last_match": str(history["date"].max().date()),
                "git_commit": self.git_commit(),
                "bet_threshold": entry["bet_threshold"],
                "validation_metrics": entry["validation_metrics"],
                "holdout_metrics": holdout["metrics"][key],
                "success_level": holdout["level"],
            }
            self.registry.save(version, model, metadata)
            versions[role] = version
        production = {
            "champion": versions["champion"],
            "champion_no_odds": versions["champion_no_odds"],
        }
        self.production_path.write_text(
            json.dumps(production, indent=2) + "\n", encoding="utf-8", newline="\n"
        )
        return production
