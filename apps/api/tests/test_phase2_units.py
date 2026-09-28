"""Phase 2 unit tests: bag domain rules, hash chain, provider port, outbox broker."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from app.core.config import Settings
from app.core.ids import uuid7
from app.modules.bags.domain import (
    COMPONENT_SPECS,
    GENESIS_HASH,
    TRANSITIONS,
    BagEventType,
    BagStatus,
    Component,
    event_fields,
    event_hash,
    expiry_for,
    is_bag_public_id,
    new_bag_public_id,
    qr_payload,
)
from app.modules.bags.models import BagEvent
from app.modules.bags.service import _fields, verify_chain
from app.modules.outbox.service import BrokerMessage, EventBroker
from app.persistence.memory import MemoryDatabase, MemoryUnitOfWork
from app.providers.bloodbank import (
    AvailabilityQuery,
    InternalBloodBankProvider,
    MockBloodBankProvider,
    UnknownProviderTargetError,
    availability_band,
    build_bloodbank_providers,
)

NOW = datetime(2026, 9, 28, 9, 0, tzinfo=UTC)


def test_bag_public_ids_are_unique_label_friendly_and_validated() -> None:
    ids = {new_bag_public_id() for _ in range(2000)}
    assert len(ids) == 2000
    assert all(is_bag_public_id(i) and len(i) == 13 for i in ids)
    for bad in ("VYR-0000-000", "ABC-0000-0000", "VYR-OOOO-0000", "VYR-0000-000I", "", "VYR"):
        assert not is_bag_public_id(bad)
    assert qr_payload("VYR-0000-0000") == "veyra:bag:VYR-0000-0000"


def test_expiry_follows_component_shelf_life() -> None:
    assert expiry_for(Component.PLATELETS, NOW) == NOW + timedelta(days=5)
    assert expiry_for(Component.PRBC, NOW) == NOW + timedelta(days=42)
    assert set(COMPONENT_SPECS) == set(Component)


def test_lifecycle_has_no_way_back() -> None:
    assert TRANSITIONS[BagEventType.DISPATCHED] == (
        frozenset({BagStatus.AVAILABLE}),
        BagStatus.IN_TRANSIT,
    )
    for allowed_from, _ in TRANSITIONS.values():
        assert BagStatus.DISCARDED not in allowed_from  # discarded is terminal
    assert BagEventType.COLLECTED not in TRANSITIONS  # only created, never transitioned into


def _event(seq: int, prev: str, **meta: object) -> BagEvent:
    event = BagEvent(
        id=uuid7(),
        bag_id=BAG_ID,
        seq=seq,
        event_type="COLLECTED" if seq == 1 else "DISPATCHED",
        from_facility_id=None,
        to_facility_id=None,
        actor_id=None,
        occurred_at=NOW + timedelta(minutes=seq),
        meta=dict(meta),
        prev_hash=prev,
        row_hash="",
    )
    event.row_hash = event_hash(prev, _fields(event))
    return event


BAG_ID = uuid7()


def test_hash_chain_detects_edits_reordering_and_removal() -> None:
    e1 = _event(1, GENESIS_HASH)
    e2 = _event(2, e1.row_hash, request="RQ-1")
    e3 = _event(3, e2.row_hash)
    assert verify_chain([e1, e2, e3]).valid is True
    assert verify_chain([]).valid is True and verify_chain([]).head_hash is None
    assert verify_chain([e1, e3]).valid is False  # removed
    assert verify_chain([e2, e1, e3]).valid is False  # reordered
    e2.meta = {"request": "RQ-2"}
    assert verify_chain([e1, e2, e3]).valid is False  # edited
    assert event_hash("a", {"x": 1}) != event_hash("b", {"x": 1})


def test_event_hash_is_stable_across_timezone_offsets() -> None:
    """PostgreSQL hands timestamptz back in UTC; the hash must not depend on the offset."""
    from datetime import timezone

    ist = timezone(timedelta(hours=5, minutes=30))
    local = datetime(2026, 9, 28, 14, 30, 0, 123456, tzinfo=ist)
    utc = local.astimezone(UTC)
    common = {
        "bag_id": "b", "seq": 1, "event_type": "COLLECTED", "from_facility_id": None,
        "to_facility_id": None, "actor_id": None, "meta": {},
    }  # fmt: skip
    assert event_fields(occurred_at=local, **common) == event_fields(occurred_at=utc, **common)  # type: ignore[arg-type]


def test_availability_bands_never_reveal_counts() -> None:
    assert availability_band(0, 1) == "none"
    assert availability_band(2, 3) == "limited"
    assert availability_band(3, 3) == "sufficient"


async def test_mock_provider_is_deterministic_and_labelled() -> None:
    uow = MemoryUnitOfWork(MemoryDatabase())
    q = AvailabilityQuery(blood_group="O+", component="PRBC", units=2, now=NOW)
    mock = MockBloodBankProvider()
    first, second = await mock.search(uow, q), await mock.search(uow, q)
    assert first == second and len(first) == 3
    assert all(r.source.simulated and r.source.note for r in first)
    assert (await mock.resolve_target(uow, "MOCK-DGP")).facility_id is None
    with pytest.raises(UnknownProviderTargetError):
        await mock.resolve_target(uow, "MOCK-NOPE")
    ack = await mock.submit(uow, "RQ-X", NOW)
    assert ack.status == "acknowledged" and ack.source.simulated


async def test_internal_provider_rejects_non_bank_targets() -> None:
    uow = MemoryUnitOfWork(MemoryDatabase())
    internal = InternalBloodBankProvider()
    for ref in ("not-a-uuid", str(uuid7())):
        with pytest.raises(UnknownProviderTargetError):
            await internal.resolve_target(uow, ref)
    assert (await internal.submit(uow, "RQ-X", NOW)).source.simulated is False


def test_mock_banks_follow_demo_mode_and_are_refused_in_production() -> None:
    dev = Settings(_env_file=None, env="dev")  # type: ignore[call-arg]
    assert set(build_bloodbank_providers(dev)) == {"internal", "mock"}
    off = Settings(_env_file=None, env="dev", enable_mock_blood_banks=False)  # type: ignore[call-arg]
    assert set(build_bloodbank_providers(off)) == {"internal"}
    with pytest.raises(ValueError, match=r"(?i)mock"):
        Settings(  # type: ignore[call-arg]
            _env_file=None,
            env="production",
            secret_key="x" * 40,
            enable_mock_blood_banks=True,
            verification_provider="sms",
        )


def _msg(cursor: int) -> BrokerMessage:
    return BrokerMessage(cursor=cursor, event_id=str(cursor), topic="t", audience=(), data={})


async def test_broker_fans_out_and_drops_oldest_for_slow_subscribers() -> None:
    broker = EventBroker(queue_size=2)
    fast, slow = broker.subscribe(), broker.subscribe()
    broker.publish(_msg(1))
    assert (await asyncio.wait_for(fast.get(), 1)).cursor == 1
    broker.publish(_msg(2))
    broker.publish(_msg(3))
    assert [slow.get_nowait().cursor for _ in range(2)] == [2, 3]  # 1 was dropped
    broker.unsubscribe(slow)
    broker.publish(_msg(4))
    assert slow.empty() and broker.subscriber_count == 1
