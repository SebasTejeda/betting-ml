from pathlib import Path

import pandas as pd
import pytest

from betting_ml.adapters.football_data import FootballDataSource
from betting_ml.adapters.team_names import TeamNameResolver, UnknownTeamError
from betting_ml.adapters.understat import UnderstatSource
from betting_ml.config import PROJECT_ROOT, TeamAliases, load_leagues, load_team_aliases


@pytest.fixture
def resolver() -> TeamNameResolver:
    aliases = TeamAliases.model_validate(
        {
            "teams": {
                "E0": {
                    "Man United": {"understat": ["Manchester United"]},
                    "Arsenal": {},
                },
                "I1": {"Parma": {"understat": ["Parma Calcio 1913"]}},
            }
        }
    )
    return TeamNameResolver(aliases)


def test_resolve_exact(resolver: TeamNameResolver) -> None:
    assert resolver.resolve("E0", "understat", "Manchester United") == "Man United"
    assert resolver.resolve("E0", "football_data", "Man United") == "Man United"
    assert resolver.resolve("E0", "understat", "Arsenal") == "Arsenal"
    assert resolver.resolve("I1", "understat", "Parma Calcio 1913") == "Parma"
    assert resolver.teams("E0") == ["Arsenal", "Man United"]
    assert resolver.leagues == ["E0", "I1"]


def test_unknown_team_raises(resolver: TeamNameResolver) -> None:
    with pytest.raises(UnknownTeamError):
        resolver.resolve("E0", "football_data", "Manchester United")  # only an understat alias


def test_canonicalize_lists_all_unknown(resolver: TeamNameResolver) -> None:
    frame = pd.DataFrame(
        {
            "league": ["E0", "E0"],
            "home_team": ["Manchester United", "Chelsea"],
            "away_team": ["Arsenal", "Spurs"],
        }
    )
    with pytest.raises(UnknownTeamError) as err:
        resolver.canonicalize(frame, "understat")
    assert err.value.unknown == {("E0", "understat"): {"Chelsea", "Spurs"}}
    ok = resolver.canonicalize(frame.iloc[:1], "understat")
    assert ok.iloc[0]["home_team"] == "Man United"


def test_lenient_lookup(resolver: TeamNameResolver) -> None:
    assert resolver.lookup("E0", "manchester united") == "Man United"
    assert resolver.lookup("E0", "MAN-UNITED") == "Man United"
    assert resolver.lookup("E0", "Man Utd FC") is None
    assert resolver.lookup("XX", "Arsenal") is None


def test_conflicting_alias_rejected() -> None:
    aliases = TeamAliases.model_validate(
        {"teams": {"E0": {"A": {"understat": ["X"]}, "B": {"understat": ["X"]}}}}
    )
    with pytest.raises(ValueError, match="maps to"):
        TeamNameResolver(aliases)


def test_config_aliases_cover_all_leagues() -> None:
    resolver = TeamNameResolver(load_team_aliases())
    assert set(load_leagues().codes) <= set(resolver.leagues)
    assert resolver.resolve("F1", "understat", "Paris Saint Germain") == "Paris SG"
    assert resolver.resolve("D1", "understat", "Borussia M.Gladbach") == "M'gladbach"


RAW = PROJECT_ROOT / "data" / "raw"


@pytest.mark.skipif(not (RAW / "football_data").exists(), reason="raw data not downloaded")
def test_all_downloaded_teams_are_mapped() -> None:
    """Fails as soon as a raw file contains a team not present in team_aliases.yaml."""
    leagues = load_leagues()
    resolver = TeamNameResolver(load_team_aliases())
    football_data = FootballDataSource(RAW)
    understat = UnderstatSource(
        RAW, league_codes={lg.code: lg.understat or lg.code for lg in leagues.leagues}
    )
    unknown: dict[str, set[str]] = {}
    for league in leagues.codes:
        for season in leagues.seasons.all:
            for source, adapter in (("football_data", football_data), ("understat", understat)):
                path: Path = adapter.raw_path(league, season)
                if not path.exists():
                    continue
                frame = adapter.fetch_season(league, season)
                names = set(frame["home_team"]) | set(frame["away_team"])
                missing = resolver.unknown_names(league, source, names)  # type: ignore[arg-type]
                if missing:
                    unknown.setdefault(f"{league}/{source}", set()).update(missing)
    assert unknown == {}
