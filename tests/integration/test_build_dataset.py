import json
from pathlib import Path

import pandas as pd
import pytest

from betting_ml.adapters.football_data import CANONICAL_COLUMNS, parse_csv
from betting_ml.adapters.parquet_repository import HoldoutAccessError, ParquetMatchRepository
from betting_ml.adapters.team_names import TeamNameResolver, UnknownTeamError
from betting_ml.adapters.understat import XG_COLUMNS, parse_league_data
from betting_ml.application.build_dataset import BuildDataset, QualityLog, clean_results
from betting_ml.config import LeaguesFile, load_team_aliases

FIXTURES = Path(__file__).parents[1] / "fixtures"


def _leagues() -> LeaguesFile:
    return LeaguesFile.model_validate(
        {
            "seasons": {"train": ["2024-25"], "holdout": "2025-26", "current": "2026-27"},
            "leagues": [
                {
                    "code": "E0",
                    "name": "Premier League",
                    "country": "England",
                    "football_data": "E0",
                    "understat": "EPL",
                }
            ],
        }
    )


class FakeResults:
    def __init__(self, extra: pd.DataFrame | None = None) -> None:
        self.extra = extra

    def fetch_season(self, league: str, season: str) -> pd.DataFrame:
        files = {
            "2024-25": "football_data_E0_2425.csv",
            "2026-27": "football_data_E0_2627.csv",
        }
        if season not in files:
            return pd.DataFrame(columns=CANONICAL_COLUMNS)
        frame = parse_csv((FIXTURES / files[season]).read_bytes(), league, season)
        if self.extra is not None and season == "2024-25":
            frame = pd.concat([frame, self.extra], ignore_index=True)
        return frame


class FakeXg:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail

    def fetch_season(self, league: str, season: str) -> pd.DataFrame:
        if self.fail:
            raise ConnectionError("understat down")
        if season != "2024-25":
            return pd.DataFrame(columns=XG_COLUMNS)
        payload = json.loads((FIXTURES / "understat_EPL_2024.json").read_text(encoding="utf-8"))
        return parse_league_data(payload, league, season)


def _build(tmp_path: Path, results: FakeResults, xg: FakeXg) -> BuildDataset:
    return BuildDataset(
        leagues=_leagues(),
        match_source=results,
        xg_source=xg,
        resolver=TeamNameResolver(load_team_aliases()),
        repository=ParquetMatchRepository(tmp_path / "processed"),
        report_path=tmp_path / "reports" / "data_quality.md",
    )


def test_build_dataset_end_to_end(tmp_path: Path) -> None:
    result = _build(tmp_path, FakeResults(), FakeXg()).run()
    assert len(result.matches) == 8
    assert len(result.current) == 4
    assert result.holdout.empty
    matches = result.matches
    # Understat 'Manchester United' was canonicalised and joined to football-data 'Man United'.
    mu = matches[matches["home_team"] == "Man United"].iloc[0]
    assert mu["home_xg"] == pytest.approx(2.04268)
    assert mu["match_id"] == "E0-2024-08-16-man-united-fulham"
    assert matches["kickoff_utc"].is_monotonic_increasing
    # The 6 Understat matches in the fixture are joined; the rest are reported.
    assert matches["home_xg"].notna().sum() == 6
    # Current season falls back to football-data xG.
    assert (result.current["xg_source"] == "football_data").all()
    report = (tmp_path / "reports" / "data_quality.md").read_text(encoding="utf-8")
    assert "Partidos por liga y temporada" in report
    assert "Partidos sin xG emparejado" in report
    repo = ParquetMatchRepository(tmp_path / "processed")
    assert len(repo.load("matches")) == 8
    with pytest.raises(HoldoutAccessError):
        repo.load("holdout")
    assert (
        len(ParquetMatchRepository(tmp_path / "processed", allow_holdout=True).load("holdout")) == 0
    )


def test_pipeline_continues_without_xg(tmp_path: Path) -> None:
    result = _build(tmp_path, FakeResults(), FakeXg(fail=True)).run()
    assert len(result.quality.xg_source_failures) == 3
    assert result.matches["home_xg"].isna().all()
    assert "Fallos de la fuente de xG" in (tmp_path / "reports" / "data_quality.md").read_text(
        encoding="utf-8"
    )


def test_unknown_team_fails_loudly(tmp_path: Path) -> None:
    extra = parse_csv((FIXTURES / "football_data_E0_2425.csv").read_bytes(), "E0", "2024-25")
    extra = extra.iloc[:1].assign(home_team="Man Utd FC")
    with pytest.raises(UnknownTeamError, match="Man Utd FC"):
        _build(tmp_path, FakeResults(extra), FakeXg()).run()


def test_clean_results_rules() -> None:
    frame = parse_csv((FIXTURES / "football_data_E0_2425.csv").read_bytes(), "E0", "2024-25")
    dup = frame.iloc[:1]
    bad_result = frame.iloc[1:2].assign(result="A")  # 0-2 is actually A; make it inconsistent
    bad_result = bad_result.assign(home_goals=3)
    unplayed = frame.iloc[2:3].assign(home_goals=float("nan"), date=pd.Timestamp("2025-05-01"))
    bad_odds = frame.iloc[3:4].assign(avg_odds_h=1.0, date=pd.Timestamp("2025-05-02"))
    frame = pd.concat([frame, dup, unplayed, bad_odds], ignore_index=True)
    frame.iloc[1] = bad_result.iloc[0]
    quality = QualityLog()
    cleaned = clean_results(frame, quality)
    assert quality.duplicates_removed == 1
    assert quality.unplayed_removed == 1
    assert quality.inconsistent_results_fixed == 1
    assert quality.invalid_odds_nulled == 1
    assert len(cleaned) == 9
    assert cleaned.iloc[1]["result"] == "H"
