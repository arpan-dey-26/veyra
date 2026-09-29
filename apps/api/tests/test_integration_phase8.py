"""Integration (Phase 8): concurrency, append-only triggers and trace integrity on PostgreSQL.

Races use two independent HTTP sessions for the same user (separate DB connections) fired with
``asyncio.gather`` — no sleeps: row locks and optimistic versions decide the outcome.
"""

from __future__ import annotations

import asyncio
import secrets
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import AsyncClient, Response
from sqlalchemy import text

from app.modules.bags.models import BagEvent
from app.modules.bags.service import verify_chain
from app.modules.outbox.service import BrokerMessage, EventBroker, emit, relay_once
from tests.conftest import csrf
from tests.test_integration_phase1 import _client, live_app
from tests.test_integration_phase2 import _admin, _donor, _facility_staff, _needed_by

pytestmark = pytest.mark.integration
__all__ = ["live_app"]  # re-exported fixture

API = "/api/v1"


class _Setup:
    def __init__(self, app: FastAPI) -> None:
        self.app = app
        self.clients: list[AsyncClient] = []

    async def build(self, *, bags: int, group: str) -> None:
        tag = secrets.token_hex(4)
        self.admin = await _admin(self.app, tag)
        self.bank = await _facility_staff(self.app, self.admin, "BLOOD_BANK", tag)
        self.hospital = await _facility_staff(self.app, self.admin, "HOSPITAL", tag)
        donor, mobile = await _donor(self.app, tag)
        self.clients += [self.admin, self.bank, self.hospital, donor]
        self.bank_id = (await self.bank.get(f"{API}/facilities/me")).json()["id"]
        found = await self.bank.post(
            f"{API}/donors/lookup", json={"mobile": mobile}, headers=csrf(self.bank)
        )
        d = await self.bank.post(
            f"{API}/donations",
            json={"donor_id": found.json()["donor_id"], "blood_group": group, "volume_ml": 450,
                  "components": ["PRBC", "FFP", "PLATELETS"][:bags]},
            headers=csrf(self.bank),
        )  # fmt: skip
        assert d.status_code == 201, d.text
        self.bags = [b["public_id"] for b in d.json()["bags"]]
        self.group = group

    def twin(self, client: AsyncClient) -> AsyncClient:
        """A second, independent session for the same signed-in user."""
        other = _client(self.app)
        other.cookies.update(client.cookies)
        self.clients.append(other)
        return other

    async def request(self, component: str = "PRBC") -> str:
        r = await self.hospital.post(
            f"{API}/requests",
            json={"provider": "internal", "target_ref": self.bank_id, "blood_group": self.group,
                  "component": component, "units": 1, "urgency": "emergency",
                  "needed_by": _needed_by()},
            headers=csrf(self.hospital),
        )  # fmt: skip
        assert r.status_code == 201, r.text
        return str(r.json()["id"])

    async def close(self) -> None:
        for c in self.clients:
            await c.aclose()


@pytest.fixture
async def setup(live_app: FastAPI) -> Any:
    s = _Setup(live_app)
    try:
        yield s
    finally:
        await s.close()


async def _events(app: FastAPI, public_id: str) -> list[BagEvent]:
    async with app.state.uow_factory() as uow:
        bag = await uow.bags.get_by_public_id(public_id)
        assert bag is not None
        return list(await uow.bags.list_events(bag.id))


def _codes(results: list[Response]) -> list[int]:
    return sorted(r.status_code for r in results)


async def test_the_same_request_is_fulfilled_exactly_once(setup: _Setup) -> None:
    await setup.build(bags=1, group="B-")
    rid = await setup.request()
    bank2 = setup.twin(setup.bank)
    results = list(
        await asyncio.gather(
            setup.bank.post(f"{API}/requests/{rid}/fulfil", json={}, headers=csrf(setup.bank)),
            bank2.post(f"{API}/requests/{rid}/fulfil", json={}, headers=csrf(bank2)),
        )
    )
    assert _codes(results) == [200, 409], [r.text for r in results]
    events = await _events(setup.app, setup.bags[0])
    assert [e.event_type for e in events] == ["COLLECTED", "DISPATCHED"]
    assert verify_chain(events).valid


async def test_one_bag_confirmed_for_two_requests_goes_to_exactly_one(setup: _Setup) -> None:
    await setup.build(bags=1, group="A-")
    first, second = await setup.request(), await setup.request()
    bag = setup.bags[0]
    bank2 = setup.twin(setup.bank)
    results = list(
        await asyncio.gather(
            setup.bank.post(
                f"{API}/requests/{first}/fulfil", json={"bag_public_ids": [bag]},
                headers=csrf(setup.bank),
            ),
            bank2.post(
                f"{API}/requests/{second}/fulfil", json={"bag_public_ids": [bag]},
                headers=csrf(bank2),
            ),
        )
    )  # fmt: skip
    assert _codes(results) == [200, 409], [r.text for r in results]
    loser = next(r for r in results if r.status_code == 409)
    assert loser.json()["code"] == "bag_not_eligible"
    shipments = (await setup.hospital.get(f"{API}/shipments")).json()["shipments"]
    assert len(shipments) == 1  # one shipment, for the winner only
    events = await _events(setup.app, bag)
    assert [e.event_type for e in events].count("DISPATCHED") == 1
    assert verify_chain(events).valid


async def _arrived_shipment(setup: _Setup) -> tuple[str, str, str]:
    await setup.build(bags=1, group="O-")
    rid = await setup.request()
    bag = setup.bags[0]
    r = await setup.bank.post(
        f"{API}/requests/{rid}/fulfil", json={"bag_public_ids": [bag]}, headers=csrf(setup.bank)
    )
    assert r.status_code == 200, r.text
    [s] = (await setup.hospital.get(f"{API}/shipments")).json()["shipments"]
    sid = str(s["id"])
    for action in ("advance", "advance", "advance", "advance", "arrive"):
        r = await setup.bank.post(
            f"{API}/simulator/shipments/{sid}/{action}", headers=csrf(setup.bank)
        )
        assert r.status_code == 200, r.text
    detail = (await setup.hospital.get(f"{API}/shipments/{sid}")).json()
    assert detail["status"] == "arrived", detail["status"]
    return sid, rid, bag


async def test_concurrent_receipts_record_exactly_one_receipt(setup: _Setup) -> None:
    sid, rid, bag = await _arrived_shipment(setup)
    hospital2 = setup.twin(setup.hospital)
    # One click on the shipment page and one on the legacy request receipt, at the same time.
    results = list(
        await asyncio.gather(
            setup.hospital.post(f"{API}/shipments/{sid}/receive", headers=csrf(setup.hospital)),
            hospital2.post(f"{API}/requests/{rid}/receive", headers=csrf(hospital2)),
        )
    )
    assert _codes(results) == [200, 409], [r.text for r in results]
    events = await _events(setup.app, bag)
    types = [e.event_type for e in events]
    assert types.count("RECEIVED") == 1 and types.count("SHIPMENT_RECEIVED") == 1
    assert verify_chain(events).valid
    detail = (await setup.hospital.get(f"{API}/shipments/{sid}")).json()
    assert detail["status"] == "received" and detail["request_status"] == "fulfilled"


async def test_concurrent_simulator_actions_keep_a_gapless_timeline(setup: _Setup) -> None:
    await setup.build(bags=1, group="AB+")
    rid = await setup.request()
    bag = setup.bags[0]
    await setup.bank.post(
        f"{API}/requests/{rid}/fulfil", json={"bag_public_ids": [bag]}, headers=csrf(setup.bank)
    )
    [s] = (await setup.hospital.get(f"{API}/shipments")).json()["shipments"]
    sid = s["id"]
    timeline_url = f"{API}/shipments/{sid}/timeline"
    before = len((await setup.hospital.get(timeline_url)).json()["events"])
    bank2 = setup.twin(setup.bank)
    results = list(
        await asyncio.gather(
            *(
                c.post(f"{API}/simulator/shipments/{sid}/advance", headers=csrf(c))
                for c in (setup.bank, bank2, setup.bank, bank2)
            )
        )
    )
    assert all(r.status_code in (200, 409) for r in results), [r.text for r in results]
    ok = sum(r.status_code == 200 for r in results)
    assert ok >= 1
    timeline = (await setup.hospital.get(timeline_url)).json()
    seqs = [e["seq"] for e in timeline["events"]]
    assert seqs == list(range(1, len(seqs) + 1)) and len(seqs) > before  # gapless, unique
    # The serialized outcome equals `ok` sequential advances: none lost, none doubled.
    detail = (await setup.hospital.get(f"{API}/shipments/{sid}")).json()
    expected = [("picked_up", 0), ("in_transit", 1), ("in_transit", 2), ("in_transit", 3)]
    assert (detail["status"], detail["current_checkpoint"]) == expected[ok - 1]
    events = await _events(setup.app, bag)
    assert verify_chain(events).valid
    assert [e.seq for e in events] == list(range(1, len(events) + 1))


class _Counting(EventBroker):
    def __init__(self) -> None:
        super().__init__()
        self.seen: list[str] = []

    def publish(self, message: BrokerMessage) -> None:
        self.seen.append(str(message.event_id))


async def test_concurrent_relays_never_publish_an_event_twice(live_app: FastAPI) -> None:
    factory, clock = live_app.state.uow_factory, live_app.state.clock
    async with factory() as uow:
        for i in range(40):
            await emit(uow, clock, topic="test.phase8", aggregate_type="test",
                       aggregate_id=str(i), audience=[None], payload={"i": i})  # fmt: skip
        await uow.commit()
    a, b = _Counting(), _Counting()
    await asyncio.gather(
        relay_once(factory, a, clock, batch=25), relay_once(factory, b, clock, batch=25)
    )
    assert not set(a.seen) & set(b.seen)
    assert len(a.seen) == len(set(a.seen)) and len(b.seen) == len(set(b.seen))


async def test_every_append_only_trigger_is_installed_and_enabled(live_app: FastAPI) -> None:
    expected = {
        ("audit", "audit_logs", "audit_logs_append_only"),
        ("trace", "bag_events", "bag_events_append_only"),
        ("telemetry", "readings", "readings_append_only"),
        ("network", "shipment_events", "shipment_events_append_only"),
    }
    async with live_app.state.db.engine.connect() as conn:
        rows = await conn.execute(
            text(
                "SELECT n.nspname, c.relname, t.tgname, t.tgenabled FROM pg_trigger t "
                "JOIN pg_class c ON c.oid = t.tgrelid "
                "JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE NOT t.tgisinternal"
            )
        )
        # tgenabled is a "char": asyncpg returns bytes
        found = {
            (r[0], r[1], r[2]): r[3].decode() if isinstance(r[3], bytes) else r[3] for r in rows
        }
    for key in expected:
        assert found.get(key) == "O", (key, found.get(key))  # 'O' = enabled (origin mode)


async def test_every_bag_trace_in_the_database_verifies(live_app: FastAPI) -> None:
    async with live_app.state.db.engine.connect() as conn:
        ids = [r[0] for r in await conn.execute(text("SELECT public_id FROM trace.blood_bags"))]
    if not ids:
        pytest.skip("no bags yet")
    broken = []
    async with live_app.state.uow_factory() as uow:
        for public_id in ids:
            bag = await uow.bags.get_by_public_id(public_id)
            assert bag is not None
            if not verify_chain(list(await uow.bags.list_events(bag.id))).valid:
                broken.append(public_id)
    assert broken == []


async def test_live_engine_hides_bound_parameters(live_app: FastAPI) -> None:
    assert live_app.state.db.engine.sync_engine.hide_parameters is True
