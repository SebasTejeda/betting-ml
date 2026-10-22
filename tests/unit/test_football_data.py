from pathlib import Path

import pandas as pd
import pytest
import requests

from betting_ml.adapters.football_data import (
    CANONICAL_COLUMNS,
    ODDS_COLUMNS,
    FootballDataSource,
    parse_csv,
    season_code,
)
from betting_ml.adapters.http import DownloadError, HttpClient

FIXTURES = Path(__file__).parents[1] / "fixtures"


def _load(name: str, league: str = "E0", season: str = "2014-15") -> pd.DataFrame:
    return parse_csv((FIXTURES / name).read_bytes(), league, season)


def test_season_code() -> None:
    assert season_code("2014-15") == "1415"
    assert season_code("2026-27") == "2627"


def test_old_season_maps_betbrain_columns() -> None:
    df = _load("football_data_E0_1415.csv")
    assert list(df.columns) == CANONICAL_COLUMNS
    assert len(df) == 8  # trailing empty row dropped
    first = df.iloc[0]
    assert first["home_team"] == "Arsenal"
    assert first["away_team"] == "Crystal Palace"
    assert first["home_goals"] == 2 and first["away_goals"] == 1 and first["result"] == "H"
    assert first["avg_odds_h"] > 1 and first["max_odds_h"] >= first["avg_odds_h"]
    assert first["ps_odds_h"] > 1 and first["psc_odds_h"] > 1
    assert pd.isna(first["avgc_odds_h"])  # closing average does not exist in 2014-15
    assert first["avg_over25"] > 1  # BbAv>2.5
    assert first["date"] == pd.Timestamp("2014-08-16")
    assert first["match_id"] == "E0-2014-08-16-arsenal-crystal-palace"


def test_missing_time_is_imputed_in_uk_time() -> None:
    df = _load("football_data_E0_1415.csv")
    assert df["kickoff_time_imputed"].all()
    # 15:00 BST (UTC+1) in August -> 14:00 UTC
    assert df.iloc[0]["kickoff_utc"] == pd.Timestamp("2014-08-16 14:00", tz="UTC")


def test_new_season_maps_avg_columns_and_time() -> None:
    df = _load("football_data_E0_2425.csv", season="2024-25")
    first = df.iloc[0]
    assert first["home_team"] == "Man United"
    assert not first["kickoff_time_imputed"]
    assert first["kickoff_utc"] == pd.Timestamp("2024-08-16 19:00", tz="UTC")
    assert first["avg_odds_h"] > 1 and first["avgc_odds_h"] > 1 and first["psc_odds_h"] > 1
    assert df["home_shots"].notna().all()


def test_over_under_25_odds_are_normalized() -> None:
    """Spec 003, T004: pre-closing and closing Over/Under 2.5 prices of every source."""
    raw = pd.read_csv(FIXTURES / "football_data_E0_2425.csv", encoding="latin-1").iloc[0]
    df = _load("football_data_E0_2425.csv", season="2024-25")
    first = df.iloc[0]
    pairs = {
        "b365": ("B365>2.5", "B365<2.5"),
        "ps": ("P>2.5", "P<2.5"),
        "avg": ("Avg>2.5", "Avg<2.5"),
        "max": ("Max>2.5", "Max<2.5"),
        "b365c": ("B365C>2.5", "B365C<2.5"),
        "psc": ("PC>2.5", "PC<2.5"),
        "avgc": ("AvgC>2.5", "AvgC<2.5"),
        "maxc": ("MaxC>2.5", "MaxC<2.5"),
    }
    for prefix, (over, under) in pairs.items():
        assert first[f"{prefix}_over25"] == pytest.approx(float(raw[over]))
        assert first[f"{prefix}_under25"] == pytest.approx(float(raw[under]))
    # Every Over/Under column is in the canonical schema and counted as odds.
    assert {f"{p}_{s}25" for p in pairs for s in ("over", "under")} <= set(ODDS_COLUMNS)


def test_current_season_without_pinnacle() -> None:
    df = _load("football_data_E0_2627.csv", season="2026-27")
    assert df["ps_odds_h"].isna().all()
    assert df["avg_odds_h"].notna().all()
    assert df["fd_home_xg"].notna().all()


def test_winter_time_conversion_and_latin1() -> None:
    header = "Div,Date,Time,HomeTeam,AwayTeam,FTHG,FTAG,FTR,Referee,AvgH,AvgD,AvgA\n"
    row = "SP1,05/01/2020,20:00,Alavés,Getafe,1,1,D,J Muñiz,2.5,3.1,3.0\n"
    content = (header + row).encode("latin-1")
    df = parse_csv(content, "SP1", "2019-20")
    assert df.iloc[0]["home_team"] == "Alavés"
    # GMT in January -> same hour in UTC
    assert df.iloc[0]["kickoff_utc"] == pd.Timestamp("2020-01-05 20:00", tz="UTC")
    assert df.iloc[0]["match_id"] == "SP1-2020-01-05-alaves-getafe"


def test_bad_inputs() -> None:
    with pytest.raises(ValueError, match="required"):
        parse_csv(b"Div,Foo\nE0,1\n", "E0", "2014-15")
    with pytest.raises(ValueError, match="unparseable"):
        parse_csv(b"Div,Date,HomeTeam,AwayTeam\nE0,2014-08-16,A,B\n", "E0", "2014-15")


class _FakeResponse:
    def __init__(self, content: bytes, status: int = 200) -> None:
        self.content = content
        self.status_code = status

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"status {self.status_code}")


class _FakeSession(requests.Session):
    def __init__(self, responses: list[object]) -> None:
        super().__init__()
        self.responses = responses
        self.calls: list[str] = []

    def get(self, url: str, **_: object) -> _FakeResponse:  # type: ignore[override]
        self.calls.append(url)
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        assert isinstance(item, _FakeResponse)
        return item


def test_source_downloads_once_and_caches(tmp_path: Path) -> None:
    content = (FIXTURES / "football_data_E0_2425.csv").read_bytes()
    session = _FakeSession([_FakeResponse(content)])
    http = HttpClient(session=session, sleep=lambda _: None)
    source = FootballDataSource(tmp_path, http=http)
    df = source.fetch_season("E0", "2024-25")
    assert len(df) == 8
    assert session.calls == ["https://www.football-data.co.uk/mmz4281/2425/E0.csv"]
    assert source.raw_path("E0", "2024-25").with_suffix(".meta.json").exists()
    source.fetch_season("E0", "2024-25")  # cached: no new request
    assert len(session.calls) == 1


def test_current_season_is_refreshed(tmp_path: Path) -> None:
    content = (FIXTURES / "football_data_E0_2627.csv").read_bytes()
    session = _FakeSession([_FakeResponse(content), _FakeResponse(content)])
    http = HttpClient(session=session, sleep=lambda _: None)
    source = FootballDataSource(tmp_path, http=http, refresh_seasons={"2026-27"})
    source.fetch_season("E0", "2026-27")
    source.fetch_season("E0", "2026-27")
    assert len(session.calls) == 2


def test_http_retries_then_succeeds() -> None:
    waits: list[float] = []
    session = _FakeSession(
        [requests.ConnectionError("boom"), _FakeResponse(b"x", 500), _FakeResponse(b"ok")]
    )
    http = HttpClient(session=session, sleep=waits.append, backoff_seconds=1)
    assert http.get("http://x").content == b"ok"
    assert waits == [1, 2]


def test_http_gives_up_and_404() -> None:
    session = _FakeSession([requests.ConnectionError("a"), requests.ConnectionError("b")])
    http = HttpClient(session=session, sleep=lambda _: None, retries=2)
    with pytest.raises(DownloadError, match="after 2 attempts"):
        http.get("http://x")
    http404 = HttpClient(session=_FakeSession([_FakeResponse(b"", 404)]), sleep=lambda _: None)
    with pytest.raises(DownloadError, match="404"):
        http404.get("http://x")


def test_http_polite_delay() -> None:
    waits: list[float] = []
    session = _FakeSession([_FakeResponse(b"1"), _FakeResponse(b"2")])
    http = HttpClient(session=session, sleep=waits.append, delay_seconds=3)
    http.get("http://x")
    http.get("http://y")
    assert len(waits) == 1 and 0 < waits[0] <= 3
