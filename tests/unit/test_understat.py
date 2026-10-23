import json
from pathlib import Path

import pandas as pd
import pytest

from betting_ml.adapters.http import HttpClient
from betting_ml.adapters.understat import (
    XG_COLUMNS,
    UnderstatSource,
    parse_league_data,
    season_year,
)
from tests.http_fakes import StreamedBody

FIXTURE = Path(__file__).parents[1] / "fixtures" / "understat_EPL_2024.json"


def _payload() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_season_year() -> None:
    assert season_year("2014-15") == "2014"


def test_parse_league_data() -> None:
    df = parse_league_data(_payload(), "E0", "2024-25")
    assert list(df.columns) == XG_COLUMNS
    first = df.iloc[0]
    assert first["home_team"] == "Manchester United"
    assert first["away_team"] == "Fulham"
    assert first["home_xg"] == pytest.approx(2.04268)
    assert first["away_xg"] == pytest.approx(0.418711)
    assert first["home_goals"] == 1
    assert first["kickoff_utc"] == pd.Timestamp("2024-08-16 19:00", tz="UTC")
    assert first["date"] == pd.Timestamp("2024-08-16")
    assert first["is_result"]


def test_unplayed_match_has_nan_xg() -> None:
    df = parse_league_data(_payload(), "E0", "2024-25")
    last = df.iloc[-1]
    assert not last["is_result"]
    assert pd.isna(last["home_xg"]) and pd.isna(last["home_goals"])


def test_invalid_payload() -> None:
    with pytest.raises(ValueError):
        parse_league_data({"teams": {}}, "E0", "2024-25")


class _Resp(StreamedBody):
    status_code = 200

    def __init__(self, content: bytes) -> None:
        self.content = content

    def raise_for_status(self) -> None:
        return None


class _Session:
    def __init__(self, content: bytes) -> None:
        self.content = content
        self.calls: list[tuple[str, dict]] = []
        self.headers: dict[str, str] = {}

    def get(self, url: str, **kwargs: object) -> _Resp:
        self.calls.append((url, kwargs))
        return _Resp(self.content)


def test_source_downloads_with_headers_and_caches(tmp_path: Path) -> None:
    session = _Session(FIXTURE.read_bytes())
    http = HttpClient(session=session, sleep=lambda _: None)  # type: ignore[arg-type]
    source = UnderstatSource(tmp_path, http=http, league_codes={"E0": "EPL"})
    df = source.fetch_season("E0", "2024-25")
    assert len(df) == 7
    url, kwargs = session.calls[0]
    assert url == "https://understat.com/getLeagueData/EPL/2024"
    assert kwargs["headers"]["X-Requested-With"] == "XMLHttpRequest"  # type: ignore[index]
    assert source.raw_path("E0", "2024-25") == tmp_path / "understat" / "EPL" / "2024.json"
    source.fetch_season("E0", "2024-25")
    assert len(session.calls) == 1


def test_source_rejects_unexpected_payload(tmp_path: Path) -> None:
    session = _Session(b'{"error": "blocked"}')
    http = HttpClient(session=session, sleep=lambda _: None)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="unexpected"):
        UnderstatSource(tmp_path, http=http).fetch_season("EPL", "2024-25")
