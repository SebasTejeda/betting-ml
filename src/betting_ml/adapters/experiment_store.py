"""Stores experiment results: reports/experiments.csv (one row per experiment id),
reports/experiments/{id}.json (details), reports/figures/ and fold predictions."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

CSV_COLUMNS = [
    "exp_id",
    "name",
    "hypothesis",
    "model",
    "feature_groups",
    "uses_odds",
    "val_ll_f1",
    "val_ll_f2",
    "val_ll_f3",
    "val_ll_mean",
    "val_brier",
    "val_rps",
    "val_ece",
    "val_acc",
    "bet_threshold",
    "n_bets",
    "roi_flat",
    "roi_ci_low",
    "roi_ci_high",
    "clv_mean",
    "runtime_s",
    "git_commit",
    "timestamp",
    "conclusion",
]


class FileExperimentStore:
    def __init__(self, reports_dir: Path, predictions_dir: Path) -> None:
        self.reports_dir = reports_dir
        self.predictions_dir = predictions_dir

    @property
    def csv_path(self) -> Path:
        return self.reports_dir / "experiments.csv"

    @property
    def figures_dir(self) -> Path:
        return self.reports_dir / "figures"

    def read_rows(self) -> pd.DataFrame:
        if not self.csv_path.exists():
            return pd.DataFrame(columns=CSV_COLUMNS)
        return pd.read_csv(
            self.csv_path, dtype={"conclusion": str}, keep_default_na=False, na_values=[""]
        )

    @property
    def history_path(self) -> Path:
        return self.reports_dir / "experiments_history.csv"

    def upsert_row(self, row: dict[str, Any]) -> None:
        """Insert or replace (same exp_id: a re-run after a bug fix, experiments.md §1.6).

        The replaced row is appended to experiments_history.csv (nothing is lost) and the new
        row starts without conclusion, since the old one may no longer apply."""
        rows = self.read_rows()
        previous = rows[rows["exp_id"] == row["exp_id"]]
        if len(previous):
            header = not self.history_path.exists()
            previous[CSV_COLUMNS].to_csv(
                self.history_path, mode="a", header=header, index=False, lineterminator="\n"
            )
        rows = rows[rows["exp_id"] != row["exp_id"]]
        new = pd.DataFrame([{c: row.get(c, "") for c in CSV_COLUMNS}])
        rows = new if rows.empty else pd.concat([rows, new], ignore_index=True)
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        rows[CSV_COLUMNS].to_csv(self.csv_path, index=False, lineterminator="\n")

    def set_conclusion(self, exp_id: str, conclusion: str) -> None:
        rows = self.read_rows()
        if exp_id not in set(rows["exp_id"]):
            raise KeyError(exp_id)
        rows["conclusion"] = rows["conclusion"].astype(object)
        rows.loc[rows["exp_id"] == exp_id, "conclusion"] = conclusion
        rows[CSV_COLUMNS].to_csv(self.csv_path, index=False, lineterminator="\n")

    def save_details(self, exp_id: str, details: dict[str, Any]) -> Path:
        path = self.reports_dir / "experiments" / f"{exp_id}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(details, indent=2, ensure_ascii=False, default=str) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        return path

    def load_details(self, exp_id: str) -> dict[str, Any]:
        path = self.reports_dir / "experiments" / f"{exp_id}.json"
        return json.loads(path.read_text(encoding="utf-8"))

    def save_predictions(self, exp_id: str, predictions: pd.DataFrame) -> Path:
        self.predictions_dir.mkdir(parents=True, exist_ok=True)
        path = self.predictions_dir / f"{exp_id}.parquet"
        predictions.to_parquet(path, index=False)
        return path

    def load_predictions(self, exp_id: str) -> pd.DataFrame:
        return pd.read_parquet(self.predictions_dir / f"{exp_id}.parquet")
