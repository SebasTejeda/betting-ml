"""Spec 003, T013: the database rejects impossible data even when the API is bypassed, the
migration that adds the CHECK constraints never deletes nor fixes rows, and SQLite runs with
WAL, a busy timeout and foreign keys. Spec 004 (I02): the same for the market of a bet
(migration 0010)."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import sqlalchemy as sa
from alembic import command
from sqlalchemy.exc import IntegrityError

from betting_ml.adapters.sql.db import (
    BUSY_TIMEOUT_MS,
    DatabaseConfigError,
    _alembic_config,
    check_pragmas,
    make_engine,
    prepare,
    upgrade,
)
from betting_ml.adapters.sql.models import Base
from betting_ml.domain.markets import (
    LINE_MARKETS,
    SELECTIONS,
    InvalidSelectionError,
    Market,
    validate_selection,
)

CREATED = "2026-10-03 10:00:00.000000"
LATER = "2026-10-03 22:00:00.000000"
BET: dict[str, Any] = {
    "created_at": CREATED,
    "match_id": "E0-2026-10-03-arsenal-chelsea",
    "league": "E0",
    "home_team": "Arsenal",
    "away_team": "Chelsea",
    "outcome": "A",
    "bookmaker": "teapuesto",
    "odds": 4.4,
    "stake": 10.0,
    "kind": "paper",
    "status": "pendiente",
    "from_experimental_signal": 0,
    "warnings": "",
    "no_reference": 0,
    "profit": None,
    "settled_at": None,
    "result_source": None,
    "fair_probability": 0.21,
    "ev": -0.05,
    "clv": None,
}
SETTINGS: dict[str, Any] = {
    "id": 1,
    "bankroll_initial": 500.0,
    "currency": "PEN",
    "monthly_loss_limit": 100.0,
    "max_stake_pct": 0.02,
    "kelly_fraction": 0.25,
    "min_edge": 0.02,
}
SESSION: dict[str, Any] = {
    "token_hash": "a" * 64,
    "csrf_token": "c" * 43,
    "created_at": CREATED,
    "last_seen_at": CREATED,
    "expires_at": LATER,
    "password_fingerprint": "f" * 64,
}
LOST = {"status": "perdida", "profit": -10.0, "settled_at": LATER, "result_source": "manual"}


def _insert(connection: sa.Connection, table: str, row: dict[str, Any]) -> None:
    """Plain SQL, as a script or a bug could do: no ORM, no domain, no API."""
    columns = ", ".join(row)
    values = ", ".join(f":{c}" for c in row)
    connection.execute(sa.text(f"INSERT INTO {table} ({columns}) VALUES ({values})"), row)


@pytest.fixture
def engine() -> sa.Engine:
    engine = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return engine


def test_valid_rows_are_accepted(engine: sa.Engine) -> None:
    won = {"status": "ganada", "profit": 34.0, "settled_at": LATER, "result_source": "official"}
    void = {"status": "nula", "profit": 0.0, "settled_at": LATER, "result_source": "manual"}
    with engine.begin() as connection:
        for changes in ({}, won, LOST, void, {"clv": 0.12, "ev": None, "fair_probability": None}):
            _insert(connection, "bets", {**BET, **changes})
        _insert(connection, "settings", SETTINGS)
        _insert(connection, "sessions", SESSION)
        assert connection.execute(sa.text("SELECT count(*) FROM bets")).scalar() == 5


@pytest.mark.parametrize(
    ("changes", "constraint"),
    [
        ({"odds": 1.0}, "ck_bets_odds"),
        ({"odds": 0.5}, "ck_bets_odds"),
        ({"stake": 0}, "ck_bets_stake"),
        ({"stake": -5}, "ck_bets_stake"),
        ({"stake": 10.005}, "ck_bets_stake"),
        ({"kind": "credit"}, "ck_bets_kind"),
        ({"status": "won"}, "ck_bets_status"),
        ({"outcome": "home"}, "ck_bets_outcome"),
        ({"result_source": "hacker"}, "ck_bets_result_source"),
        ({"profit": 5.0}, "ck_bets_settlement"),  # pending with a profit
        ({"settled_at": LATER}, "ck_bets_settlement"),
        ({"status": "ganada", "settled_at": LATER}, "ck_bets_settlement"),  # settled, no profit
        ({**LOST, "profit": -3.0}, "ck_bets_profit"),  # a lost bet loses the whole stake
        ({**LOST, "status": "nula"}, "ck_bets_profit"),  # a void bet has no profit
        ({**LOST, "status": "ganada"}, "ck_bets_profit"),  # a won bet cannot lose money
        ({**LOST, "profit": -10.001}, "ck_bets_profit"),
        ({"fair_probability": 1.5}, "ck_bets_fair_probability"),
        ({"ev": -2}, "ck_bets_ev"),
        ({"clv": 5000}, "ck_bets_clv"),
    ],
)
def test_impossible_bets_are_rejected(
    engine: sa.Engine, changes: dict[str, Any], constraint: str
) -> None:
    with pytest.raises(IntegrityError, match=constraint), engine.begin() as connection:
        _insert(connection, "bets", {**BET, **changes})


@pytest.mark.parametrize(
    ("table", "row", "constraint"),
    [
        ("settings", {**SETTINGS, "bankroll_initial": -1}, "ck_settings_bankroll_initial"),
        ("settings", {**SETTINGS, "monthly_loss_limit": 0.001}, "ck_settings_monthly_loss_limit"),
        ("settings", {**SETTINGS, "currency": "pen"}, "ck_settings_currency"),
        ("settings", {**SETTINGS, "max_stake_pct": 0}, "ck_settings_max_stake"),
        ("settings", {**SETTINGS, "max_stake_pct": 1.5}, "ck_settings_max_stake"),
        ("settings", {**SETTINGS, "kelly_fraction": 2}, "ck_settings_kelly_fraction"),
        ("settings", {**SETTINGS, "min_edge": -0.1}, "ck_settings_min_edge"),
        ("sessions", {**SESSION, "token_hash": "short"}, "ck_sessions_token_hash"),
        ("sessions", {**SESSION, "expires_at": CREATED}, "ck_sessions_expiry"),
        ("sessions", {**SESSION, "last_seen_at": "2026-10-02 00:00:00"}, "ck_sessions_last_seen"),
        (
            "settings_history",
            {
                "changed_at": CREATED,
                "field": "monthly_loss_limit",
                "old_value": "100",
                "new_value": "50",
                "effective_from": "next",
            },
            "ck_settings_history_effective_from",
        ),
        (
            "bookmakers",
            {"key": "x", "name": "X", "role": "owner", "accessible": 1, "source": "api"},
            "ck_bookmakers_role",
        ),
        (
            "bookmakers",
            {"key": "x", "name": "X", "role": "soft", "accessible": 1, "source": "scraper"},
            "ck_bookmakers_source",
        ),
        (
            "odds_snapshots",
            {"fetched_at": CREATED, "source": "the_odds_api", "credits_used": -1, "leagues": ""},
            "ck_odds_snapshots_credits_used",
        ),
    ],
)
def test_impossible_rows_are_rejected(
    engine: sa.Engine, table: str, row: dict[str, Any], constraint: str
) -> None:
    with pytest.raises(IntegrityError, match=constraint), engine.begin() as connection:
        _insert(connection, table, row)


@pytest.mark.parametrize(("odds", "outcome"), [(1.0, "H"), (2.0, "X")])
def test_impossible_quotes_are_rejected(engine: sa.Engine, odds: float, outcome: str) -> None:
    with engine.begin() as connection:
        _insert(
            connection,
            "odds_snapshots",
            {"id": 1, "fetched_at": CREATED, "source": "manual", "leagues": ""},
        )
    quote = {
        "snapshot_id": 1,
        "match_id": BET["match_id"],
        "league": "E0",
        "home_team": "Arsenal",
        "away_team": "Chelsea",
        "bookmaker_key": "pinnacle",
        "market": "h2h",
        "outcome": outcome,
        "odds": odds,
    }
    with pytest.raises(IntegrityError, match="ck_odds_quotes"), engine.begin() as connection:
        _insert(connection, "odds_quotes", quote)


# ------------------------------------------------------------------ migration 0005
def _url(tmp_path: Path, name: str = "app.db") -> str:
    return f"sqlite:///{(tmp_path / name).as_posix()}"


def _checks(engine: sa.Engine) -> dict[str, set[tuple[str, str]]]:
    inspector = sa.inspect(engine)
    return {
        table: {
            (c["name"], re.sub(r"\s+", " ", c["sqltext"]).strip())
            for c in inspector.get_check_constraints(table)
        }
        for table in Base.metadata.tables
        if table in inspector.get_table_names()  # older revisions lack the newer tables
    }


def _revision(engine: sa.Engine) -> str:
    with engine.connect() as connection:
        return str(connection.execute(sa.text("SELECT version_num FROM alembic_version")).scalar())


def test_migrated_schema_has_the_same_checks_as_the_models(tmp_path: Path) -> None:
    url = _url(tmp_path)
    upgrade(url)
    memory = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(memory)
    migrated = _checks(make_engine(url))
    assert migrated == _checks(memory)
    assert sum(len(c) for c in migrated.values()) == 36  # 32 of spec 003 + 4 of 0010


def test_migration_keeps_valid_data(tmp_path: Path) -> None:
    url = _url(tmp_path)
    upgrade(url, "0004")
    engine = make_engine(url)
    with engine.begin() as connection:
        _insert(connection, "bets", {**BET, "note": "primera"})
        _insert(connection, "bets", {**BET, **LOST})
        _insert(connection, "settings", SETTINGS)
    with engine.connect() as connection:
        before = connection.execute(sa.text("SELECT * FROM bets ORDER BY id")).all()
    engine.dispose()
    upgrade(url)
    engine = make_engine(url)
    with engine.connect() as connection:
        after = connection.execute(sa.text("SELECT * FROM bets ORDER BY id")).all()
        # + version (0006), then market, selection and line (0009)
        assert [row[:-4] for row in after] == before
        assert [tuple(row[-4:]) for row in after] == [(1, "h2h", None, None)] * 2
        assert connection.execute(sa.text("SELECT currency FROM settings")).scalar() == "PEN"
    assert _revision(engine) != "0004"
    with pytest.raises(IntegrityError), engine.begin() as connection:
        _insert(connection, "bets", {**BET, "odds": 1.0})


def test_migration_aborts_listing_invalid_rows_and_changes_nothing(tmp_path: Path) -> None:
    url = _url(tmp_path)
    upgrade(url, "0004")
    engine = make_engine(url)
    with engine.begin() as connection:
        _insert(connection, "bets", BET)  # rowid 1, valid
        _insert(connection, "bets", {**BET, "odds": 1.0, "note": "SECRET-NOTE"})  # rowid 2
        _insert(connection, "bets", {**BET, **LOST, "profit": -2.0})  # rowid 3
        _insert(connection, "settings", {**SETTINGS, "currency": "pen"})
    with engine.connect() as connection:
        before = connection.execute(sa.text("SELECT * FROM bets ORDER BY id")).all()
    engine.dispose()

    with pytest.raises(RuntimeError, match="0005 abortada") as error:
        upgrade(url)
    message = str(error.value)
    assert "bets.ck_bets_odds: rowid 2" in message
    assert "bets.ck_bets_profit: rowid 3" in message
    assert "settings.ck_settings_currency: rowid 1" in message
    assert "rowid 1" not in message.split("bets.ck_bets_odds")[1].split("\n")[0]
    assert "SECRET" not in message and "pen" not in message  # rowids, never values

    engine = make_engine(url)
    assert _revision(engine) == "0004"
    with engine.connect() as connection:
        assert connection.execute(sa.text("SELECT * FROM bets ORDER BY id")).all() == before
    assert all(not checks for checks in _checks(engine).values())

    with engine.begin() as connection:  # the owner fixes the rows by hand…
        connection.execute(sa.text("UPDATE bets SET odds = 1.5 WHERE id = 2"))
        connection.execute(sa.text("UPDATE bets SET profit = -10.0 WHERE id = 3"))
        connection.execute(sa.text("UPDATE settings SET currency = 'PEN'"))
    engine.dispose()
    upgrade(url)  # …and migrates again
    engine = make_engine(url)
    with engine.connect() as connection:
        assert connection.execute(sa.text("SELECT count(*) FROM bets")).scalar() == 3


def test_downgrade_removes_the_checks_and_keeps_the_data(tmp_path: Path) -> None:
    url = _url(tmp_path)
    upgrade(url)
    engine = make_engine(url)
    with engine.begin() as connection:
        _insert(connection, "bets", BET)
    engine.dispose()
    command.downgrade(_alembic_config(url), "0004")  # through 0006 and 0005
    engine = make_engine(url)
    assert all(not checks for checks in _checks(engine).values())
    with engine.connect() as connection:
        assert connection.execute(sa.text("SELECT count(*) FROM bets")).scalar() == 1
    assert {i["name"] for i in sa.inspect(engine).get_indexes("bets")} >= {
        "ix_bets_match_id",
        "ix_bets_status_kind",
    }


def test_databases_created_from_the_models_are_stamped_without_rebuilding(tmp_path: Path) -> None:
    url = _url(tmp_path, "old.db")
    Base.metadata.create_all(make_engine(url))
    engine = prepare(url)
    assert _checks(engine) == _checks(make_engine(url))
    assert _revision(engine) != "0004"


# ------------------------------------------------------------------ pragmas
def test_file_database_uses_wal_busy_timeout_and_foreign_keys(tmp_path: Path) -> None:
    engine = prepare(_url(tmp_path))
    assert check_pragmas(engine) == {
        "journal_mode": "wal",
        "busy_timeout": BUSY_TIMEOUT_MS,
        "foreign_keys": 1,
    }
    with engine.connect() as connection:  # every pooled connection, not only the first
        assert connection.exec_driver_sql("PRAGMA busy_timeout").scalar() == BUSY_TIMEOUT_MS


def test_memory_database_has_the_same_pragmas_except_wal() -> None:
    found = check_pragmas(prepare("sqlite:///:memory:"))
    assert found["journal_mode"] == "memory"
    assert found["foreign_keys"] == 1


def test_startup_fails_fast_without_the_pragmas(tmp_path: Path) -> None:
    plain = sa.create_engine(_url(tmp_path, "plain.db"))  # no make_engine: no pragmas
    with pytest.raises(DatabaseConfigError, match="foreign_keys"):
        check_pragmas(plain)
    impatient = sa.create_engine(_url(tmp_path, "impatient.db"), connect_args={"timeout": 0})
    with pytest.raises(DatabaseConfigError, match="busy_timeout"):
        check_pragmas(impatient)


def test_foreign_keys_are_enforced(engine: sa.Engine) -> None:
    quote = {
        "snapshot_id": 999,
        "match_id": BET["match_id"],
        "league": "E0",
        "home_team": "",
        "away_team": "",
        "bookmaker_key": "pinnacle",
        "market": "h2h",
        "outcome": "H",
        "odds": 2.0,
    }
    with pytest.raises(IntegrityError, match="FOREIGN KEY"), engine.begin() as connection:
        _insert(connection, "odds_quotes", quote)


# ------------------------------------------------------------------ markets (spec 004, I02)
def _market_bet(market: str, selection: str | None, line: float | None) -> dict[str, Any]:
    return {**BET, "outcome": None, "market": market, "selection": selection, "line": line}


def _valid_market_bets() -> list[dict[str, Any]]:
    """Every selection the domain accepts, with a line when its market needs one."""
    lines = {Market.TOTALS: 2.5, Market.TEAM_TOTALS: 0.5, Market.EUROPEAN_HANDICAP: -1.0}
    rows = [
        _market_bet(market.value, selection, lines.get(market))
        for market, selections in SELECTIONS.items()
        if market is not Market.H2H and selections is not None
        for selection in selections
    ]
    rows += [_market_bet("correct_score", s, None) for s in ("0-0", "2-1", "10-3", "1-10")]
    rows += [_market_bet("totals", "under", 9.5), _market_bet("european_handicap", "home", 0)]
    return [*rows, _market_bet("european_handicap", "draw", 10)]


def test_every_market_the_domain_accepts_is_accepted(engine: sa.Engine) -> None:
    rows = _valid_market_bets()
    assert {r["market"] for r in rows} == {m.value for m in Market} - {"h2h"}
    assert set(LINE_MARKETS) == {Market.TOTALS, Market.TEAM_TOTALS, Market.EUROPEAN_HANDICAP}
    with engine.begin() as connection:
        for row in rows:
            _insert(connection, "bets", row)
        _insert(connection, "bets", BET)  # 1X2: outcome, no selection, no line


IMPOSSIBLE_MARKETS = [
    ({"market": "poker", "outcome": None}, "ck_bets_market"),
    ({"market": "H2H"}, "ck_bets_market"),
    ({"outcome": None}, "ck_bets_outcome_market"),  # 1X2 without its outcome
    ({**_market_bet("btts", "yes", None), "outcome": "H"}, "ck_bets_outcome_market"),
    ({"selection": "home"}, "ck_bets_selection"),  # 1X2 uses outcome
    (_market_bet("btts", None, None), "ck_bets_selection"),
    (_market_bet("btts", "over", None), "ck_bets_selection"),
    (_market_bet("double_chance", "1x", None), "ck_bets_selection"),
    (_market_bet("draw_no_bet", "draw", None), "ck_bets_selection"),
    (_market_bet("totals", "home_over", 2.5), "ck_bets_selection"),
    (_market_bet("team_totals", "over", 1.5), "ck_bets_selection"),
    (_market_bet("european_handicap", "1X", 1), "ck_bets_selection"),
    (_market_bet("correct_score", None, None), "ck_bets_selection"),
    (_market_bet("correct_score", "", None), "ck_bets_selection"),
    (_market_bet("correct_score", "2-1-0", None), "ck_bets_selection"),
    (_market_bet("correct_score", "100-1", None), "ck_bets_selection"),
    (_market_bet("correct_score", "a-b", None), "ck_bets_selection"),
    (_market_bet("correct_score", " 2-1", None), "ck_bets_selection"),
    ({"line": 2.5}, "ck_bets_line"),  # 1X2 has no line
    (_market_bet("btts", "yes", 2.5), "ck_bets_line"),
    (_market_bet("correct_score", "2-1", 0.5), "ck_bets_line"),
    (_market_bet("totals", "over", None), "ck_bets_line"),
    (_market_bet("totals", "over", 2.0), "ck_bets_line"),
    (_market_bet("totals", "over", 2.25), "ck_bets_line"),  # no Asian lines
    (_market_bet("totals", "over", -0.5), "ck_bets_line"),
    (_market_bet("totals", "over", 10.5), "ck_bets_line"),
    (_market_bet("team_totals", "home_over", 0), "ck_bets_line"),
    (_market_bet("european_handicap", "home", None), "ck_bets_line"),
    (_market_bet("european_handicap", "home", 0.5), "ck_bets_line"),
    (_market_bet("european_handicap", "home", 11), "ck_bets_line"),
    (_market_bet("european_handicap", "home", -11), "ck_bets_line"),
]


@pytest.mark.parametrize(("changes", "constraint"), IMPOSSIBLE_MARKETS)
def test_impossible_markets_are_rejected(
    engine: sa.Engine, changes: dict[str, Any], constraint: str
) -> None:
    with pytest.raises(IntegrityError, match=constraint), engine.begin() as connection:
        _insert(connection, "bets", {**BET, **changes})


@pytest.mark.parametrize(
    "row",
    [
        {**BET, **changes}
        for changes, constraint in IMPOSSIBLE_MARKETS
        # the outcome/market pairing is checked by ``Bet`` itself, a 1X2 bet has no selection
        if constraint in {"ck_bets_selection", "ck_bets_line"}
        and changes.get("market", "h2h") != "h2h"
        and changes.get("selection") is not None
    ],
)
def test_the_domain_refuses_what_the_database_refuses(row: dict[str, Any]) -> None:
    """Integration I08: a bet coming from anywhere but the API (CLI, script) is refused by the
    domain with a clear error, never by a CHECK as a 500."""
    with pytest.raises(InvalidSelectionError):
        validate_selection(row["market"], row["selection"], row.get("line"))


def test_an_existing_bet_cannot_be_changed_into_an_impossible_one(engine: sa.Engine) -> None:
    with engine.begin() as connection:
        _insert(connection, "bets", _market_bet("totals", "over", 2.5))
    for statement in (
        "UPDATE bets SET line = 2.25",
        "UPDATE bets SET selection = NULL",
        "UPDATE bets SET market = 'h2h'",
    ):
        with pytest.raises(IntegrityError, match="ck_bets_"), engine.begin() as connection:
            connection.execute(sa.text(statement))


def test_migration_0010_aborts_listing_invalid_bets_and_changes_nothing(tmp_path: Path) -> None:
    url = _url(tmp_path)
    upgrade(url, "0009")
    engine = make_engine(url)
    with engine.begin() as connection:
        _insert(connection, "bets", _market_bet("totals", "over", 2.5))  # rowid 1, valid
        _insert(connection, "bets", {**_market_bet("poker", "SECRET-PICK", None)})  # rowid 2
        _insert(connection, "bets", _market_bet("totals", "over", 2.25))  # rowid 3
        _insert(connection, "bets", {**BET, "outcome": None})  # rowid 4
    with engine.connect() as connection:
        before = connection.execute(sa.text("SELECT * FROM bets ORDER BY id")).all()
    engine.dispose()

    with pytest.raises(RuntimeError, match="0010 abortada") as error:
        upgrade(url)
    message = str(error.value)
    assert "bets.ck_bets_market: rowid 2" in message
    assert "bets.ck_bets_selection: rowid 2" in message
    assert "bets.ck_bets_line: rowid 3" in message
    assert "bets.ck_bets_outcome_market: rowid 4" in message
    assert "rowid 1" not in message
    assert "SECRET" not in message and "poker" not in message and "2.25" not in message

    engine = make_engine(url)
    assert _revision(engine) == "0009"
    with engine.connect() as connection:
        assert connection.execute(sa.text("SELECT * FROM bets ORDER BY id")).all() == before
    assert not {name for name, _ in _checks(engine)["bets"]} & {
        "ck_bets_market",
        "ck_bets_outcome_market",
        "ck_bets_selection",
        "ck_bets_line",
    }

    with engine.begin() as connection:  # the owner fixes the bets by hand…
        connection.execute(
            sa.text("UPDATE bets SET market = 'btts', selection = 'yes' WHERE id = 2")
        )
        connection.execute(sa.text("UPDATE bets SET line = 2.5 WHERE id = 3"))
        connection.execute(sa.text("UPDATE bets SET outcome = 'A' WHERE id = 4"))
    engine.dispose()
    upgrade(url)  # …and migrates again
    engine = make_engine(url)
    assert _revision(engine) == "0010"
    with engine.connect() as connection:
        assert connection.execute(sa.text("SELECT count(*) FROM bets")).scalar() == 4


def test_migration_0010_keeps_the_rows_and_its_downgrade_only_drops_its_checks(
    tmp_path: Path,
) -> None:
    url = _url(tmp_path)
    upgrade(url, "0009")
    engine = make_engine(url)
    with engine.begin() as connection:
        for row in (BET, *_valid_market_bets()):
            _insert(connection, "bets", row)
        before = connection.execute(sa.text("SELECT * FROM bets ORDER BY id")).all()
    checks_0009 = _checks(engine)
    engine.dispose()
    upgrade(url)
    engine = make_engine(url)
    with engine.connect() as connection:
        assert connection.execute(sa.text("SELECT * FROM bets ORDER BY id")).all() == before
    engine.dispose()
    command.downgrade(_alembic_config(url), "0009")
    engine = make_engine(url)
    assert _checks(engine) == checks_0009
    with engine.connect() as connection:
        assert connection.execute(sa.text("SELECT * FROM bets ORDER BY id")).all() == before
