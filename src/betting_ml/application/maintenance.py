"""Maintenance use cases (spec 003, US5–US6): integrity verification."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from betting_ml.domain.audit import AuditRecord, verify_chain, verify_states
from betting_ml.domain.ports import IntegritySource

STATEFUL_ENTITIES = ("bet", "settings")


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
