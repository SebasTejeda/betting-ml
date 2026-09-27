"""Regression for the empty /matches of Saturday 2026-09-26 (spec 002 §7, T002).

Extract of the real fixtures.csv downloaded that day: it only lists lower divisions (E2, E3,
EC, SC1, SP2) because the 5 supported leagues had no matches (break between matchdays). The
date/time handling is correct; this pins it down with the real file format.
"""

from datetime import UTC, date, datetime
from pathlib import Path

from betting_ml.adapters.fixtures import parse_fixtures
from betting_ml.adapters.team_names import TeamNameResolver
from betting_ml.config import TeamAliases, load_team_aliases
from betting_ml.domain.entities import fixtures_on

EXTRACT = Path(__file__).parents[1] / "fixtures" / "fixtures_20260926_real_extract.csv"
TOP5 = {"E0": "E0", "SP1": "SP1", "D1": "D1", "I1": "I1", "F1": "F1"}


def test_no_supported_league_in_the_real_file() -> None:
    fixtures, unknown = parse_fixtures(
        EXTRACT.read_bytes(), TOP5, TeamNameResolver(load_team_aliases())
    )
    assert fixtures == [] and unknown == set()


def test_real_format_dates_and_lima_filter() -> None:
    """If SP2 were supported, its 26/09 match would be found on 26/09 in Lima."""
    aliases = TeamAliases.model_validate(
        {"teams": {"SP2": {name: {} for name in ("Girona", "Albacete", "Ceuta", "Sociedad B")}}}
    )
    fixtures, unknown = parse_fixtures(
        EXTRACT.read_bytes(), {"SP2": "SP2"}, TeamNameResolver(aliases)
    )
    assert unknown == set()
    by_home = {f.home_team: f for f in fixtures}
    # dd/mm/yyyy: 26/09/2026 is 26 September (not 9 February); 13:00 BST -> 12:00 UTC.
    assert by_home["Ceuta"].kickoff_utc == datetime(2026, 9, 26, 12, 0, tzinfo=UTC)
    assert by_home["Girona"].kickoff_utc == datetime(2026, 9, 25, 18, 30, tzinfo=UTC)
    lima = fixtures_on(fixtures, date(2026, 9, 26), "America/Lima")
    assert [f.home_team for f in lima] == ["Ceuta"]
    assert by_home["Ceuta"].match_id == "SP2-2026-09-26-ceuta-sociedad-b"
