from pathlib import Path

import pandas as pd
import pytest

from betting_ml.adapters.elo_snapshots import EloSnapshotSource
from betting_ml.adapters.europe_names import EuropeTeamResolver
from betting_ml.adapters.parquet_repository import ParquetMatchRepository
from betting_ml.adapters.team_names import TeamNameResolver
from betting_ml.application.build_club_elo import BuildClubElo
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
    mean = after_first.mean()  # league mean = 1500 (zero-sum)
    expected_a = after_first["ENG|A"] + (mean - after_first["ENG|A"]) / 3
    assert pre.loc[1, "home_elo"] == pytest.approx(expected_a)  # regressed 1/3 to the mean
    # New club: mean of the league at that moment (A already regressed, B still active) − 50.
    current_mean = (expected_a + after_first["ENG|B"]) / 2
    assert pre.loc[1, "away_elo"] == pytest.approx(current_mean - 50)


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
    assert list(on.columns) == ["club", "country", "level", "elo", "valid_from", "valid_to"]
    assert snapshot(history, "2020-01-01").empty
    late = snapshot(history, "2022-01-01", active_days=400)
    assert late["level"].isna().all()  # inactive for more than 400 days


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


def test_elo_leagues_catalog() -> None:
    catalog = load_elo_leagues()
    assert catalog["domestic"] == {"E0": "ENG", "SP1": "ESP", "D1": "GER", "I1": "ITA", "F1": "FRA"}
    assert {e["country"] for e in catalog["openfootball"]} >= {"NED", "POR"}
    assert ClubEloParams().season_regression == pytest.approx(1 / 3)
