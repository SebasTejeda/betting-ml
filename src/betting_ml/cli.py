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

    # X-Forwarded-For is not trusted (uvicorn trusts it from 127.0.0.1 by default): a local
    # client could otherwise pick a fresh IP per request and dodge the login lockout. A trusted
    # reverse proxy is configured explicitly in the deployment (spec 003, T020).
    uvicorn.run("betting_ml.api.main:app", host=host, port=port, reload=reload, proxy_headers=False)


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


ACTOR_HELP = "Quién lo ejecuta, para la auditoría: cli (a mano) o scheduler (tarea programada)"


def _actor(value: str) -> str:
    if value not in ("cli", "scheduler"):
        raise typer.BadParameter("usa cli o scheduler")
    return value


@app.command()
def odds(
    league: list[str] = typer.Option(None, help="Ligas (por defecto todas)"),
    actor: str = typer.Option("cli", help=ACTOR_HELP, callback=_actor),
) -> None:
    """Refresco manual de cuotas desde The Odds API (consume créditos: ~2 por liga)."""
    from betting_ml.application.refresh_odds import OddsBudgetLowError
    from betting_ml.container import Container

    use_case = Container().refresh_odds
    try:
        result = use_case.refresh(league or None, actor=actor)
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
def settle(actor: str = typer.Option("cli", help=ACTOR_HELP, callback=_actor)) -> None:
    """Liquida las apuestas pendientes con los resultados de football-data y calcula el CLV."""
    from betting_ml.container import Container

    result = Container().settle_bets.run(actor=actor)
    typer.echo(
        f"liquidadas={result.settled} con CLV={result.clv_computed} pendientes={result.still_pending}"
    )


@app.command("verify-integrity")
def verify_integrity() -> None:
    """Comprueba la base (integrity_check, foreign_key_check), la cadena de la auditoría y que
    cada apuesta y los ajustes coinciden con su último evento. Código 1 si algo falla."""
    from betting_ml.container import Container

    report = Container().verify_integrity().run()
    checked = ", ".join(f"{entity}={n}" for entity, n in report.checked.items())
    typer.echo(f"eventos de auditoría={report.records} filas comparadas: {checked}")
    if not report.ok:
        for problem in report.problems:
            typer.echo(f"FALLO: {problem}", err=True)
        raise typer.Exit(code=1)
    typer.echo("Integridad verificada: sin problemas")


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


@app.command("hash-password")
def hash_password() -> None:
    """Pide la contraseña del dueño (sin eco) y muestra su hash Argon2id para APP_PASSWORD_HASH."""
    from betting_ml.adapters.argon2_hasher import Argon2Hasher

    password = typer.prompt("Contraseña", hide_input=True, confirmation_prompt=True)
    if len(password) < 12:
        typer.echo("Usa al menos 12 caracteres.", err=True)
        raise typer.Exit(code=1)
    typer.echo(f"APP_PASSWORD_HASH={Argon2Hasher().hash(password)}")


if __name__ == "__main__":  # pragma: no cover
    app()
