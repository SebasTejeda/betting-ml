"""Command line interface (typer). Each Makefile target maps to one command."""

from __future__ import annotations

import logging

import typer

app = typer.Typer(help="betting-ml: datos, experimentos, evaluación y API.", no_args_is_help=True)


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


@app.command()
def version() -> None:
    """Muestra la versión del paquete."""
    from betting_ml import __version__

    typer.echo(__version__)


@app.command()
def data(verbose: bool = False) -> None:
    """Descarga, limpia y une los datos; escribe data/processed/*.parquet y el reporte."""
    from betting_ml.container import Container

    _setup_logging(verbose)
    result = Container().build_dataset().run()
    typer.echo(
        f"matches={len(result.matches)} holdout={len(result.holdout)} "
        f"current={len(result.current)} xg_match_rate={result.xg_match_rate:.2%}"
    )


@app.command("data-europe")
def data_europe(verbose: bool = False) -> None:
    """Champions/Europa League y ligas (openfootball) + Elo propio entre ligas (spec 003)."""
    from betting_ml.container import Container

    _setup_logging(verbose)
    container = Container()
    elo = container.build_club_elo().run()
    typer.echo(
        f"club_elo: matches={len(elo.matches)} clubs={elo.history['key'].nunique()} "
        f"last={elo.matches['date'].max().date()}"
    )
    result = container.build_europe().run()
    typer.echo(
        f"europe_matches={len(result.matches)} europe_holdout={len(result.holdout)} "
        f"rating_coverage={result.rating_coverage:.2%} snapshots={result.snapshots}"
    )


@app.command()
def analyze(
    home: str,
    away: str,
    day: str = typer.Option(None, "--date", help="Fecha del partido (YYYY-MM-DD); hoy por defecto"),
    competition: str = typer.Option(None, help="Liga (E0, SP1…) o UCL/UEL"),
) -> None:
    """Análisis de un partido por consola (spec 003): mercados, lo más probable y forma."""
    from datetime import date as _date

    from betting_ml.container import Container

    analysis = Container().analyze_match.analyze(
        home, away, _date.fromisoformat(day) if day else None, competition
    )
    m = analysis.match
    eg = m["expected_goals"]
    typer.echo(
        f"{m['home_team']} vs {m['away_team']} · {m['competition']} · {m['date']} · "
        f"goles esperados {eg['home']:.2f} - {eg['away']:.2f} ({m['model']})"
    )
    for warning in m["warnings"]:
        typer.echo(f"  ! {warning}")
    if analysis.best_options_note:
        typer.echo(f"Mejores opciones: {analysis.best_options_note}")
    typer.echo("Lo más probable:")
    for item in analysis.most_likely:
        typer.echo(f"  - {item['label']}: {item['price_comment']} [{item['confidence']}]")
        for reason in item["reasons"]:
            typer.echo(f"      · {reason['text']}")
    for side in ("home", "away"):
        form = analysis.form[side]
        typer.echo(f"Forma {form['team']}: {form['summary']['streak']}")


@app.command("validate-cross-league")
def validate_cross_league(
    final: bool = typer.Option(False, "--final", help="Test europeo 2025-26, UNA sola vez (lock)"),
    verbose: bool = False,
) -> None:
    """Ajuste entre ligas walk-forward y calibración europea (spec 003, T006)."""
    from betting_ml.container import Container

    _setup_logging(verbose)
    if final:
        evaluation = Container().validate_cross_league_final().run_final()
        for name, metrics in evaluation.metrics.items():
            typer.echo(
                f"{name}: ll_1x2={metrics['log_loss_1x2']:.4f} ll_ou25={metrics['log_loss_ou25']:.4f}"
            )
        typer.echo(f"test={evaluation.n_test} · niveles publicados: {evaluation.levels}")
        return
    result = Container().validate_cross_league().run()
    for name, metrics in result.mean.items():
        typer.echo(
            f"{name}: ll_1x2={metrics['log_loss_1x2']:.4f} ll_ou25={metrics['log_loss_ou25']:.4f} "
            f"brier={metrics['brier_1x2']:.4f}"
        )
    typer.echo(
        f"elegido: {result.chosen} · niveles: {[(c.group, c.confidence) for c in result.calibration]}"
    )


@app.command("validate-markets")
def validate_markets(
    final: bool = typer.Option(False, "--final", help="Test 2025-26, UNA sola vez (lock)"),
    verbose: bool = False,
) -> None:
    """Calibración de los mercados derivados y backtest Más/Menos 2.5 en F1–F3 (spec 003)."""
    from betting_ml.container import Container

    _setup_logging(verbose)
    if final:
        evaluation = Container().validate_markets_final().run_final()
        counts = {
            lvl: list(evaluation.levels.values()).count(lvl) for lvl in ("alta", "media", "baja")
        }
        typer.echo(f"nivel spec 003: {evaluation.spec_level} · publicados: {counts}")
        typer.echo(f"informe: {evaluation.report_path}")
        return
    result = Container().validate_markets().run()
    for cal in result.calibration:
        worst_ece = max(s["ece"] for s in cal.by_selection.values())
        slot, sel = max(cal.by_selection.items(), key=lambda kv: abs(kv[1]["rel_bias"]))
        typer.echo(
            f"{cal.group:<24} {cal.confidence:<5} max_ece={worst_ece:.4f} "
            f"mayor_sesgo={slot} {sel['rel_bias']:+.1%} (z {sel['rel_bias_z']:+.1f}) "
            f"ll={cal.model['log_loss']:.4f} (base {cal.baseline['log_loss']:.4f})"
        )
    for scenario, data in result.ou_backtest["scenarios"].items():
        typer.echo(f"ou25 {scenario}: umbral={data['chosen_threshold']}")


@app.command()
def exp(exp_id: str, verbose: bool = False, skip_existing: bool = False) -> None:
    """Corre un experimento de configs/experiments/{ID}_*.yaml en F1–F3."""
    from betting_ml.config import load_experiment
    from betting_ml.container import Container

    _setup_logging(verbose)
    container = Container()
    config = load_experiment(exp_id, container.settings.configs_dir / "experiments")
    if skip_existing:
        recorded = set(container.experiment_store.read_rows()["exp_id"])
        if set(config.model_specs()) <= recorded:
            typer.echo(f"{exp_id} ya está en experiments.csv; se omite (--skip-existing).")
            return
    for result in container.run_experiment().run(config):
        row = result.row
        typer.echo(
            f"{row['exp_id']} {row['model']}: val_ll_mean={row['val_ll_mean']} "
            f"(F1 {row['val_ll_f1']}, F2 {row['val_ll_f2']}, F3 {row['val_ll_f3']}) "
            f"ece={row['val_ece']} bets={row['n_bets']} roi={row['roi_flat']} "
            f"[{row['roi_ci_low']}, {row['roi_ci_high']}] clv={row['clv_mean']} "
            f"t={row['runtime_s']}s"
        )


@app.command()
def conclude(exp_id: str, text: str) -> None:
    """Escribe la conclusión de un experimento en reports/experiments.csv."""
    from betting_ml.container import Container

    Container().experiment_store.set_conclusion(exp_id, text)
    typer.echo(f"{exp_id}: conclusión registrada")


@app.command()
def select(skip_if_locked: bool = False) -> None:
    """Elige campeón y campeón sin cuotas (experiments.md §4) → models/champion.json."""
    import json

    from betting_ml.application.select_champion import check_champions_match_lock
    from betting_ml.container import Container

    container = Container()
    use_case = container.select_champion()
    if skip_if_locked and use_case.lock_path is not None and use_case.lock_path.exists():
        lock = json.loads(use_case.lock_path.read_text(encoding="utf-8"))
        if lock.get("status") != "completed":
            typer.echo(f"El lock del holdout quedó en estado {lock.get('status')!r}.", err=True)
            raise typer.Exit(code=1)
        selection_file = json.loads(container.champion_path.read_text(encoding="utf-8"))
        check_champions_match_lock(selection_file, lock)
        typer.echo(
            "Campeón ya evaluado en el holdout; champion.json coincide con el lock. Se omite."
        )
        return
    selection = use_case.run()
    for label, entry in (
        ("champion", selection.champion),
        ("champion_no_odds", selection.champion_no_odds),
    ):
        typer.echo(
            f"{label}: {entry['experiment_id']} ({entry['model']}) "
            f"val_ll={entry['validation_metrics']['log_loss']:.5f} — {entry['reason']}"
        )
    for exp_id, why in selection.excluded.items():
        typer.echo(f"  excluido {exp_id}: {why}")


@app.command()
def holdout(verbose: bool = False, skip_if_done: bool = False) -> None:
    """Evaluación final ÚNICA sobre el holdout (crea reports/HOLDOUT_USED.lock)."""
    from betting_ml.container import Container

    _setup_logging(verbose)
    use_case = Container().evaluate_holdout()
    if skip_if_done and use_case.lock_path.exists():
        import json

        status = json.loads(use_case.lock_path.read_text(encoding="utf-8")).get("status")
        if status != "completed":
            typer.echo(f"El lock del holdout quedó en estado {status!r}: revisar a mano.", err=True)
            raise typer.Exit(code=1)
        typer.echo(f"Holdout ya evaluado ({use_case.lock_path}); se omite.")
        return
    report = use_case.run()
    for name, values in report.results["metrics"].items():
        typer.echo(f"{name}: log_loss={values['log_loss']:.5f} ece={values['ece']:.4f}")
    subset = report.results["pinnacle_closing_subset"]
    typer.echo(
        f"Subconjunto con cierre de Pinnacle (n={subset['n']}): campeón {subset['champion']:.5f} "
        f"vs Pinnacle {subset['psc']:.5f}"
    )
    typer.echo(f"Nivel alcanzado: {report.level}")


@app.command()
def report() -> None:
    """Genera reports/REPORT.md a partir de los resultados registrados."""
    from betting_ml.container import Container

    typer.echo(f"Informe escrito en {Container().generate_report().run()}")


@app.command("train-prod")
def train_prod(verbose: bool = False) -> None:
    """Re-entrena campeón y campeón sin cuotas con todos los datos disponibles."""
    from betting_ml.container import Container

    _setup_logging(verbose)
    versions = Container().train_production().run()
    typer.echo(f"Modelos de producción: {versions}")


@app.command()
def track() -> None:
    """Califica las predicciones servidas con los resultados reales (US6)."""
    from betting_ml.container import Container

    tracking = Container().tracking
    graded = tracking.update()
    typer.echo(f"Predicciones calificadas ahora: {graded}")
    typer.echo(f"Resumen: {tracking.summary().to_dict()}")


@app.command()
def serve(host: str = "127.0.0.1", port: int = 8000, reload: bool = False) -> None:
    """Levanta la API REST (Swagger en /docs)."""
    import uvicorn

    uvicorn.run("betting_ml.api.main:app", host=host, port=port, reload=reload)


@app.command("backtest-002")
def backtest_002() -> None:
    """Backtest de la estrategia de referencia Pinnacle en F1–F3 (spec 002, repetible)."""
    from betting_ml.container import Container

    payload = Container().backtest_pinnacle().run_validation()
    for key, result in payload["results"].items():
        typer.echo(
            f"{key:<26} u={result['threshold']:<5} apuestas={result['n_bets']:<5} "
            f"ROI={_fmt(result['roi_flat'])} [{_fmt(result['roi_ci_low'])}, {_fmt(result['roi_ci_high'])}] "
            f"CLV={_fmt(result['clv_mean'])} [{_fmt(result['clv_ci_low'])}, {_fmt(result['clv_ci_high'])}]"
        )
    gate = payload["gate"]
    typer.echo(f"Puerta (CLV medio > 0 en validación): {'PASA' if gate['passed'] else 'NO PASA'}")


@app.command("backtest-002-final")
def backtest_002_final() -> None:
    """Test ÚNICO de la estrategia en la temporada de holdout (crea HOLDOUT_002_USED.lock)."""
    from betting_ml.container import Container

    payload = Container().backtest_pinnacle_final().run_final()
    for key, result in payload["test"]["results"].items():
        typer.echo(
            f"{key:<26} u={result['threshold']:<5} apuestas={result['n_bets']:<5} "
            f"ROI={_fmt(result['roi_flat'])} CLV={_fmt(result['clv_mean'])}"
        )
    typer.echo(f"Nivel: {payload['level']} — conclusión: {payload['conclusion']}")


@app.command()
def odds(league: list[str] = typer.Option(None, help="Ligas (por defecto todas)")) -> None:
    """Refresco manual de cuotas desde The Odds API (consume créditos: ~2 por liga)."""
    from betting_ml.application.refresh_odds import OddsBudgetLowError
    from betting_ml.container import Container

    use_case = Container().refresh_odds
    try:
        result = use_case.refresh(league or None)
    except OddsBudgetLowError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(
        f"snapshot={result.snapshot_id} ligas={result.leagues} eventos={result.events} "
        f"créditos usados={result.credits_used} restantes={result.credits_remaining}"
    )
    if result.unmapped_teams:
        typer.echo(
            f"EQUIPOS SIN MAPEAR (agregar a team_aliases.yaml): {result.unmapped_teams}", err=True
        )


@app.command()
def settle() -> None:
    """Liquida las apuestas pendientes con los resultados de football-data y calcula el CLV."""
    from betting_ml.container import Container

    result = Container().settle_bets.run()
    typer.echo(
        f"liquidadas={result.settled} con CLV={result.clv_computed} pendientes={result.still_pending}"
    )


@app.command("db-upgrade")
def db_upgrade() -> None:
    """Aplica las migraciones de la base SQLite (spec 002)."""
    from betting_ml.adapters.sql.db import upgrade
    from betting_ml.config import get_settings

    upgrade(get_settings().database_url)
    typer.echo("Base de datos al día")


@app.command("backtest-002-report")
def backtest_002_report() -> None:
    """Regenera REPORT_002_backtest.md con el análisis de margen (no abre el holdout)."""
    from betting_ml.container import Container

    typer.echo(f"Informe escrito en {Container().backtest_pinnacle().refresh_report()}")


@app.command("openapi")
def openapi(out: str = "frontend/src/api/openapi.json") -> None:
    """Exporta el contrato OpenAPI de la API (sin levantarla) para generar los tipos del frontend."""
    import json
    from pathlib import Path

    from betting_ml.api.main import create_app
    from betting_ml.config import PROJECT_ROOT

    path = Path(out) if Path(out).is_absolute() else PROJECT_ROOT / out
    path.parent.mkdir(parents=True, exist_ok=True)
    spec = create_app().openapi()  # no lifespan: nothing is loaded
    path.write_bytes((json.dumps(spec, indent=2, ensure_ascii=False) + "\n").encode("utf-8"))
    typer.echo(f"OpenAPI escrito en {path} ({len(spec['paths'])} rutas)")


def _fmt(value: float | None) -> str:
    return "  —  " if value is None else f"{100 * value:+.2f}%"


if __name__ == "__main__":  # pragma: no cover
    app()
