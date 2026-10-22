"""Use case: walk-forward validation of the cross-league adjustment and European calibration
(spec 003, T006 + the European part of T007; rules pre-registered in decisions.md).

For every season 2018-19…2024-25 the models are trained on earlier European seasons only and
predict that season; the ridge penalty is chosen with the last training season (inner
validation). Never reads the European holdout (2025-26, its own lock).
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Callable
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
    worst,
)
from betting_ml.ml.models.cross_league import CrossLeagueModel, FrequencyModel, eligible
from betting_ml.ml.models.poisson import outcome_probabilities, over_under_probabilities
from betting_ml.ml.plots import market_calibration_plot

logger = logging.getLogger(__name__)

EVAL_SEASONS = ("2018-19", "2019-20", "2020-21", "2021-22", "2022-23", "2023-24", "2024-25")
RIDGE_GRID = (0.3, 1.0, 3.0, 10.0, 30.0, 100.0, 300.0)
INNER_SEASONS = 2
DEFAULT_RIDGE = 10.0
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
    """Ridge with the lowest mean 1X2 log loss over the last ``INNER_SEASONS`` training seasons,
    each predicted by a model fitted on the seasons before it (inner validation; checkpoint:
    one season alone was too noisy)."""
    seasons = sorted(train["season"].unique())
    inner = seasons[-INNER_SEASONS:] if len(seasons) > INNER_SEASONS else seasons[1:]
    if not inner:
        return DEFAULT_RIDGE
    scores: dict[float, float] = {}
    for ridge in RIDGE_GRID:
        losses = [
            _ll_1x2(
                CrossLeagueModel(mode=mode, ridge=ridge).fit(train[train["season"] < s]),  # type: ignore[arg-type]
                train[train["season"] == s],
            )
            for s in inner
        ]
        scores[ridge] = float(np.mean(losses))
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


# ---------------------------------------------------------------- one-time European test

EUROPE_LOCK_FILE = "HOLDOUT_003_EUROPE_USED.lock"
EUROPE_CALIBRATION_FILE = "market_calibration_europe.json"
EUROPE_REPORT_FILE = "REPORT_003_europe.md"


class HoldoutEuropeAlreadyUsedError(RuntimeError):
    pass


@dataclass
class EuropeFinalEvaluation:
    metrics: dict[str, dict[str, float]]
    calibration: list[GroupCalibration]
    levels: dict[str, str]  # published: worst of validation and test
    n_test: int
    report_path: Path


class ValidateCrossLeagueFinal(ValidateCrossLeague):
    """ONE-TIME evaluation on the European 2025-26 holdout (rules in decisions.md)."""

    def __init__(
        self,
        repository: MatchRepository,
        reports_dir: Path,
        git_commit: Callable[[], str] = lambda: "unknown",
    ) -> None:
        super().__init__(repository, reports_dir)
        self.git_commit = git_commit

    @property
    def lock_path(self) -> Path:
        return self.reports_dir / EUROPE_LOCK_FILE

    def _lock(self, status: str, **extra: Any) -> None:
        body = {
            "status": status,
            "timestamp": datetime.now(UTC).isoformat(timespec="seconds"),
            "git_commit": self.git_commit(),
            **extra,
        }
        self.lock_path.write_text(json.dumps(body, indent=2) + "\n", encoding="utf-8", newline="\n")

    def run_final(self) -> EuropeFinalEvaluation:
        if self.lock_path.exists():
            raise HoldoutEuropeAlreadyUsedError(f"{self.lock_path} exists: already evaluated.")
        validation_path = self.reports_dir / REPORT_FILE
        if not validation_path.exists():
            raise FileNotFoundError("run `validate-cross-league` before the European test")
        validation_bytes = validation_path.read_bytes()
        validation_sha = hashlib.sha256(validation_bytes).hexdigest()
        validation = json.loads(validation_bytes.decode("utf-8"))
        self._lock("started", validation_json_sha256=validation_sha)

        train = eligible(self.repository.load("europe_matches")).sort_values(["date", "match_id"])
        raw_test = self.repository.load("europe_holdout")
        test = eligible(raw_test).sort_values(["date", "match_id"])
        if test.empty:
            raise ValueError("no eligible European test matches")
        if train["date"].max() >= test["date"].min():
            raise ValueError("training data overlaps the European test")
        season = str(test["season"].iloc[0])
        models: dict[str, CrossLeagueModel | FrequencyModel] = {
            "M0": FrequencyModel().fit(train),
            "M1": CrossLeagueModel(mode="raw").fit(train),
            "M2": CrossLeagueModel(mode="decomposed", ridge=choose_ridge(train)).fit(train),
        }
        metrics: dict[str, dict[str, float]] = {}
        scored = test
        for name, model in models.items():
            mats = model.score_matrices(test)
            metrics[name] = match_metrics(mats, test)
            if name == validation["chosen"]:
                scored = test.assign(fold=season, matrix=list(mats))
        calibration = self._calibrate(scored, train)
        test_levels = {c.group: c.confidence for c in calibration}
        published: dict[str, str] = {
            group: worst([validation["levels"][group], level])
            for group, level in test_levels.items()
        }
        payload = {
            "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "scope": f"Champions {season}, clubes de países del catálogo (evaluado una sola vez)",
            "n_test_matches": len(test),
            "n_test_raw": len(raw_test),
            "model": validation["chosen"],
            "metrics": metrics,
            "validation_levels": validation["levels"],
            "test_levels": test_levels,
            "levels": published,
            "test_groups": [asdict(c) for c in calibration],
        }
        (self.reports_dir / EUROPE_CALIBRATION_FILE).write_text(
            json.dumps(payload, indent=2, ensure_ascii=False, default=_json_default),
            encoding="utf-8",
            newline="\n",
        )
        report = self.reports_dir / EUROPE_REPORT_FILE
        report.write_text(render_europe_report(payload, validation), encoding="utf-8", newline="\n")
        self._lock(
            "completed",
            validation_json_sha256=validation_sha,
            n_test_matches=len(test),
            levels=published,
        )
        return EuropeFinalEvaluation(metrics, calibration, published, len(test), report)


def render_europe_report(payload: dict[str, Any], validation: dict[str, Any]) -> str:
    names = {"M0": "Frecuencias", "M1": "Elo crudo", "M2": "Elo + desplazamiento por liga"}
    lines = [
        "# Spec 003 — Partidos entre ligas (Champions/Europa League)",
        "",
        f"- Test: {payload['scope']}: {payload['n_test_matches']} partidos elegibles de "
        f"{payload['n_test_raw']} (lock `{EUROPE_LOCK_FILE}`).",
        "- Rating: Elo propio entre ligas sobre openfootball (ClubElo caído); fuerza = nivel del "
        "club en su liga + desplazamiento de la liga estimado con partidos europeos.",
        "- Elegibles: clubes de países del catálogo con ≥ 10 partidos con rating en el último "
        "año y un partido de liga en los 60 días previos.",
        "",
        "## Modelos",
        "",
        "| Modelo | Log loss 1X2 validación (media 2018-25) | Log loss 1X2 test "
        "| Log loss Más/Menos 2.5 test | Goles esperados / reales (test) |",
        "|---|---|---|---|---|",
    ]
    for key, label in names.items():
        val = validation["mean"][key]["log_loss_1x2"]
        test = payload["metrics"][key]
        lines.append(
            f"| {label} | {val:.4f} | {test['log_loss_1x2']:.4f} | {test['log_loss_ou25']:.4f} "
            f"| {test['expected_goals']:.2f} / {test['actual_goals']:.2f} |"
        )
    lines += [
        "",
        "## Niveles de confianza",
        "",
        "| Mercado | Validación | Test | Publicado |",
        "|---|---|---|---|",
    ]
    for group, level in payload["levels"].items():
        lines.append(
            f"| `{group}` | {payload['validation_levels'][group]} "
            f"| {payload['test_levels'][group]} | **{level}** |"
        )
    lines += [
        "",
        "## Cómo leerlo",
        "",
        "- Los niveles valen para partidos entre clubes de países del catálogo; para el resto la "
        "API no da análisis (`503 RATINGS_UNAVAILABLE`).",
        "- `alta` exige ≥ 400 casos positivos: con el test europeo no se puede alcanzar.",
        "- Más/Menos 2.5 está bien calibrado pero distingue poco entre partidos; 1X2 queda `baja` "
        "en validación por una ECE apenas por encima del umbral con sesgo ≈ 0 (decisions.md).",
        "- Los partidos entre ligas siempre llevan el aviso de más incertidumbre.",
        "",
    ]
    return "\n".join(lines)
