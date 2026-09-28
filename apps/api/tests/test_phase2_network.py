"""Phase 2 core blood network, end to end on the in-memory unit of work.

donation → labelled bags → inventory → availability search → request (idempotent)
→ FEFO dispatch → receive → trace chain, plus the scope/visibility boundaries.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Callable
from dataclasses import dataclass

import pytest
from fastapi import FastAPI
from httpx import AsyncClient

from app.modules.bags.domain import is_bag_public_id
from app.modules.outbox.service import BrokerMessage, relay_once
from app.persistence.memory import MemoryDatabase, memory_uow_factory
from tests.conftest import MutableClock, csrf, login, register_and_verify, seed_user

API = "/api/v1"


@dataclass
class Net:
    donor: AsyncClient
    donor2: AsyncClient
    bank: AsyncClient
    bank2: AsyncClient
    hospital: AsyncClient
    hospital2: AsyncClient
    admin: AsyncClient
    bank_id: str
    hospital_id: str

    async def relogin(self) -> None:
        """After moving the test clock by days, sessions have (correctly) expired."""
        for client, email in (
            (self.donor, "arpan@example.in"),
            (self.donor2, "rina@example.in"),
            (self.bank, "bank@x.in"),
            (self.bank2, "bank2@x.in"),
            (self.hospital, "h@x.in"),
            (self.hospital2, "h2@x.in"),
            (self.admin, "a@x.in"),
        ):
            await login(client, email)


@pytest.fixture
async def net(
    api_app: FastAPI, memdb: MemoryDatabase, make_client: Callable[[], AsyncClient]
) -> Net:
    c = {k: make_client() for k in ("donor", "donor2", "bank", "bank2", "h", "h2", "admin")}
    await register_and_verify(c["donor"])
    await register_and_verify(
        c["donor2"], email="rina@example.in", mobile="9812345678", full_name="Rina Sen"
    )
    bank = await seed_user(
        api_app,
        memdb,
        role="BLOOD_BANK",
        email="bank@x.in",
        mobile="+919000000011",
        facility_type="BLOOD_BANK",
    )
    await seed_user(
        api_app,
        memdb,
        role="BLOOD_BANK",
        email="bank2@x.in",
        mobile="+919000000012",
        facility_type="BLOOD_BANK",
    )
    hospital = await seed_user(
        api_app,
        memdb,
        role="HOSPITAL",
        email="h@x.in",
        mobile="+919000000013",
        facility_type="HOSPITAL",
    )
    await seed_user(
        api_app,
        memdb,
        role="HOSPITAL",
        email="h2@x.in",
        mobile="+919000000014",
        facility_type="HOSPITAL",
    )
    await seed_user(api_app, memdb, role="ADMIN", email="a@x.in", mobile="+919000000015")
    for key, email in (
        ("bank", "bank@x.in"),
        ("bank2", "bank2@x.in"),
        ("h", "h@x.in"),
        ("h2", "h2@x.in"),
        ("admin", "a@x.in"),
    ):
        await login(c[key], email)
    assert bank.facility and hospital.facility
    return Net(
        donor=c["donor"], donor2=c["donor2"], bank=c["bank"], bank2=c["bank2"],
        hospital=c["h"], hospital2=c["h2"], admin=c["admin"],
        bank_id=str(bank.facility.id), hospital_id=str(hospital.facility.id),
    )  # fmt: skip


async def lookup(bank: AsyncClient, mobile: str = "9876543210") -> dict[str, object]:
    r = await bank.post(f"{API}/donors/lookup", json={"mobile": mobile}, headers=csrf(bank))
    assert r.status_code == 200, r.text
    data: dict[str, object] = r.json()
    return data


async def donate(
    bank: AsyncClient,
    donor_id: object,
    *,
    group: str = "O+",
    components: list[str] | None = None,
    collected_at: str | None = None,
) -> dict[str, object]:
    body: dict[str, object] = {
        "donor_id": donor_id,
        "blood_group": group,
        "volume_ml": 450,
        "components": components or ["PRBC", "FFP"],
    }
    if collected_at:
        body["collected_at"] = collected_at
    r = await bank.post(f"{API}/donations", json=body, headers=csrf(bank))
    assert r.status_code == 201, r.text
    data: dict[str, object] = r.json()
    return data


def request_body(target: str, units: int = 1, **kw: object) -> dict[str, object]:
    return {
        "provider": "internal",
        "target_ref": target,
        "blood_group": "O+",
        "component": "PRBC",
        "units": units,
        "urgency": "urgent",
        "needed_by": "2026-09-29T09:00:00Z",
        **kw,
    }


async def make_request(net: Net, units: int = 1, key: str | None = None) -> dict[str, object]:
    headers = csrf(net.hospital) | ({"Idempotency-Key": key} if key else {})
    r = await net.hospital.post(
        f"{API}/requests", json=request_body(net.bank_id, units), headers=headers
    )
    assert r.status_code in (200, 201), r.text
    data: dict[str, object] = r.json()
    return data


# ---------------------------------------------------------------- donations


async def test_lookup_exposes_only_desk_fields(net: Net) -> None:
    found = await lookup(net.bank)
    assert set(found) == {
        "donor_id", "full_name", "mobile_masked", "blood_group", "blood_group_status",
        "last_donation_at", "eligible_from", "eligible_now",
    }  # fmt: skip
    assert found["mobile_masked"] == "+91******3210"
    assert found["blood_group_status"] == "self_declared" and found["eligible_now"] is True
    missing = await net.bank.post(
        f"{API}/donors/lookup", json={"mobile": "9000011111"}, headers=csrf(net.bank)
    )
    assert missing.status_code == 404


async def test_record_donation_creates_labelled_bags_with_genesis_trace(net: Net) -> None:
    donor_id = (await lookup(net.bank))["donor_id"]
    donation = await donate(net.bank, donor_id, group="O-")
    bags = donation["bags"]
    assert isinstance(bags, list) and len(bags) == 2
    for bag in bags:
        assert is_bag_public_id(bag["public_id"])
        assert bag["qr_payload"] == f"veyra:bag:{bag['public_id']}"
        assert bag["status"] == "available" and bag["current_facility_id"] == net.bank_id
    ffp = next(b for b in bags if b["component"] == "FFP")
    prbc = next(b for b in bags if b["component"] == "PRBC")
    assert ffp["volume_ml"] == 200 and prbc["volume_ml"] == 250
    assert ffp["expires_at"] > prbc["expires_at"]  # plasma keeps far longer than red cells

    trace = (await net.bank.get(f"{API}/bags/{prbc['public_id']}")).json()
    assert [e["event_type"] for e in trace["events"]] == ["COLLECTED"]
    assert trace["events"][0]["prev_hash"] == "0" * 64
    assert (
        trace["chain"]["valid"] is True
        and "not anchored on a blockchain" in (trace["chain"]["note"])
    )
    # The bank's typing confirms (and corrects) the donor's self-declared group.
    profile = (await net.donor.get(f"{API}/donors/me")).json()
    assert profile["blood_group"] == "O-" and profile["blood_group_status"] == "confirmed"


async def test_minimum_donation_interval_is_enforced(net: Net, clock: MutableClock) -> None:
    donor_id = (await lookup(net.bank))["donor_id"]
    await donate(net.bank, donor_id)
    again = await net.bank.post(
        f"{API}/donations",
        json={"donor_id": donor_id, "blood_group": "O+", "volume_ml": 350},
        headers=csrf(net.bank),
    )
    assert again.status_code == 409 and again.json()["code"] == "donor_not_eligible"
    assert (await lookup(net.bank))["eligible_now"] is False
    clock.advance(days=90)
    await net.relogin()
    await donate(net.bank, donor_id, components=["WHOLE_BLOOD"])


@pytest.mark.parametrize(
    ("body", "status"),
    [
        ({"volume_ml": 500}, 422),
        ({"components": ["WHOLE_BLOOD", "FFP"]}, 422),
        ({"components": ["PRBC", "PRBC"]}, 422),
        ({"blood_group": "O"}, 422),
        ({"collected_at": "2026-09-30T09:00:00Z"}, 422),  # future
        ({"collected_at": "2026-09-20T09:00:00Z"}, 422),  # > 48 h back-dated
        ({"unexpected": True}, 422),
    ],
)
async def test_donation_input_is_validated(net: Net, body: dict[str, object], status: int) -> None:
    donor_id = (await lookup(net.bank))["donor_id"]
    payload = {"donor_id": donor_id, "blood_group": "O+", "volume_ml": 450, **body}
    r = await net.bank.post(f"{API}/donations", json=payload, headers=csrf(net.bank))
    assert r.status_code == status, r.text


# ---------------------------------------------------------------- inventory


async def test_inventory_summary_counts_expiry_and_is_facility_scoped(
    net: Net, clock: MutableClock
) -> None:
    d1 = (await lookup(net.bank))["donor_id"]
    d2 = (await lookup(net.bank, "9812345678"))["donor_id"]
    await donate(net.bank, d1, components=["PRBC", "PLATELETS"])
    await donate(net.bank, d2, components=["PRBC"])
    summary = (await net.bank.get(f"{API}/inventory/summary")).json()
    rows = {(r["blood_group"], r["component"]): r for r in summary["rows"]}
    assert rows[("O+", "PRBC")]["available"] == 2 and summary["total_available"] == 3
    assert "verify against current national" in summary["reference_note"]

    clock.advance(days=3)  # platelets (5 days) now expire within 72 h
    await net.relogin()
    rows = {
        (r["blood_group"], r["component"]): r
        for r in (await net.bank.get(f"{API}/inventory/summary")).json()["rows"]
    }
    assert rows[("O+", "PLATELETS")]["expiring_soon"] == 1
    clock.advance(days=3)  # … and are now expired: no longer counted as available
    await net.relogin()
    rows = {
        (r["blood_group"], r["component"]): r
        for r in (await net.bank.get(f"{API}/inventory/summary")).json()["rows"]
    }
    assert rows[("O+", "PLATELETS")] | {"next_expiry": None} == {
        "blood_group": "O+", "component": "PLATELETS", "available": 0, "expired": 1,
        "expiring_soon": 0, "next_expiry": None,
    }  # fmt: skip

    other = (await net.bank2.get(f"{API}/inventory/summary")).json()
    assert other["total_available"] == 0 and other["rows"] == []
    listing = (await net.bank.get(f"{API}/inventory/bags", params={"component": "PRBC"})).json()
    assert listing["meta"]["total"] == 2
    assert (await net.bank2.get(f"{API}/inventory/bags")).json()["meta"]["total"] == 0


async def test_discard_is_holder_only_and_follows_the_lifecycle(net: Net) -> None:
    donor_id = (await lookup(net.bank))["donor_id"]
    bag = (await donate(net.bank, donor_id, components=["PRBC"]))["bags"][0]  # type: ignore[index]
    path = f"{API}/bags/{bag['public_id']}/discard"
    other = await net.bank2.post(path, json={"reason": "damaged"}, headers=csrf(net.bank2))
    assert other.status_code == 404
    ok = await net.bank.post(path, json={"reason": "damaged"}, headers=csrf(net.bank))
    assert ok.status_code == 200 and ok.json()["status"] == "discarded"
    again = await net.bank.post(path, json={"reason": "damaged"}, headers=csrf(net.bank))
    assert again.status_code == 409 and again.json()["code"] == "invalid_transition"
    trace = (await net.bank.get(f"{API}/bags/{bag['public_id']}")).json()
    assert [e["event_type"] for e in trace["events"]] == ["COLLECTED", "DISCARDED"]
    assert trace["events"][1]["meta"] == {"reason": "damaged"}


# ---------------------------------------------------------------- availability


async def test_availability_is_banded_and_labels_simulated_banks(net: Net) -> None:
    donor_id = (await lookup(net.bank))["donor_id"]
    await donate(net.bank, donor_id, components=["PRBC"])
    r = await net.hospital.get(
        f"{API}/network/availability",
        params={"blood_group": "O+", "component": "PRBC", "units": 2},
    )
    assert r.status_code == 200
    results = r.json()["results"]
    internal = [x for x in results if x["provider"] == "internal"]
    mock = [x for x in results if x["provider"] == "mock"]
    assert {x["target_ref"]: x["band"] for x in internal}[net.bank_id] == "limited"
    assert all(x["source"]["simulated"] is False for x in internal)
    assert len(mock) == 3 and all(x["source"]["simulated"] is True for x in mock)
    assert all("no real blood bank" in x["source"]["note"] for x in mock)
    for item in results:  # never exact stock
        assert set(item) == {"provider", "target_ref", "name", "city", "state", "band", "source"}


# ---------------------------------------------------------------- requests


async def test_full_request_lifecycle_dispatches_fefo_and_extends_the_trace(
    net: Net, clock: MutableClock
) -> None:
    d1 = (await lookup(net.bank))["donor_id"]
    d2 = (await lookup(net.bank, "9812345678"))["donor_id"]
    older = (await donate(net.bank, d1, components=["PRBC"], collected_at="2026-09-27T09:00:00Z"))[
        "bags"
    ][0]  # type: ignore[index]
    newer = (await donate(net.bank, d2, components=["PRBC"]))["bags"][0]  # type: ignore[index]

    req = await make_request(net, units=1, key="req-key-0001")
    assert req["status"] == "pending" and req["target_name"].startswith("Seed Blood_Bank")
    assert str(req["reference"]).startswith("RQ-") and req["source"]["simulated"] is False

    incoming = (await net.bank.get(f"{API}/requests")).json()
    assert [x["id"] for x in incoming["data"]] == [req["id"]]
    assert (await net.bank2.get(f"{API}/requests")).json()["meta"]["total"] == 0
    assert (await net.bank2.get(f"{API}/requests/{req['id']}")).status_code == 404
    assert (await net.hospital2.get(f"{API}/requests/{req['id']}")).status_code == 404
    # Before dispatch the hospital can't see the bank's bags.
    assert (await net.hospital.get(f"{API}/bags/{older['public_id']}")).status_code == 404

    clock.advance(minutes=10)
    r = await net.bank.post(
        f"{API}/requests/{req['id']}/fulfil", json={"note": "On the way"}, headers=csrf(net.bank)
    )
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["status"] == "dispatched" and out["response_note"] == "On the way"
    assert [b["public_id"] for b in out["bags"]] == [older["public_id"]]  # first-expiry-first-out
    twice = await net.bank.post(
        f"{API}/requests/{req['id']}/fulfil", json={}, headers=csrf(net.bank)
    )
    assert twice.status_code == 409 and twice.json()["code"] == "invalid_request_state"

    stock = (await net.bank.get(f"{API}/inventory/summary")).json()
    assert stock["total_available"] == 1
    trace = (await net.hospital.get(f"{API}/bags/{older['public_id']}")).json()
    assert trace["bag"]["status"] == "in_transit"
    assert (await net.hospital.get(f"{API}/bags/{newer['public_id']}")).status_code == 404
    assert (await net.hospital2.get(f"{API}/bags/{older['public_id']}")).status_code == 404

    clock.advance(hours=1)
    await net.relogin()
    rec = await net.hospital.post(f"{API}/requests/{req['id']}/receive", headers=csrf(net.hospital))
    assert rec.status_code == 200 and rec.json()["status"] == "fulfilled"
    trace = (await net.hospital.get(f"{API}/bags/{older['public_id']}")).json()
    assert trace["bag"]["status"] == "received"
    assert trace["bag"]["current_facility_id"] == net.hospital_id
    assert [e["event_type"] for e in trace["events"]] == ["COLLECTED", "DISPATCHED", "RECEIVED"]
    assert trace["chain"] == trace["chain"] | {"valid": True, "length": 3}
    # The bank still sees the bag's history after hand-over; the hospital now holds it.
    assert (await net.bank.get(f"{API}/bags/{older['public_id']}")).status_code == 200
    hospital_stock = (await net.hospital.get(f"{API}/inventory/summary")).json()
    assert hospital_stock["total_available"] == 1
    # Admin (network oversight) can trace any bag.
    assert (await net.admin.get(f"{API}/bags/{newer['public_id']}")).status_code == 200


async def test_idempotency_key_replays_and_rejects_a_different_body(net: Net) -> None:
    first = await make_request(net, key="same-key-123")
    headers = csrf(net.hospital) | {"Idempotency-Key": "same-key-123"}
    replay = await net.hospital.post(
        f"{API}/requests", json=request_body(net.bank_id), headers=headers
    )
    assert replay.status_code == 200 and replay.json()["id"] == first["id"]
    changed = await net.hospital.post(
        f"{API}/requests", json=request_body(net.bank_id, units=3), headers=headers
    )
    assert changed.status_code == 422 and changed.json()["code"] == "idempotency_key_reused"
    assert (await net.hospital.get(f"{API}/requests")).json()["meta"]["total"] == 1
    # Different key → a genuinely new request.
    await make_request(net, key="other-key-456")
    assert (await net.hospital.get(f"{API}/requests")).json()["meta"]["total"] == 2


async def test_insufficient_stock_leaves_the_request_pending(net: Net) -> None:
    donor_id = (await lookup(net.bank))["donor_id"]
    await donate(net.bank, donor_id, components=["PRBC"])
    req = await make_request(net, units=3)
    r = await net.bank.post(f"{API}/requests/{req['id']}/fulfil", json={}, headers=csrf(net.bank))
    assert r.status_code == 409 and r.json()["code"] == "insufficient_stock"
    assert "1 of 3" in r.json()["detail"]
    again = (await net.hospital.get(f"{API}/requests/{req['id']}")).json()
    assert again["status"] == "pending" and again["bags"] == []
    stock = (await net.bank.get(f"{API}/inventory/summary")).json()
    assert stock["total_available"] == 1


async def test_expired_bags_are_never_dispatched(net: Net, clock: MutableClock) -> None:
    donor_id = (await lookup(net.bank))["donor_id"]
    await donate(net.bank, donor_id, components=["PLATELETS"])
    clock.advance(days=6)
    await net.relogin()
    body = request_body(net.bank_id, component="PLATELETS", needed_by="2026-10-05T09:00:00Z")
    r = await net.hospital.post(f"{API}/requests", json=body, headers=csrf(net.hospital))
    assert r.status_code == 201
    f = await net.bank.post(
        f"{API}/requests/{r.json()['id']}/fulfil", json={}, headers=csrf(net.bank)
    )
    assert f.status_code == 409 and f.json()["code"] == "insufficient_stock"


async def test_reject_cancel_and_state_rules(net: Net) -> None:
    a = await make_request(net)
    b = await make_request(net)
    short = await net.bank.post(
        f"{API}/requests/{a['id']}/reject", json={"note": " "}, headers=csrf(net.bank)
    )
    assert short.status_code == 422
    rej = await net.bank.post(
        f"{API}/requests/{a['id']}/reject", json={"note": "No O+ stock"}, headers=csrf(net.bank)
    )
    assert rej.status_code == 200 and rej.json()["status"] == "rejected"
    late = await net.hospital.post(f"{API}/requests/{a['id']}/cancel", headers=csrf(net.hospital))
    assert late.status_code == 409
    not_mine = await net.hospital2.post(
        f"{API}/requests/{b['id']}/cancel", headers=csrf(net.hospital2)
    )
    assert not_mine.status_code == 404
    ok = await net.hospital.post(f"{API}/requests/{b['id']}/cancel", headers=csrf(net.hospital))
    assert ok.status_code == 200 and ok.json()["status"] == "cancelled"
    early = await net.hospital.post(f"{API}/requests/{b['id']}/receive", headers=csrf(net.hospital))
    assert early.status_code == 409


async def test_request_input_rules(net: Net) -> None:
    async def create(body: dict[str, object]) -> int:
        r = await net.hospital.post(f"{API}/requests", json=body, headers=csrf(net.hospital))
        return r.status_code

    assert await create(request_body(net.bank_id, units=0)) == 422
    assert await create(request_body(net.bank_id, units=21)) == 422
    assert await create(request_body(net.hospital_id)) == 422  # a hospital is not a blood bank
    assert await create(request_body("not-a-uuid")) == 422
    assert await create(request_body(net.bank_id, needed_by="2026-09-01T00:00:00Z")) == 409
    bad_key = await net.hospital.post(
        f"{API}/requests",
        json=request_body(net.bank_id),
        headers=csrf(net.hospital) | {"Idempotency-Key": "short"},
    )
    assert bad_key.status_code == 422


async def test_mock_provider_is_simulated_and_never_reaches_a_real_bank(net: Net) -> None:
    r = await net.hospital.post(
        f"{API}/requests",
        json=request_body("MOCK-HWH", provider="mock"),
        headers=csrf(net.hospital),
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["status"] == "acknowledged" and body["target_facility_id"] is None
    assert body["source"]["simulated"] is True and "Simulated" in body["response_note"]
    assert (await net.bank.get(f"{API}/requests")).json()["meta"]["total"] == 0
    unknown = await net.hospital.post(
        f"{API}/requests",
        json=request_body("MOCK-XXX", provider="mock"),
        headers=csrf(net.hospital),
    )
    assert unknown.status_code == 422
    cancel = await net.hospital.post(
        f"{API}/requests/{body['id']}/cancel", headers=csrf(net.hospital)
    )
    assert cancel.json()["status"] == "cancelled"


# ---------------------------------------------------------------- donor view


async def test_donor_history_shows_impact_but_never_the_recipient(net: Net) -> None:
    donor_id = (await lookup(net.bank))["donor_id"]
    await donate(net.bank, donor_id, components=["PRBC", "FFP"])
    req = await make_request(net)
    await net.bank.post(f"{API}/requests/{req['id']}/fulfil", json={}, headers=csrf(net.bank))
    mine = (await net.donor.get(f"{API}/donors/me/donations")).json()
    assert mine["eligible_now"] is False and mine["interval_days"] == 90
    [donation] = mine["donations"]
    assert donation["bags_total"] == 2 and donation["bags_sent_to_hospitals"] == 1
    assert donation["bags_in_stock"] == 1
    text = str(mine)
    assert "Hospital" not in text and net.hospital_id not in text
    other = (await net.donor2.get(f"{API}/donors/me/donations")).json()
    assert other["donations"] == [] and other["eligible_now"] is True


# ---------------------------------------------------------------- trace integrity


async def test_trace_chain_detects_tampering(net: Net, memdb: MemoryDatabase) -> None:
    donor_id = (await lookup(net.bank))["donor_id"]
    bag = (await donate(net.bank, donor_id, components=["PRBC"]))["bags"][0]  # type: ignore[index]
    await net.bank.post(
        f"{API}/bags/{bag['public_id']}/discard", json={"reason": "other"}, headers=csrf(net.bank)
    )
    url = f"{API}/bags/{bag['public_id']}"
    assert (await net.bank.get(url)).json()["chain"]["valid"] is True
    event = next(e for e in memdb.bag_events if e.event_type == "DISCARDED")
    event.meta = {"reason": "expired"}  # simulate an edit that bypassed the DB trigger
    assert (await net.bank.get(url)).json()["chain"]["valid"] is False


async def test_trace_lookup_normalises_case_and_rejects_garbage(net: Net) -> None:
    donor_id = (await lookup(net.bank))["donor_id"]
    bag = (await donate(net.bank, donor_id, components=["PRBC"]))["bags"][0]  # type: ignore[index]
    lower = str(bag["public_id"]).lower()
    assert (await net.bank.get(f"{API}/bags/{lower}")).status_code == 200
    assert (await net.bank.get(f"{API}/bags/'%3B--")).status_code == 422


# ---------------------------------------------------------------- outbox + SSE


def _sse_events(text: str) -> list[dict[str, str]]:
    events = []
    for block in text.split("\n\n"):
        fields = dict(
            line.split(": ", 1) for line in block.splitlines() if line and not line.startswith(":")
        )
        if "event" in fields:
            events.append(fields)
    return events


async def test_outbox_events_are_transactional_and_audience_scoped(
    net: Net, api_app: FastAPI, memdb: MemoryDatabase, clock: MutableClock
) -> None:
    donor_id = (await lookup(net.bank))["donor_id"]
    await donate(net.bank, donor_id, components=["PRBC"])
    req = await make_request(net)
    await net.bank.post(f"{API}/requests/{req['id']}/fulfil", json={}, headers=csrf(net.bank))
    # A failed command writes no event.
    before = len(memdb.outbox)
    fail = await net.bank.post(
        f"{API}/requests/{req['id']}/fulfil", json={}, headers=csrf(net.bank)
    )
    assert fail.status_code == 409 and len(memdb.outbox) == before

    topics = [e.topic for e in memdb.outbox]
    assert topics == [
        "inventory.updated", "request.created", "inventory.updated", "request.dispatched",
    ]  # fmt: skip
    for event in memdb.outbox:  # no donor identity in broadcast payloads
        assert "donor" not in str(event.payload).lower()

    broker = api_app.state.broker
    queue = broker.subscribe()
    published = await relay_once(memory_uow_factory(memdb), broker, clock)
    assert published == 4 and queue.qsize() == 4
    assert all(e.published_at is not None for e in memdb.outbox)
    assert await relay_once(memory_uow_factory(memdb), broker, clock) == 0  # nothing left
    broker.unsubscribe(queue)

    hosp = await net.hospital.get(f"{API}/stream", params={"once": "true"})
    assert hosp.status_code == 200 and hosp.headers["content-type"].startswith("text/event-stream")
    assert [e["event"] for e in _sse_events(hosp.text)] == [
        "request.created", "request.dispatched",
    ]  # fmt: skip
    bank = _sse_events((await net.bank.get(f"{API}/stream", params={"once": "true"})).text)
    assert len(bank) == 4
    assert _sse_events((await net.bank2.get(f"{API}/stream", params={"once": "true"})).text) == []
    # Resume after the first hospital event (Last-Event-ID) → only what was missed.
    first_id = _sse_events(hosp.text)[0]["id"]
    resumed = await net.hospital.get(
        f"{API}/stream", params={"once": "true"}, headers={"Last-Event-ID": first_id}
    )
    assert [e["event"] for e in _sse_events(resumed.text)] == ["request.dispatched"]


async def test_audit_records_phase2_actions_without_health_data(
    net: Net, memdb: MemoryDatabase
) -> None:
    donor_id = (await lookup(net.bank))["donor_id"]
    await donate(net.bank, donor_id, group="A+", components=["PRBC"])
    await make_request(net)
    actions = [a.action for a in memdb.audit]
    for action in ("donor.looked_up", "donation.recorded", "blood_request.created"):
        assert action in actions
    recorded = next(a for a in memdb.audit if a.action == "donation.recorded")
    assert recorded.meta == {"bags": 1, "blood_group_corrected": True}


# ---------------------------------------------------------------- demo seed


async def test_demo_network_seed_is_idempotent_and_staff_can_sign_in(
    api_app: FastAPI, memdb: MemoryDatabase, make_client: Callable[[], AsyncClient]
) -> None:
    from app.persistence.memory import MemoryUnitOfWork
    from app.scripts.seed_demo import DEMO_ADMIN_PASSWORD, ensure_demo_network

    kwargs = {
        "hasher": api_app.state.hasher,
        "clock": api_app.state.clock,
        "password": DEMO_ADMIN_PASSWORD,
    }
    first = await ensure_demo_network(MemoryUnitOfWork(memdb), **kwargs)
    again = await ensure_demo_network(MemoryUnitOfWork(memdb), **kwargs)
    assert [c for _, c in first] == [True, True] and [c for _, c in again] == [False, False]
    assert len(memdb.facilities) == 2 and all("(Demo)" in f.name for f in memdb.facilities.values())
    for email, kind in (("bank@veyra.demo", "BLOOD_BANK"), ("hospital@veyra.demo", "HOSPITAL")):
        c = make_client()
        await login(c, email, DEMO_ADMIN_PASSWORD)
        facility = (await c.get(f"{API}/facilities/me")).json()
        assert facility["type"] == kind


async def test_live_sse_pushes_relayed_events_to_the_right_audience(
    net: Net, api_app: FastAPI, memdb: MemoryDatabase, clock: MutableClock
) -> None:
    """Drives the real streaming endpoint over raw ASGI (httpx buffers whole bodies)."""

    async def open_stream(
        client: AsyncClient,
    ) -> tuple[asyncio.Task[None], list[bytes], asyncio.Event]:
        chunks: list[bytes] = []
        disconnect = asyncio.Event()
        cookie = "; ".join(f"{k}={v}" for k, v in client.cookies.items())
        scope = {
            "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": "GET",
            "scheme": "http", "path": f"{API}/stream", "raw_path": f"{API}/stream".encode(),
            "query_string": b"", "root_path": "", "client": ("127.0.0.1", 1),
            "server": ("api.veyra.test", 80),
            "headers": [(b"host", b"api.veyra.test"), (b"cookie", cookie.encode())],
        }  # fmt: skip
        sent_request = False

        async def receive() -> dict[str, object]:
            nonlocal sent_request
            if not sent_request:
                sent_request = True
                return {"type": "http.request", "body": b"", "more_body": False}
            await disconnect.wait()
            return {"type": "http.disconnect"}

        async def send(message: dict[str, object]) -> None:
            if message["type"] == "http.response.body":
                chunks.append(message.get("body", b""))  # type: ignore[arg-type]

        task = asyncio.create_task(api_app(scope, receive, send))
        return task, chunks, disconnect

    async def wait_for(chunks: list[bytes], needle: bytes) -> bool:
        for _ in range(100):
            if needle in b"".join(chunks):
                return True
            await asyncio.sleep(0.01)
        return False

    h_task, h_chunks, h_stop = await open_stream(net.hospital)
    b2_task, b2_chunks, b2_stop = await open_stream(net.bank2)
    assert await wait_for(h_chunks, b": connected")
    assert await wait_for(b2_chunks, b": connected")

    req = await make_request(net)
    await relay_once(memory_uow_factory(memdb), api_app.state.broker, clock)
    assert await wait_for(h_chunks, b"event: request.created")
    assert str(req["id"]).encode() in b"".join(h_chunks)
    assert b"event:" not in b"".join(b2_chunks)  # another bank never sees it

    for stop in (h_stop, b2_stop):
        stop.set()
    # Wake the generators so they notice the disconnect, then make sure they are gone.
    api_app.state.broker.publish(
        BrokerMessage(cursor=10**9, event_id="x", topic="noop", audience=(), data={})
    )
    for task in (h_task, b2_task):
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
