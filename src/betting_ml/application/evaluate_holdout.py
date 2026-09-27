"""Use case: the ONE-TIME final evaluation on the holdout season (experiments.md §6).

1. Refuses to run if reports/HOLDOUT_USED.lock exists.
2. Trains the champion and champion_no_odds on every training season.
3. Evaluates them, the E01 baselines and E02 on the holdout.
4. Applies the betting simulation with the thresholds fixed in validation.
5. Writes holdout_results.json + figures and creates the lock.
6. Determines the success level (spec §6).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from betting_ml.config import FeaturesFile, LeaguesFile, with_overrides
from betting_ml.domain.metrics import evaluate
from betting_ml.domain.ports import MatchRepository
from betting_ml.ml.betting import simulate
from betting_ml.ml.features.pipeline import ALL_GROUPS, TARGET, FeaturePipeline
from betting_ml.ml.models.factory import build_model
from betting_ml.ml.plots import calibration_plot, roi_plot
from betting_ml.ml.validation import check_temporal_order, final_split

HOLDOUT = "holdout"
MATCHES = "matches"
LOCK_NAME = "HOLDOUT_USED.lock"
MAX_ECE = 0.03
GOOD_MARGIN = 0.005
MIN_BETS_EXCELLENT = 300
BASELINES = {
    "E01-freq": {"type": "frequencies"},
    "E01-avg": {"type": "market", "source": "avg", "method": "shin"},
    "E01-psc": {"type": "market", "source": "psc", "method": "shin"},
}
OUTCOMES = ["p_home", "p_draw", "p_away"]


class HoldoutAlreadyUsedError(RuntimeError):
    pass


@dataclass
class HoldoutReport:
    level: str
    results: dict[str, Any]


def success_level(
    champion: dict[str, float],
    frequencies: float,
    e02: float,
    market_avg: float,
    psc_subset: dict[str, float],
    best_strategy: dict[str, Any] | None,
) -> tuple[str, dict[str, bool]]:
    """spec §6. Levels are cumulative: Bueno and Excelente require the Mínimo."""
    checks = {
        "minimo_vs_frecuencias": champion["log_loss"] < frequencies,
        "minimo_vs_e02": champion["log_loss"] < e02,
        "minimo_ece": champion["ece"] < MAX_ECE,
        "bueno_vs_mercado_avg": champion["log_loss"] <= market_avg + GOOD_MARGIN,
        "excelente_vs_pinnacle_cierre": psc_subset["champion"] < psc_subset["psc"],
        "excelente_estrategia_valor": bool(
            best_strategy
            and best_strategy["n_bets"] >= MIN_BETS_EXCELLENT
            and best_strategy["roi_flat"] > 0
            and best_strategy["roi_ci_low"] > 0
        ),
    }
    minimo = checks["minimo_vs_frecuencias"] and checks["minimo_vs_e02"] and checks["minimo_ece"]
    if not minimo:
        return "No alcanzado", checks
    if checks["excelente_vs_pinnacle_cierre"] or checks["excelente_estrategia_valor"]:
        return "Excelente", checks
    if checks["bueno_vs_mercado_avg"]:
        return "Bueno", checks
    return "Mínimo", checks


class EvaluateHoldout:
    def __init__(
        self,
        repository: MatchRepository,
        leagues: LeaguesFile,
        features: FeaturesFile,
        champion_path: Path,
        load_details: Callable[[str], dict[str, Any]],
        reports_dir: Path,
        git_commit: Callable[[], str],
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.repository = repository
        self.leagues = leagues
        self.features = features
        self.champion_path = champion_path
        self.load_details = load_details
        self.reports_dir = reports_dir
        self.git_commit = git_commit
        self.clock = clock

    @property
    def lock_path(self) -> Path:
        return self.reports_dir / LOCK_NAME

    def run(self) -> HoldoutReport:
        if self.lock_path.exists():
            raise HoldoutAlreadyUsedError(
                f"{self.lock_path} exists: the holdout was already evaluated (constitution §II)."
            )
        selection = json.loads(self.champion_path.read_text(encoding="utf-8"))
        # Claim the holdout before reading it: even a crash counts as "used".
        self._write_lock(selection, status="started")
        champion, no_odds = selection["champion"], selection["champion_no_odds"]
        specs: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {
            "champion": (champion["spec"], champion.get("feature_overrides", {})),
            "champion_no_odds": (no_odds["spec"], no_odds.get("feature_overrides", {})),
            "E02": (self.load_details("E02")["spec"], {}),
            **{name: (spec, {}) for name, spec in BASELINES.items()},
        }
        predictions = {name: self._fit_predict(spec, ov) for name, (spec, ov) in specs.items()}
        holdout = predictions["E01-freq"][0]
        y = holdout[TARGET].astype(int).to_numpy()
        metrics = {name: evaluate(y, proba).to_dict() for name, (_, proba) in predictions.items()}
        psc_subset = self._psc_subset(holdout, predictions)
        betting = {
            "champion": self._betting(
                holdout, predictions["champion"][1], champion["bet_threshold"]
            ),
            "champion_no_odds": self._betting(
                holdout, predictions["champion_no_odds"][1], no_odds["bet_threshold"]
            ),
        }
        best_strategy = max(
            (b["realistic"] for b in betting.values() if b["realistic"]["n_bets"] > 0),
            key=lambda s: s["roi_ci_low"],
            default=None,
        )
        level, checks = success_level(
            metrics["champion"],
            metrics["E01-freq"]["log_loss"],
            metrics["E02"]["log_loss"],
            metrics["E01-avg"]["log_loss"],
            psc_subset,
            best_strategy,
        )
        figures = self._figures(holdout, y, predictions, champion, no_odds)
        results = {
            "evaluated_at": self.clock().isoformat(timespec="seconds"),
            "git_commit": self.git_commit(),
            "holdout_season": self.leagues.seasons.holdout,
            "n_matches": len(holdout),
            "train_seasons": list(self.leagues.seasons.train),
            "champion": champion["experiment_id"],
            "champion_no_odds": no_odds["experiment_id"],
            "metrics": metrics,
            "pinnacle_closing_subset": psc_subset,
            "betting": betting,
            "metrics_by_league": self._by_league(holdout, predictions),
            "level": level,
            "level_checks": checks,
            "figures": figures,
        }
        path = self.reports_dir / "holdout_results.json"
        path.write_text(
            json.dumps(results, indent=2, ensure_ascii=False, default=float) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        self._write_lock(selection, status="completed", level=level)
        return HoldoutReport(level, results)

    # ------------------------------------------------------------------ steps
    def _frames(self, overrides: dict[str, Any]) -> tuple[pd.DataFrame, pd.DataFrame]:
        matches = self.repository.load(MATCHES)
        holdout = self.repository.load(HOLDOUT)
        fold = final_split(self.leagues.seasons.train, self.leagues.seasons.holdout)
        data = pd.concat([matches, holdout], ignore_index=True)
        frame = FeaturePipeline(with_overrides(self.features, overrides)).transform(
            data, ALL_GROUPS
        )
        train, valid = fold.split(frame)
        check_temporal_order(train, valid)
        return train, valid

    def _fit_predict(
        self, spec: dict[str, Any], overrides: dict[str, Any]
    ) -> tuple[pd.DataFrame, np.ndarray]:
        train, valid = self._frames(overrides)
        model = build_model(spec, with_overrides(self.features, overrides)).fit(train)
        proba = model.predict_proba(valid)
        if proba.shape != (len(valid), 3) or not np.allclose(proba.sum(axis=1), 1.0, atol=1e-6):
            raise ValueError("invalid probabilities on the holdout")
        return valid.reset_index(drop=True), proba

    @staticmethod
    def _psc_subset(
        holdout: pd.DataFrame, predictions: dict[str, tuple[pd.DataFrame, np.ndarray]]
    ) -> dict[str, float]:
        """Pinnacle closing odds only cover part of the holdout: compare on that subset."""
        cols = ["psc_odds_h", "psc_odds_d", "psc_odds_a"]
        mask = holdout[cols].notna().all(axis=1).to_numpy().copy()
        if "closing_odds_invalid" in holdout:
            mask &= ~holdout["closing_odds_invalid"].to_numpy(dtype=bool)
        y = holdout[TARGET].astype(int).to_numpy()[mask]
        if mask.sum() == 0:
            return {"n": 0, "coverage": 0.0, "champion": float("nan"), "psc": float("nan")}
        out: dict[str, float] = {"n": int(mask.sum()), "coverage": float(mask.mean())}
        for name in ("champion", "champion_no_odds", "E01-avg", "E01-psc"):
            key = "psc" if name == "E01-psc" else name
            out[key] = evaluate(y, predictions[name][1][mask]).log_loss
        return out

    @staticmethod
    def _betting(holdout: pd.DataFrame, proba: np.ndarray, threshold: float) -> dict[str, Any]:
        realistic = simulate(holdout, proba, threshold, "avg")
        optimistic = simulate(holdout, proba, threshold, "max")
        return {
            "threshold": threshold,
            "realistic": realistic.summary(),
            "optimistic": optimistic.summary(),
        }

    def _figures(
        self,
        holdout: pd.DataFrame,
        y: np.ndarray,
        predictions: dict[str, tuple[pd.DataFrame, np.ndarray]],
        champion: dict[str, Any],
        no_odds: dict[str, Any],
    ) -> list[str]:
        figures = self.reports_dir / "figures"
        paths = []
        for key, entry in (("champion", champion), ("champion_no_odds", no_odds)):
            proba = predictions[key][1]
            title = f"Holdout {self.leagues.seasons.holdout} — {entry['experiment_id']}"
            paths.append(
                calibration_plot(y, proba, figures / f"holdout_{key}_calibration.png", title)
            )
            realistic = simulate(holdout, proba, entry["bet_threshold"], "avg")
            optimistic = simulate(holdout, proba, entry["bet_threshold"], "max")
            paths.append(
                roi_plot([realistic, optimistic], figures / f"holdout_{key}_roi.png", title)
            )
        return [str(p.relative_to(self.reports_dir)).replace("\\", "/") for p in paths]

    @staticmethod
    def _by_league(
        holdout: pd.DataFrame, predictions: dict[str, tuple[pd.DataFrame, np.ndarray]]
    ) -> dict[str, dict[str, float]]:
        out: dict[str, dict[str, float]] = {}
        leagues = holdout["league"].to_numpy()
        y = holdout[TARGET].astype(int).to_numpy()
        for league in sorted(set(leagues)):
            mask = leagues == league
            out[str(league)] = {
                name: evaluate(y[mask], predictions[name][1][mask]).log_loss
                for name in ("champion", "champion_no_odds", "E01-avg", "E01-freq")
            }
        return out

    def _write_lock(self, selection: dict[str, Any], status: str, level: str | None = None) -> None:
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "status": status,
            "timestamp": self.clock().isoformat(timespec="seconds"),
            "git_commit": self.git_commit(),
            "champion": selection["champion"]["experiment_id"],
            "champion_no_odds": selection["champion_no_odds"]["experiment_id"],
            "level": level,
        }
        self.lock_path.write_text(
            json.dumps(payload, indent=2) + "\n", encoding="utf-8", newline="\n"
        )
