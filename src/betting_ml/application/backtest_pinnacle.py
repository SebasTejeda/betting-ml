"""Use case (spec 002, US1): backtest of the Pinnacle-reference strategy on the validation
folds F1–F3 (repeatable). The one-time test on 2025-26 lives in `run_final` (T007)."""

from __future__ import annotations

import hashlib
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
    _bootstrap_mean,
    choose_threshold,
    evaluate,
    placebo_clv,
    select_bets,
    threshold_is_default,
)
from betting_ml.ml.plots import cumulative_plot
from betting_ml.ml.validation import walk_forward_folds

PROBA = ["p_home", "p_draw", "p_away"]
VALIDATION_FILE = "backtest_002_validation.json"
RESULTS_FILE = "backtest_002.json"
REPORT_FILE = "REPORT_002_backtest.md"
LOCK_FILE = "HOLDOUT_002_USED.lock"
# Declared before looking at the test season (decisions.md, T006): the realistic single soft
# bookmaker scenario without model filter decides the level and the conclusion.
PRIMARY = "b365|none"
GOOD_ROI_CI_LOW = -0.03
MIN_BETS_EXCELLENT = 300
# Conclusion rules fixed after checkpoint T006 (decisions.md): the optimistic `max` scenario and
# the `avg` control are informative only; evidence must come from Bet365 (a real soft book).
EVIDENCE_SCENARIO = "b365"
MIN_POOLED_BETS = 50
EXPECTED_TEST_BETS_PRIMARY = 23


class Holdout002AlreadyUsedError(RuntimeError):
    pass


def level_and_conclusion(
    validation: dict[str, Any],
    test: dict[str, dict[str, Any]],
    pooled: dict[str, dict[str, Any]] | None = None,
) -> tuple[str, str, dict[str, bool]]:
    """Spec 002 §5 (backtest part) and the continue / change / stop conclusion.

    ``pooled`` = CLV of the Bet365 variants over validation + test together (declared evidence
    for "seguir con cambios", since the test alone has little statistical power)."""
    primary = test[PRIMARY]
    checks = {
        "minimo_clv_validacion": bool(validation["gate"]["passed"]),
        "bueno_clv_test": _positive(primary["clv_mean"]),
        "bueno_roi_ci_low": primary["roi_ci_low"] is not None
        and np.isfinite(primary["roi_ci_low"])
        and primary["roi_ci_low"] > GOOD_ROI_CI_LOW,
        "excelente_roi_ci_sin_cero": primary["roi_ci_low"] is not None
        and np.isfinite(primary["roi_ci_low"])
        and primary["roi_ci_low"] > 0
        and primary["n_bets"] >= MIN_BETS_EXCELLENT,
    }
    if not checks["minimo_clv_validacion"]:
        level = "No alcanzado"
    elif checks["bueno_clv_test"] and checks["bueno_roi_ci_low"]:
        level = "Excelente" if checks["excelente_roi_ci_sin_cero"] else "Bueno"
    else:
        level = "Mínimo (backtest)"
    solid = [
        key
        for key, r in (pooled or {}).items()
        if key.startswith(f"{EVIDENCE_SCENARIO}|")
        and r["n"] >= MIN_POOLED_BETS
        and _positive(r["clv_ci_low"])
    ]
    checks["seguir_con_cambios_clv_b365_agrupado_ic_positivo"] = bool(solid)
    if level in ("Bueno", "Excelente"):
        conclusion = "seguir"
    elif solid:
        conclusion = "seguir con cambios"
    else:
        conclusion = "no seguir"
    return level, conclusion, checks


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
        load_holdout_predictions: Callable[[], pd.DataFrame] | None = None,
    ) -> None:
        self.load_holdout_predictions = load_holdout_predictions
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
                results[key] = {
                    **result.summary(),
                    "threshold_by_default": threshold_is_default(frame, scenario, proba),
                }
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
                "realistic_reading": {
                    k: {
                        "clv_mean": results[k]["clv_mean"],
                        "clv_ci_low": results[k]["clv_ci_low"],
                        "clv_ci_high": results[k]["clv_ci_high"],
                        "n_bets": results[k]["n_bets"],
                    }
                    for k in results
                    if k.startswith(f"{EVIDENCE_SCENARIO}|")
                },
            },
            "control_avg": {
                k: {"clv_mean": results[k]["clv_mean"], "n_bets": results[k]["n_bets"]}
                for k in results
                if k.startswith("avg|")
            },
            "placebo": {s: placebo_clv(frame, s) for s in SCENARIOS}
            | {"max_longshots": placebo_clv(frame, "max", min_odds=5.0)},
            "figures": figures,
        }
        self._write(VALIDATION_FILE, payload)
        return payload

    # ------------------------------------------------------------------ final test
    @property
    def lock_path(self) -> Path:
        return self.reports_dir / LOCK_FILE

    def _precheck_holdout_predictions(self) -> pd.DataFrame:
        """Checks that do not open the holdout season, so a broken setup does not burn it."""
        if self.load_holdout_predictions is None:
            raise ValueError("holdout predictions loader not configured")
        predictions = self.load_holdout_predictions()
        needed = ["match_id"] + [
            f"{v}__{c}" for v in ("champion", "champion_no_odds") for c in PROBA
        ]
        missing = [c for c in needed if c not in predictions.columns]
        if missing or predictions.empty or predictions["match_id"].duplicated().any():
            raise ValueError(f"holdout predictions are incomplete (missing columns: {missing})")
        return predictions

    def test_frame(
        self, predictions: pd.DataFrame | None = None
    ) -> tuple[pd.DataFrame, dict[str, np.ndarray]]:
        """Holdout season with the spec-001 holdout predictions (models trained without it)."""
        holdout = self.repository.load("holdout")
        frame = holdout.copy()
        frame["target"] = frame["result"].map(RESULT_TO_TARGET)
        frame = frame.sort_values(["date", "kickoff_utc", "match_id"]).reset_index(drop=True)
        if predictions is None:
            predictions = self._precheck_holdout_predictions()
        preds = predictions.set_index("match_id")
        models = {}
        for variant in ("champion", "champion_no_odds"):
            cols = [f"{variant}__{c}" for c in PROBA]
            aligned = preds[cols].reindex(frame["match_id"])
            if aligned.isna().any().any():
                raise ValueError(f"missing holdout predictions of {variant}")
            models[variant] = aligned.to_numpy()
        return frame, models

    def run_final(self) -> dict[str, Any]:
        """ONE-TIME evaluation on the test season with the thresholds fixed in validation."""
        if self.lock_path.exists():
            raise Holdout002AlreadyUsedError(
                f"{self.lock_path} exists: the final backtest already ran."
            )
        validation_path = self.reports_dir / VALIDATION_FILE
        if not validation_path.exists():
            raise FileNotFoundError("run `make backtest-002` (validation) before the final test")
        validation_bytes = validation_path.read_bytes()
        validation = json.loads(validation_bytes.decode("utf-8"))
        predictions = self._precheck_holdout_predictions()
        hashes = {
            "validation_json_sha256": hashlib.sha256(validation_bytes).hexdigest(),
            "holdout_predictions_sha256": _frame_hash(predictions),
        }
        self._lock("started", **hashes)
        frame, models = self.test_frame(predictions)
        coverage = {
            prefix: float(frame[[f"{prefix}_odds_{s}" for s in "hda"]].notna().all(axis=1).mean())
            for prefix in ("ps", "psc", "max", "b365", "avg")
        }
        test: dict[str, dict[str, Any]] = {}
        curves: dict[str, dict[str, list[float]]] = {s: {} for s in SCENARIOS}
        bets = []
        for scenario in SCENARIOS:
            for variant in VARIANTS:
                key = _key(scenario, variant)
                threshold = float(validation["results"][key]["threshold"])
                proba = None if variant == "none" else models[variant]
                result = evaluate(frame, threshold, scenario, variant, proba)
                test[key] = result.summary()
                curves[scenario][f"{variant} (u={threshold:g})"] = result.cumulative_profit
                chosen = select_bets(frame, threshold, scenario, proba)
                bets.append(chosen.assign(scenario=scenario, variant=variant, threshold=threshold))
        artifacts = self.reports_dir / "holdout_artifacts"
        artifacts.mkdir(parents=True, exist_ok=True)
        bets_path = artifacts / "backtest_002_test_bets.parquet"
        pd.concat(bets, ignore_index=True).to_parquet(bets_path, index=False)
        pooled = self._pooled_evidence(validation, frame, models)
        level, conclusion, checks = level_and_conclusion(validation, test, pooled)
        ps_ok = frame[["ps_odds_h", "ps_odds_d", "ps_odds_a"]].notna().all(axis=1)
        month = pd.to_datetime(frame["date"]).dt.strftime("%Y-%m")
        payload = {
            "generated_at": self.clock().isoformat(timespec="seconds"),
            "git_commit": self.git_commit(),
            "primary_strategy": PRIMARY,
            "validation": validation,
            "test": {
                "season": self.leagues.seasons.holdout,
                "n_matches": len(frame),
                "odds_coverage": coverage,
                "pinnacle_coverage_by_league": ps_ok.groupby(frame["league"])
                .mean()
                .round(4)
                .to_dict(),
                "pinnacle_coverage_by_month": ps_ok.groupby(month).mean().round(4).to_dict(),
                "placebo": {s: placebo_clv(frame, s) for s in SCENARIOS}
                | {"max_longshots": placebo_clv(frame, "max", min_odds=5.0)},
                "results": test,
                "bets_file": str(bets_path.relative_to(self.reports_dir)).replace("\\", "/"),
                "figures": self._figures(curves, "002_test"),
            },
            "pooled_b365_evidence": pooled,
            "expected_test_bets_primary": EXPECTED_TEST_BETS_PRIMARY,
            "hashes": hashes,
            "level": level,
            "level_checks": checks,
            "conclusion": conclusion,
        }
        self._write(RESULTS_FILE, payload)
        (self.reports_dir / REPORT_FILE).write_text(
            render_report(_clean(payload)), encoding="utf-8", newline="\n"
        )
        self._lock("completed", level=level, conclusion=conclusion, **hashes)
        return payload

    def _pooled_evidence(
        self,
        validation: dict[str, Any],
        test_frame: pd.DataFrame,
        test_models: dict[str, np.ndarray],
    ) -> dict[str, dict[str, Any]]:
        """CLV of the Bet365 variants over validation + test (same fixed thresholds)."""
        valid_frame, valid_models = self.validation_frame()
        out = {}
        for variant in VARIANTS:
            key = _key(EVIDENCE_SCENARIO, variant)
            threshold = float(validation["results"][key]["threshold"])
            clvs = []
            for frame, models in ((valid_frame, valid_models), (test_frame, test_models)):
                proba = None if variant == "none" else models[variant]
                bets = select_bets(frame, threshold, EVIDENCE_SCENARIO, proba)  # type: ignore[arg-type]
                clvs.append(bets["clv"].to_numpy())
            values = np.concatenate(clvs)
            values = values[np.isfinite(values)]
            low, high = _bootstrap_mean(values)
            out[key] = {
                "n": int(values.size),
                "clv_mean": float(values.mean()) if values.size else float("nan"),
                "clv_ci_low": low,
                "clv_ci_high": high,
            }
        return out

    def _lock(self, status: str, **extra: Any) -> None:
        body = {
            "status": status,
            "timestamp": self.clock().isoformat(timespec="seconds"),
            "git_commit": self.git_commit(),
            **extra,
        }
        self.lock_path.write_text(json.dumps(body, indent=2) + "\n", encoding="utf-8", newline="\n")

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


def _frame_hash(frame: pd.DataFrame) -> str:
    return hashlib.sha256(
        pd.util.hash_pandas_object(frame, index=False).values.tobytes()
    ).hexdigest()


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


# ---------------------------------------------------------------------- report
def _pct(value: Any, digits: int = 1) -> str:
    return "—" if value is None else f"{100 * float(value):+.{digits}f} %"


def _ci(low: Any, high: Any) -> str:
    return "—" if low is None or high is None else f"[{_pct(low)}, {_pct(high)}]"


SCENARIO_TEXT = {
    "max": "mejor cuota (optimista, solo informativo)",
    "b365": "Bet365 (una casa blanda)",
    "avg": "promedio (control)",
}
VARIANT_TEXT = {
    "none": "sin filtro",
    "champion": "filtro campeón E12",
    "champion_no_odds": "filtro sin cuotas E06",
}
CONCLUSION_TEXT = {
    "seguir": "La estrategia principal alcanza el nivel Bueno en el test (CLV positivo y peor caso razonable acotado).",
    "seguir con cambios": "La estrategia principal no alcanza el nivel Bueno en el test, pero alguna variante con Bet365 tiene CLV positivo con IC 95 % por encima de 0 sumando validación y test.",
    "no seguir": "Ninguna variante con Bet365 muestra un CLV positivo con IC 95 % por encima de 0 (validación + test). El escenario de mejor cuota no cuenta porque sus precios no son apostables de forma fiable.",
}


def _results_table(results: dict[str, dict[str, Any]]) -> str:
    lines = [
        "| Cuotas | Variante | Umbral | Apuestas | Con CLV | Acierto | ROI plano | IC 95 % ROI | CLV medio | IC 95 % CLV | % CLV > 0 |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for key, r in results.items():
        scenario, variant = key.split("|")
        default = " (por defecto)" if r.get("threshold_by_default") else ""
        lines.append(
            f"| {SCENARIO_TEXT[scenario]} | {VARIANT_TEXT[variant]} | {r['threshold']:.2f}{default} | "
            f"{r['n_bets']} | {r['clv_n']} | {_pct(r['hit_rate']).lstrip('+')} | {_pct(r['roi_flat'])} | "
            f"{_ci(r['roi_ci_low'], r['roi_ci_high'])} | {_pct(r['clv_mean'], 2)} | "
            f"{_ci(r['clv_ci_low'], r['clv_ci_high'])} | {_pct(r['clv_positive_rate']).lstrip('+')} |"
        )
    return "\n".join(lines)


def _placebo_table(validation: dict[str, Any], test: dict[str, Any]) -> str:
    names = {
        "max": "mejor cuota",
        "max_longshots": "mejor cuota, cuota ≥ 5",
        "b365": "Bet365",
        "avg": "promedio",
    }
    lines = ["| Fuente de cuota (sin selección) | CLV validación | CLV test |", "|---|---|---|"]
    for key, label in names.items():
        v = (validation.get("placebo") or {}).get(key, {})
        s = (test.get("placebo") or {}).get(key, {})
        lines.append(f"| {label} | {_pct(v.get('clv_mean'), 2)} | {_pct(s.get('clv_mean'), 2)} |")
    return "\n".join(lines)


def _pooled_table(pooled: dict[str, dict[str, Any]]) -> str:
    lines = ["| Variante (Bet365) | Apuestas con CLV | CLV medio | IC 95 % |", "|---|---|---|---|"]
    for key, r in pooled.items():
        lines.append(
            f"| {VARIANT_TEXT[key.split('|')[1]]} | {r['n']} | {_pct(r['clv_mean'], 2)} | "
            f"{_ci(r['clv_ci_low'], r['clv_ci_high'])} |"
        )
    return "\n".join(lines)


def _breakdown(result: dict[str, Any], key: str, title: str) -> str:
    rows = result.get(key) or {}
    if not rows:
        return ""
    lines = [f"**{title}**", "", "| Grupo | Apuestas | ROI | CLV medio |", "|---|---|---|---|"]
    for name, v in rows.items():
        lines.append(f"| {name} | {v['n_bets']} | {_pct(v['roi'])} | {_pct(v['clv_mean'], 2)} |")
    return "\n".join(lines) + "\n"


def render_report(payload: dict[str, Any]) -> str:
    validation, test = payload["validation"], payload["test"]
    primary = test["results"][payload["primary_strategy"]]
    coverage = test["odds_coverage"]
    checks = "\n".join(
        f"| {k} | {'✅' if v else '❌'} |" for k, v in payload["level_checks"].items()
    )
    by_league = ", ".join(
        f"{k} {100 * v:.0f} %" for k, v in (test.get("pinnacle_coverage_by_league") or {}).items()
    )
    return "\n".join(
        [
            "# Backtest de la estrategia de referencia Pinnacle (spec 002, US1)",
            "",
            "## Resumen",
            "",
            f"- **Conclusión: {payload['conclusion'].upper()}.** {CONCLUSION_TEXT[payload['conclusion']]}",
            f"- **Nivel (parte backtest de la spec §5): {payload['level']}.**",
            f"- Estrategia principal (declarada antes del test): Bet365 sin filtro. En el test "
            f"{test['season']}: **{primary['n_bets']} apuestas** (se esperaban ~{payload['expected_test_bets_primary']}), "
            f"ROI {_pct(primary['roi_flat'])} (IC 95 % {_ci(primary['roi_ci_low'], primary['roi_ci_high'])}), "
            f"CLV medio {_pct(primary['clv_mean'], 2)} (IC 95 % {_ci(primary['clv_ci_low'], primary['clv_ci_high'])}, "
            f"{primary['clv_n']} apuestas con cierre de Pinnacle).",
            f"- Con {primary['n_bets']} apuestas el test **no tiene potencia estadística**: el ROI es casi puro ruido y "
            "ni el nivel Bueno ni su ausencia son concluyentes. La evidencia principal es el CLV sumando validación y test.",
            "- En validación, el ROI de Bet365 sin filtro (+31.5 % con 130 apuestas) fue suerte: su CLV era solo +0.9 % con un IC que incluía el 0.",
            "",
            "## Método",
            "",
            "- Probabilidad justa: Shin sobre las cuotas de Pinnacle **pre-cierre** (`ps_odds_*`). Las de cierre (`psc_odds_*`) solo se usan para medir el CLV.",
            "- Se apuesta al resultado de mayor EV si `cuota × p_justa − 1 > umbral`, como máximo una apuesta por partido. Escenarios: Bet365 (`b365`, una casa blanda real, **decide la conclusión**), mejor cuota del mercado (`max`, solo informativo) y promedio (`avg`, control).",
            "- Variantes: sin filtro, y con filtro del modelo (`p_modelo ≥ p_justa`) usando predicciones fuera de muestra del campeón E12 y del modelo sin cuotas E06.",
            f'- Umbral elegido en F1–F3 ({", ".join(validation["seasons"])}): {validation["threshold_rule"]}. "Por defecto" = ningún umbral llegó a 300 apuestas.',
            f"- Test: {test['season']} ({test['n_matches']} partidos), evaluado una sola vez (lock `HOLDOUT_002_USED.lock`).",
            f"- Cobertura de cuotas en el test: Pinnacle pre-cierre {100 * coverage['ps']:.0f} %, Pinnacle cierre {100 * coverage['psc']:.0f} %, Bet365 {100 * coverage['b365']:.0f} %, máx. {100 * coverage['max']:.0f} %. Sin Pinnacle no hay referencia ni apuesta. Cobertura de Pinnacle por liga: {by_league}.",
            "",
            "## Validación F1–F3",
            "",
            _results_table(validation["results"]),
            "",
            "## Test (una sola vez)",
            "",
            _results_table(test["results"]),
            "",
            "![ROI acumulado — Bet365](figures/002_test_b365_roi.png)",
            "",
            "## Evidencia agrupada (validación + test) — Bet365",
            "",
            _pooled_table(payload.get("pooled_b365_evidence") or {}),
            "",
            "## Placebo: CLV de la fuente de cuota sin ninguna selección",
            "",
            "Si se apostara a todos los resultados a esa cuota. La diferencia con la tabla anterior es lo que aporta la regla de selección.",
            "",
            _placebo_table(validation, test),
            "",
            "## Detalle de la estrategia principal en el test",
            "",
            _breakdown(primary, "by_league", "Por liga"),
            _breakdown(primary, "by_odds_range", "Por rango de cuota"),
            "## Nivel alcanzado",
            "",
            "| Condición | Cumple |",
            "|---|---|",
            checks,
            "",
            "El nivel Mínimo de la spec también exige el sistema completo (US2–US6) funcionando; aquí solo se evalúa la parte del backtest. Hay 6 variantes × 4 umbrales: sin corrección por comparaciones múltiples, un IC que apenas excluye el 0 es evidencia débil.",
            "",
            "## Advertencias",
            "",
            "- `max` (mejor cuota de football-data/Oddsportal) mezcla exchanges sin comisión y precios atípicos o desactualizados: en el 23 % de los partidos de validación la suma de 1/cuota es < 1 (arbitraje). Su CLV positivo mide que el precio máximo supera a Pinnacle, no que se pueda apostar a ese precio.",
            "- En Bet365 el borde desaparece al subir el EV (validación: CLV +1.8 % con EV 1–3 %, −2.5 % con EV > 5 %): cuando la casa blanda se aleja mucho de Pinnacle pre-cierre, el precio desactualizado suele ser el de Pinnacle.",
            "- Las casas limitan cuentas ganadoras; el backtest no lo modela. Las cuotas de football-data se toman en un momento fijo (normalmente viernes o martes).",
            "",
            "> **Juego responsable.** Apostar implica riesgo de pérdida. Ningún backtest garantiza resultados futuros.",
            "",
        ]
    )
