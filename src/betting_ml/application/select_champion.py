"""Use case: choose the champion and the best model without odds using ONLY validation
metrics (experiments.md §4) and write models/champion.json."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

MAX_ECE = 0.03
MAX_FOLD_GAP_VS_REFERENCE = 0.01
SIMPLICITY_TIE = 0.001
REFERENCE_EXPERIMENT = "E02"
FOLDS = ("val_ll_f1", "val_ll_f2", "val_ll_f3")
# logistic < Poisson/DC < blend < boosting < stacking (experiments.md §4.3)
SIMPLICITY = {"logistic": 0, "goals": 1, "blend": 2, "boosting": 3, "stacking": 4}


def simplicity_rank(spec: dict[str, Any]) -> int:
    kind = spec.get("type")
    if kind == "calibrated":
        return simplicity_rank(spec["base"])
    if kind == "sklearn":
        return SIMPLICITY["logistic" if spec.get("kind") == "logistic" else "boosting"]
    if kind == "optuna_lightgbm":
        return SIMPLICITY["boosting"]
    if kind in ("poisson", "dixon_coles"):
        return SIMPLICITY["goals"]
    if kind == "blend":
        return SIMPLICITY["blend"]
    if kind == "stacking":
        return SIMPLICITY["stacking"]
    return SIMPLICITY["logistic"]  # frequencies / market: trivial


@dataclass
class Selection:
    champion: dict[str, Any]
    champion_no_odds: dict[str, Any]
    candidates: pd.DataFrame
    excluded: dict[str, str]


def _as_bool(value: Any) -> bool:
    return str(value).strip().lower() in ("true", "1", "yes")


def eligible(rows: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, str]]:
    """Rule §4.1: ECE < 0.03 and no fold worse than E02 by more than 0.01 log loss."""
    reference = rows[rows["exp_id"] == REFERENCE_EXPERIMENT]
    if reference.empty:
        raise ValueError(f"{REFERENCE_EXPERIMENT} (stability reference) has not been run")
    ref = reference.iloc[0]
    excluded: dict[str, str] = {}
    keep = []
    for _, row in rows.iterrows():
        exp_id = str(row["exp_id"])
        if exp_id.startswith("E01"):
            excluded[exp_id] = "línea base (referencia, no candidato)"
            continue
        if float(row["val_ece"]) >= MAX_ECE:
            excluded[exp_id] = f"ECE {float(row['val_ece']):.4f} ≥ {MAX_ECE}"
            continue
        gaps = [float(row[f]) - float(ref[f]) for f in FOLDS]
        if max(gaps) > MAX_FOLD_GAP_VS_REFERENCE:
            excluded[exp_id] = (
                f"inestable: un fold es {max(gaps):.4f} peor que {REFERENCE_EXPERIMENT}"
            )
            continue
        keep.append(row)
    return pd.DataFrame(keep, columns=rows.columns), excluded


def pick(candidates: pd.DataFrame, specs: dict[str, dict[str, Any]]) -> tuple[pd.Series, str]:
    """Rule §4.2–4.3: lowest mean log loss; a simpler model within 0.001 wins."""
    if candidates.empty:
        raise ValueError("no eligible candidates")
    ordered = candidates.sort_values("val_ll_mean")
    best = ordered.iloc[0]
    best_rank = simplicity_rank(specs[best["exp_id"]])
    reason = f"menor log loss medio de validación ({float(best['val_ll_mean']):.5f})"
    simpler = ordered[
        (ordered["val_ll_mean"] - best["val_ll_mean"] < SIMPLICITY_TIE)
        & (ordered["exp_id"].map(lambda e: simplicity_rank(specs[e])) < best_rank)
    ]
    if not simpler.empty:
        ranked = simpler.assign(_rank=simpler["exp_id"].map(lambda e: simplicity_rank(specs[e])))
        winner = ranked.sort_values(["_rank", "val_ll_mean"]).iloc[0]
        reason = (
            f"desempate por simplicidad: {winner['exp_id']} ({float(winner['val_ll_mean']):.5f}) "
            f"está a menos de {SIMPLICITY_TIE} de {best['exp_id']} ({float(best['val_ll_mean']):.5f}) "
            "y es un modelo más simple"
        )
        return winner, reason
    return best, reason


class SelectChampion:
    def __init__(
        self,
        read_rows: Callable[[], pd.DataFrame],
        load_details: Callable[[str], dict[str, Any]],
        output_path: Path,
        git_commit: Callable[[], str],
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.read_rows = read_rows
        self.load_details = load_details
        self.output_path = output_path
        self.git_commit = git_commit
        self.clock = clock

    def run(self) -> Selection:
        rows = self.read_rows()
        candidates, excluded = eligible(rows)
        specs = {e: self.load_details(e)["spec"] for e in candidates["exp_id"]}
        best, reason = pick(candidates, specs)
        no_odds = candidates[~candidates["uses_odds"].map(_as_bool)]
        best_no_odds, reason_no_odds = pick(no_odds, specs)
        selection = Selection(
            champion=self._entry(best, specs, reason),
            champion_no_odds=self._entry(best_no_odds, specs, reason_no_odds),
            candidates=candidates,
            excluded=excluded,
        )
        self._write(selection)
        return selection

    def _entry(
        self, row: pd.Series, specs: dict[str, dict[str, Any]], reason: str
    ) -> dict[str, Any]:
        exp_id = str(row["exp_id"])
        details = self.load_details(exp_id)
        return {
            "experiment_id": exp_id,
            "name": row["name"],
            "model": row["model"],
            "uses_odds": _as_bool(row["uses_odds"]),
            "spec": specs[exp_id],
            "feature_overrides": details["config"].get("feature_overrides", {}),
            "bet_threshold": float(row["bet_threshold"]),
            "validation_metrics": {
                "log_loss": float(row["val_ll_mean"]),
                "log_loss_by_fold": {f[-2:].upper(): float(row[f]) for f in FOLDS},
                "brier": float(row["val_brier"]),
                "rps": float(row["val_rps"]),
                "ece": float(row["val_ece"]),
                "accuracy": float(row["val_acc"]),
            },
            "reason": reason,
        }

    def _write(self, selection: Selection) -> None:
        payload = {
            "created_at": self.clock().isoformat(timespec="seconds"),
            "git_commit": self.git_commit(),
            "rule": (
                "experiments.md §4: candidatos con ECE < 0.03 y ningún fold peor que E02 por más "
                "de 0.01; gana el menor log loss medio F1–F3; un candidato más simple a menos de "
                "0.001 gana (logística < Poisson/DC < blend < boosting < stacking). Solo métricas "
                "de validación; el holdout no se usa."
            ),
            "champion": selection.champion,
            "champion_no_odds": selection.champion_no_odds,
            "candidates": [
                {
                    "experiment_id": r["exp_id"],
                    "val_ll_mean": float(r["val_ll_mean"]),
                    "val_ece": float(r["val_ece"]),
                    "uses_odds": _as_bool(r["uses_odds"]),
                }
                for _, r in selection.candidates.sort_values("val_ll_mean").iterrows()
            ],
            "excluded": selection.excluded,
        }
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        self.output_path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n"
        )
