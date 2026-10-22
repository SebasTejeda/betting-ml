"""Use case: validation of the derived markets on F1–F3 (spec 003, US1 · T007).

Out-of-sample score matrices for every validation match (`goal_model.validation_matrices`),
calibration of every market group against the per-league baseline, and the Over/Under 2.5
value backtest with CLV against Pinnacle's closing price. Writes
`reports/market_validation_003.json` and `reports/figures/003_*`. Never reads the holdout
(the final, single evaluation on 2025-26 is T009).

European competitions (UCL/UEL) are calibrated in T006/T007-bis once ClubElo is available.
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

from betting_ml.config import BettingMarketsFile
from betting_ml.domain.markets import Market, selection_mask
from betting_ml.domain.ports import MatchRepository
from betting_ml.ml.calibration_markets import (
    OU_SCENARIOS,
    OU_THRESHOLDS,
    GroupCalibration,
    baseline_rates,
    calibrate,
    choose_threshold,
    groups_for,
    placebo_ou_clv,
    select_ou_bets,
    selection_records,
    summarize_bets,
    weighted_placebo,
)
from betting_ml.ml.models.goal_model import FoldSpec, folds_from_experiment, validation_matrices
from betting_ml.ml.plots import cumulative_plot, market_calibration_plot

logger = logging.getLogger(__name__)

OU_COLUMNS = [f"{p}_{s}25" for p in ("b365", "avg", "max", "ps", "psc") for s in ("over", "under")]


@dataclass
class MarketValidation:
    calibration: list[GroupCalibration]
    ou_backtest: dict[str, Any]
    n_matches: int

    def levels(self) -> dict[str, str]:
        return {c.group: c.confidence for c in self.calibration}


class ValidateMarkets:
    def __init__(
        self,
        repository: MatchRepository,
        catalog: BettingMarketsFile,
        experiment_path: Path,
        reports_dir: Path,
    ) -> None:
        self.repository = repository
        self.catalog = catalog
        self.experiment_path = experiment_path
        self.reports_dir = reports_dir

    @property
    def figures_dir(self) -> Path:
        return self.reports_dir / "figures"

    def folds(self) -> list[FoldSpec]:
        return folds_from_experiment(json.loads(self.experiment_path.read_text(encoding="utf-8")))

    def run(self) -> MarketValidation:
        matches = self.repository.load("matches")
        folds = self.folds()
        logger.info("Computing out-of-sample score matrices for %s", [f.name for f in folds])
        matrices = validation_matrices(matches, folds)
        extra = ["match_id", "season", "home_goals", "away_goals", *OU_COLUMNS]
        scored = matrices.merge(matches[extra], on="match_id", how="left", validate="one_to_one")

        groups = groups_for(self.catalog.specs)
        records = selection_records(scored, groups)
        rates = pd.concat(
            [
                baseline_rates(matches[matches["season"].isin(f.train)], groups).assign(fold=f.name)
                for f in folds
            ]
        )
        records = records.merge(
            rates.rename(columns={"rate": "p_base"}),
            on=["fold", "league", "group", "selection"],
            how="left",
            validate="many_to_one",
        )
        if records["p_base"].isna().any():
            raise ValueError("baseline missing for some records (league without training data?)")
        calibration = calibrate(records, groups)
        backtest = self._ou_backtest(scored)
        result = MarketValidation(calibration, backtest, n_matches=len(scored))
        self._write(result, folds)
        return result

    def _ou_backtest(self, scored: pd.DataFrame) -> dict[str, Any]:
        won, _ = selection_mask(Market.TOTALS, "over", 2.5)
        mats = np.stack(scored["matrix"].to_numpy())
        frame = scored.drop(columns=["matrix"]).assign(p_over=(mats * won).sum(axis=(1, 2)))
        frame = frame.dropna(subset=["psc_over25", "psc_under25"])  # CLV needs the closing price
        out: dict[str, Any] = {"n_matches_with_closing": len(frame), "scenarios": {}}
        for scenario in OU_SCENARIOS:
            by_threshold = {
                t: summarize_bets(select_ou_bets(frame, t, scenario)) for t in OU_THRESHOLDS
            }
            chosen = choose_threshold(by_threshold)
            placebo = placebo_ou_clv(frame, scenario)
            chosen_summary = by_threshold[chosen] if chosen is not None else None
            out["scenarios"][scenario] = {
                "chosen_threshold": chosen,
                "chosen_at_grid_edge": chosen in (OU_THRESHOLDS[0], OU_THRESHOLDS[-1]),
                "placebo_same_side_mix": (
                    weighted_placebo(placebo, chosen_summary["over_share"])
                    if chosen_summary is not None
                    else None
                ),
                "by_threshold": {
                    f"{t:g}": {k: v for k, v in r.items() if k != "cumulative_profit"}
                    for t, r in by_threshold.items()
                },
                "by_season": (
                    {
                        str(season): {
                            k: v
                            for k, v in summarize_bets(group).items()
                            if k != "cumulative_profit"
                        }
                        for season, group in select_ou_bets(frame, chosen, scenario).groupby(
                            "season"
                        )
                    }
                    if chosen is not None
                    else {}
                ),
                "placebo": placebo,
            }
            if chosen is not None:
                cumulative_plot(
                    {f"{scenario}, umbral {chosen:.0%}": by_threshold[chosen]["cumulative_profit"]},
                    self.figures_dir / f"003_ou25_validation_{scenario}.png",
                    f"Más/Menos 2.5 en validación (F1–F3) — {scenario}",
                )
        return out

    def _write(self, result: MarketValidation, folds: list[FoldSpec]) -> None:
        by_market: dict[str, dict[str, list[dict[str, float]]]] = {}
        for cal in result.calibration:
            for slot, metrics in cal.by_selection.items():
                label = slot if cal.line is None else f"{slot} {cal.line:g}"
                by_market.setdefault(cal.market, {})[label] = metrics["curve"]
        for market, curves in by_market.items():
            entry = self.catalog.get(market)
            market_calibration_plot(
                curves,
                self.figures_dir / f"003_calibration_{market}.png",
                f"{entry.name if entry else market} — validación F1–F3",
            )
        payload = {
            "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "scope": "validation F1–F3, ligas locales (sin holdout)",
            "folds": [asdict(f) for f in folds],
            "n_matches": result.n_matches,
            "rules": {
                "nivel": "por selección; el grupo toma el de su peor selección (checkpoint T008)",
                "alta": "ECE < 0.02, |sesgo relativo| < 5 % y el grupo mejora a la línea base",
                "media": "ECE < 0.04 y |sesgo relativo| < 10 %",
                "baja": "resto",
            },
            "levels": result.levels(),
            "groups": [asdict(c) for c in result.calibration],
            "ou25_backtest": result.ou_backtest,
        }
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        path = self.reports_dir / "market_validation_003.json"
        path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False, default=_json_default),
            encoding="utf-8",
        )


def _json_default(value: object) -> object:
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, float) and not np.isfinite(value):
        return None
    raise TypeError(f"not serializable: {type(value)}")
