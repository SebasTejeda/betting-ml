"""SQLite backup files (spec 003, US6): consistent hot copies with the SQLite backup API.

A copy is a single self-contained file (rollback journal, no ``-wal``/``-shm``), so its
SHA-256 identifies it. Candidates for a restore are opened read-only and immutable: checking
them never writes a byte.
"""

from __future__ import annotations

import hashlib
import sqlite3
from contextlib import closing
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.pool import NullPool

from betting_ml.adapters.sql.audit import SqlIntegrity
from betting_ml.adapters.sql.db import BUSY_TIMEOUT_MS, MEMORY_URL, resolve_url, session_factory

REQUIRED_TABLES = {"alembic_version", "bets", "settings"}
CHUNK = 1 << 20


def database_path(url: str) -> Path:
    """The file behind a ``sqlite:///`` URL (a database in memory cannot be backed up)."""
    resolved = resolve_url(url)
    prefix = "sqlite:///"
    if not resolved.startswith(prefix) or resolved == MEMORY_URL:
        raise ValueError(f"copias solo para una base SQLite en archivo, no {url!r}")
    return Path(resolved[len(prefix) :])


def _read_only(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro&immutable=1", uri=True)


class SqliteBackups:
    def __init__(self, database: Path) -> None:
        self.database = database

    def exists(self) -> bool:
        return self.database.is_file()

    def copy_to(self, target: Path) -> None:
        """Hot copy of the live database: consistent even while the API writes."""
        with (
            closing(sqlite3.connect(self.database, timeout=BUSY_TIMEOUT_MS / 1000)) as source,
            closing(sqlite3.connect(target)) as copy,
        ):
            source.backup(copy)
            copy.execute("PRAGMA journal_mode=DELETE")  # one file: nothing left in a -wal

    def restore_from(self, candidate: Path) -> None:
        """Overwrite the live database page by page inside SQLite's own locking (never a file
        swap under an open connection), then keep it in WAL mode."""
        with (
            closing(_read_only(candidate)) as source,
            closing(sqlite3.connect(self.database, timeout=BUSY_TIMEOUT_MS / 1000)) as live,
        ):
            source.backup(live)
            live.execute("PRAGMA journal_mode=WAL")
            live.execute("PRAGMA wal_checkpoint(TRUNCATE)")

    @staticmethod
    def sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as file:
            while chunk := file.read(CHUNK):
                digest.update(chunk)
        return digest.hexdigest()

    def check(self, path: Path) -> list[str]:
        """SQLite's own checks and the tables of this application; empty if all is well."""
        if not path.is_file():
            return [f"{path.name}: no existe"]
        if self.database.is_file() and path.resolve() == self.database.resolve():
            return [f"{path.name}: es la base activa, no una copia"]
        try:
            with closing(_read_only(path)) as connection:
                problems = [
                    f"integrity_check: {line}"
                    for (line,) in connection.execute("PRAGMA integrity_check")
                    if line != "ok"
                ]
                problems += [
                    f"foreign_key_check: {table} rowid {rowid} -> {parent}"
                    for table, rowid, parent, _ in connection.execute("PRAGMA foreign_key_check")
                ]
                tables = {
                    name
                    for (name,) in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type = 'table'"
                    )
                }
        except sqlite3.DatabaseError as exc:
            return [f"{path.name}: no es una base SQLite válida ({exc})"]
        missing = REQUIRED_TABLES - tables
        if missing:
            problems.append(f"{path.name}: no es una base de betting-ml (faltan {sorted(missing)})")
        return problems

    @staticmethod
    def has_audit(path: Path) -> bool:
        with closing(_read_only(path)) as connection:
            found = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'audit_log'"
            ).fetchone()
            return found is not None

    @staticmethod
    def integrity_source(path: Path) -> SqlIntegrity:
        """The audit chain and rows of a candidate, read-only."""
        engine = create_engine("sqlite://", creator=lambda: _read_only(path), poolclass=NullPool)
        return SqlIntegrity(session_factory(engine))
