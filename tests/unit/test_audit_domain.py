"""Spec 003, T015: canonical payloads and the SHA-256 chain of the audit log (pure domain)."""

from __future__ import annotations

import hashlib
import random
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from betting_ml.domain.audit import (
    GENESIS_HASH,
    AuditEvent,
    AuditInfo,
    AuditRecord,
    canonical,
    chain_hash,
    payload,
    seal,
    verify_chain,
    verify_states,
)

T0 = datetime(2026, 10, 22, 12, tzinfo=UTC)


def _event(i: int, rng: random.Random | None = None) -> AuditEvent:
    rng = rng or random.Random(i)
    entity = rng.choice(["bet", "settings", "session", "odds_snapshot"])
    state = {"id": i, "stake": rng.choice([10.0, 5.5, 0.01]), "status": rng.choice(["a", "b"])}
    return AuditEvent(
        ts_utc=T0 + timedelta(seconds=i),
        actor=rng.choice(["session", "api_key", "cli", "scheduler"]),
        action=rng.choice(["BET_CREATED", "BET_UPDATED", "SETTINGS_CHANGED"]),
        entity=entity,
        entity_id=str(rng.randint(1, 5)),
        before=None if rng.random() < 0.3 else state,
        after=state,
    )


def _chain(n: int, seed: int) -> list[AuditRecord]:
    rng = random.Random(seed)
    records, prev = [], GENESIS_HASH
    for seq in range(1, n + 1):
        record = seal(seq, prev, _event(seq, rng))
        records.append(record)
        prev = record.hash
    return records


# ------------------------------------------------------------------ canonical form
def test_genesis_is_the_hash_of_the_documented_seed() -> None:
    assert hashlib.sha256(b"betting-ml-audit-genesis").hexdigest() == GENESIS_HASH


def test_canonical_json_is_order_independent_and_compact() -> None:
    a = canonical({"b": 1, "a": {"y": Decimal("10.50"), "x": T0}})
    b = canonical({"a": {"x": T0, "y": Decimal("10.50")}, "b": 1})
    assert a == b == '{"a":{"x":"2026-10-22T12:00:00+00:00","y":"10.50"},"b":1}'


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), object()])
def test_canonical_json_refuses_what_it_cannot_reproduce(bad: object) -> None:
    with pytest.raises((ValueError, TypeError)):
        canonical({"x": bad})


def test_same_event_same_hash_and_any_change_another_hash() -> None:
    event = _event(1)
    assert seal(1, GENESIS_HASH, event) == seal(1, GENESIS_HASH, event)
    base = seal(1, GENESIS_HASH, event).hash
    assert seal(2, GENESIS_HASH, event).hash != base  # the position is signed
    assert seal(1, "0" * 64, event).hash != base  # so is the link
    assert seal(1, GENESIS_HASH, replace(event, actor="migration")).hash != base
    assert seal(1, GENESIS_HASH, replace(event, after={"id": 1})).hash != base
    assert seal(1, GENESIS_HASH, replace(event, detail={"client": "x"})).hash != base


def test_payload_carries_the_format_version_and_every_field() -> None:
    fields = seal(7, GENESIS_HASH, _event(7)).fields()
    assert fields["v"] == 1 and fields["seq"] == 7
    assert set(fields) == {
        "v",
        "seq",
        "ts_utc",
        "actor",
        "action",
        "entity",
        "entity_id",
        "before",
        "after",
        "detail",
    }


def test_actor_must_be_known() -> None:
    assert AuditInfo("scheduler").actor == "scheduler"
    with pytest.raises(ValueError, match="unknown actor"):
        AuditInfo("root")


# ------------------------------------------------------------------ chain (property tests)
SEEDS = range(40)


@pytest.mark.parametrize("seed", SEEDS)
def test_any_untouched_chain_verifies(seed: int) -> None:
    assert verify_chain(_chain(random.Random(seed).randint(1, 30), seed)) == []


@pytest.mark.parametrize("seed", SEEDS)
def test_an_edited_payload_is_reported_with_its_seq(seed: int) -> None:
    rng = random.Random(seed)
    records = _chain(rng.randint(1, 30), seed)
    k = rng.randrange(len(records))
    records[k] = replace(records[k], payload=records[k].payload.replace('"after"', '"afte_"'))
    assert any(p.startswith(f"seq {records[k].seq}:") for p in verify_chain(records))


@pytest.mark.parametrize("seed", SEEDS)
def test_a_resealed_record_breaks_the_link_of_the_next(seed: int) -> None:
    """Rewriting one record with a valid hash of its own still breaks the next link."""
    rng = random.Random(seed)
    records = _chain(rng.randint(2, 30), seed)
    k = rng.randrange(len(records) - 1)
    forged = seal(records[k].seq, records[k].prev_hash, replace(_event(k + 1), actor="cli"))
    if forged.hash == records[k].hash:  # same random event: nothing was changed
        return
    records[k] = forged
    assert f"seq {records[k + 1].seq}: no enlaza con el registro anterior" in verify_chain(records)


@pytest.mark.parametrize("seed", SEEDS)
def test_a_removed_or_reordered_record_is_reported(seed: int) -> None:
    rng = random.Random(seed)
    records = _chain(rng.randint(3, 30), seed)
    k = rng.randrange(1, len(records) - 1)
    removed = records[:k] + records[k + 1 :]
    assert f"seq {k + 1}: falta (el siguiente es {k + 2})" in verify_chain(removed)
    swapped = records[:]
    swapped[k], swapped[k + 1] = swapped[k + 1], swapped[k]
    assert verify_chain(swapped)


@pytest.mark.parametrize("seed", SEEDS)
def test_columns_must_match_what_was_signed(seed: int) -> None:
    rng = random.Random(seed)
    records = _chain(rng.randint(1, 30), seed)
    k = rng.randrange(len(records))
    other = "scheduler" if records[k].actor != "scheduler" else "cli"
    records[k] = replace(records[k], actor=other)
    assert f"seq {records[k].seq}: las columnas no coinciden con lo firmado" in verify_chain(
        records
    )


def test_the_first_record_must_start_from_the_genesis() -> None:
    records = _chain(3, 1)
    first = seal(1, "f" * 64, _event(1, random.Random(1)))
    assert "seq 1: no enlaza con el registro anterior" in verify_chain([first, *records[1:]])


def test_chain_hash_is_sha256_of_link_and_payload() -> None:
    text = payload(1, _event(1))
    expected = hashlib.sha256((GENESIS_HASH + text).encode()).hexdigest()
    assert chain_hash(GENESIS_HASH, text) == expected


# ------------------------------------------------------------------ current states
def _last(after: dict | None, seq: int = 9) -> dict:  # type: ignore[type-arg]
    return {"seq": seq, "after": after}


def test_states_equal_to_their_last_event_pass() -> None:
    state = {"id": 1, "stake": 10.0, "note": None}
    assert verify_states("bet", {"1": state}, {"1": _last(dict(state)), "2": _last(None)}) == []


def test_state_differences_are_reported() -> None:
    problems = verify_states(
        "bet",
        {"1": {"id": 1, "stake": 999.0}, "3": {"id": 3}},
        {"1": _last({"id": 1, "stake": 10.0}, seq=4), "2": _last({"id": 2})},
    )
    assert problems == [
        "bet 1: no coincide con su último evento (seq 4)",
        "bet 2: falta, pero su último evento no es un borrado",
        "bet 3: existe sin ningún evento en la auditoría",
    ]
