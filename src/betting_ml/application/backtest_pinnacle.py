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
    select_bets,
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


class Holdout002AlreadyUsedError(RuntimeError):
    pass


def level_and_conclusion(
    validation: dict[str, Any], test: dict[str, dict[str, Any]]
) -> tuple[str, str, dict[str, bool]]:
    """Spec 002 §5 (backtest part) and the continue / change / stop conclusion."""
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
    others = [k for k, r in test.items() if not k.startswith("avg|") and _positive(r["clv_mean"])]
    if level in ("Bueno", "Excelente"):
        conclusion = "seguir"
    elif others:
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

    # ------------------------------------------------------------------ final test
    @property
    def lock_path(self) -> Path:
        return self.reports_dir / LOCK_FILE

    def test_frame(self) -> tuple[pd.DataFrame, dict[str, np.ndarray]]:
        """Holdout season with the spec-001 holdout predictions (models trained without it)."""
        holdout = self.repository.load("holdout")
        frame = holdout.copy()
        frame["target"] = frame["result"].map(RESULT_TO_TARGET)
        frame = frame.sort_values(["date", "kickoff_utc", "match_id"]).reset_index(drop=True)
        if self.load_holdout_predictions is None:
            raise ValueError("holdout predictions loader not configured")
        preds = self.load_holdout_predictions().set_index("match_id")
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
        validation = json.loads(validation_path.read_text(encoding="utf-8"))
        self._lock("started")
        frame, models = self.test_frame()
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
        level, conclusion, checks = level_and_conclusion(validation, test)
        payload = {
            "generated_at": self.clock().isoformat(timespec="seconds"),
            "git_commit": self.git_commit(),
            "primary_strategy": PRIMARY,
            "validation": validation,
            "test": {
                "season": self.leagues.seasons.holdout,
                "n_matches": len(frame),
                "odds_coverage": coverage,
                "results": test,
                "bets_file": str(bets_path.relative_to(self.reports_dir)).replace("\\", "/"),
                "figures": self._figures(curves, "002_test"),
            },
            "level": level,
            "level_checks": checks,
            "conclusion": conclusion,
        }
        self._write(RESULTS_FILE, payload)
        (self.reports_dir / REPORT_FILE).write_text(
            render_report(_clean(payload)), encoding="utf-8", newline="\n"
        )
        self._lock("completed", level=level, conclusion=conclusion)
        return payload

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
    "max": "mejor cuota (optimista)",
    "b365": "Bet365 (una casa blanda)",
    "avg": "promedio (control)",
}
VARIANT_TEXT = {
    "none": "sin filtro",
    "champion": "filtro campeón E12",
    "champion_no_odds": "filtro sin cuotas E06",
}
CONCLUSION_TEXT = {
    "seguir": "La estrategia principal tiene CLV positivo en el test y un peor caso razonable acotado: se sigue construyendo la spec 002.",
    "seguir con cambios": "La estrategia principal no alcanza el nivel Bueno en el test, pero algún escenario mantiene CLV positivo: se sigue, con los cambios indicados abajo.",
    "no seguir": "Ningún escenario mantiene CLV positivo en el test: no hay evidencia para construir la herramienta sobre esta estrategia.",
}


def _results_table(results: dict[str, dict[str, Any]]) -> str:
    lines = [
        "| Cuotas | Variante | Umbral | Apuestas | Acierto | ROI plano | IC 95 % ROI | CLV medio | IC 95 % CLV | % CLV > 0 | Máx. drawdown (u) |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for key, r in results.items():
        scenario, variant = key.split("|")
        lines.append(
            f"| {SCENARIO_TEXT[scenario]} | {VARIANT_TEXT[variant]} | {r['threshold']:.2f} | {r['n_bets']} | "
            f"{_pct(r['hit_rate']).lstrip('+')} | {_pct(r['roi_flat'])} | {_ci(r['roi_ci_low'], r['roi_ci_high'])} | "
            f"{_pct(r['clv_mean'], 2)} | {_ci(r['clv_ci_low'], r['clv_ci_high'])} | "
            f"{_pct(r['clv_positive_rate']).lstrip('+')} | {r['max_drawdown_flat']:.1f} |"
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
    return "\n".join(
        [
            "# Backtest de la estrategia de referencia Pinnacle (spec 002, US1)",
            "",
            "## Resumen",
            "",
            f"- **Conclusión: {payload['conclusion'].upper()}.** {CONCLUSION_TEXT[payload['conclusion']]}",
            f"- **Nivel (parte backtest de la spec §5): {payload['level']}.**",
            f"- Estrategia principal (declarada antes del test): Bet365 sin filtro. En el test "
            f"{test['season']}: {primary['n_bets']} apuestas, ROI {_pct(primary['roi_flat'])} "
            f"(IC 95 % {_ci(primary['roi_ci_low'], primary['roi_ci_high'])}), CLV medio "
            f"{_pct(primary['clv_mean'], 2)} (IC 95 % {_ci(primary['clv_ci_low'], primary['clv_ci_high'])}).",
            "- El ROI con pocos cientos de apuestas es mayormente ruido; el indicador fiable es el CLV.",
            "",
            "## Método",
            "",
            "- Probabilidad justa: Shin sobre las cuotas de Pinnacle **pre-cierre** (`ps_odds_*`). Las de cierre (`psc_odds_*`) solo se usan para medir el CLV.",
            "- Se apuesta al resultado de mayor EV si `cuota × p_justa − 1 > umbral`, como máximo una apuesta por partido. Escenarios de cuota: mejor cuota del mercado (`max`, optimista), Bet365 (`b365`, una casa blanda) y promedio (`avg`, control).",
            "- Variantes: sin filtro, y con filtro del modelo (`p_modelo ≥ p_justa`) usando predicciones fuera de muestra del campeón E12 y del modelo sin cuotas E06.",
            f"- Umbral elegido en F1–F3 ({', '.join(validation['seasons'])}): {validation['threshold_rule']}.",
            f"- Test: {test['season']} ({test['n_matches']} partidos), evaluado una sola vez (lock `HOLDOUT_002_USED.lock`).",
            f"- Cobertura de cuotas en el test: Pinnacle pre-cierre {100 * coverage['ps']:.0f} %, Pinnacle cierre {100 * coverage['psc']:.0f} %, Bet365 {100 * coverage['b365']:.0f} %, máx. {100 * coverage['max']:.0f} %. Sin Pinnacle no se apuesta: en el test solo se evalúa ~la mitad de los partidos.",
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
            "El nivel Mínimo de la spec también exige el sistema completo (US2–US6) funcionando; aquí solo se evalúa la parte del backtest.",
            "",
            "## Advertencias",
            "",
            "- El escenario `max` usa la mejor cuota entre decenas de casas; su CLV positivo en validación viene sobre todo de longshots con precios atípicos (hasta +83 % sobre Pinnacle) que suelen ser inaccesibles, tener límites bajos o ser errores. No es una estimación realista.",
            "- Las casas limitan cuentas ganadoras; el backtest no lo modela.",
            "- Las cuotas de football-data se toman en un momento fijo (normalmente el viernes o el martes); en vivo los precios cambian.",
            "",
            "> **Juego responsable.** Apostar implica riesgo de pérdida. Ningún backtest garantiza resultados futuros.",
            "",
        ]
    )
