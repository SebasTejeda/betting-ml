from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
import requests

from betting_ml.adapters.fixtures import FootballDataFixtures, fixtures_on, parse_fixtures
from betting_ml.adapters.http import HttpClient
from betting_ml.adapters.team_names import TeamNameResolver
from betting_ml.config import load_team_aliases
from tests.http_fakes import StreamedBody

SAMPLE = Path(__file__).parents[1] / "fixtures" / "fixtures_sample.csv"
CODES = {"E0": "E0", "SP1": "SP1", "D1": "D1", "I1": "I1", "F1": "F1"}


@pytest.fixture(scope="module")
def resolver() -> TeamNameResolver:
    return TeamNameResolver(load_team_aliases())


def test_parse_filters_leagues_and_converts_to_utc(resolver: TeamNameResolver) -> None:
    fixtures, unknown = parse_fixtures(SAMPLE.read_bytes(), CODES, resolver)
    assert [f.home_team for f in fixtures] == ["Arsenal", "Man United", "Real Madrid", "Liverpool"]
    assert unknown == {"E0/Arsenal FC"}
    first = fixtures[0]
    assert first.kickoff_utc == datetime(2026, 10, 3, 11, 30, tzinfo=UTC)  # 12:30 BST
    assert first.match_id == "E0-2026-10-03-arsenal-chelsea"
    assert first.average_odds is not None and first.average_odds.home == pytest.approx(1.82)
    assert first.best_odds is not None and first.best_odds.home >= first.average_odds.home
    spain = fixtures[2]
    assert spain.average_odds is None  # AvgH missing in the sample
    assert spain.best_odds is not None


def test_fixtures_on_lima_date(resolver: TeamNameResolver) -> None:
    fixtures, _ = parse_fixtures(SAMPLE.read_bytes(), CODES, resolver)
    lima = fixtures_on(fixtures, date(2026, 10, 3), "America/Lima")
    # Liverpool-Everton kicks off 00:30 UK on Oct 4th = 18:30 on Oct 3rd in Lima.
    assert [f.home_team for f in lima] == ["Arsenal", "Man United", "Liverpool"]
    assert [f.home_team for f in fixtures_on(fixtures, date(2026, 10, 4), "America/Lima")] == [
        "Real Madrid"
    ]
    assert fixtures_on(fixtures, date(2026, 10, 5), "America/Lima") == []


def test_no_supported_league(resolver: TeamNameResolver) -> None:
    content = SAMPLE.read_bytes().replace(b"\nE0,", b"\nE3,").replace(b"\nSP1,", b"\nSP2,")
    assert parse_fixtures(content, CODES, resolver) == ([], set())


class _Resp(StreamedBody):
    status_code = 200

    def __init__(self, content: bytes) -> None:
        self.content = content

    def raise_for_status(self) -> None:
        return None


class _Session:
    def __init__(self) -> None:
        self.calls = 0
        self.fail = False
        self.headers: dict[str, str] = {}

    def get(self, url: str, **_: object) -> _Resp:
        self.calls += 1
        if self.fail:
            raise requests.ConnectionError("down")
        return _Resp(SAMPLE.read_bytes())


def test_cache_six_hours_and_fallback(tmp_path: Path, resolver: TeamNameResolver) -> None:
    now = [datetime(2026, 10, 3, 8, 0, tzinfo=UTC)]
    session = _Session()
    source = FootballDataFixtures(
        tmp_path,
        resolver,
        CODES,
        cache_hours=6,
        http=HttpClient(session=session, sleep=lambda _: None, retries=1),  # type: ignore[arg-type]
        clock=lambda: now[0],
    )
    assert len(source.fetch_fixtures()) == 4
    assert session.calls == 1 and source.last_update == now[0]
    now[0] += timedelta(hours=5)
    source.fetch_fixtures()
    assert session.calls == 1  # cached
    now[0] += timedelta(hours=2)
    source.fetch_fixtures()
    assert session.calls == 2  # stale -> downloaded again
    source.fetch_fixtures(force_refresh=True)
    assert session.calls == 3
    session.fail = True
    now[0] += timedelta(hours=8)
    assert len(source.fetch_fixtures()) == 4  # download failed -> cached copy
    assert source.unknown_teams == {"E0/Arsenal FC"}


def test_download_failure_without_cache_raises(tmp_path: Path, resolver: TeamNameResolver) -> None:
    session = _Session()
    session.fail = True
    source = FootballDataFixtures(
        tmp_path,
        resolver,
        CODES,
        http=HttpClient(session=session, sleep=lambda _: None, retries=1),  # type: ignore[arg-type]
    )
    with pytest.raises(Exception, match="failed"):
        source.fetch_fixtures()
