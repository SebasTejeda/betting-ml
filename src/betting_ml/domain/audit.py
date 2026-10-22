"""Append-only, hash-chained audit log (spec 003, US5). Pure: no database, no clock.

Every record signs its canonical payload together with the hash of the previous record::

    hash_n = SHA-256(hash_{n-1} || payload_n)      hash_0 = SHA-256("betting-ml-audit-genesis")

The payload is canonical JSON (sorted keys, no spaces, Decimal and dates as text), so the same
event always gives the same hash. It carries a format version: the format of stored records
never changes in place, a new format would get a new ``v``.

Scope: the chain detects records altered, removed or inserted in the middle, and (compared
with the current data) journal rows changed outside the application. Whoever holds the database
file can still rewrite the whole chain; off-site backups with their hash cover that case.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any

FORMAT_VERSION = 1
GENESIS_HASH = hashlib.sha256(b"betting-ml-audit-genesis").hexdigest()

# who acted: the owner in the browser, a machine key, the command line, a scheduled task, a
# migration (baseline of the data that existed before the log), an unauthenticated client (a
# failed login) or code without a caller
ACTORS = ("session", "api_key", "cli", "scheduler", "migration", "anonymous", "system")


@dataclass(frozen=True)
class AuditInfo:
    """Who does what, as the use case knows it. The repository adds the entity, the states
    before and after (read in the same transaction) and the chain."""

    actor: str = "system"
    action: str | None = None  # None: the repository's default for the operation
    detail: Mapping[str, Any] | None = None  # extra facts, never secrets

    def __post_init__(self) -> None:
        if self.actor not in ACTORS:
            raise ValueError(f"unknown actor {self.actor!r}")


SYSTEM = AuditInfo()  # a write without a known caller (tests, internal steps): still audited


@dataclass(frozen=True)
class AuditEvent:
    ts_utc: datetime
    actor: str
    action: str
    entity: str
    entity_id: str | None
    before: Mapping[str, Any] | None = None
    after: Mapping[str, Any] | None = None
    detail: Mapping[str, Any] | None = None


@dataclass(frozen=True)
class AuditRecord:
    """A stored record: its columns, the payload that was signed and the chain links."""

    seq: int
    actor: str
    action: str
    entity: str
    entity_id: str | None
    payload: str
    prev_hash: str
    hash: str

    def fields(self) -> dict[str, Any]:
        loaded: dict[str, Any] = json.loads(self.payload)
        return loaded


def _plain(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, bytes):
        return value.hex()
    raise TypeError(f"not serialisable in the audit log: {type(value).__name__}")


def canonical(value: Any) -> str:
    """Canonical JSON: the same data always gives the same text (and NaN is refused)."""
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
        default=_plain,
    )


def payload(seq: int, event: AuditEvent) -> str:
    return canonical(
        {
            "v": FORMAT_VERSION,
            "seq": seq,
            "ts_utc": event.ts_utc,
            "actor": event.actor,
            "action": event.action,
            "entity": event.entity,
            "entity_id": event.entity_id,
            "before": event.before,
            "after": event.after,
            "detail": event.detail,
        }
    )


def chain_hash(prev_hash: str, signed_payload: str) -> str:
    return hashlib.sha256((prev_hash + signed_payload).encode("utf-8")).hexdigest()


def seal(seq: int, prev_hash: str, event: AuditEvent) -> AuditRecord:
    """The record that follows ``prev_hash`` at position ``seq``."""
    text = payload(seq, event)
    return AuditRecord(
        seq=seq,
        actor=event.actor,
        action=event.action,
        entity=event.entity,
        entity_id=event.entity_id,
        payload=text,
        prev_hash=prev_hash,
        hash=chain_hash(prev_hash, text),
    )


def verify_chain(records: Iterable[AuditRecord]) -> list[str]:
    """Problems of the chain in ``seq`` order, each naming the record (empty = intact)."""
    problems: list[str] = []
    expected_seq, prev = 1, GENESIS_HASH
    for record in records:
        if record.seq != expected_seq:
            problems.append(f"seq {expected_seq}: falta (el siguiente es {record.seq})")
        if record.prev_hash != prev:
            problems.append(f"seq {record.seq}: no enlaza con el registro anterior")
        if chain_hash(record.prev_hash, record.payload) != record.hash:
            problems.append(f"seq {record.seq}: el contenido no coincide con su hash (alterado)")
        else:
            fields = record.fields()
            signed = (
                fields.get("seq"),
                fields.get("actor"),
                fields.get("action"),
                fields.get("entity"),
                fields.get("entity_id"),
            )
            columns = (record.seq, record.actor, record.action, record.entity, record.entity_id)
            if signed != columns:
                problems.append(f"seq {record.seq}: las columnas no coinciden con lo firmado")
        expected_seq, prev = record.seq + 1, record.hash
    return problems


def comparable(state: Mapping[str, Any] | None) -> Any:
    """A state as it reads back from a payload (JSON types), for comparisons."""
    return None if state is None else json.loads(canonical(state))


def verify_states(
    entity: str,
    current: Mapping[str, Mapping[str, Any]],
    last_events: Mapping[str, Mapping[str, Any]],
) -> list[str]:
    """Each current row must equal the ``after`` of its last event, and each entity whose
    last event removed it must be gone: anything else was changed outside the application."""
    problems = []
    for key in sorted(set(current) | set(last_events), key=_natural):
        event = last_events.get(key)
        row = current.get(key)
        if event is None:
            problems.append(f"{entity} {key}: existe sin ningún evento en la auditoría")
        elif row is None and event.get("after") is not None:
            problems.append(f"{entity} {key}: falta, pero su último evento no es un borrado")
        elif row is not None and comparable(row) != event.get("after"):
            problems.append(
                f"{entity} {key}: no coincide con su último evento (seq {event.get('seq')})"
            )
    return problems


def _natural(key: str) -> tuple[int, str]:
    return (int(key), "") if key.isdigit() else (0, key)
