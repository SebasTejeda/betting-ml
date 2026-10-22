from pathlib import Path

import pandas as pd
import pytest

from betting_ml.adapters.elo_snapshots import EloSnapshotSource
from betting_ml.adapters.europe_names import EuropeTeamResolver
from betting_ml.adapters.parquet_repository import ParquetMatchRepository
from betting_ml.adapters.team_names import TeamNameResolver
from betting_ml.application.build_club_elo import BuildClubElo, turnover_errors
from betting_ml.config import TeamAliases, load_elo_leagues
from betting_ml.ml.features.elo import expected_home_score
from betting_ml.ml.models.club_elo import ClubEloParams, club_key, compute_club_elo, snapshot


def _row(
    day: str, season: str, home: str, away: str, hg: int, ag: int, domestic: bool = True
) -> dict:
    hc, ac = home.split("|")[0], away.split("|")[0]
    return {
        "date": pd.Timestamp(day),
        "season": season,
        "home_key": home,
        "away_key": away,
        "home_country": hc,
        "away_country": ac,
        "home_goals": hg,
        "away_goals": ag,
        "domestic": domestic,
    }


def test_elo_update_is_zero_sum_and_uses_ratings_before_the_match() -> None:
    matches = pd.DataFrame(
        [
            _row("2020-08-01", "2020-21", "ENG|A", "ENG|B", 2, 0),
            _row("2020-08-08", "2020-21", "ENG|B", "ENG|A", 1, 1),
        ]
    )
    pre, history = compute_club_elo(matches)
    assert pre.loc[0, ["home_elo", "away_elo"]].tolist() == [1500.0, 1500.0]
    gain = 20 * 1.5 * (1 - expected_home_score(1500, 1500, 60))  # 2-goal win
    assert pre.loc[1, "away_elo"] == pytest.approx(1500 + gain)  # A after its win
    assert pre.loc[1, "home_elo"] == pytest.approx(1500 - gain)
    last = history.groupby("key")["elo"].last()
    assert last.sum() == pytest.approx(3000.0)  # zero-sum
    assert pre.loc[1, "home_recent"] == 1  # one rated match in the previous 365 days


def test_promoted_club_and_season_regression_towards_its_league() -> None:
    rows = [_row("2020-08-01", "2020-21", "ENG|A", "ENG|B", 5, 0)] * 1
    rows += [_row("2021-08-01", "2021-22", "ENG|A", "ENG|C", 0, 0)]
    pre, history = compute_club_elo(pd.DataFrame(rows))
    after_first = history[history["date"] == "2020-08-01"].set_index("key")["elo"]
    base = after_first.mean()  # base of 2021-22, fixed at its first match (zero-sum: 1500)
    expected_a = after_first["ENG|A"] + (base - after_first["ENG|A"]) / 3
    assert pre.loc[1, "home_elo"] == pytest.approx(expected_a)  # regressed 1/3 to the base
    assert pre.loc[1, "away_elo"] == pytest.approx(base - 50)  # promoted: base − 50
    assert history["season"].tolist()[-1] == "2021-22"


def test_first_season_of_a_league_has_no_cascade() -> None:
    """Every club of a league seen for the first time starts at the same rating."""
    rows = [
        _row("2018-08-01", "2018-19", "NED|A", "NED|B", 1, 0),
        _row("2018-08-01", "2018-19", "NED|C", "NED|D", 0, 0),
        _row("2018-08-02", "2018-19", "NED|E", "NED|F", 2, 2),
    ]
    pre, _ = compute_club_elo(pd.DataFrame(rows))
    assert set(pre[["home_elo", "away_elo"]].to_numpy().ravel()) == {1500.0}


def test_league_back_after_a_gap_uses_its_last_clubs() -> None:
    rows = [
        _row("2020-08-01", "2020-21", "SCO|A", "SCO|B", 3, 0),
        _row("2023-08-01", "2023-24", "SCO|A", "SCO|C", 0, 0),  # two seasons without data
    ]
    pre, _ = compute_club_elo(pd.DataFrame(rows))
    assert pre.loc[1, "away_elo"] == pytest.approx(1500 - 50)  # base = mean of A and B


def test_league_gap_only_moves_with_european_matches() -> None:
    rows = [
        _row("2020-08-01", "2020-21", "ENG|A", "ENG|B", 1, 0),
        _row("2020-08-01", "2020-21", "NED|X", "NED|Y", 1, 0),
        _row("2020-09-15", "2020-21", "ENG|A", "NED|X", 3, 0, domestic=False),
    ]
    _, history = compute_club_elo(pd.DataFrame(rows))
    last = history.groupby(["country", "key"])["elo"].last()
    assert last["ENG"].mean() > 1500 > last["NED"].mean()
    assert last.sum() == pytest.approx(4 * 1500)


def test_missing_columns() -> None:
    with pytest.raises(ValueError):
        compute_club_elo(pd.DataFrame({"date": []}))


def test_snapshot_is_strictly_before_the_day() -> None:
    matches = pd.DataFrame(
        [
            _row("2020-08-01", "2020-21", "ENG|A", "ENG|B", 2, 0),
            _row("2020-09-15", "2020-21", "ENG|A", "SUI|Z", 0, 3, domestic=False),
        ]
    )
    _, history = compute_club_elo(matches)
    before = snapshot(history, "2020-09-15")
    on = snapshot(history, "2020-09-16")
    a_before = before.loc[before.club == "A", "elo"].iloc[0]
    assert "Z" not in set(before.club)  # Z has not played yet on the 15th
    assert on.loc[on.club == "A", "elo"].iloc[0] < a_before  # the 15th counts from the 16th
    assert on.loc[on.club == "Z", "level"].isna().all()  # no league match: not level 1
    assert before.loc[before.club == "A", "level"].iloc[0] == 1
    assert list(on.columns) == [
        "club",
        "country",
        "level",
        "elo",
        "valid_from",
        "valid_to",
        "recent",
        "last_match",
        "last_league_match",
    ]
    a = on[on.club == "A"].iloc[0]
    assert a["recent"] == 2 and a["last_match"] == pd.Timestamp("2020-09-15")
    assert a["last_league_match"] == pd.Timestamp("2020-08-01")  # the European one does not count
    assert pd.isna(on[on.club == "Z"]["last_league_match"].iloc[0])
    assert snapshot(history, "2020-01-01").empty
    assert snapshot(history, "2022-01-01", recent_days=365)["recent"].eq(0).all()


def test_relegated_clubs_leave_level_one_when_the_new_season_starts() -> None:
    rows = [
        _row("2020-08-01", "2020-21", "ENG|A", "ENG|B", 1, 0),
        _row("2021-08-01", "2021-22", "ENG|A", "ENG|C", 1, 0),  # B relegated, C promoted
    ]
    _, history = compute_club_elo(pd.DataFrame(rows))
    snap = snapshot(history, "2021-08-09").set_index("club")["level"]
    assert snap["A"] == 1 and snap["C"] == 1 and pd.isna(snap["B"])


def test_unify_foreign_names() -> None:
    resolver = EuropeTeamResolver(TeamNameResolver(TeamAliases.model_validate({"teams": {}})))
    league = {"AFC Ajax", "PSV", "Feyenoord Rotterdam", "FC Twente '65"}
    assert resolver.unify_foreign("AFC Ajax", "NED", league) == "AFC Ajax"
    assert resolver.unify_foreign("Ajax", "NED", league) == "AFC Ajax"
    assert resolver.unify_foreign("Feyenoord", "NED", league) == "Feyenoord Rotterdam"
    assert resolver.unify_foreign("AZ Alkmaar", "NED", league) == "AZ Alkmaar"  # not guessed


class _Results:
    def fetch_league(self, folder: str, file: str, country: str, season: str) -> pd.DataFrame:
        if season != "2020-21":
            return pd.DataFrame()
        return pd.DataFrame(
            {
                "competition": file,
                "season": season,
                "date": pd.to_datetime(["2020-08-02"]),
                "stage": "",
                "home_team": ["AFC Ajax"],
                "home_country": [country],
                "away_team": ["PSV"],
                "away_country": [country],
                "home_goals": [2],
                "away_goals": [1],
                "extra_time": [False],
            }
        )

    def fetch_season(self, competition: str, season: str) -> pd.DataFrame:
        if competition != "UCL" or season != "2020-21":
            return pd.DataFrame()
        return pd.DataFrame(
            {
                "competition": "UCL",
                "season": season,
                "date": pd.to_datetime(["2020-10-20"]),
                "stage": "Group",
                "home_team": ["Ajax"],
                "home_country": ["NED"],
                "away_team": ["Liverpool FC"],
                "away_country": ["ENG"],
                "home_goals": [0],
                "away_goals": [1],
                "extra_time": [False],
            }
        )


def test_build_club_elo_joins_leagues_and_europe(tmp_path: Path) -> None:
    repository = ParquetMatchRepository(tmp_path, allow_holdout=True)
    repository.save(
        "matches",
        pd.DataFrame(
            {
                "league": ["E0"],
                "season": ["2020-21"],
                "date": pd.to_datetime(["2020-08-01"]),
                "home_team": ["Liverpool"],
                "away_team": ["Chelsea"],
                "home_goals": [1.0],
                "away_goals": [0.0],
            }
        ),
    )
    aliases = TeamAliases.model_validate(
        {"teams": {"E0": {"Liverpool": {"openfootball": ["Liverpool FC"]}, "Chelsea": {}}}}
    )
    catalog = {
        "domestic": {"E0": "ENG"},
        "openfootball": [{"country": "NED", "folder": "netherlands", "file": "nl1"}],
    }
    result = BuildClubElo(
        repository, _Results(), EuropeTeamResolver(TeamNameResolver(aliases)), catalog, ["2020-21"]
    ).run()
    assert set(result.matches["source"]) == {"football_data", "openfootball_league", "UCL"}
    europe = result.matches[result.matches["source"] == "UCL"].iloc[0]
    assert europe["home_key"] == club_key("NED", "AFC Ajax")  # unified with the league name
    assert europe["away_key"] == club_key("ENG", "Liverpool")  # canonical name
    assert europe["home_elo"] > 1500  # Ajax won its league match before
    source = EloSnapshotSource(repository)
    ratings = source.ratings_on(pd.Timestamp("2020-10-21").date())
    assert {"AFC Ajax", "Liverpool", "Chelsea", "PSV"} <= set(ratings["club"])
    assert source.ratings_before(pd.Timestamp("2020-10-20").date())["club"].nunique() == 4


def test_turnover_guard_catches_renamed_clubs() -> None:
    def league(season: str, names: list[str]) -> list[dict]:
        return [
            _row(f"{season[:4]}-09-01", season, f"NED|{a}", f"NED|{b}", 1, 0)
            for a, b in zip(names[::2], names[1::2], strict=True)
        ]

    base = [f"T{i}" for i in range(18)]
    promoted = [*base[:15], "P1", "P2", "P3"]
    renamed = [*base[:10], "X1", "X2", "X3", "X4", "X5", "X6", "X7", "X8"]
    ok = pd.DataFrame(league("2022-23", base) + league("2023-24", promoted))
    bad = pd.DataFrame(league("2022-23", base) + league("2023-24", renamed))
    gap = pd.DataFrame(league("2020-21", base) + league("2023-24", renamed))
    assert turnover_errors(ok) == []
    assert turnover_errors(gap) == []  # 2-season gap: up to 5 + 3·2 = 11 new clubs allowed
    long_rename = [*base[:4], *[f"Y{i}" for i in range(14)]]
    across_gap = pd.DataFrame(league("2020-21", base) + league("2023-24", long_rename))
    assert "NED 2023-24: 14 new clubs" in turnover_errors(across_gap)[0]
    errors = turnover_errors(bad)
    assert len(errors) == 1 and "NED 2023-24: 8 new clubs" in errors[0]


def test_canonical_foreign_names() -> None:
    resolver = EuropeTeamResolver(
        TeamNameResolver(TeamAliases.model_validate({"teams": {}})),
        foreign_aliases={"POR": {"Sport Lisboa e Benfica": "SL Benfica"}},
    )
    assert resolver.canonical_foreign("Sport Lisboa e Benfica", "POR") == "SL Benfica"
    assert resolver.canonical_foreign("FC Porto", "POR") == "FC Porto"
    assert resolver.from_openfootball("Sport Lisboa e Benfica", "POR").name == "SL Benfica"


def test_production_aliases_have_no_chains() -> None:
    from betting_ml.config import load_europe_aliases

    aliases = load_europe_aliases(
        Path(__file__).resolve().parents[2] / "configs" / "europe_league_aliases.yaml"
    )
    for country, names in aliases.items():
        assert not set(names.values()) & set(names), f"{country}: an alias points to another alias"


def test_elo_leagues_catalog() -> None:
    catalog = load_elo_leagues()
    assert catalog["domestic"] == {"E0": "ENG", "SP1": "ESP", "D1": "GER", "I1": "ITA", "F1": "FRA"}
    assert {e["country"] for e in catalog["openfootball"]} >= {"NED", "POR"}
    assert ClubEloParams().season_regression == pytest.approx(1 / 3)
