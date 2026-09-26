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


if __name__ == "__main__":  # pragma: no cover
    app()
