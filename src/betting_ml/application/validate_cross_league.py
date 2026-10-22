"""Use case: walk-forward validation of the cross-league adjustment and European calibration
(spec 003, T006 + the European part of T007; rules pre-registered in decisions.md).

For every season 2018-19…2024-25 the models are trained on earlier European seasons only and
predict that season; the ridge penalty is chosen with the last training season (inner
validation). Never reads the European holdout (2025-26, its own lock).
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from betting_ml.domain.markets import Market
from betting_ml.domain.ports import MatchRepository
from betting_ml.ml.calibration_markets import (
    Group,
    GroupCalibration,
    baseline_rates,
    calibrate,
    selection_records,
)
from betting_ml.ml.models.cross_league import CrossLeagueModel, FrequencyModel, eligible
from betting_ml.ml.models.poisson import outcome_probabilities, over_under_probabilities
from betting_ml.ml.plots import market_calibration_plot

logger = logging.getLogger(__name__)

EVAL_SEASONS = ("2018-19", "2019-20", "2020-21", "2021-22", "2022-23", "2023-24", "2024-25")
RIDGE_GRID = (1.0, 5.0, 20.0, 100.0)
GROUPS = [Group(Market.H2H), Group(Market.TOTALS, 2.5)]
REPORT_FILE = "market_validation_003_europe.json"
EPS = 1e-12


def match_metrics(mats: np.ndarray, frame: pd.DataFrame) -> dict[str, float]:
    hg, ag = frame["home_goals"].to_numpy(), frame["away_goals"].to_numpy()
    y = np.where(hg > ag, 0, np.where(hg == ag, 1, 2))
    p = np.clip(outcome_probabilities(mats), EPS, 1)
    over = np.clip(over_under_probabilities(mats, 2.5)[:, 0], EPS, 1 - EPS)
    o = (hg + ag > 2.5).astype(float)
    goals = np.arange(mats.shape[-1])
    expected = (mats.sum(axis=2) * goals).sum(axis=1) + (mats.sum(axis=1) * goals).sum(axis=1)
    return {
        "n": len(frame),
        "log_loss_1x2": float(-np.mean(np.log(p[np.arange(len(y)), y]))),
        "brier_1x2": float(np.mean(np.sum((p - np.eye(3)[y]) ** 2, axis=1))),
        "log_loss_ou25": float(-np.mean(o * np.log(over) + (1 - o) * np.log(1 - over))),
        "expected_goals": float(expected.mean()),
        "actual_goals": float((hg + ag).mean()),
    }


def _ll_1x2(model: CrossLeagueModel, frame: pd.DataFrame) -> float:
    return match_metrics(model.score_matrices(frame), frame)["log_loss_1x2"]


def choose_ridge(train: pd.DataFrame, mode: str = "decomposed") -> float:
    """Ridge picked on the last training season (inner validation)."""
    seasons = sorted(train["season"].unique())
    if len(seasons) < 2:
        return RIDGE_GRID[1]
    inner_train = train[train["season"] < seasons[-1]]
    inner_valid = train[train["season"] == seasons[-1]]
    scores = {
        r: _ll_1x2(CrossLeagueModel(mode=mode, ridge=r).fit(inner_train), inner_valid)  # type: ignore[arg-type]
        for r in RIDGE_GRID
    }
    return min(scores, key=lambda r: (scores[r], r))


@dataclass
class CrossLeagueValidation:
    by_season: dict[str, dict[str, dict[str, float]]]
    mean: dict[str, dict[str, float]]
    chosen: str
    ridges: dict[str, float]
    calibration: list[GroupCalibration]
    final_model: dict[str, Any]
    n_eligible: int


class ValidateCrossLeague:
    def __init__(self, repository: MatchRepository, reports_dir: Path) -> None:
        self.repository = repository
        self.reports_dir = reports_dir

    def run(self) -> CrossLeagueValidation:
        data = eligible(self.repository.load("europe_matches")).sort_values(["date", "match_id"])
        by_season: dict[str, dict[str, dict[str, float]]] = {}
        ridges: dict[str, float] = {}
        preds: dict[str, list[pd.DataFrame]] = {"M0": [], "M1": [], "M2": []}
        for season in EVAL_SEASONS:
            train, valid = data[data["season"] < season], data[data["season"] == season]
            if train.empty or valid.empty:
                continue
            ridge = choose_ridge(train)
            ridges[season] = ridge
            models: dict[str, CrossLeagueModel | FrequencyModel] = {
                "M0": FrequencyModel().fit(train),
                "M1": CrossLeagueModel(mode="raw").fit(train),
                "M2": CrossLeagueModel(mode="decomposed", ridge=ridge).fit(train),
            }
            by_season[season] = {}
            for name, model in models.items():
                mats = model.score_matrices(valid)
                by_season[season][name] = match_metrics(mats, valid)
                preds[name].append(valid.assign(fold=season, matrix=list(mats)))
        mean = {
            name: {
                key: float(np.mean([by_season[s][name][key] for s in by_season]))
                for key in ("log_loss_1x2", "brier_1x2", "log_loss_ou25")
            }
            for name in ("M0", "M1", "M2")
        }
        chosen = "M2" if mean["M2"]["log_loss_1x2"] < mean["M1"]["log_loss_1x2"] else "M1"
        calibration = self._calibrate(pd.concat(preds[chosen], ignore_index=True), data)
        final = (
            CrossLeagueModel(mode="decomposed", ridge=choose_ridge(data)).fit(data)
            if chosen == "M2"
            else CrossLeagueModel(mode="raw").fit(data)
        )
        result = CrossLeagueValidation(
            by_season=by_season,
            mean=mean,
            chosen=chosen,
            ridges=ridges,
            calibration=calibration,
            final_model={k: v for k, v in asdict(final).items()},
            n_eligible=len(data),
        )
        self._write(result)
        return result

    def _calibrate(self, scored: pd.DataFrame, data: pd.DataFrame) -> list[GroupCalibration]:
        scored = scored.assign(league="EUR")
        records = selection_records(scored, GROUPS)
        rates = pd.concat(
            [
                baseline_rates(data[data["season"] < s].assign(league="EUR"), GROUPS).assign(fold=s)
                for s in scored["fold"].unique()
            ]
        )
        records = records.merge(
            rates.rename(columns={"rate": "p_base"}),
            on=["fold", "league", "group", "selection"],
            how="left",
            validate="many_to_one",
        )
        return calibrate(records, GROUPS)

    def _write(self, result: CrossLeagueValidation) -> None:
        curves = {
            f"{cal.group} {slot}": metrics["curve"]
            for cal in result.calibration
            for slot, metrics in cal.by_selection.items()
        }
        market_calibration_plot(
            curves,
            self.reports_dir / "figures" / "003_calibration_europe.png",
            "Partidos europeos — walk-forward 2018-19…2024-25",
        )
        payload = {
            "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "scope": "UCL/UEL 2018-19…2024-25, clubes de países del catálogo (sin holdout)",
            "n_eligible_matches": result.n_eligible,
            "models": {
                "M0": "frecuencias de goles",
                "M1": "Elo crudo",
                "M2": "Elo descompuesto + desplazamiento por liga (ridge)",
            },
            "chosen": result.chosen,
            "mean": result.mean,
            "by_season": result.by_season,
            "ridge_by_season": result.ridges,
            "levels": {c.group: c.confidence for c in result.calibration},
            "groups": [asdict(c) for c in result.calibration],
            "final_model": result.final_model,
        }
        path = self.reports_dir / REPORT_FILE
        path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False, default=_json_default),
            encoding="utf-8",
            newline="\n",
        )


def _json_default(value: object) -> object:
    if isinstance(value, np.generic):
        return value.item()
    raise TypeError(f"not serializable: {type(value)}")
