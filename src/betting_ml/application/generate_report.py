"""Use case: build reports/REPORT.md (US4) from the recorded results. It only reads files
written by earlier steps (experiments.csv, champion.json, holdout_results.json)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

LEVEL_TEXT = {
    "No alcanzado": "no alcanza el nivel mínimo",
    "Mínimo": "alcanza el nivel **Mínimo**",
    "Bueno": "alcanza el nivel **Bueno**",
    "Excelente": "alcanza el nivel **Excelente**",
}
MODEL_LABELS = {
    "champion": "Campeón",
    "champion_no_odds": "Mejor sin cuotas",
    "E02": "E02 (logística Elo)",
    "E01-freq": "Frecuencias por liga",
    "E01-avg": "Mercado Avg pre-cierre (Shin)",
    "E01-psc_with_freq_fallback": "Pinnacle cierre con relleno de frecuencias*",
}


def _f(value: Any, digits: int = 4) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)) or value == "":
        return "—"
    return f"{float(value):.{digits}f}"


def _pct(value: Any, digits: int = 1) -> str:
    if value is None or value == "" or (isinstance(value, float) and pd.isna(value)):
        return "—"
    return f"{100 * float(value):+.{digits}f} %"


def _table(headers: list[str], rows: list[list[str]]) -> str:
    lines = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    lines += ["| " + " | ".join(str(c) for c in row) + " |" for row in rows]
    return "\n".join(lines)


class GenerateReport:
    def __init__(self, reports_dir: Path, champion_path: Path) -> None:
        self.reports_dir = reports_dir
        self.champion_path = champion_path

    def run(self) -> Path:
        experiments = pd.read_csv(self.reports_dir / "experiments.csv", keep_default_na=False)
        selection = json.loads(self.champion_path.read_text(encoding="utf-8"))
        holdout_path = self.reports_dir / "holdout_results.json"
        holdout = (
            json.loads(holdout_path.read_text(encoding="utf-8")) if holdout_path.exists() else None
        )
        text = render(experiments, selection, holdout)
        path = self.reports_dir / "REPORT.md"
        path.write_text(text, encoding="utf-8", newline="\n")
        return path


def render(
    experiments: pd.DataFrame, selection: dict[str, Any], holdout: dict[str, Any] | None
) -> str:
    champion = selection["champion"]
    no_odds = selection["champion_no_odds"]
    parts = [
        "# Informe final — Modelo de predicción 1X2 (spec 001)",
        "",
        _summary(champion, no_odds, holdout),
        "## 1. Datos",
        "",
        "Cinco grandes ligas (E0, SP1, D1, I1, F1), temporadas 2014-15 a 2024-25 para entrenar y "
        "validar (19 837 partidos) y 2025-26 como holdout (1 752 partidos), con resultados y cuotas "
        "de football-data.co.uk y xG de Understat (emparejamiento 100 % tras la segunda pasada). "
        "Detalle en [`data_quality.md`](data_quality.md).",
        "",
        "## 2. Validación",
        "",
        "Walk-forward por temporada con ventana expansiva: F1 valida en 2022-23, F2 en 2023-24 y F3 "
        "en 2024-25, entrenando con todas las temporadas anteriores. Los hiperparámetros (ξ, Optuna, "
        "calibración, pesos) se eligen solo con la última temporada de entrenamiento de cada fold. "
        "Métrica principal: log loss multiclase (menor es mejor).",
        "",
        "## 3. Experimentos",
        "",
        _experiments_table(experiments),
        "",
        "Figuras por experimento en [`figures/`](figures/) (`{ID}_calibration.png`, `{ID}_roi.png`). "
        "El ROI de validación es optimista: el umbral de apuesta se elige sobre las mismas "
        "predicciones (ver `decisions.md`).",
        "",
        _stopping_notes(experiments),
        "## 4. Campeón y por qué",
        "",
        _champion_section(champion, no_odds, selection),
    ]
    if holdout is None:
        parts += ["## 5. Holdout", "", "El holdout todavía no se ha evaluado.", ""]
    else:
        parts += [
            _holdout_section(holdout),
            _betting_section(holdout),
            _league_section(holdout),
            _level_section(holdout),
        ]
    parts += [_limitations(holdout), _next_steps()]
    return "\n".join(parts) + "\n"


def _summary(
    champion: dict[str, Any], no_odds: dict[str, Any], holdout: dict[str, Any] | None
) -> str:
    if holdout is None:
        return "Resumen pendiente de la evaluación en el holdout.\n"
    m = holdout["metrics"]
    diff = holdout["paired_log_loss_differences"]["champion_vs_E01-avg"]
    realistic = holdout["betting"]["champion"]["realistic"]
    return "\n".join(
        [
            "## Resumen",
            "",
            f"- El campeón **{champion['experiment_id']}** ({champion['model']}) "
            f"{LEVEL_TEXT[holdout['level']]} del criterio de éxito en el holdout "
            f"{holdout['holdout_season']}: log loss {_f(m['champion']['log_loss'])} frente a "
            f"{_f(m['E01-avg']['log_loss'])} del mercado promedio pre-cierre (umbral de Bueno: "
            f"{_f(m['E01-avg']['log_loss'] + 0.005)}).",
            f"- **El modelo no le gana al mercado.** Es {_f(diff['mean_diff'])} peor que usar "
            f"directamente las probabilidades del mercado (IC 95 % [{_f(diff['ci_low'])}, "
            f"{_f(diff['ci_high'])}]). El nivel Bueno depende de la tolerancia de +0.005 y el IC "
            "la contiene, así que el resultado no es concluyente.",
            f"- Sin cuotas, el mejor modelo ({no_odds['experiment_id']}) logra "
            f"{_f(m['champion_no_odds']['log_loss'])}: mejora a las frecuencias "
            f"({_f(m['E01-freq']['log_loss'])}) y al Elo de E02 ({_f(m['E02']['log_loss'])}) pero "
            "queda lejos del mercado.",
            f"- Apostar con el campeón no es rentable: {realistic['n_bets']} apuestas con cuota "
            f"promedio, ROI {_pct(realistic['roi_flat'])} (IC 95 % "
            f"[{_pct(realistic['roi_ci_low'])}, {_pct(realistic['roi_ci_high'])}]) y CLV "
            f"{_pct(realistic['clv_mean'])} frente al cierre de Pinnacle.",
            "",
        ]
    )


def _experiments_table(experiments: pd.DataFrame) -> str:
    rows = []
    for _, r in experiments.iterrows():
        rows.append(
            [
                r["exp_id"],
                r["model"],
                "sí" if str(r["uses_odds"]).lower() == "true" else "no",
                _f(r["val_ll_f1"]),
                _f(r["val_ll_f2"]),
                _f(r["val_ll_f3"]),
                f"**{_f(r['val_ll_mean'])}**",
                _f(r["val_ece"], 3),
                str(r["n_bets"]),
                _pct(r["roi_flat"]),
                r["conclusion"],
            ]
        )
    headers = [
        "ID",
        "Modelo",
        "Cuotas",
        "F1",
        "F2",
        "F3",
        "Media",
        "ECE",
        "Apuestas",
        "ROI",
        "Conclusión",
    ]
    return _table(headers, rows)


def _stopping_notes(experiments: pd.DataFrame) -> str:
    ran = {str(e).split("-")[0] for e in experiments["exp_id"]}
    skipped = [f"E{i:02d}" for i in range(1, 16) if f"E{i:02d}" not in ran]
    return (
        "**Regla de parada.** La familia sin cuotas se detuvo tras E09 (4 experimentos seguidos "
        "sin mejorar el mejor log loss en más de 0.002); E12 alcanzó en validación el umbral del "
        "nivel Bueno (≤ mercado Avg + 0.005), lo que activa la parada anticipada. "
        f"No se corrieron: {', '.join(skipped)}. La aplicación de la regla por familia se decidió "
        "después de ver E06–E08 (registrada antes de E09 en `decisions.md`); con la regla global "
        "literal no se habría probado ningún modelo con cuotas.\n"
    )


def _champion_section(
    champion: dict[str, Any], no_odds: dict[str, Any], selection: dict[str, Any]
) -> str:
    rows = []
    for label, entry in (("Campeón", champion), ("Mejor sin cuotas", no_odds)):
        vm = entry["validation_metrics"]
        rows.append(
            [
                label,
                entry["experiment_id"],
                entry["model"],
                _f(vm["log_loss"]),
                _f(vm["brier"]),
                _f(vm["ece"], 3),
                _f(entry["bet_threshold"], 2),
                entry["reason"],
            ]
        )
    excluded = "; ".join(f"{k}: {v}" for k, v in selection.get("excluded", {}).items())
    return "\n".join(
        [
            f"Regla: {selection['rule']}",
            "",
            _table(
                ["Rol", "ID", "Modelo", "Log loss val.", "Brier", "ECE", "Umbral", "Motivo"], rows
            ),
            "",
            f"Excluidos: {excluded}.",
            "",
        ]
    )


def _holdout_section(holdout: dict[str, Any]) -> str:
    rows = []
    for key, label in MODEL_LABELS.items():
        m = holdout["metrics"][key]
        rows.append(
            [
                label,
                _f(m["log_loss"]),
                _f(m["brier"]),
                _f(m["rps"]),
                _f(m["ece"], 3),
                _f(m["accuracy"], 3),
            ]
        )
    diffs = holdout["paired_log_loss_differences"]
    diff_rows = [
        [k.replace("_vs_", " − "), _f(v["mean_diff"]), f"[{_f(v['ci_low'])}, {_f(v['ci_high'])}]"]
        for k, v in diffs.items()
    ]
    sub = holdout["pinnacle_closing_subset"]
    return "\n".join(
        [
            f"## 5. Evaluación final en el holdout {holdout['holdout_season']}",
            "",
            f"Evaluado una sola vez ({holdout['evaluated_at']}, commit `{holdout['git_commit']}`), "
            f"entrenando con {holdout['train_seasons'][0]}…{holdout['train_seasons'][-1]}. "
            f"{holdout['n_matches']} partidos.",
            "",
            _table(["Modelo", "Log loss", "Brier", "RPS", "ECE", "Acierto"], rows),
            "",
            "\\* Pinnacle solo publica cuotas de cierre para el "
            f"{100 * sub['coverage']:.0f} % del holdout; en el resto esa fila usa frecuencias, así que "
            "no es la línea base de Pinnacle. La comparación válida es sobre el subconjunto:",
            "",
            _table(
                [
                    "Subconjunto con cierre de Pinnacle",
                    "n",
                    "Campeón",
                    "Sin cuotas",
                    "Mercado Avg",
                    "Pinnacle cierre",
                ],
                [
                    [
                        "",
                        str(sub["n"]),
                        _f(sub["champion"]),
                        _f(sub["champion_no_odds"]),
                        _f(sub["E01-avg"]),
                        _f(sub["psc"]),
                    ]
                ],
            ),
            "",
            "Diferencias de log loss por partido (IC 95 % bootstrap pareado, 2000 remuestreos; "
            "negativo = el primero es mejor):",
            "",
            _table(["Comparación", "Diferencia media", "IC 95 %"], diff_rows),
            "",
            "![Calibración del campeón](figures/holdout_champion_calibration.png)",
            "",
        ]
    )


def _betting_section(holdout: dict[str, Any]) -> str:
    rows = []
    for model in ("champion", "champion_no_odds"):
        b = holdout["betting"][model]
        for scenario, label in (("realistic", "Realista (Avg)"), ("optimistic", "Optimista (Max)")):
            r = b[scenario]
            rows.append(
                [
                    MODEL_LABELS[model],
                    label,
                    _f(b["threshold"], 2),
                    str(r["n_bets"]),
                    _pct(r["hit_rate"]).lstrip("+"),
                    _pct(r["roi_flat"]),
                    f"[{_pct(r['roi_ci_low'])}, {_pct(r['roi_ci_high'])}]",
                    _f(r["max_drawdown_flat"], 1),
                    _pct(r["clv_mean"]),
                    _pct(r["roi_kelly"]),
                    _f(r["final_bankroll_kelly"], 3),
                ]
            )
    headers = [
        "Modelo",
        "Cuotas",
        "Umbral EV",
        "Apuestas",
        "Acierto",
        "ROI plano",
        "IC 95 %",
        "Máx. drawdown (u)",
        "CLV medio",
        "ROI Kelly",
        "Bankroll final Kelly",
    ]
    return "\n".join(
        [
            "## 6. Simulación de apuestas en el holdout",
            "",
            "Una apuesta por partido (la de mayor EV) si EV = p × cuota − 1 supera el umbral fijado "
            "en validación. Stake plano de 1 unidad y Kelly 25 % con tope del 2 % del bankroll. "
            "CLV = cuota tomada / cuota justa de cierre de Pinnacle − 1 (solo donde existe).",
            "",
            _table(headers, rows),
            "",
            "Ningún intervalo de ROI es enteramente positivo y el CLV medio es negativo en todos "
            "los casos: no hay evidencia de ventaja frente al mercado. El escenario optimista (mejor "
            "cuota entre casas) mejora el ROI porque la mejor cuota tiene margen casi nulo, lo que "
            "anticipa el valor del comparador de la spec 002, pero su IC también incluye el 0.",
            "",
            "![ROI acumulado del campeón](figures/holdout_champion_roi.png)",
            "",
        ]
    )


def _league_section(holdout: dict[str, Any]) -> str:
    rows = [
        [league, _f(v["champion"]), _f(v["champion_no_odds"]), _f(v["E01-avg"]), _f(v["E01-freq"])]
        for league, v in holdout["metrics_by_league"].items()
    ]
    return "\n".join(
        [
            "## 7. Análisis por liga (holdout, log loss)",
            "",
            _table(["Liga", "Campeón", "Sin cuotas", "Mercado Avg", "Frecuencias"], rows),
            "",
            _league_comment(holdout["metrics_by_league"]),
            "",
        ]
    )


def _league_comment(by_league: dict[str, dict[str, float]]) -> str:
    better = [lg for lg, v in by_league.items() if v["champion"] <= v["E01-avg"] + 0.0005]
    hardest = max(by_league, key=lambda lg: by_league[lg]["E01-avg"])
    lead = (
        f"El campeón iguala o mejora al mercado (±0.0005) en: {', '.join(better)}; en el resto queda por detrás."
        if better
        else "El campeón queda por detrás del mercado en todas las ligas."
    )
    return f"{lead} La liga más difícil de predecir para el mercado es {hardest}."


def _level_section(holdout: dict[str, Any]) -> str:
    checks = holdout["level_checks"]
    names = {
        "minimo_vs_frecuencias": "Mínimo: mejor que frecuencias",
        "minimo_vs_e02": "Mínimo: mejor que E02 (Elo)",
        "minimo_ece": "Mínimo: ECE < 0.03",
        "bueno_vs_mercado_avg": "Bueno: ≤ mercado Avg + 0.005",
        "excelente_vs_pinnacle_cierre": "Excelente: < Pinnacle al cierre (subconjunto)",
        "excelente_estrategia_valor": "Excelente: ROI > 0 con IC sin 0 y ≥ 300 apuestas",
    }
    rows = [[names[k], "✅" if v else "❌"] for k, v in checks.items()]
    return "\n".join(
        [
            f"## 8. Nivel alcanzado: {holdout['level']}",
            "",
            _table(["Condición (spec §6)", "Cumple"], rows),
            "",
        ]
    )


def _limitations(holdout: dict[str, Any] | None) -> str:
    return "\n".join(
        [
            "## 9. Limitaciones",
            "",
            "- **El campeón es peor que el mercado solo**, en validación (los tres folds) y en el "
            "holdout. Para estimar probabilidades es preferible usar el mercado directamente; el "
            "modelo sirve como sistema completo (con versión sin cuotas) pero no aporta ventaja.",
            "- El nivel Bueno se apoya en la tolerancia de +0.005, y el IC de la diferencia con el "
            "mercado la contiene: con otra temporada podría no cumplirse.",
            "- E13 (stacking de modelo sin cuotas + mercado), la vía natural para no quedar por debajo "
            "del mercado, no se probó por la regla de parada. Tampoco E10, E11, E14 ni E15.",
            "- La regla de parada se aplicó por familia de modelos (decisión tomada tras ver E06–E08).",
            "- Pinnacle dejó de aparecer en football-data a mitad de 2025-26: la línea base de cierre "
            "del holdout cubre solo ~51 % de partidos y en 2026-27 no hay Pinnacle. El mercado Avg "
            "de las temporadas recientes tiene más margen que en el entrenamiento.",
            "- ECE sobre ~1 750 partidos es ruidoso; la condición ECE < 0.03 puede fallar por azar.",
            "- El ROI de validación es optimista (el umbral se elige sobre las mismas predicciones).",
            "- Features solo de liga: no hay copas ni competiciones europeas (el descanso y la "
            "congestión subestiman la carga real), ni lesiones o alineaciones.",
            "- Temporadas 2014-15 a 2018-19 sin hora de inicio (se imputa 15:00 UK).",
            "",
        ]
    )


def _next_steps() -> str:
    return "\n".join(
        [
            "## 10. Próximos pasos",
            "",
            "1. Probar E13 (stacking logístico sobre [p_sin_cuotas, p_mercado]) como nuevo ciclo de "
            "experimentos, con un holdout nuevo (2026-27 completo) para no reutilizar el actual.",
            "2. Comparador de casas (spec 002): la mejor cuota reduce el margen a ~0 % y, en la simulación, lleva el ROI a "
            "≈ 0 (sin evidencia de ventaja).",
            "3. Features de alineaciones/lesiones y calendario europeo.",
            "4. Seguimiento en vivo (US6) para acumular evidencia fuera de muestra en 2026-27.",
            "",
            "> **Juego responsable.** Proyecto educativo. Ningún modelo garantiza ganancias y este, en "
            "particular, no muestra ventaja frente al mercado.",
        ]
    )
