"""Use case (spec 002, US1): backtest of the Pinnacle-reference strategy on the validation
folds F1–F3 (repeatable). The one-time test on 2025-26 lives in `run_final` (T007)."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from betting_ml.config import LeaguesFile
from betting_ml.domain.ports import MatchRepository
from betting_ml.ml.features.pipeline import RESULT_TO_TARGET
from betting_ml.ml.pinnacle_backtest import (
    SCENARIOS,
    THRESHOLDS,
    VARIANTS,
    Scenario,
    StrategyResult,
    Variant,
    choose_threshold,
    evaluate,
)
from betting_ml.ml.plots import cumulative_plot
from betting_ml.ml.validation import walk_forward_folds

PROBA = ["p_home", "p_draw", "p_away"]
VALIDATION_FILE = "backtest_002_validation.json"


def _key(scenario: str, variant: str) -> str:
    return f"{scenario}|{variant}"


class BacktestPinnacle:
    def __init__(
        self,
        repository: MatchRepository,
        leagues: LeaguesFile,
        champion_path: Path,
        load_predictions: Callable[[str], pd.DataFrame],
        reports_dir: Path,
        git_commit: Callable[[], str],
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.repository = repository
        self.leagues = leagues
        self.champion_path = champion_path
        self.load_predictions = load_predictions
        self.reports_dir = reports_dir
        self.git_commit = git_commit
        self.clock = clock

    # ------------------------------------------------------------------ data
    def validation_frame(self) -> tuple[pd.DataFrame, dict[str, np.ndarray]]:
        """F1–F3 validation seasons with out-of-fold model probabilities aligned."""
        matches = self.repository.load("matches")
        folds = walk_forward_folds(self.leagues.seasons.train)
        seasons = [f.valid_season for f in folds]
        frame = matches[matches["season"].isin(seasons)].copy()
        frame["target"] = frame["result"].map(RESULT_TO_TARGET)
        frame = frame.sort_values(["date", "kickoff_utc", "match_id"]).reset_index(drop=True)
        selection = json.loads(self.champion_path.read_text(encoding="utf-8"))
        models = {}
        for variant in ("champion", "champion_no_odds"):
            exp_id = selection[variant]["experiment_id"]
            preds = self.load_predictions(exp_id).set_index("match_id")[PROBA]
            aligned = preds.reindex(frame["match_id"])
            if aligned.isna().any().any():
                raise ValueError(f"missing out-of-fold predictions of {exp_id}")
            models[variant] = aligned.to_numpy()
        return frame, models

    # ------------------------------------------------------------------ validation
    def run_validation(self) -> dict[str, Any]:
        frame, models = self.validation_frame()
        results: dict[str, dict[str, Any]] = {}
        grid: dict[str, dict[str, dict[str, float]]] = {}
        curves: dict[str, dict[str, list[float]]] = {s: {} for s in SCENARIOS}
        for scenario in SCENARIOS:
            for variant in VARIANTS:
                proba = None if variant == "none" else models[variant]
                key = _key(scenario, variant)
                grid[key] = {
                    str(t): _brief(evaluate(frame, t, scenario, variant, proba, n_bootstrap=200))
                    for t in THRESHOLDS
                }
                threshold = choose_threshold(frame, scenario, proba)
                result = evaluate(frame, threshold, scenario, variant, proba)
                results[key] = result.summary()
                curves[scenario][f"{variant} (u={threshold:g})"] = result.cumulative_profit
        figures = self._figures(curves, "002_validation")
        positive = [
            k for k, r in results.items() if _positive(r["clv_mean"]) and not k.startswith("avg|")
        ]
        payload = {
            "stage": "validation",
            "generated_at": self.clock().isoformat(timespec="seconds"),
            "git_commit": self.git_commit(),
            "seasons": sorted(frame["season"].unique().tolist()),
            "n_matches": len(frame),
            "decision": "Shin sobre Pinnacle pre-cierre (ps_odds); CLV contra Pinnacle cierre (psc_odds)",
            "threshold_rule": (
                "umbral de {0.01, 0.02, 0.03, 0.05} con mayor CLV medio en F1–F3 entre los que "
                "tienen ≥ 300 apuestas; empate o ninguno → el menor"
            ),
            "results": results,
            "threshold_grid": grid,
            "gate": {
                "rule": "seguir si alguna variante (sin contar el control avg) tiene CLV medio > 0",
                "variants_with_positive_clv": positive,
                "passed": bool(positive),
            },
            "control_avg": {k: results[k]["clv_mean"] for k in results if k.startswith("avg|")},
            "figures": figures,
        }
        self._write(VALIDATION_FILE, payload)
        return payload

    # ------------------------------------------------------------------ helpers
    def _figures(self, curves: dict[str, dict[str, list[float]]], prefix: str) -> list[str]:
        paths = []
        for scenario, series in curves.items():
            path = self.reports_dir / "figures" / f"{prefix}_{scenario}_roi.png"
            title = f"Estrategia Pinnacle — cuotas {scenario} ({prefix.split('_')[-1]})"
            cumulative_plot(series, path, title)
            paths.append(str(path.relative_to(self.reports_dir)).replace("\\", "/"))
        return paths

    def _write(self, name: str, payload: dict[str, Any]) -> Path:
        path = self.reports_dir / name
        path.write_text(
            json.dumps(_clean(payload), indent=2, ensure_ascii=False, default=_json_default) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        return path


def _positive(value: Any) -> bool:
    return value is not None and np.isfinite(value) and value > 0


def _brief(result: StrategyResult) -> dict[str, float]:
    return {
        "n_bets": result.n_bets,
        "roi_flat": result.roi_flat,
        "clv_mean": result.clv_mean,
        "clv_positive_rate": result.clv_positive_rate,
    }


def _clean(value: Any) -> Any:
    """NaN/inf are not valid JSON: store them as null."""
    if isinstance(value, dict):
        return {k: _clean(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_clean(v) for v in value]
    if isinstance(value, float | np.floating) and not np.isfinite(value):
        return None
    return value


def _json_default(value: Any) -> Any:
    if isinstance(value, np.floating | np.integer):
        return value.item()
    return str(value)


__all__ = ["BacktestPinnacle", "Scenario", "Variant"]
