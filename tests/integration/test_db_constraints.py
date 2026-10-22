"""Spec 003, T013: the database rejects impossible data even when the API is bypassed, the
migration that adds the CHECK constraints never deletes nor fixes rows, and SQLite runs with
WAL, a busy timeout and foreign keys."""

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
    assert sum(len(c) for c in migrated.values()) == 32


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
