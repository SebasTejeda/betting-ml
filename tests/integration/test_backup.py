"""Spec 003, T016: hot SQLite backups with their SHA-256, retention, and a restore that refuses
any copy whose hash, SQLite checks or audit chain do not pass (and copies the live state first)."""

from __future__ import annotations

import hashlib
import random
import re
import sqlite3
import threading
from collections.abc import Callable, Iterator
from contextlib import closing
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from itertools import count
from pathlib import Path

import pytest
from sqlalchemy.orm import Session, sessionmaker
from typer.testing import CliRunner

from betting_ml.adapters.sql.audit import SqlAuditLog, SqlIntegrity
from betting_ml.adapters.sql.backup import SqliteBackups, database_path
from betting_ml.adapters.sql.db import prepare, session_factory
from betting_ml.adapters.sql.repositories import SqlBetRepository, SqlSettingsRepository
from betting_ml.application.maintenance import (
    PRE_RESTORE_PREFIX,
    BackupDatabase,
    BackupError,
    RestoreDatabase,
    RestoreError,
    VerifyIntegrity,
    sidecar_of,
)
from betting_ml.cli import app
from betting_ml.config import Settings
from betting_ml.domain.entities import Outcome
from betting_ml.domain.journal import Bet, BetKind

NOW = datetime(2026, 10, 22, 12, tzinfo=UTC)


def _bet(n: int = 0) -> Bet:
    return Bet(
        f"E0-2026-10-10-arsenal-chelsea-{n}",
        "E0",
        Outcome.AWAY,
        "betsson",
        Decimal("4.40"),
        Decimal("10.00"),
        BetKind.PAPER,
        datetime(2026, 10, 9, tzinfo=UTC),
        kickoff_utc=datetime(2026, 10, 10, 14, tzinfo=UTC),
    )


def _ticking() -> Callable[[], datetime]:
    """One second later on every call: each copy gets its own name."""
    seconds = count()
    return lambda: NOW + timedelta(seconds=next(seconds))


@pytest.fixture
def live(tmp_path: Path) -> Path:
    return tmp_path / "app.db"


@pytest.fixture
def sessions(live: Path) -> Iterator[sessionmaker[Session]]:
    engine = prepare(f"sqlite:///{live.as_posix()}")
    yield session_factory(engine)
    engine.dispose()


def _history(sessions: sessionmaker[Session], bets: int = 3) -> None:
    repository = SqlBetRepository(sessions)
    for n in range(bets):
        bet = repository.add(_bet(n))
        repository.update(replace(bet, note="x"))
    settings = SqlSettingsRepository(sessions)
    settings.save(replace(settings.get(), min_edge=0.03))


def _backups(
    live: Path, keep: int = 14, clock: Callable[[], datetime] | None = None
) -> BackupDatabase:
    return BackupDatabase(SqliteBackups(live), live.parent / "backups", keep, clock or _ticking())


def _restore(live: Path, keep: int = 14) -> RestoreDatabase:
    backups = _backups(live, keep)
    return RestoreDatabase(backups.files, backups)


def _bet_count(path: Path) -> int:
    with closing(sqlite3.connect(path)) as connection:
        return int(connection.execute("SELECT count(*) FROM bets").fetchone()[0])


def _reseal(path: Path) -> None:
    """Forge a sidecar that matches whatever the file now holds."""
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    sidecar_of(path).write_text(f"{digest}  {path.name}\n", encoding="utf-8")


def _pre_restore_copies(live: Path) -> list[Path]:
    return sorted((live.parent / "backups").glob(f"{PRE_RESTORE_PREFIX}-*.db"))


# ------------------------------------------------------------------ backup
def test_a_backup_is_one_checked_file_with_its_sha256(
    live: Path, sessions: sessionmaker[Session]
) -> None:
    _history(sessions)
    result = _backups(live).run()
    assert result.path.name == "app-20261022-120000.db" and result.removed == []
    assert result.sha256 == hashlib.sha256(result.path.read_bytes()).hexdigest()
    assert sidecar_of(result.path).read_text(encoding="utf-8") == (
        f"{result.sha256}  {result.path.name}\n"  # the format of ``sha256sum -c``
    )
    # Self-contained: rollback journal, nothing left in a -wal beside it.
    assert sorted(p.name for p in result.path.parent.iterdir()) == [
        result.path.name,
        sidecar_of(result.path).name,
    ]
    with closing(sqlite3.connect(result.path)) as connection:
        assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "delete"
    assert _bet_count(result.path) == 3
    assert _restore(live).verify(result.path) == []


def test_a_hot_backup_taken_while_the_api_writes_is_consistent(
    live: Path, sessions: sessionmaker[Session]
) -> None:
    """Every copy taken in the middle of a stream of writes passes SQLite's checks and the
    audit verification: no half-written bet, no bet without its event."""
    _history(sessions, bets=1)
    stop = threading.Event()
    errors: list[BaseException] = []

    def writer() -> None:
        repository = SqlBetRepository(sessions)
        n = 100
        try:
            while not stop.is_set():
                bet = repository.add(_bet(n))
                repository.update(replace(bet, note=f"n{n}"))
                n += 1
        except BaseException as exc:  # surfaced below, in the test thread
            errors.append(exc)

    thread = threading.Thread(target=writer)
    thread.start()
    backups, restore = _backups(live), _restore(live)
    try:
        copies = [backups.run() for _ in range(6)]
    finally:
        stop.set()
        thread.join(timeout=60)
    assert not errors, errors[0]
    for copy in copies:
        assert restore.verify(copy.path) == [], copy.path.name
    counts = [_bet_count(copy.path) for copy in copies]
    assert counts == sorted(counts) and counts[-1] > counts[0]  # they did run during writes


def test_retention_keeps_the_newest_copies_of_each_kind(
    live: Path, sessions: sessionmaker[Session]
) -> None:
    _history(sessions, bets=1)
    backups = _backups(live, keep=3)
    stray = backups.directory / "app-manual-copy.db"  # not named by the scheme: never touched
    backups.directory.mkdir()
    stray.write_bytes(b"x")
    results = [backups.run() for _ in range(5)]
    assert [r.removed for r in results] == [[], [], [], [results[0].path], [results[1].path]]
    kept = sorted(backups.directory.glob("app-2*.db"))
    assert kept == [r.path for r in results[2:]]
    assert not sidecar_of(results[0].path).exists() and stray.exists()
    pre = backups.run(PRE_RESTORE_PREFIX)  # another kind: rotated on its own
    assert pre.removed == [] and sorted(backups.directory.glob("app-2*.db")) == kept


def test_copies_in_the_same_second_rotate_in_order(
    live: Path, sessions: sessionmaker[Session]
) -> None:
    _history(sessions, bets=1)
    backups = _backups(live, keep=2, clock=lambda: NOW)
    names = [backups.run().path.name for _ in range(3)]
    assert names == [
        "app-20261022-120000.db",
        "app-20261022-120000-2.db",
        "app-20261022-120000-3.db",
    ]
    assert sorted(p.name for p in backups.directory.glob("*.db")) == sorted(names[1:])


def test_a_copy_that_fails_its_checks_is_removed(
    live: Path, sessions: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    _history(sessions, bets=1)
    backups = _backups(live)
    monkeypatch.setattr(backups.files, "check", lambda path: ["integrity_check: broken"])
    with pytest.raises(BackupError, match="no pasó la verificación"):
        backups.run()
    assert list(backups.directory.iterdir()) == []


def test_nothing_to_back_up(tmp_path: Path) -> None:
    with pytest.raises(BackupError, match="no hay base"):
        _backups(tmp_path / "missing.db").run()
    with pytest.raises(ValueError, match="solo para una base SQLite en archivo"):
        database_path("sqlite://")


# ------------------------------------------------------------------ restore
def test_restore_brings_back_the_copy_and_keeps_the_replaced_state(
    live: Path, sessions: sessionmaker[Session]
) -> None:
    _history(sessions)
    copy = _backups(live).run().path
    SqlBetRepository(sessions).add(_bet(99))  # made after the copy
    assert _bet_count(live) == 4

    result = _restore(live).run(copy)

    assert result.restored == copy and result.previous is not None
    assert result.previous.name.startswith(f"{PRE_RESTORE_PREFIX}-")
    assert _bet_count(live) == 3 and _bet_count(result.previous) == 4
    assert VerifyIntegrity(SqlIntegrity(sessions)).run().problems == []
    assert _restore(live).verify(result.previous) == []  # the way back is verified too
    with closing(sqlite3.connect(live)) as connection:
        assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    SqlBetRepository(sessions).add(_bet(100))  # the API keeps working on the restored data
    assert VerifyIntegrity(SqlIntegrity(sessions)).run().problems == []


def _tamper_sidecar(copy: Path) -> None:
    sidecar_of(copy).write_text(f"{'0' * 64}  {copy.name}\n", encoding="utf-8")


def _flip_a_byte(copy: Path) -> None:
    data = bytearray(copy.read_bytes())
    data[len(data) // 2] ^= 0xFF
    copy.write_bytes(bytes(data))


def _not_a_hash(copy: Path) -> None:
    sidecar_of(copy).write_text("ok\n", encoding="utf-8")


def _no_sidecar(copy: Path) -> None:
    sidecar_of(copy).unlink()


def _no_file(copy: Path) -> None:
    copy.unlink()


def _garbage(copy: Path) -> None:
    copy.write_bytes(random.Random(1).randbytes(64 * 1024))
    _reseal(copy)


def _corrupt_pages(copy: Path) -> None:
    """Keep the header page, destroy every other page: a hash that matches is not enough."""
    data = copy.read_bytes()
    copy.write_bytes(data[:4096] + random.Random(2).randbytes(len(data) - 4096))
    _reseal(copy)


def _not_ours(copy: Path) -> None:
    copy.unlink()
    with closing(sqlite3.connect(copy)) as connection:
        connection.execute("CREATE TABLE notes (x)")
        connection.commit()
    _reseal(copy)


def _bet_edited_outside(copy: Path) -> None:
    """A valid SQLite file with a forged hash: only the audit chain gives it away."""
    with closing(sqlite3.connect(copy)) as connection:
        connection.execute("UPDATE bets SET stake = '1000.00' WHERE id = 1")
        connection.commit()
    _reseal(copy)


def _without_audit(copy: Path) -> None:
    """Edited, its log dropped and stamped back before spec 003: nothing left to check it
    against, so it is refused unless the owner asks for a legacy restore."""
    with closing(sqlite3.connect(copy)) as connection:
        connection.execute("UPDATE bets SET stake = '1000.00' WHERE id = 1")
        connection.execute("DROP TABLE audit_log")
        connection.execute("UPDATE alembic_version SET version_num = '0006'")
        connection.commit()
    _reseal(copy)


@pytest.mark.parametrize(
    ("tamper", "reason"),
    [
        (_tamper_sidecar, "el SHA-256 no coincide"),
        (_flip_a_byte, "el SHA-256 no coincide"),
        (_not_a_hash, "no contiene un SHA-256"),
        (_no_sidecar, "falta app-20261022-120000.db.sha256"),
        (_no_file, "no existe"),
        (_garbage, "no es una base SQLite válida"),
        (_corrupt_pages, "integrity_check|no es una base SQLite válida"),
        (_not_ours, "no es una base de betting-ml"),
        (_bet_edited_outside, "bet 1: no coincide con su último evento"),
        (_without_audit, "no tiene auditoría"),
    ],
)
def test_restore_refuses_a_bad_copy_and_leaves_everything_as_it_was(
    live: Path,
    sessions: sessionmaker[Session],
    tamper: Callable[[Path], None],
    reason: str,
) -> None:
    _history(sessions)
    copy = _backups(live).run().path
    SqlBetRepository(sessions).add(_bet(99))
    tamper(copy)
    restore = _restore(live)

    problems = restore.verify(copy)
    assert problems and any(re.search(reason, p) for p in problems), problems
    with pytest.raises(RestoreError, match="copia rechazada"):
        restore.run(copy)

    assert _bet_count(live) == 4  # untouched
    assert _pre_restore_copies(live) == []  # nothing was even copied
    assert VerifyIntegrity(SqlIntegrity(sessions)).run().problems == []


def test_restore_refuses_the_live_database_itself(
    live: Path, sessions: sessionmaker[Session]
) -> None:
    _history(sessions, bets=1)
    _reseal(live)
    problems = _restore(live).verify(live)
    assert any("es la base activa" in p for p in problems), problems


def test_restoring_a_pre_restore_copy_does_not_rotate_it_away(
    live: Path, sessions: sessionmaker[Session]
) -> None:
    """Undoing a restore: with keep=1 the new pre-restore copy would evict the one being
    restored, so the rotation must spare it."""
    _history(sessions, bets=1)
    copy = _backups(live).run().path
    SqlBetRepository(sessions).add(_bet(99))
    first = _restore(live, keep=1).run(copy).previous
    assert first is not None and _bet_count(live) == 1

    second = _restore(live, keep=1).run(first)

    assert first.exists() and _bet_count(live) == 2
    assert second.previous is not None and _bet_count(second.previous) == 1


def test_a_legacy_copy_is_restored_only_when_asked(
    live: Path, sessions: sessionmaker[Session]
) -> None:
    _history(sessions)
    copy = _backups(live).run().path
    _without_audit(copy)
    with pytest.raises(RestoreError, match="--allow-legacy"):
        _restore(live).run(copy)
    assert _restore(live).verify(copy, allow_legacy=True) == []
    _restore(live).run(copy, allow_legacy=True)
    assert _bet_count(live) == 3


def _insert_session(path: Path) -> None:
    with closing(sqlite3.connect(path)) as connection:
        connection.execute(
            "INSERT INTO sessions (token_hash, csrf_token, created_at, last_seen_at, expires_at,"
            " password_fingerprint) VALUES (:h, :c, '2026-10-22 10:00:00', '2026-10-22 10:00:00',"
            " '2026-10-23 10:00:00', :f)",
            {"h": "a" * 64, "c": "b" * 64, "f": "c" * 64},
        )
        connection.commit()


def test_restore_closes_every_session_and_is_audited(
    live: Path, sessions: sessionmaker[Session]
) -> None:
    """A session logged out after the copy was taken would come back to life with it."""
    _history(sessions)
    _insert_session(live)
    copy = _backups(live).run().path
    _restore(live).run(copy, actor="cli")
    with closing(sqlite3.connect(live)) as connection:
        assert connection.execute("SELECT count(*) FROM sessions").fetchone()[0] == 0
    last = SqlAuditLog(sessions).records()[-1]
    assert (last.actor, last.action, last.entity) == ("cli", "DB_RESTORED", "database")
    assert copy.name in last.payload and SqliteBackups.sha256(copy) in last.payload
    assert VerifyIntegrity(SqlIntegrity(sessions)).run().problems == []


def _break(live: Path, sessions: sessionmaker[Session]) -> bytes:
    """Keep the header page, destroy the rest: SQLite reports the live database malformed."""
    sessions.kw["bind"].dispose()  # the API is stopped
    data = live.read_bytes()
    broken = data[:4096] + random.Random(3).randbytes(len(data) - 4096)
    live.write_bytes(broken)
    return broken


def test_a_damaged_live_database_is_restored_only_with_force(
    live: Path, sessions: sessionmaker[Session]
) -> None:
    _history(sessions)
    copy = _backups(live).run().path
    broken = _break(live, sessions)
    restore = _restore(live)

    with pytest.raises(RestoreError, match="--force"):
        restore.run(copy)
    assert live.read_bytes() == broken  # untouched

    result = restore.run(copy, force=True)

    assert result.previous is not None and not result.previous_verified
    assert result.previous.name.startswith("unverified-pre-restore-")
    assert result.previous.read_bytes() == broken  # kept as it was, for forensics
    assert _bet_count(live) == 3
    assert VerifyIntegrity(SqlIntegrity(sessions)).run().problems == []


# ------------------------------------------------------------------ CLI
@pytest.fixture
def cli_settings(live: Path, monkeypatch: pytest.MonkeyPatch) -> Settings:
    config = Settings(
        _env_file=None,
        database_url=f"sqlite:///{live.as_posix()}",
        data_dir=live.parent,
        backup_keep=5,
    )
    monkeypatch.setattr("betting_ml.container.get_settings", lambda: config)
    return config


def test_cli_backup_and_restore(
    live: Path, sessions: sessionmaker[Session], cli_settings: Settings
) -> None:
    _history(sessions)
    made = CliRunner().invoke(app, ["backup"])
    assert made.exit_code == 0, made.output
    copy = next((live.parent / "backups").glob("app-*.db"))
    assert f"Copia: {copy}" in made.output
    assert f"SHA-256: {SqliteBackups.sha256(copy)}" in made.output
    SqlBetRepository(sessions).add(_bet(99))

    declined = CliRunner().invoke(app, ["restore", str(copy)], input="n\n")
    assert declined.exit_code == 1 and "¿Reemplazar la base actual?" in declined.output
    assert _bet_count(live) == 4 and _pre_restore_copies(live) == []

    restored = CliRunner().invoke(app, ["restore", str(copy), "--yes"])
    assert restored.exit_code == 0, restored.output
    assert f"Restaurada: {copy.name}" in restored.output and "Estado anterior" in restored.output
    assert _bet_count(live) == 3 and len(_pre_restore_copies(live)) == 1


def test_cli_restore_refuses_a_tampered_copy(
    live: Path, sessions: sessionmaker[Session], cli_settings: Settings
) -> None:
    _history(sessions)
    assert CliRunner().invoke(app, ["backup"]).exit_code == 0
    copy = next((live.parent / "backups").glob("app-*.db"))
    _bet_edited_outside(copy)
    refused = CliRunner().invoke(app, ["restore", str(copy), "--yes"])
    assert refused.exit_code == 1
    assert "RECHAZADA: bet 1: no coincide" in refused.output
    assert _pre_restore_copies(live) == []


def test_cli_backup_without_a_database_fails(cli_settings: Settings) -> None:
    failed = CliRunner().invoke(app, ["backup"])
    assert failed.exit_code == 1 and "no hay base de datos" in failed.output


def test_cli_restore_over_a_damaged_database(
    live: Path, sessions: sessionmaker[Session], cli_settings: Settings
) -> None:
    _history(sessions)
    assert CliRunner().invoke(app, ["backup"]).exit_code == 0
    copy = next((live.parent / "backups").glob("app-*.db"))
    _break(live, sessions)
    refused = CliRunner().invoke(app, ["restore", str(copy), "--yes"])
    assert refused.exit_code == 1 and "--force" in refused.output
    assert refused.exception is None or isinstance(refused.exception, SystemExit)  # no traceback
    forced = CliRunner().invoke(app, ["restore", str(copy), "--yes", "--force"])
    assert forced.exit_code == 0, forced.output
    assert "en bruto, sin verificar" in forced.output and "Sesiones cerradas" in forced.output
    assert _bet_count(live) == 3
