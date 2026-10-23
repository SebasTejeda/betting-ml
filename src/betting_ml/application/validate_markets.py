"""Use case: validation of the derived markets on F1–F3 (spec 003, US1 · T007) and the
one-time final evaluation on 2025-26 (T009, lock `reports/HOLDOUT_003_USED.lock`).

Out-of-sample score matrices for every validation match (`goal_model.validation_matrices`),
calibration of every market group against the per-league baseline, and the Over/Under 2.5
value backtest with CLV against Pinnacle's closing price. Writes
`reports/market_validation_003.json` and `reports/figures/003_*`. `run` never reads the
holdout; `ValidateMarketsFinal.run_final` reads it once, with the rules fixed in decisions.md,
and writes `reports/market_calibration.json` (levels read by the API) and
`reports/REPORT_003_markets.md`.

European competitions (UCL/UEL) are calibrated in T006/T007-bis once ClubElo is available.
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Callable, Mapping
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
    worst,
)
from betting_ml.ml.models.goal_model import (
    DEFAULT_XI,
    FoldSpec,
    ScoreMatrixModel,
    folds_from_experiment,
    validation_matrices,
)
from betting_ml.ml.plots import cumulative_plot, market_calibration_plot

logger = logging.getLogger(__name__)

OU_COLUMNS = [f"{p}_{s}25" for p in ("b365", "avg", "max", "ps", "psc") for s in ("over", "under")]
VALIDATION_FILE = "market_validation_003.json"
CALIBRATION_FILE = "market_calibration.json"
REPORT_FILE = "REPORT_003_markets.md"
LOCK_FILE = "HOLDOUT_003_USED.lock"
MAIN_SCENARIO = "b365"
GOOD_MIN_HIGH_GROUPS = 4
EXCELLENT_MIN_BETS = 300
RULES = {
    "nivel": "por selección; el grupo toma el de su peor selección (checkpoint T008)",
    "alta": "ECE < 0.02, |sesgo relativo| < 5 %, el grupo mejora a la línea base y ≥ 400 casos",
    "media": "el resto (incluye sesgo > 10 % no significativo: muestra insuficiente)",
    "baja": "ECE ≥ 0.04, o sesgo relativo > 10 % significativo (|z| ≥ 2)",
}


class Holdout003AlreadyUsedError(RuntimeError):
    pass


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
        git_commit: Callable[[], str] = lambda: "unknown",
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.repository = repository
        self.catalog = catalog
        self.experiment_path = experiment_path
        self.reports_dir = reports_dir
        self.git_commit = git_commit
        self.clock = clock

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
            "generated_at": self.clock().isoformat(timespec="seconds"),
            "scope": "validation F1–F3, ligas locales (sin holdout)",
            "folds": [asdict(f) for f in folds],
            "n_matches": result.n_matches,
            "rules": RULES,
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


# ---------------------------------------------------------------------- final test (T009)


@dataclass
class FinalEvaluation:
    calibration: list[GroupCalibration]
    ou_backtest: dict[str, Any]
    n_matches: int
    levels: dict[str, str]  # published = worst of validation and test
    spec_level: str
    report_path: Path


def _matrices_hash(scored: pd.DataFrame) -> str:
    digest = hashlib.sha256()
    for match_id, matrix in zip(scored["match_id"], scored["matrix"], strict=True):
        digest.update(str(match_id).encode())
        digest.update(np.round(np.asarray(matrix), 12).tobytes())
    return digest.hexdigest()


def spec_level(test_levels: Mapping[str, str], main: dict[str, Any]) -> str:
    """Level of spec §5 with the rules pre-registered in decisions.md (T009)."""
    high = sum(level == "alta" for level in test_levels.values())
    raw = main.get("clv_mean")
    clv = float(raw) if raw is not None else float("nan")
    n_bets = int(main.get("n_bets", 0))
    if high >= GOOD_MIN_HIGH_GROUPS and np.isfinite(clv) and clv >= 0:
        excellent = (
            clv > 0
            and n_bets >= EXCELLENT_MIN_BETS
            and (main["roi_ci_low"] > 0 or main["roi_ci_high"] < 0)
        )
        return "Excelente" if excellent else "Bueno"
    return "Mínimo"


class ValidateMarketsFinal(ValidateMarkets):
    """ONE-TIME evaluation on the 2025-26 holdout (repository opened with the holdout)."""

    @property
    def lock_path(self) -> Path:
        return self.reports_dir / LOCK_FILE

    def _lock(self, status: str, **extra: Any) -> None:
        body = {
            "status": status,
            "timestamp": self.clock().isoformat(timespec="seconds"),
            "git_commit": self.git_commit(),
            **extra,
        }
        self.lock_path.write_text(json.dumps(body, indent=2) + "\n", encoding="utf-8", newline="\n")

    def run_final(self) -> FinalEvaluation:
        if self.lock_path.exists():
            raise Holdout003AlreadyUsedError(f"{self.lock_path} exists: T009 already ran.")
        validation_path = self.reports_dir / VALIDATION_FILE
        if not validation_path.exists():
            raise FileNotFoundError("run `validate-markets` (F1–F3) before the final test")
        validation_bytes = validation_path.read_bytes()
        validation_sha = hashlib.sha256(validation_bytes).hexdigest()
        validation = json.loads(validation_bytes.decode("utf-8"))
        thresholds = {
            s: data["chosen_threshold"]
            for s, data in validation["ou25_backtest"]["scenarios"].items()
        }
        self._lock("started", validation_json_sha256=validation_sha)

        matches = self.repository.load("matches")
        test = self.repository.load("holdout").sort_values(["date", "match_id"])
        if matches["date"].max() >= test["date"].min():
            raise ValueError("training data overlaps the test season")
        logger.info("Final test: %d matches of %s", len(test), sorted(test["season"].unique()))
        mats = ScoreMatrixModel(xi=DEFAULT_XI).walk_forward(matches, test)
        extra = ["match_id", "league", "date", "season", "home_goals", "away_goals", *OU_COLUMNS]
        scored = test[extra].reset_index(drop=True).assign(fold="test", matrix=list(mats))

        groups = groups_for(self.catalog.specs)
        rates = baseline_rates(matches, groups).assign(fold="test")
        records = selection_records(scored, groups).merge(
            rates.rename(columns={"rate": "p_base"}),
            on=["fold", "league", "group", "selection"],
            how="left",
            validate="many_to_one",
        )
        if records["p_base"].isna().any():
            raise ValueError("baseline missing for some test records")
        calibration = calibrate(records, groups)
        test_levels = {c.group: c.confidence for c in calibration}
        published: dict[str, str] = {
            group: worst([validation["levels"][group], level])
            for group, level in test_levels.items()
        }
        backtest = self._ou_test(scored, thresholds)
        main = backtest["scenarios"][MAIN_SCENARIO]["result"]
        level = spec_level(test_levels, main)

        self._write_calibration(calibration, validation, published, backtest, len(scored), level)
        report = self.reports_dir / REPORT_FILE
        report.write_text(
            render_report(calibration, validation, published, backtest, len(scored), level),
            encoding="utf-8",
            newline="\n",
        )
        self._lock(
            "completed",
            validation_json_sha256=validation_sha,
            test_matrices_sha256=_matrices_hash(scored),
            level=level,
        )
        return FinalEvaluation(calibration, backtest, len(scored), published, level, report)

    def _ou_test(self, scored: pd.DataFrame, thresholds: dict[str, float | None]) -> dict[str, Any]:
        won, _ = selection_mask(Market.TOTALS, "over", 2.5)
        mats = np.stack(scored["matrix"].to_numpy())
        frame = scored.drop(columns=["matrix"]).assign(p_over=(mats * won).sum(axis=(1, 2)))
        frame = frame.dropna(subset=["psc_over25", "psc_under25"])
        out: dict[str, Any] = {"n_matches_with_closing": len(frame), "scenarios": {}}
        for scenario in OU_SCENARIOS:
            threshold = thresholds.get(scenario)
            placebo = placebo_ou_clv(frame, scenario)
            if threshold is None:
                out["scenarios"][scenario] = {"threshold": None, "result": {}, "placebo": placebo}
                continue
            result = summarize_bets(select_ou_bets(frame, threshold, scenario))
            cumulative = result.pop("cumulative_profit")
            out["scenarios"][scenario] = {
                "threshold": threshold,
                "result": result,
                "placebo": placebo,
                "placebo_same_side_mix": (
                    weighted_placebo(placebo, result["over_share"]) if result["n_bets"] else None
                ),
            }
            if cumulative:
                cumulative_plot(
                    {f"{scenario}, umbral {threshold:.0%}": cumulative},
                    self.figures_dir / f"003_ou25_test_{scenario}.png",
                    f"Más/Menos 2.5 en el test 2025-26 — {scenario}",
                )
        return out

    def _write_calibration(
        self,
        calibration: list[GroupCalibration],
        validation: dict[str, Any],
        published: dict[str, str],
        backtest: dict[str, Any],
        n_matches: int,
        level: str,
    ) -> None:
        payload = {
            "generated_at": self.clock().isoformat(timespec="seconds"),
            "scope": "ligas locales; partidos europeos pendientes (T006, lock propio)",
            "rules": RULES,
            "published_level": "peor entre validación (F1–F3) y test (2025-26)",
            "levels": published,
            "validation_levels": validation["levels"],
            "test_levels": {c.group: c.confidence for c in calibration},
            "experimental": {m.key.value: m.experimental for m in self.catalog.markets},
            "n_test_matches": n_matches,
            "spec_level": level,
            "test_groups": [asdict(c) for c in calibration],
            "ou25_test": backtest,
        }
        path = self.reports_dir / CALIBRATION_FILE
        path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False, default=_json_default),
            encoding="utf-8",
            newline="\n",
        )


def _pct(value: float | None, digits: int = 1) -> str:
    if value is None or not np.isfinite(value):
        return "—"
    return f"{value * 100:+.{digits}f} %"


def render_report(
    calibration: list[GroupCalibration],
    validation: dict[str, Any],
    published: dict[str, str],
    backtest: dict[str, Any],
    n_matches: int,
    level: str,
) -> str:
    val_groups = {g["group"]: g for g in validation["groups"]}
    counts = {lvl: sum(v == lvl for v in published.values()) for lvl in ("alta", "media", "baja")}
    test_high = sum(c.confidence == "alta" for c in calibration)
    lines = [
        "# Spec 003 — Validación de los mercados derivados",
        "",
        f"**Nivel alcanzado (spec §5): {level}.**",
        "",
        "- Modelo: Dixon-Coles sobre xG (E09 de la spec 001), ξ = 0.003, walk-forward con "
        "re-ajuste semanal; ninguna cuota entra al modelo.",
        f"- Test: temporada 2025-26 de las 5 ligas ({n_matches} partidos), evaluado una sola vez "
        "(lock `HOLDOUT_003_USED.lock`).",
        "- Validación: folds F1–F3 de la spec 001 (2022-23, 2023-24, 2024-25).",
        "- Partidos europeos (Champions/Europa League): **pendientes** (ClubElo caído; T006 y "
        "una evaluación aparte con su propio lock).",
        "",
        "## Cómo se asigna la confianza",
        "",
        'Cada selección (por ejemplo, "Más de 2.5") es un evento sí/no. Se mide su calibración '
        "(ECE, 10 bins) y su sesgo relativo (probabilidad media / frecuencia real − 1). El grupo "
        "(mercado y línea) toma el nivel de su peor selección:",
        "",
        f"- **alta**: {RULES['alta']};",
        f"- **media**: {RULES['media']};",
        f"- **baja**: {RULES['baja']}.",
        "",
        "La comparación con la línea base (frecuencia histórica por liga) es por grupo, no por "
        "selección. El nivel publicado es el **peor entre validación y test**. Los mercados "
        "`baja` se muestran solo como información, sin consejos de valor.",
        "",
        f"Resultado publicado: **{counts['alta']} alta, {counts['media']} media, "
        f"{counts['baja']} baja** (en el test solo: {test_high} alta).",
        "",
        "## Niveles por mercado",
        "",
        "| Grupo | Validación | Test | Publicado | Mayor sesgo en test | ECE máx. test "
        "| Log loss test (base) |",
        "|---|---|---|---|---|---|---|",
    ]
    for cal in calibration:
        slot, sel = max(cal.by_selection.items(), key=lambda kv: abs(kv[1]["rel_bias"]))
        max_ece = max(s["ece"] for s in cal.by_selection.values())
        note = " (derivado de 1X2)" if cal.derived_from else ""
        lines.append(
            f"| `{cal.group}`{note} | {val_groups[cal.group]['confidence']} | {cal.confidence} "
            f"| **{published[cal.group]}** | {slot} {_pct(sel['rel_bias'])} "
            f"(z {sel['rel_bias_z']:+.1f}) | {max_ece:.3f} | {cal.model['log_loss']:.4f} "
            f"({cal.baseline['log_loss']:.4f}) |"
        )
    lines += [
        "",
        "## Backtest de valor en Más/Menos 2.5",
        "",
        "Probabilidad del modelo contra la cuota **pre-cierre** de cada escenario; umbral fijado "
        "en validación; una apuesta por partido; CLV contra el cierre de Pinnacle (solo para "
        "medir).",
        "",
        '| Escenario | Umbral | Apuestas | % a "Más" | ROI (IC 95 %) | CLV medio (IC 95 %) '
        "| Placebo misma mezcla |",
        "|---|---|---|---|---|---|---|",
    ]
    for scenario, data in backtest["scenarios"].items():
        r = data["result"]
        if not r or not r["n_bets"]:
            lines.append(f"| {scenario} | — | 0 | — | — | — | — |")
            continue
        lines.append(
            f"| {scenario} | {data['threshold']:.0%} | {r['n_bets']} | {r['over_share']:.0%} | "
            f"{_pct(r['roi_flat'])} ({_pct(r['roi_ci_low'])}, {_pct(r['roi_ci_high'])}) | "
            f"{_pct(r['clv_mean'])} ({_pct(r['clv_ci_low'])}, {_pct(r['clv_ci_high'])}) | "
            f"{_pct(data.get('placebo_same_side_mix'))} |"
        )
    val_b365 = validation["ou25_backtest"]["scenarios"][MAIN_SCENARIO]
    chosen = val_b365["chosen_threshold"]
    val_main = val_b365["by_threshold"].get(f"{chosen:g}", {}) if chosen is not None else {}
    main = backtest["scenarios"][MAIN_SCENARIO]["result"]
    clv = main.get("clv_mean") if main else None
    if clv is not None and np.isfinite(clv) and clv >= 0:
        verdict = (
            "el CLV de Bet365 no es negativo en el test, pero junto con la validación no basta "
            "para apostar dinero real"
        )
    else:
        verdict = (
            "la selección del modelo no le gana al cierre (CLV negativo): no hay valor demostrado"
        )
    lines += [
        "",
        f"En validación (F1–F3), Bet365 dio CLV {_pct(val_main.get('clv_mean'))} con "
        f"{val_main.get('n_bets', 0)} apuestas (placebo misma mezcla "
        f"{_pct(val_b365.get('placebo_same_side_mix'))}).",
        "",
        "## Conclusión",
        "",
        f"- **Probabilidades:** {counts['alta'] + counts['media']} de {len(published)} grupos "
        "pueden generar consejos (alta/media); los `baja` solo como información.",
        f"- **Valor en Más/Menos 2.5:** {verdict}. Los consejos de valor siguen **EXPERIMENTAL "
        "— solo papel** (principio XI).",
        "- **Sesgo conocido:** el modelo espera más goles de los reales porque se ajusta sobre "
        "xG; los mercados de muchos goles salen sobreestimados (decisions.md). Recalibrarlo es "
        "un experimento futuro.",
        "",
    ]
    return "\n".join(lines)


def _json_default(value: object) -> object:
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, float) and not np.isfinite(value):
        return None
    raise TypeError(f"not serializable: {type(value)}")
