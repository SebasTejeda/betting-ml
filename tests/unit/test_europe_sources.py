from datetime import date
from pathlib import Path

import pandas as pd
import pytest
import requests

from betting_ml.adapters.clubelo import ClubEloFormatError, ClubEloSource, parse_ratings_csv
from betting_ml.adapters.europe_names import (
    ClubEloNameError,
    EuropeanTeam,
    EuropeTeamResolver,
    normalize_club,
)
from betting_ml.adapters.http import HttpClient
from betting_ml.adapters.openfootball import (
    OpenFootballFormatError,
    OpenFootballSource,
    declared_matches,
    parse_score,
    parse_txt,
)
from betting_ml.adapters.parquet_repository import HoldoutAccessError, ParquetMatchRepository
from betting_ml.adapters.team_names import TeamNameResolver, UnknownTeamError
from betting_ml.application.build_europe import (
    BuildEuropeDataset,
    european_match_id,
    league_strength,
)
from betting_ml.config import TeamAliases, load_europe_aliases, load_leagues, load_team_aliases
from betting_ml.domain.ratings import snapshot_date

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
OF_SAMPLE = FIXTURES / "openfootball" / "cl_2023-24_sample.txt"
ELO_SAMPLE = FIXTURES / "clubelo" / "2023-09-18.csv"


class _Response:
    def __init__(self, content: bytes, status_code: int = 200) -> None:
        self.content = content
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"status {self.status_code}")


class _Session(requests.Session):
    def __init__(self, responses: list[_Response]) -> None:
        super().__init__()
        self.responses = responses
        self.calls: list[str] = []

    def get(self, url: str, **_: object) -> _Response:  # type: ignore[override]
        self.calls.append(url)
        return self.responses.pop(0)


def _http(responses: list[_Response]) -> tuple[HttpClient, _Session]:
    session = _Session(responses)
    return HttpClient(session=session, sleep=lambda _: None), session


# --- openfootball


def test_parse_openfootball_sample() -> None:
    content = OF_SAMPLE.read_text(encoding="utf-8")
    df = parse_txt(content, "UCL", "2023-24")
    assert len(df) == 10  # the unplayed match (no score) is skipped
    first = df.iloc[0]
    assert (first.home_team, first.home_country, first.away_team) == (
        "AC Milan",
        "ITA",
        "Newcastle United FC",
    )
    assert first.date == pd.Timestamp("2023-09-19")
    assert first.stage == "Group, Matchday 1"
    # Year inferred from the season: March belongs to 2024.
    porto = df[df.home_team == "Arsenal FC"].iloc[0]
    assert porto.date == pd.Timestamp("2024-03-12")
    # Extra time: the 90-minute score is used, not the a.e.t. or penalties result.
    assert (porto.home_goals, porto.away_goals, porto.extra_time) == (1, 0, True)
    city = df[df.away_team == "Real Madrid CF"].iloc[0]
    assert (city.home_goals, city.away_goals) == (1, 1)
    assert declared_matches(content) == 17


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("0-0", (0, 0, False)),
        ("1-3 (1-1)", (1, 3, False)),
        ("2-1 a.e.t. (1-1, 0-0)", (1, 1, True)),
        ("4-2 pen. 1-0 a.e.t. (1-0, 1-0)", (1, 0, True)),
        ("", None),
        ("-", None),
    ],
)
def test_parse_score(text: str, expected: tuple[int, int, bool] | None) -> None:
    assert parse_score(text) == expected


def test_parse_score_rejects_aet_without_full_time() -> None:
    with pytest.raises(OpenFootballFormatError):
        parse_score("2-1 a.e.t.")


def test_match_before_any_date_is_an_error() -> None:
    with pytest.raises(OpenFootballFormatError):
        parse_txt("    18:45  A FC (ENG) v B FC (ESP)  1-0\n", "UCL", "2023-24")


def test_openfootball_source_caches_and_handles_missing_seasons(tmp_path: Path) -> None:
    http, session = _http([_Response(OF_SAMPLE.read_bytes()), _Response(b"404: Not Found", 404)])
    source = OpenFootballSource(tmp_path, http=http)
    df = source.fetch_season("UCL", "2023-24")
    assert len(df) == 10
    assert session.calls[0].endswith("/2023-24/cl.txt")
    assert source.raw_path("UCL", "2023-24").with_suffix(".meta.json").exists()
    source.fetch_season("UCL", "2023-24")  # cached
    assert len(session.calls) == 1
    assert source.fetch_season("UEL", "2019-20").empty  # the repo has no file for it
    assert session.calls[1].endswith("/2019-20/el.txt")


def test_openfootball_more_matches_than_declared_is_an_error(tmp_path: Path) -> None:
    content = OF_SAMPLE.read_text(encoding="utf-8").replace("# Matches    17", "# Matches    3")
    http, _ = _http([_Response(content.encode())])
    with pytest.raises(OpenFootballFormatError):
        OpenFootballSource(tmp_path, http=http).fetch_season("UCL", "2023-24")


# --- ClubElo


def test_parse_clubelo_csv() -> None:
    df = parse_ratings_csv(ELO_SAMPLE.read_bytes())
    assert list(df.columns) == ["club", "country", "level", "elo", "valid_from", "valid_to"]
    assert df.loc[df.club == "Man City", "elo"].iloc[0] == pytest.approx(2063.9)
    assert df.loc[df.club == "Hamburg", "level"].iloc[0] == 2
    assert df.valid_from.dtype.kind == "M"


@pytest.mark.parametrize(
    "body",
    [
        b"",
        b"Club,Elo\nA,1500\n",
        b"Rank,Club,Country,Level,Elo,From,To\n1,A,ENG,1,x,2023-01-01,2023-01-02\n",
    ],
)
def test_clubelo_format_errors(body: bytes) -> None:
    with pytest.raises(ClubEloFormatError):
        parse_ratings_csv(body)


@pytest.mark.parametrize(
    ("match_day", "snapshot"),
    [
        (date(2023, 9, 19), date(2023, 9, 18)),  # Tuesday → Monday of the same week
        (date(2023, 9, 21), date(2023, 9, 18)),  # Thursday
        (date(2023, 9, 18), date(2023, 9, 11)),  # Monday → previous Monday (strictly before)
        (date(2024, 6, 1), date(2024, 5, 27)),  # Saturday final
    ],
)
def test_snapshot_date_is_strictly_before_the_match(match_day: date, snapshot: date) -> None:
    assert snapshot_date(match_day) == snapshot
    assert snapshot_date(match_day) < match_day
    assert snapshot_date(match_day).weekday() == 0


def test_clubelo_source_caches_past_days_and_refreshes_today(tmp_path: Path) -> None:
    body = ELO_SAMPLE.read_bytes()
    http, session = _http([_Response(body), _Response(body), _Response(body)])
    source = ClubEloSource(tmp_path, http=http, today=date(2023, 9, 20))
    source.ratings_before(date(2023, 9, 19))
    source.ratings_on(date(2023, 9, 18))  # cached
    assert session.calls == ["http://api.clubelo.com/2023-09-18"]
    source.ratings_on(date(2023, 9, 20))
    source.ratings_on(date(2023, 9, 20))  # today is always refreshed
    assert len(session.calls) == 3
    with pytest.raises(ValueError):
        source.ratings_on(date(2023, 9, 21))


def test_clubelo_does_not_cache_an_invalid_response(tmp_path: Path) -> None:
    http, _ = _http([_Response(b"<html>error</html>")])
    source = ClubEloSource(tmp_path, http=http, today=date(2023, 9, 20))
    with pytest.raises(ClubEloFormatError):
        source.ratings_on(date(2023, 9, 18))
    assert not source.raw_path(date(2023, 9, 18)).exists()


# --- names


def _aliases() -> TeamAliases:
    return TeamAliases.model_validate(
        {
            "teams": {
                "E0": {
                    "Man City": {"openfootball": ["Manchester City FC"]},
                    "Newcastle": {"openfootball": ["Newcastle United FC"]},
                },
                "SP1": {
                    "Ath Madrid": {
                        "openfootball": ["Club Atlético de Madrid"],
                        "clubelo": ["Atletico"],
                    },
                    "Barcelona": {"openfootball": ["FC Barcelona"]},
                    "Real Madrid": {"openfootball": ["Real Madrid CF"]},
                },
                "D1": {
                    "Dortmund": {"openfootball": ["Borussia Dortmund"]},
                    "RB Leipzig": {"clubelo": ["Leipzig"]},
                },
                "I1": {
                    "Milan": {"openfootball": ["AC Milan"]},
                    "Lazio": {"openfootball": ["SS Lazio"]},
                },
                "F1": {"Paris SG": {"openfootball": ["Paris Saint-Germain FC"]}},
            }
        }
    )


def _resolver(overrides: dict[str, dict[str, str]] | None = None) -> EuropeTeamResolver:
    return EuropeTeamResolver(TeamNameResolver(_aliases()), overrides)


@pytest.mark.parametrize(
    ("name", "key"),
    [
        ("FC Red Bull Salzburg", "redbullsalzburg"),
        ("Club Atlético de Madrid", "atleticomadrid"),
        ("FK Crvena Zvezda", "crvenazvezda"),
        ("BSC Young Boys", "bscyoungboys"),
    ],
)
def test_normalize_club(name: str, key: str) -> None:
    assert normalize_club(name) == key


def test_domestic_and_foreign_teams() -> None:
    resolver = _resolver()
    ratings = parse_ratings_csv(ELO_SAMPLE.read_bytes())
    atleti = resolver.from_openfootball("Club Atlético de Madrid", "ESP")
    assert atleti == EuropeanTeam("Ath Madrid", "SP1", domestic=True)
    assert resolver.clubelo_name(atleti, ratings) == "Atletico"  # via the clubelo alias
    milan = resolver.from_openfootball("AC Milan", "ITA")
    assert resolver.clubelo_name(milan, ratings) == "Milan"  # canonical name exists in ClubElo
    monaco = EuropeTeamResolver(
        TeamNameResolver(
            TeamAliases.model_validate(
                {"teams": {"F1": {"Monaco": {"openfootball": ["AS Monaco FC"]}}}}
            )
        )
    ).from_openfootball("AS Monaco FC", "MCO")
    assert monaco.league == "F1" and monaco.country == "FRA"  # Monaco plays in Ligue 1
    zvezda = resolver.from_openfootball("FK Crvena Zvezda", "SRB")
    assert zvezda == EuropeanTeam("FK Crvena Zvezda", "SRB", domestic=False)
    assert resolver.clubelo_name(zvezda, ratings) == "Crvena Zvezda"
    young_boys = resolver.from_openfootball("BSC Young Boys", "SUI")
    assert resolver.clubelo_name(young_boys, ratings) == "Young Boys"  # containment match
    antwerp = resolver.from_openfootball("Royal Antwerp FC", "BEL")
    assert resolver.clubelo_name(antwerp, ratings) == "Antwerp"
    celtic = resolver.from_openfootball("Celtic FC", "SCO")
    assert resolver.clubelo_name(celtic, ratings) is None  # not in the snapshot: not guessed
    renamed = ratings.assign(club=ratings.club.replace({"Antwerp": "R Antwerp"}))
    assert resolver.clubelo_name(antwerp, renamed) is None  # ambiguous/unknown names stay unmatched
    fixed = _resolver({"BEL": {"Royal Antwerp FC": "R Antwerp"}})
    assert fixed.clubelo_name(antwerp, renamed) == "R Antwerp"


def test_domestic_team_without_clubelo_name_is_an_error() -> None:
    resolver = _resolver()
    ratings = parse_ratings_csv(ELO_SAMPLE.read_bytes())
    lazio = resolver.from_openfootball("SS Lazio", "ITA")
    assert resolver.clubelo_name(lazio, ratings) == "Lazio"
    city = resolver.from_openfootball("Manchester City FC", "ENG")
    with pytest.raises(ClubEloNameError):
        resolver.clubelo_name(city, ratings[ratings.club != "Man City"])


def test_unknown_domestic_openfootball_name_is_reported() -> None:
    frame = parse_txt(OF_SAMPLE.read_text(encoding="utf-8"), "UCL", "2023-24")
    error = _resolver().unknown_openfootball(frame)
    assert isinstance(error, UnknownTeamError)
    assert error.unknown == {("E0", "openfootball"): {"Arsenal FC"}}
    with pytest.raises(UnknownTeamError):
        _resolver().from_openfootball("Arsenal FC", "ENG")


def test_production_aliases_cover_every_european_club_of_our_leagues() -> None:
    """Every openfootball alias resolves and Monaco is mapped (team_aliases.yaml)."""
    resolver = EuropeTeamResolver(TeamNameResolver(load_team_aliases()), load_europe_aliases())
    assert resolver.from_openfootball("Club Atlético de Madrid", "ESP").name == "Ath Madrid"
    assert resolver.from_openfootball("FC Internazionale Milano", "ITA").name == "Inter"
    assert resolver.from_openfootball("AS Monaco FC", "MCO").name == "Monaco"
    assert resolver.from_openfootball("RB Leipzig", "GER").name == "RB Leipzig"


# --- use case


class _Results:
    def __init__(self, frames: dict[tuple[str, str], pd.DataFrame]) -> None:
        self.frames = frames

    def fetch_season(self, competition: str, season: str) -> pd.DataFrame:
        return self.frames.get((competition, season), pd.DataFrame())


class _Ratings:
    def __init__(self) -> None:
        self.days: list[date] = []

    def ratings_on(self, day: date) -> pd.DataFrame:
        self.days.append(day)
        return parse_ratings_csv(ELO_SAMPLE.read_bytes())

    def ratings_before(self, match_date: date) -> pd.DataFrame:
        return self.ratings_on(snapshot_date(match_date))


def _sample_frames() -> dict[tuple[str, str], pd.DataFrame]:
    frame = parse_txt(OF_SAMPLE.read_text(encoding="utf-8"), "UCL", "2023-24")
    frame = frame[frame.home_team != "Arsenal FC"]  # Arsenal is not in the test aliases
    holdout = frame.head(2).assign(season="2025-26", date=pd.Timestamp("2025-09-16"))
    return {("UCL", "2023-24"): frame, ("UCL", "2025-26"): holdout}


def test_build_europe_dataset(tmp_path: Path) -> None:
    repository = ParquetMatchRepository(tmp_path / "processed")
    ratings = _Ratings()
    report = tmp_path / "europe_data_quality.md"
    result = BuildEuropeDataset(
        leagues=load_leagues(),
        results=_Results(_sample_frames()),
        ratings=ratings,
        names=_resolver(),
        repository=repository,
        report_path=report,
    ).run()
    assert len(result.matches) == 9 and len(result.holdout) == 2
    assert set(ratings.days) == {date(2023, 9, 18), date(2024, 3, 11), date(2025, 9, 15)}
    row = result.matches[result.matches.match_id == "UCL-2023-09-19-milan-newcastle"].iloc[0]
    assert row.home_league == "I1" and row.home_domestic and row.home_elo == pytest.approx(1808.7)
    assert row.elo_date < row.date
    # League strength = mean level-1 ClubElo of the country on that snapshot.
    assert row.away_league_elo == pytest.approx((2063.9 + 1858.1 + 1601.0) / 3)
    young_boys = result.matches[result.matches.home_team == "BSC Young Boys"].iloc[0]
    assert not young_boys.home_domestic and young_boys.home_league == "SUI"
    assert result.unmatched_foreign == {"SCO": {"Celtic FC"}}
    assert 0.8 < result.rating_coverage < 1.0
    assert repository.exists("europe_matches") and repository.exists("europe_holdout")
    with pytest.raises(HoldoutAccessError):
        repository.load("europe_holdout")
    text = report.read_text(encoding="utf-8")
    assert "Celtic FC" in text and "2025-26" in text


def test_build_europe_fails_on_unknown_domestic_club(tmp_path: Path) -> None:
    frames = {
        ("UCL", "2023-24"): parse_txt(OF_SAMPLE.read_text(encoding="utf-8"), "UCL", "2023-24")
    }
    use_case = BuildEuropeDataset(
        leagues=load_leagues(),
        results=_Results(frames),
        ratings=_Ratings(),
        names=_resolver(),
        repository=ParquetMatchRepository(tmp_path),
        report_path=tmp_path / "r.md",
    )
    with pytest.raises(UnknownTeamError):
        use_case.run()


def test_build_europe_without_results(tmp_path: Path) -> None:
    use_case = BuildEuropeDataset(
        leagues=load_leagues(),
        results=_Results({}),
        ratings=_Ratings(),
        names=_resolver(),
        repository=ParquetMatchRepository(tmp_path),
        report_path=tmp_path / "r.md",
    )
    with pytest.raises(RuntimeError):
        use_case.run()


def test_helpers() -> None:
    assert european_match_id("UCL", date(2026, 10, 22), "Real Madrid", "RB Leipzig") == (
        "UCL-2026-10-22-real-madrid-rb-leipzig"
    )
    strength = league_strength(parse_ratings_csv(ELO_SAMPLE.read_bytes()))
    assert "GER" in strength and strength["GER"] == pytest.approx(
        (1849.5 + 1810.2) / 2
    )  # level 2 excluded


# --- domestic league files (own Elo, T006)

LEAGUE_V = """= Netherlands Eredivisie 2019/20
# Matches    4

▪ Matchday 1
  Fri Aug 9 2019
    20:00  FC Groningen            v NAC Breda                4-1 (3-0)
  Sat Aug 10
           Telstar 1963            v FC Twente '65            1-1
  Sat Feb 29
           AFC Ajax                v PSV                      2-0 (1-0)
  Sun Jul 26
           AZ                      v SBV Excelsior
"""

LEAGUE_INFIX = """= Scotland | Premiership 2026/27
# Matches  3

▪ 1st Phase - 1
Fri Jul 31 2026
  20:00   Dundee United  1-1 (1-0)  Rangers
                  (Lachlan Rose 38'; Thelo AASGAARD 56')
Sat Aug 1
  15:00   Falkirk  0-2 (0-1)  St. Mirren
                  (Killian PHILLIPS 11', 87')
  17:30   Aberdeen   v   Heart of Midlothian
"""


def test_parse_league_file_with_v() -> None:
    df = parse_txt(LEAGUE_V, "nl1", "2019-20", country="NED")
    assert len(df) == 3  # the unplayed match is skipped
    assert set(df["home_country"]) == {"NED"} and set(df["away_country"]) == {"NED"}
    assert df.iloc[1][["home_team", "away_team"]].tolist() == ["Telstar 1963", "FC Twente '65"]
    assert df.iloc[2]["date"] == pd.Timestamp("2020-02-29")  # leap day, year from the season


def test_parse_league_file_with_score_between_teams() -> None:
    df = parse_txt(LEAGUE_INFIX, "sco1", "2026-27", country="SCO")
    assert df[["home_team", "away_team", "home_goals", "away_goals"]].values.tolist() == [
        ["Dundee United", "Rangers", 1, 1],
        ["Falkirk", "St. Mirren", 0, 2],
    ]
    assert df.iloc[1]["date"] == pd.Timestamp("2026-08-01")


def test_dates_without_year_follow_the_previous_date() -> None:
    """UCL files go back in time (group by group) and 2019-20 ran into August 2020."""
    content = """# Matches 5
▪ Group A
  Tue Sep 17 2019
    18:45  A FC (ENG)  v  B FC (ESP)  1-0
  Wed Dec 11
    21:00  B FC (ESP)  v  A FC (ENG)  0-0
▪ Group B
  Tue Sep 17
    21:00  C FC (ITA)  v  D FC (FRA)  2-2
▪ Round of 16
  Wed Mar 11
    21:00  D FC (FRA)  v  B FC (ESP)  0-1
▪ Final
  Sun Aug 23
    21:00  A FC (ENG)  v  C FC (ITA)  1-0
"""
    df = parse_txt(content, "UCL", "2019-20")
    assert df["date"].dt.date.astype(str).tolist() == [
        "2019-09-17",
        "2019-12-11",
        "2019-09-17",
        "2020-03-11",
        "2020-08-23",
    ]


def test_fetch_league_downloads_from_openfootball_europe(tmp_path: Path) -> None:
    http, session = _http([_Response(LEAGUE_V.encode()), _Response(b"404: Not Found", 404)])
    source = OpenFootballSource(tmp_path, http=http)
    df = source.fetch_league("netherlands", "nl1", "NED", "2019-20")
    assert len(df) == 3
    assert session.calls[0].endswith("/europe/master/netherlands/2019-20_nl1.txt")
    assert source.fetch_league("netherlands", "nl1", "NED", "2015-16").empty
