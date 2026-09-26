from pathlib import Path

from betting_ml.config import Settings
from betting_ml.container import Container


def test_container_wires_build_dataset(tmp_path: Path) -> None:
    settings = Settings(_env_file=None, data_dir=tmp_path / "data", reports_dir=tmp_path / "rep")
    container = Container(settings)
    use_case = container.build_dataset()
    assert use_case.report_path == tmp_path / "rep" / "data_quality.md"
    assert container.football_data.url("E0", "2014-15").endswith("/1415/E0.csv")
    assert container.understat.understat_league("SP1") == "La_liga"
    assert (
        container.repository.path("matches") == tmp_path / "data" / "processed" / "matches.parquet"
    )
    assert container.features.elo.k > 0
