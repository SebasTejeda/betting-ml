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
def exp(exp_id: str, verbose: bool = False) -> None:
    """Corre un experimento de configs/experiments/{ID}_*.yaml en F1–F3."""
    from betting_ml.config import load_experiment
    from betting_ml.container import Container

    _setup_logging(verbose)
    container = Container()
    config = load_experiment(exp_id, container.settings.configs_dir / "experiments")
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


if __name__ == "__main__":  # pragma: no cover
    app()
