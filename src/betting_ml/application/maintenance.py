"""Maintenance use cases (spec 003, US5–US6): integrity verification, backup and restore."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from betting_ml.domain.audit import AuditRecord, verify_chain, verify_states
from betting_ml.domain.ports import DatabaseFiles, IntegritySource

STATEFUL_ENTITIES = ("bet", "settings")
HASH_LENGTH = 64


@dataclass
class IntegrityReport:
    records: int
    checked: dict[str, int]  # rows compared with their last event, per entity
    problems: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems


def last_events(records: list[AuditRecord], entity: str) -> dict[str, dict[str, Any]]:
    """The signed fields of the latest event of each ``entity`` id."""
    latest: dict[str, dict[str, Any]] = {}
    for record in records:
        if record.entity == entity and record.entity_id is not None:
            latest[record.entity_id] = record.fields()
    return latest


class VerifyIntegrity:
    """``PRAGMA integrity_check`` and ``foreign_key_check``, the audit chain, and every bet and
    the settings equal to their last audited state (else: changed outside the application)."""

    def __init__(self, source: IntegritySource) -> None:
        self.source = source

    def run(self) -> IntegrityReport:
        problems = list(self.source.pragma_problems())
        records: list[AuditRecord] = self.source.records()
        problems += verify_chain(records)
        checked = {}
        for entity in STATEFUL_ENTITIES:
            current = self.source.current_states(entity)
            checked[entity] = len(current)
            problems += verify_states(entity, current, last_events(records, entity))
        return IntegrityReport(records=len(records), checked=checked, problems=problems)


# ---------------------------------------------------------------------- backups (US6)
BACKUP_PREFIX = "app"
PRE_RESTORE_PREFIX = "pre-restore"
SIDECAR = ".sha256"


class BackupError(RuntimeError):
    """The copy failed its own checks: it was removed, the live database is untouched."""


class RestoreError(RuntimeError):
    """The candidate was refused before touching the live database."""


@dataclass(frozen=True)
class BackupResult:
    path: Path
    sha256: str
    removed: list[Path]


@dataclass(frozen=True)
class RestoreResult:
    restored: Path
    previous: Path | None  # copy of the state that was replaced


def sidecar_of(path: Path) -> Path:
    return path.with_name(path.name + SIDECAR)


class BackupDatabase:
    """``data/backups/app-YYYYMMDD-HHMMSS.db`` + ``.sha256`` (``sha256sum`` format), checked
    after writing, keeping the newest ``keep`` copies of each kind."""

    def __init__(
        self,
        files: DatabaseFiles,
        directory: Path,
        keep: int,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        if keep < 1:
            raise ValueError("keep must be ≥ 1")
        self.files = files
        self.directory = directory
        self.keep = keep
        self.clock = clock

    def _target(self, prefix: str) -> Path:
        stamp = self.clock().strftime("%Y%m%d-%H%M%S")
        target = self.directory / f"{prefix}-{stamp}.db"
        n = 1
        while target.exists() or sidecar_of(target).exists():  # two copies in one second
            n += 1
            target = self.directory / f"{prefix}-{stamp}-{n}.db"
        return target

    def run(self, prefix: str = BACKUP_PREFIX, protect: Path | None = None) -> BackupResult:
        """``protect``: a copy the rotation must keep (the one about to be restored)."""
        if not self.files.exists():
            raise BackupError("no hay base de datos que copiar")
        self.directory.mkdir(parents=True, exist_ok=True)
        target = self._target(prefix)
        self.files.copy_to(target)
        problems = self.files.check(target)
        if problems:
            target.unlink(missing_ok=True)
            raise BackupError("la copia no pasó la verificación: " + "; ".join(problems))
        digest = self.files.sha256(target)
        sidecar_of(target).write_text(f"{digest}  {target.name}\n", encoding="utf-8")
        return BackupResult(target, digest, self._rotate(prefix, protect))

    def _rotate(self, prefix: str, protect: Path | None = None) -> list[Path]:
        """Oldest first by (timestamp, collision number) parsed from the name; files that do
        not follow the naming scheme are never touched."""
        pattern = re.compile(rf"{re.escape(prefix)}-(\d{{8}}-\d{{6}})(?:-(\d+))?\.db")
        kept = None if protect is None else protect.resolve()
        aged = []
        for path in self.directory.glob(f"{prefix}-*.db"):
            match = pattern.fullmatch(path.name)
            if match and path.is_file() and path.resolve() != kept:
                aged.append(((match[1], int(match[2] or 1)), path))
        copies = [path for _, path in sorted(aged)]
        old = copies[: -self.keep]
        for path in old:
            path.unlink()
            sidecar_of(path).unlink(missing_ok=True)
        return old


class RestoreDatabase:
    """Replace the live database with a verified copy: its SHA-256 must match its sidecar,
    SQLite's checks and the audit chain must pass, and the current state is copied first."""

    def __init__(self, files: DatabaseFiles, backups: BackupDatabase) -> None:
        self.files = files
        self.backups = backups

    def verify(self, candidate: Path) -> list[str]:
        sidecar = sidecar_of(candidate)
        if not candidate.is_file():
            return [f"{candidate.name}: no existe"]
        if not sidecar.is_file():
            return [f"{candidate.name}: falta {sidecar.name} (sin hash no se restaura)"]
        expected = (sidecar.read_text(encoding="utf-8").split() or [""])[0].lower()
        if len(expected) != HASH_LENGTH or not all(c in "0123456789abcdef" for c in expected):
            return [f"{sidecar.name}: no contiene un SHA-256"]
        if self.files.sha256(candidate) != expected:
            return [f"{candidate.name}: el SHA-256 no coincide con {sidecar.name}"]
        problems = self.files.check(candidate)
        if not problems and self.files.has_audit(candidate):
            problems += VerifyIntegrity(self.files.integrity_source(candidate)).run().problems
        return problems

    def run(self, candidate: Path) -> RestoreResult:
        problems = self.verify(candidate)
        if problems:
            raise RestoreError("copia rechazada: " + "; ".join(problems))
        previous = (
            self.backups.run(PRE_RESTORE_PREFIX, protect=candidate).path
            if self.files.exists()
            else None
        )
        self.files.restore_from(candidate)
        return RestoreResult(candidate, previous)
