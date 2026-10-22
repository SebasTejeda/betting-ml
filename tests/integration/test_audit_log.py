"""Spec 003, T015: every change appends its audit event in the same transaction, the log is
append-only, and verify-integrity catches altered records and rows changed outside the API."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
import sqlalchemy as sa
from alembic import command
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session, sessionmaker
from typer.testing import CliRunner

from betting_ml.adapters.argon2_hasher import Argon2Hasher
from betting_ml.adapters.memory_rate_limiter import MemoryRateLimiter
from betting_ml.adapters.sql.audit import SqlAuditLog, SqlIntegrity
from betting_ml.adapters.sql.db import (
    _alembic_config,
    make_engine,
    prepare,
    session_factory,
    upgrade,
)
from betting_ml.adapters.sql.models import APPEND_ONLY_TRIGGERS
from betting_ml.adapters.sql.repositories import (
    SqlBetRepository,
    SqlOddsRepository,
    SqlSessionStore,
    SqlSettingsRepository,
)
from betting_ml.application.authenticate import Authenticate, InvalidCredentialsError
from betting_ml.application.maintenance import VerifyIntegrity
from betting_ml.application.throttle import LoginThrottle
from betting_ml.cli import app
from betting_ml.config import Settings
from betting_ml.domain.audit import AuditInfo
from betting_ml.domain.entities import Outcome
from betting_ml.domain.journal import (
    Bet,
    BetKind,
    BetStatus,
    OddsQuote,
    OddsSnapshot,
    QuoteSource,
    SettingsChange,
    VersionConflictError,
)

NOW = datetime(2026, 10, 22, 12, tzinfo=UTC)


def _bet() -> Bet:
    return Bet(
        "E0-2026-10-10-arsenal-chelsea",
        "E0",
        Outcome.AWAY,
        "betsson",
        Decimal("4.40"),
        Decimal("10.00"),
        BetKind.PAPER,
        datetime(2026, 10, 9, tzinfo=UTC),
        kickoff_utc=datetime(2026, 10, 10, 14, tzinfo=UTC),
    )


@pytest.fixture
def sessions(tmp_path: Path) -> sessionmaker[Session]:
    return session_factory(prepare(f"sqlite:///{(tmp_path / 'app.db').as_posix()}"))


def _verify(sessions: sessionmaker[Session]) -> list[str]:
    return VerifyIntegrity(SqlIntegrity(sessions)).run().problems


def _actions(sessions: sessionmaker[Session]) -> list[tuple[str, str, str | None]]:
    return [(r.actor, r.action, r.entity_id) for r in SqlAuditLog(sessions).records()]


def _sql(sessions: sessionmaker[Session], statement: str) -> None:
    with sessions.begin() as session:
        session.execute(sa.text(statement))


# ------------------------------------------------------------------ recording
def test_every_change_appends_its_event_and_the_chain_verifies(
    sessions: sessionmaker[Session],
) -> None:
    bets, settings = SqlBetRepository(sessions), SqlSettingsRepository(sessions)
    bet = bets.add(_bet(), AuditInfo("api_key", "BET_CREATED"))
    bet = bets.update(replace(bet, note="nota"), AuditInfo("session"))
    bets.update(bet.settle(BetStatus.LOST, NOW, "manual"), AuditInfo("session", "BET_SETTLED"))
    other = bets.add(_bet(), AuditInfo("cli"))
    bets.delete(other.id, AuditInfo("cli", "BET_DELETED"))  # type: ignore[arg-type]
    saved = settings.save(replace(settings.get(), min_edge=0.03), (), AuditInfo("session"))
    quote = OddsQuote(bet.match_id, "E0", "pinnacle", Outcome.HOME, 2.0)
    SqlOddsRepository(sessions).save_snapshot(
        OddsSnapshot(NOW, QuoteSource.API, [quote], 100, 2, ["E0"]), AuditInfo("scheduler")
    )
    assert _actions(sessions) == [
        ("api_key", "BET_CREATED", "1"),
        ("session", "BET_UPDATED", "1"),
        ("session", "BET_SETTLED", "1"),
        ("cli", "BET_CREATED", "2"),
        ("cli", "BET_DELETED", "2"),
        ("session", "SETTINGS_CHANGED", "1"),
        ("scheduler", "ODDS_REFRESHED", "1"),
    ]
    records = SqlAuditLog(sessions).records()
    settled = records[2].fields()
    assert settled["before"]["status"] == "pendiente" and settled["after"]["status"] == "perdida"
    assert settled["after"]["version"] == 3
    assert records[4].fields()["after"] is None  # a deletion keeps the "before" only
    assert records[5].fields()["after"]["min_edge"] == 0.03 and saved.version == 1
    assert records[6].fields()["after"]["quotes"] == 1
    assert _verify(sessions) == []


def test_a_rejected_change_writes_no_event(sessions: sessionmaker[Session]) -> None:
    bets = SqlBetRepository(sessions)
    read = bets.add(_bet())
    bets.update(replace(read, note="primera"))
    with pytest.raises(VersionConflictError):
        bets.update(replace(read, note="segunda"))
    assert [a for _, a, _ in _actions(sessions)] == ["BET_CREATED", "BET_UPDATED"]


def test_no_change_without_its_event(
    sessions: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Same transaction: if the event cannot be written, the change is rolled back too."""

    def broken(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("audit down")

    monkeypatch.setattr("betting_ml.adapters.sql.repositories.record_change", broken)
    with pytest.raises(RuntimeError, match="audit down"):
        SqlBetRepository(sessions).add(_bet())
    with sessions() as session:
        assert session.execute(sa.text("SELECT count(*) FROM bets")).scalar() == 0


# ------------------------------------------------------------------ append-only
@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE audit_log SET actor = 'cli' WHERE seq = 1",
        "UPDATE audit_log SET payload = '{}'",
        "DELETE FROM audit_log WHERE seq = 1",
        "DELETE FROM audit_log",
    ],
)
def test_the_log_rejects_update_and_delete(sessions: sessionmaker[Session], statement: str) -> None:
    SqlBetRepository(sessions).add(_bet())
    with pytest.raises(DBAPIError, match="solo inserción"):
        _sql(sessions, statement)
    assert len(SqlAuditLog(sessions).records()) == 1


def test_both_schemas_have_the_append_only_triggers(sessions: sessionmaker[Session]) -> None:
    memory = make_engine("sqlite:///:memory:")
    from betting_ml.adapters.sql.models import Base

    Base.metadata.create_all(memory)
    for engine in (memory, sessions.kw["bind"]):
        with engine.connect() as connection:
            names = connection.execute(
                sa.text("SELECT name FROM sqlite_master WHERE type = 'trigger'")
            ).scalars()
            assert set(names) == set(APPEND_ONLY_TRIGGERS)


# ------------------------------------------------------------------ verify-integrity
def _with_history(sessions: sessionmaker[Session]) -> None:
    bets = SqlBetRepository(sessions)
    for _ in range(3):
        bet = bets.add(_bet())
        bets.update(replace(bet, note="x"))
    settings = SqlSettingsRepository(sessions)
    settings.save(replace(settings.get(), min_edge=0.03))


def test_an_altered_record_is_reported_with_its_seq(sessions: sessionmaker[Session]) -> None:
    _with_history(sessions)
    assert _verify(sessions) == []
    # someone with the database file drops the trigger and edits a record
    _sql(sessions, "DROP TRIGGER audit_log_no_update")
    _sql(
        sessions, "UPDATE audit_log SET payload = replace(payload, '\"x\"', '\"y\"') WHERE seq = 2"
    )
    assert "seq 2: el contenido no coincide con su hash (alterado)" in _verify(sessions)


def test_a_deleted_record_is_reported(sessions: sessionmaker[Session]) -> None:
    _with_history(sessions)
    _sql(sessions, "DROP TRIGGER audit_log_no_delete")
    _sql(sessions, "DELETE FROM audit_log WHERE seq = 3")
    assert "seq 3: falta (el siguiente es 4)" in _verify(sessions)


@pytest.mark.parametrize(
    ("statement", "problem"),
    [
        ("UPDATE bets SET stake = 999 WHERE id = 2", "bet 2: no coincide con su último evento"),
        (
            "UPDATE bets SET status = 'ganada', profit = 34, settled_at = '2026-10-11'"
            " WHERE id = 1",
            "bet 1: no coincide con su último evento",
        ),
        ("DELETE FROM bets WHERE id = 3", "bet 3: falta, pero su último evento no es un borrado"),
        (
            "INSERT INTO bets (created_at, match_id, league, home_team, away_team, outcome,"
            " bookmaker, odds, stake, kind, status, from_experimental_signal, warnings,"
            " no_reference) SELECT created_at, match_id, league, home_team, away_team, outcome,"
            " bookmaker, odds, stake, kind, status, from_experimental_signal, warnings,"
            " no_reference FROM bets WHERE id = 1",
            "bet 4: existe sin ningún evento en la auditoría",
        ),
        ("UPDATE settings SET monthly_loss_limit = 1000", "settings 1: no coincide"),
    ],
)
def test_rows_changed_outside_the_api_are_detected(
    sessions: sessionmaker[Session], statement: str, problem: str
) -> None:
    _with_history(sessions)
    _sql(sessions, statement)
    problems = _verify(sessions)
    assert any(p.startswith(problem) for p in problems), problems


def test_verify_integrity_runs_sqlite_checks_too(sessions: sessionmaker[Session]) -> None:
    _with_history(sessions)
    with sessions.begin() as session:
        session.execute(sa.text("PRAGMA foreign_keys = OFF"))
        session.execute(
            sa.text(
                "INSERT INTO odds_quotes (snapshot_id, match_id, league, home_team, away_team,"
                " bookmaker_key, market, outcome, odds) VALUES (999, 'm', 'E0', '', '', 'x',"
                " 'h2h', 'H', 2.0)"
            )
        )
        session.execute(sa.text("PRAGMA foreign_keys = ON"))
    assert any(p.startswith("foreign_key_check: odds_quotes") for p in _verify(sessions))


def test_cli_exit_code(
    sessions: sessionmaker[Session], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = Settings(_env_file=None, database_url=f"sqlite:///{(tmp_path / 'app.db').as_posix()}")
    monkeypatch.setattr("betting_ml.container.get_settings", lambda: config)
    _with_history(sessions)
    ok = CliRunner().invoke(app, ["verify-integrity"])
    assert ok.exit_code == 0, ok.output
    assert "Integridad verificada" in ok.output and "bet=3" in ok.output
    _sql(sessions, "UPDATE bets SET stake = 1 WHERE id = 1")
    failed = CliRunner().invoke(app, ["verify-integrity"])
    assert failed.exit_code == 1
    assert "FALLO: bet 1: no coincide" in failed.output


# ------------------------------------------------------------------ migration 0007
def test_migration_seals_a_baseline_of_existing_data(tmp_path: Path) -> None:
    url = f"sqlite:///{(tmp_path / 'old.db').as_posix()}"
    upgrade(url, "0006")
    engine = make_engine(url)
    with engine.begin() as connection:
        for note in ("a", "b"):
            connection.execute(
                sa.text(
                    "INSERT INTO bets (created_at, match_id, league, home_team, away_team,"
                    " outcome, bookmaker, odds, stake, kind, status, from_experimental_signal,"
                    " warnings, no_reference, note) VALUES ('2026-10-09 00:00:00.000000',"
                    " 'E0-2026-10-10-a-b', 'E0', '', '', 'A', 'betsson', 4.4, 10, 'paper',"
                    " 'pendiente', 0, '', 0, :note)"
                ),
                {"note": note},
            )
        connection.execute(
            sa.text(
                "INSERT INTO settings (id, bankroll_initial, currency, monthly_loss_limit,"
                " max_stake_pct, kelly_fraction, min_edge) VALUES (1, 500, 'PEN', 100, 0.02,"
                " 0.25, 0.02)"
            )
        )
    engine.dispose()
    upgrade(url)
    sessions = session_factory(make_engine(url))
    assert _actions(sessions) == [
        ("migration", "BASELINE", "1"),
        ("migration", "BASELINE", "2"),
        ("migration", "BASELINE", "1"),
    ]
    assert _verify(sessions) == []
    bets = SqlBetRepository(sessions)
    bets.update(replace(bets.get(1), note="después"))  # type: ignore[arg-type]
    assert _verify(sessions) == []
    with pytest.raises(DBAPIError, match="solo inserción"):
        _sql(sessions, "DELETE FROM audit_log")


# ------------------------------------------------------------------ login and logout
def test_login_failure_success_and_logout_are_audited_without_secrets(
    sessions: sessionmaker[Session],
) -> None:
    hasher = Argon2Hasher(time_cost=1, memory_cost=1024, parallelism=1)
    auth = Authenticate(
        sessions=SqlSessionStore(sessions),
        hasher=hasher,
        password_hash=hasher.hash("correct horse"),
        secret=b"audit-tests-secret-0123456789abcdef",
        idle=timedelta(minutes=30),
        max_age=timedelta(hours=12),
        throttle=LoginThrottle(MemoryRateLimiter(), max_attempts=100),
        audit_log=SqlAuditLog(sessions),
    )
    with pytest.raises(InvalidCredentialsError):
        auth.login("wrong password", client="203.0.113.7")
    login = auth.login("correct horse", client="203.0.113.7")
    auth.logout(login.token)
    auth.logout(login.token)  # already gone: nothing to audit
    assert _actions(sessions) == [
        ("anonymous", "LOGIN_FAILED", None),
        ("session", "LOGIN_OK", None),
        ("session", "LOGOUT", None),
    ]
    text = " ".join(r.payload for r in SqlAuditLog(sessions).records())
    assert "203.0.113.7" in text
    for secret in ("wrong password", "correct horse", login.token, login.session.token_hash):
        assert secret not in text
    assert _verify(sessions) == []


def test_concurrent_appends_keep_one_unbroken_chain(sessions: sessionmaker[Session]) -> None:
    """Standalone events from several threads (failed logins at once): the write lock taken
    before reading the head means no two events get the same seq or link."""
    import threading

    log = SqlAuditLog(sessions)
    barrier = threading.Barrier(4)
    errors: list[BaseException] = []

    def worker(n: int) -> None:
        barrier.wait()
        try:
            for i in range(15):
                log.append(AuditInfo("anonymous", "LOGIN_FAILED", {"n": n, "i": i}), "session")
        except BaseException as exc:  # surfaced below, in the test thread
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(n,)) for n in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)
    assert not errors, errors[0]
    assert len(log.records()) == 60
    assert _verify(sessions) == []


# ------------------------------------------------------------------ limit history (checkpoint A1)
def _raise_limit(sessions: sessionmaker[Session]) -> None:
    """Raising the loss limit only applies next month: that rule lives in settings_history."""
    settings = SqlSettingsRepository(sessions)
    current = settings.get()
    settings.save(
        replace(current, monthly_loss_limit=Decimal("5000.00")),
        [SettingsChange(NOW, "monthly_loss_limit", "100.00", "5000.00", "2026-11")],
    )


def test_each_limit_change_is_audited_with_when_it_applies(
    sessions: sessionmaker[Session],
) -> None:
    _raise_limit(sessions)
    records = SqlAuditLog(sessions).records()
    assert [(r.action, r.entity) for r in records] == [
        ("SETTINGS_CHANGED", "settings"),
        ("SETTINGS_HISTORY_ADDED", "settings_change"),
    ]
    assert '"effective_from":"2026-11"' in records[1].payload
    assert _verify(sessions) == []


@pytest.mark.parametrize(
    ("statement", "problem"),
    [
        (
            "UPDATE settings_history SET effective_from = '2026-10'",  # apply the raise now
            "settings_change 1: no coincide con su último evento",
        ),
        ("DELETE FROM settings_history", "settings_change 1: falta"),
        (
            "INSERT INTO settings_history (changed_at, field, old_value, new_value,"
            " effective_from) VALUES ('2026-10-01 00:00:00', 'monthly_loss_limit', '100',"
            " '9999', '2026-09')",
            "settings_change 2: existe sin ningún evento",
        ),
    ],
)
def test_limit_history_changed_outside_the_api_is_detected(
    sessions: sessionmaker[Session], statement: str, problem: str
) -> None:
    _raise_limit(sessions)
    _sql(sessions, statement)
    assert any(p.startswith(problem) for p in _verify(sessions)), _verify(sessions)


def test_migration_0008_seals_the_existing_limit_history(tmp_path: Path) -> None:
    url = f"sqlite:///{(tmp_path / 'old.db').as_posix()}"
    upgrade(url, "0007")
    engine = make_engine(url)
    with engine.begin() as connection:
        connection.execute(
            sa.text(
                "INSERT INTO settings_history (changed_at, field, old_value, new_value,"
                " effective_from) VALUES ('2026-09-01 00:00:00.000000', 'monthly_loss_limit',"
                " '100.00', '200.00', '2026-10')"
            )
        )
    engine.dispose()
    upgrade(url)
    sessions = session_factory(make_engine(url))
    assert _actions(sessions) == [("migration", "BASELINE", "1")]
    assert _verify(sessions) == []
    sessions.kw["bind"].dispose()
    command.downgrade(_alembic_config(url), "0007")  # the events stay…
    upgrade(url)  # …and are not sealed twice
    assert _actions(sessions) == [("migration", "BASELINE", "1")]
    _sql(sessions, "UPDATE settings_history SET effective_from = '2026-09'")
    assert any(p.startswith("settings_change 1: no coincide") for p in _verify(sessions))


# ------------------------------------------------------------------ downgrade (checkpoint A2)
def test_downgrade_of_0007_never_drops_audit_events(tmp_path: Path) -> None:
    """Dropping the log and upgrading again would seal a fresh baseline over tampered data."""
    url = f"sqlite:///{(tmp_path / 'app.db').as_posix()}"
    sessions = session_factory(prepare(url))
    _with_history(sessions)
    _sql(sessions, "UPDATE bets SET stake = 1 WHERE id = 1")  # tampered…
    problems = _verify(sessions)
    assert problems
    sessions.kw["bind"].dispose()
    with pytest.raises(RuntimeError, match="Downgrade de 0007 abortado"):
        command.downgrade(_alembic_config(url), "0006")
    sessions = session_factory(prepare(url))
    assert _verify(sessions) == problems  # …and still reported: nothing was dropped


def test_downgrade_of_an_empty_log_still_works(tmp_path: Path) -> None:
    url = f"sqlite:///{(tmp_path / 'app.db').as_posix()}"
    upgrade(url)
    command.downgrade(_alembic_config(url), "0006")
    engine = make_engine(url)
    assert "audit_log" not in sa.inspect(engine).get_table_names()
    engine.dispose()


def test_a_missing_append_only_trigger_is_reported(sessions: sessionmaker[Session]) -> None:
    _with_history(sessions)
    _sql(sessions, "DROP TRIGGER audit_log_no_delete")
    assert "falta el trigger audit_log_no_delete: audit_log ya no es de solo inserción" in (
        _verify(sessions)
    )
