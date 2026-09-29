"""Phase 7: simulated shipments — state machine, route, ETA, receipt, trace, telemetry, scope."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import AsyncClient

from app.core.config import Settings
from app.modules.logistics import engine as L
from app.modules.operations.engine import Place
from app.modules.outbox.service import relay_once
from app.persistence.memory import MemoryDatabase, memory_uow_factory
from tests import test_phase2_network as phase2
from tests.conftest import MutableClock, csrf
from tests.test_phase2_network import API, Net
from tests.test_phase5_telemetry import sim
from tests.test_phase6_operations import emergency, two_bags

net = phase2.net
NOW = datetime(2026, 9, 28, 9, 0, tzinfo=UTC)
DISCLAIMER = (
    "This is a simulated logistics prototype. Routes, courier status and ETAs are not "
    "real-world navigation or delivery guarantees."
)
BANK = Place("b1", "Central Blood Bank", "Kolkata", "West Bengal")
HOSP = Place("h1", "City Hospital", "Kolkata", "West Bengal")


async def dispatch_shipment(
    net: Net, *, attach_newer: bool = False
) -> tuple[dict[str, Any], str, str]:
    """Emergency request → recommended bag → confirmed dispatch → (shipment, request id, bag)."""
    _, newer = await two_bags(net)
    if attach_newer:
        await sim(net.bank, newer, "attach")
        await sim(net.bank, newer, "tick", {"count": 1})
    req = await emergency(net)
    r = await net.bank.post(
        f"{API}/requests/{req['id']}/fulfil",
        json={"bag_public_ids": [newer]},
        headers=csrf(net.bank),
    )
    assert r.status_code == 200, r.text
    listed = (await net.bank.get(f"{API}/shipments")).json()
    [s] = listed["shipments"]
    return s, str(req["id"]), newer


async def ship(
    client: AsyncClient, sid: object, action: str, body: object = None
) -> dict[str, object]:
    r = await client.post(
        f"{API}/simulator/shipments/{sid}/{action}", json=body, headers=csrf(client)
    )
    assert r.status_code == 200, r.text
    data: dict[str, object] = r.json()
    return data


def status_of(result: dict[str, object]) -> str:
    shipment = result["shipment"]
    assert isinstance(shipment, dict)
    return str(shipment["status"])


# ---------------------------------------------------------------- engine (pure)


def test_state_machine_is_explicit() -> None:
    assert L.can("pickup", "pickup_pending") and not L.can("pickup", "in_transit")
    assert L.can("delay", "in_transit") and L.can("delay", "picked_up")
    assert not L.can("delay", "arrived") and not L.can("arrive", "delayed")
    assert L.can("receive", "arrived") and not L.can("receive", "in_transit")
    assert all(not L.can(a, "received") for a in L.TRANSITIONS)  # received is terminal
    assert L.next_action("created", -1) == "assign"
    assert L.next_action("pickup_pending", -1) == "pickup"
    assert L.next_action("picked_up", 0) == "depart"
    assert L.next_action("in_transit", 1) == "checkpoint"
    assert L.next_action("in_transit", L.LAST_WAYPOINT) is None
    assert L.next_action("delayed", 2) is None


def test_courier_and_route_are_deterministic_schematic_and_labelled() -> None:
    assert L.simulated_courier("req-1", "emergency") == L.simulated_courier("req-1", "emergency")
    c = L.simulated_courier("req-1", "emergency")
    assert c.courier_id.startswith("SIM-CR-") and c.name.startswith("Demo Courier")
    assert "simulated" in c.vehicle_type
    plan = L.plan_route(BANK, HOSP, "emergency", start=NOW)
    assert plan == L.plan_route(BANK, HOSP, "emergency", start=NOW)
    cps = plan.checkpoints
    assert [c["kind"] for c in cps] == [
        "source",
        "collection",
        "transit",
        "destination_area",
        "destination",
    ]
    assert cps[0]["name"] == BANK.name and cps[-1]["name"] == HOSP.name
    assert all("simulated" in c["name"] for c in cps[1:4])
    dist = [c["distance_km"] for c in cps]
    assert dist == sorted(dist) and dist[-1] == pytest.approx(plan.distance_km, abs=0.2)
    times = [datetime.fromisoformat(c["expected_at"]) for c in cps]
    assert times == sorted(times)
    assert times[0] == NOW + timedelta(minutes=plan.handover_minutes)
    assert sum(plan.leg_minutes) == plan.travel_minutes
    assert L.remaining_travel(cps, 0) == plan.travel_minutes and L.remaining_travel(cps, 4) == 0
    shifted = L.reschedule(cps, 1, 18)
    assert shifted[1]["expected_at"] == cps[1]["expected_at"]
    assert datetime.fromisoformat(shifted[2]["expected_at"]) == times[2] + timedelta(minutes=18)
    for cp in cps:
        assert set(cp) == {
            "seq",
            "name",
            "kind",
            "distance_km",
            "expected_at",
            "actual_at",
            "status",
        }


def test_eta_statuses() -> None:
    later = NOW + timedelta(minutes=40)

    def at(status: str, when: datetime) -> L.Eta:
        return L.eta(status=status, eta_at=when, now=NOW, delay_minutes=0, delay_active=False)

    assert at("in_transit", later).status == "on_schedule"
    assert at("in_transit", later).remaining_minutes == 40
    assert at("in_transit", NOW - timedelta(minutes=1)).status == "late"
    d = L.eta(status="delayed", eta_at=later, now=NOW, delay_minutes=18, delay_active=True)
    assert d.status == "delayed" and any("+18 min" in r for r in d.reasons)
    assert at("arrived", NOW).status == "arrived"
    assert at("received", NOW).status == "delivered"


# ---------------------------------------------------------------- API: lifecycle


async def test_confirmed_dispatch_creates_a_shipment_and_fefo_dispatch_does_not(
    net: Net, memdb: MemoryDatabase
) -> None:
    s, rid, bag = await dispatch_shipment(net)
    assert s["status"] == "pickup_pending" and s["request_id"] == rid and s["bag_count"] == 1
    assert s["courier"]["simulated"] is True and s["courier"]["name"].startswith("Demo Courier")
    assert s["eta"]["label"] == "Simulated ETA — prototype" and s["eta"]["status"] == "on_schedule"
    detail = (await net.bank.get(f"{API}/shipments/{s['id']}")).json()
    assert (
        DISCLAIMER in detail["disclaimer"] and detail["label"] == "Simulated logistics — prototype"
    )
    assert [b["public_id"] for b in detail["bags"]] == [bag] and detail["trace_valid"] is True
    assert detail["bags"][0]["status"] == "in_transit" and len(detail["checkpoints"]) == 5
    timeline = (await net.bank.get(f"{API}/shipments/{s['id']}/timeline")).json()
    assert [e["event_type"] for e in timeline["events"]] == ["SHIPMENT_CREATED", "COURIER_ASSIGNED"]
    trace = (await net.bank.get(f"{API}/bags/{bag}")).json()
    assert [e["event_type"] for e in trace["events"]] == [
        "COLLECTED",
        "DISPATCHED",
        "SHIPMENT_CREATED",
    ]
    assert trace["chain"]["valid"] is True
    assert "shipment.created" in [e.topic for e in memdb.outbox]
    assert "shipment.created" in {a.action for a in memdb.audit}
    # The existing plain dispatch (strict FEFO, no bag selection) is unchanged: no shipment.
    await two_bags_second_request(net)
    assert len((await net.bank.get(f"{API}/shipments")).json()["shipments"]) == 1


async def two_bags_second_request(net: Net) -> None:
    r = await net.hospital.post(
        f"{API}/requests", json=phase2.request_body(net.bank_id), headers=csrf(net.hospital)
    )
    ok = await net.bank.post(
        f"{API}/requests/{r.json()['id']}/fulfil", json={}, headers=csrf(net.bank)
    )
    assert ok.status_code == 200, ok.text


async def test_full_lifecycle_with_delay_resume_arrive_and_human_receipt(
    net: Net, memdb: MemoryDatabase, clock: MutableClock
) -> None:
    s, rid, bag = await dispatch_shipment(net)
    sid = s["id"]
    clock.advance(minutes=3)
    r = await ship(net.bank, sid, "advance")
    assert status_of(r) == "picked_up" and r["events"] == ["shipment.picked_up"]
    clock.advance(minutes=2)
    r = await ship(net.bank, sid, "advance")
    assert status_of(r) == "in_transit" and r["events"] == [
        "shipment.in_transit",
        "shipment.checkpoint_reached",
    ]
    before = r["shipment"]["eta"]["eta_at"]  # type: ignore[index]
    r = await ship(net.bank, sid, "delay", {"minutes": 18, "reason": "traffic_simulated"})
    assert status_of(r) == "delayed"
    eta = r["shipment"]["eta"]  # type: ignore[index]
    assert eta["status"] == "delayed" and eta["delay_minutes"] == 18 and eta["delay_active"] is True
    assert datetime.fromisoformat(eta["eta_at"]) == datetime.fromisoformat(before) + timedelta(
        minutes=18
    )
    blocked = await net.bank.post(
        f"{API}/simulator/shipments/{sid}/advance", headers=csrf(net.bank)
    )
    assert blocked.status_code == 409 and "resume" in blocked.json()["detail"]
    early = await net.bank.post(f"{API}/simulator/shipments/{sid}/arrive", headers=csrf(net.bank))
    assert early.status_code == 409 and early.json()["code"] == "invalid_shipment_transition"
    r = await ship(net.bank, sid, "resume")
    assert status_of(r) == "in_transit" and r["shipment"]["eta"]["delay_active"] is False  # type: ignore[index]
    too_soon = await net.bank.post(
        f"{API}/simulator/shipments/{sid}/arrive", headers=csrf(net.bank)
    )
    assert too_soon.status_code == 409 and "checkpoint" in too_soon.json()["detail"]
    for _ in range(2):
        clock.advance(minutes=3)
        await ship(net.bank, sid, "advance")
    final = await net.bank.post(f"{API}/simulator/shipments/{sid}/advance", headers=csrf(net.bank))
    assert final.status_code == 409 and "arrive" in final.json()["detail"]
    not_yet = await net.hospital.post(f"{API}/shipments/{sid}/receive", headers=csrf(net.hospital))
    assert not_yet.status_code == 409 and not_yet.json()["code"] == "shipment_not_arrived"
    clock.advance(minutes=1)
    r = await ship(net.bank, sid, "arrive")
    assert status_of(r) == "arrived" and r["shipment"]["eta"]["status"] == "arrived"  # type: ignore[index]
    # Nothing is received automatically.
    assert (await net.hospital.get(f"{API}/requests/{rid}")).json()["status"] == "dispatched"

    route = (await net.hospital.get(f"{API}/shipments/{sid}/route")).json()
    assert route["label"] == "Prototype logistics route — not a geographic map"
    assert [c["status"] for c in route["checkpoints"]] == ["reached"] * 5
    assert route["checkpoints"][4]["current"] is True
    assert (
        await net.bank.post(f"{API}/shipments/{sid}/receive", headers=csrf(net.bank))
    ).status_code == 403
    got = await net.hospital.post(f"{API}/shipments/{sid}/receive", headers=csrf(net.hospital))
    assert got.status_code == 200, got.text
    detail = got.json()
    assert detail["status"] == "received" and detail["request_status"] == "fulfilled"
    assert detail["bags"][0]["status"] == "received" and detail["trace_valid"] is True
    assert detail["eta"]["status"] == "delivered"
    again = await net.hospital.post(f"{API}/shipments/{sid}/receive", headers=csrf(net.hospital))
    assert again.status_code == 409

    events = [
        e["event_type"]
        for e in (await net.hospital.get(f"{API}/shipments/{sid}/timeline")).json()["events"]
    ]
    assert events == [
        "SHIPMENT_CREATED", "COURIER_ASSIGNED", "SHIPMENT_PICKED_UP", "SHIPMENT_IN_TRANSIT",
        "CHECKPOINT_REACHED", "SHIPMENT_DELAYED", "SHIPMENT_RESUMED", "CHECKPOINT_REACHED",
        "CHECKPOINT_REACHED", "SHIPMENT_ARRIVED", "SHIPMENT_RECEIVED",
    ]  # fmt: skip
    trace = (await net.hospital.get(f"{API}/bags/{bag}")).json()
    assert [e["event_type"] for e in trace["events"]] == [
        "COLLECTED", "DISPATCHED", "SHIPMENT_CREATED", "SHIPMENT_PICKED_UP", "SHIPMENT_IN_TRANSIT",
        "SHIPMENT_DELAYED", "SHIPMENT_ARRIVED", "RECEIVED", "SHIPMENT_RECEIVED",
    ]  # fmt: skip
    assert trace["chain"]["valid"] is True and trace["bag"]["status"] == "received"
    actions = {a.action for a in memdb.audit}
    for a in (
        "shipment.simulated_advance", "shipment.simulated_delay", "shipment.simulated_resume",
        "shipment.simulated_arrive", "shipment.received", "blood_request.fulfilled",
    ):  # fmt: skip
        assert a in actions, a
    delay_audit = next(a for a in memdb.audit if a.action == "shipment.simulated_delay")
    assert delay_audit.meta["minutes"] == 18 and delay_audit.meta["reason"] == "traffic_simulated"
    listed = (await net.bank.get(f"{API}/shipments")).json()
    assert (
        listed["counts"]["completed_today"] == 1 and listed["average_delivery_minutes"] == 12.0
    )  # simulated clock: 3+2+3+3+1


async def test_existing_request_receipt_still_works_and_closes_the_shipment(net: Net) -> None:
    s, rid, bag = await dispatch_shipment(net)
    r = await net.hospital.post(f"{API}/requests/{rid}/receive", headers=csrf(net.hospital))
    assert r.status_code == 200 and r.json()["status"] == "fulfilled"
    detail = (await net.hospital.get(f"{API}/shipments/{s['id']}")).json()
    assert (
        detail["status"] == "received"
        and detail["checkpoints"][4]["status"] == "confirmed_at_receipt"
    )
    timeline = (await net.hospital.get(f"{API}/shipments/{s['id']}/timeline")).json()["events"]
    arrived = next(e for e in timeline if e["event_type"] == "SHIPMENT_ARRIVED")
    assert arrived["meta"]["confirmed_at_receipt"] is True
    trace = (await net.hospital.get(f"{API}/bags/{bag}")).json()
    assert trace["chain"]["valid"] is True and trace["bag"]["status"] == "received"
    closed = await net.bank.post(
        f"{API}/simulator/shipments/{s['id']}/advance", headers=csrf(net.bank)
    )
    assert closed.status_code == 409  # received is terminal


async def test_scope_rbac_csrf_and_validation(net: Net, api_app: FastAPI) -> None:
    s, _, _ = await dispatch_shipment(net)
    sid = s["id"]
    for path in ("", "/route", "/timeline", "/telemetry"):
        assert (await net.hospital.get(f"{API}/shipments/{sid}{path}")).status_code == 200
        assert (await net.hospital2.get(f"{API}/shipments/{sid}{path}")).status_code == 404
        assert (await net.bank2.get(f"{API}/shipments/{sid}{path}")).status_code == 404
        assert (await net.admin.get(f"{API}/shipments/{sid}{path}")).status_code == 200
        assert (await net.donor.get(f"{API}/shipments/{sid}{path}")).status_code == 403
    assert (await net.hospital2.get(f"{API}/shipments")).json()["shipments"] == []
    assert (await net.bank2.get(f"{API}/shipments")).json()["shipments"] == []
    admin = (await net.admin.get(f"{API}/shipments")).json()
    assert admin["scope"] == "network" and len(admin["shipments"]) == 1
    assert (await net.hospital.get(f"{API}/shipments")).json()["scope"] == "destination"
    # Simulator: the dispatching bank only, CSRF-protected.
    adv = f"{API}/simulator/shipments/{sid}/advance"
    assert (await net.hospital.post(adv, headers=csrf(net.hospital))).status_code == 403
    assert (await net.admin.post(adv, headers=csrf(net.admin))).status_code == 403
    assert (await net.bank2.post(adv, headers=csrf(net.bank2))).status_code == 404
    assert (await net.bank.post(adv)).status_code == 403  # no CSRF header
    assert (
        await net.hospital2.post(f"{API}/shipments/{sid}/receive", headers=csrf(net.hospital2))
    ).status_code == 404
    for body in (
        {"minutes": 0},
        {"minutes": 241},
        {"reason": "because"},
        {"minutes": 5, "note": "x"},
    ):
        bad = await net.bank.post(
            f"{API}/simulator/shipments/{sid}/delay", json=body, headers=csrf(net.bank)
        )
        assert bad.status_code == 422, body


async def test_simulator_can_be_disabled_and_is_refused_in_production(
    net: Net, api_app: FastAPI
) -> None:
    s, _, _ = await dispatch_shipment(net)
    settings: Settings = api_app.state.settings
    settings.enable_logistics_simulator = False
    try:
        r = await net.bank.post(
            f"{API}/simulator/shipments/{s['id']}/advance", headers=csrf(net.bank)
        )
        assert r.status_code == 403 and r.json()["code"] == "simulator_disabled"
    finally:
        settings.enable_logistics_simulator = None
    with pytest.raises(ValueError, match="logistics"):
        Settings(  # type: ignore[call-arg]
            _env_file=None, env="production", secret_key="x" * 40,
            verification_provider="sms", enable_logistics_simulator=True,
        )  # fmt: skip


async def test_cold_chain_warning_in_transit_flags_the_shipment_without_acting(
    net: Net, memdb: MemoryDatabase
) -> None:
    s, rid, bag = await dispatch_shipment(net, attach_newer=True)
    sid = s["id"]
    await ship(net.bank, sid, "advance")
    await ship(net.bank, sid, "advance")  # in transit; the bank still holds custody
    await sim(net.bank, bag, "excursion")
    await sim(net.bank, bag, "tick", {"count": 3})
    tele = (await net.hospital.get(f"{API}/shipments/{sid}/telemetry")).json()
    assert tele["in_transit"] is True and tele["cold_chain_alert"] == "critical"
    [b] = tele["bags"]
    assert (
        b["public_id"] == bag
        and b["cold_chain_status"] == "critical"
        and b["excursion_active"] is True
    )
    assert b["latest_temperature_c"] > 8 and b["device_status"] == "paused"
    assert tele["source"]["simulated"] is True
    timeline = [
        e["event_type"]
        for e in (await net.bank.get(f"{API}/shipments/{sid}/timeline")).json()["events"]
    ]
    assert "COLD_CHAIN_WARNING" in timeline and "COLD_CHAIN_CRITICAL" in timeline
    topics = [e.topic for e in memdb.outbox]
    for t in ("temperature.warning", "temperature.critical", "cold_chain.operational_alert",
              "shipment.cold_chain_alert"):  # fmt: skip
        assert t in topics, t
    alert = next(e for e in memdb.outbox if e.topic == "shipment.cold_chain_alert")
    assert set(map(str, alert.audience)) == {net.bank_id, net.hospital_id}
    # Flagged for human review: not discarded, not received.
    detail = (await net.hospital.get(f"{API}/shipments/{sid}")).json()
    assert detail["status"] == "in_transit" and detail["bags"][0]["status"] == "in_transit"
    assert (await net.hospital.get(f"{API}/requests/{rid}")).json()["status"] == "dispatched"
    listed = (await net.bank.get(f"{API}/shipments")).json()
    assert listed["counts"]["cold_chain_alerts"] == 1


async def test_shipment_payloads_carry_no_personal_data(net: Net, memdb: MemoryDatabase) -> None:
    s, _, _ = await dispatch_shipment(net)
    for path in (
        "",
        f"/{s['id']}",
        f"/{s['id']}/route",
        f"/{s['id']}/timeline",
        f"/{s['id']}/telemetry",
    ):
        for client in (net.bank, net.hospital, net.admin):
            text = (await client.get(f"{API}/shipments{path}")).text
            for secret in (
                "Arpan",
                "Rina",
                "9876543210",
                "9812345678",
                "@example.in",
                "donor",
                "patient",
            ):
                assert secret not in text, (path, secret)
    for e in memdb.outbox:
        if e.topic.startswith("shipment."):
            assert "donor" not in str(e.payload).lower() and e.payload["simulated"] is True


# ---------------------------------------------------------------- SSE


async def test_shipment_events_are_scoped_replayable_and_unique(
    net: Net, api_app: FastAPI, memdb: MemoryDatabase, clock: MutableClock
) -> None:
    s, _, _ = await dispatch_shipment(net)
    sid = s["id"]
    for action in ("advance", "advance"):
        await ship(net.bank, sid, action)
    await ship(net.bank, sid, "delay")
    await ship(net.bank, sid, "resume")
    await ship(net.bank, sid, "advance")
    await ship(net.bank, sid, "advance")
    await ship(net.bank, sid, "arrive")
    await net.hospital.post(f"{API}/shipments/{sid}/receive", headers=csrf(net.hospital))
    await relay_once(memory_uow_factory(memdb), api_app.state.broker, clock)

    def events(text: str) -> list[tuple[int, str]]:
        out = []
        for block in text.split("\n\n"):
            fields = dict(
                line.split(": ", 1)
                for line in block.splitlines()
                if ": " in line and not line.startswith(":")
            )
            if "event" in fields:
                out.append((int(fields["id"]), fields["event"]))
        return out

    expected = [
        "shipment.created", "shipment.picked_up", "shipment.in_transit",
        "shipment.checkpoint_reached", "shipment.delayed", "shipment.resumed",
        "shipment.arrived", "shipment.received",
    ]  # fmt: skip
    for client in (net.bank, net.hospital):
        got = events((await client.get(f"{API}/stream", params={"once": "true"})).text)
        names = [n for _, n in got if n.startswith("shipment.")]
        assert [n for n in dict.fromkeys(names)] == expected
        ids = [i for i, _ in got]
        assert ids == sorted(ids) and len(ids) == len(set(ids))
    bank = events((await net.bank.get(f"{API}/stream", params={"once": "true"})).text)
    delayed_id = next(i for i, n in bank if n == "shipment.delayed")
    replay = await net.bank.get(
        f"{API}/stream", params={"once": "true"}, headers={"Last-Event-ID": str(delayed_id)}
    )
    resumed = [n for _, n in events(replay.text)]
    assert "shipment.delayed" not in resumed and "shipment.received" in resumed
    for other in (net.bank2, net.hospital2):
        assert "shipment." not in (await other.get(f"{API}/stream", params={"once": "true"})).text


def test_every_trace_event_type_fits_the_column() -> None:
    """Regression: SHIPMENT_IN_TRANSIT etc. must fit trace.bag_events.event_type."""
    from sqlalchemy import String

    from app.modules.bags.domain import BagEventType
    from app.modules.bags.models import BagEvent

    column_type = BagEvent.__table__.c.event_type.type
    assert isinstance(column_type, String) and column_type.length is not None
    assert all(len(t.value) <= column_type.length for t in BagEventType), column_type.length


async def test_replay_is_not_crowded_out_by_other_facilities_events(
    net: Net, memdb: MemoryDatabase, clock: MutableClock
) -> None:
    """Regression: a long-lived outbox must not hide the caller's events behind others'."""
    from uuid import uuid4

    from app.modules.outbox.models import OutboxEvent
    from app.modules.outbox.router import REPLAY_LIMIT

    for i in range(REPLAY_LIMIT + 50):  # another facility's traffic
        memdb.outbox.append(
            OutboxEvent(
                id=next(memdb.outbox_ids), event_id=uuid4(), topic="inventory.updated",
                aggregate_type="facility", aggregate_id=f"x{i}", audience=["someone-else"],
                payload={}, created_at=clock.now(), published_at=clock.now(), attempts=0,
            )
        )  # fmt: skip
    s, _, _ = await dispatch_shipment(net)
    for after in ("0", "1"):
        text = (
            await net.hospital.get(f"{API}/stream", params={"once": "true", "after": after})
        ).text
        assert "event: shipment.created" in text and str(s["id"]) in text, after
