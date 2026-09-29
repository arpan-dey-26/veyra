"""Phase 8: cross-phase regression, audit regressions, security hardening checks.

These tests exercise the platform end to end (donor → receipt → trace) and pin the
invariants that must hold across phases: Phase 2 plain dispatch unchanged, received bags
never dispatchable again, logistics never changing the bag lifecycle, CSRF on every unsafe
endpoint, donor and cross-facility isolation, production simulator guards.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI

from app.core.config import Settings
from app.persistence.memory import MemoryDatabase
from tests import test_phase2_network as phase2
from tests.conftest import MutableClock, csrf
from tests.test_phase2_network import API, Net
from tests.test_phase5_telemetry import sim
from tests.test_phase6_operations import emergency, two_bags
from tests.test_phase7_logistics import dispatch_shipment, ship

net = phase2.net
OPENAPI = Path(__file__).resolve().parents[3] / "packages" / "api-client" / "openapi.json"
_UUID = "0190f5d2-0000-7000-8000-000000000000"
_BAG = "VYR-0000-0000"


def _cp_eta(detail: dict[str, Any]) -> datetime:
    return datetime.fromisoformat(detail["checkpoints"][-1]["expected_at"])


# ---------------------------------------------------------------- Phase 7 audit regressions


async def test_eta_and_checkpoint_schedule_stay_consistent(net: Net, clock: MutableClock) -> None:
    """Audit finding: progress earlier/later than planned left the checkpoint schedule stale,
    so the shipment ETA and the destination checkpoint's expected time disagreed."""
    s, _, _ = await dispatch_shipment(net)
    sid = s["id"]
    for minutes, action, body in (
        (3, "advance", None),  # pickup earlier than the planned handover
        (7, "advance", None),  # depart later than planned
        (1, "delay", {"minutes": 18}),
        (25, "resume", None),  # the delay lasted longer than announced
        (2, "advance", None),
        (4, "advance", None),
    ):
        clock.advance(minutes=minutes)
        await net.relogin()
        out = await ship(net.bank, sid, action, body)
        detail = out["shipment"]
        assert isinstance(detail, dict)
        eta = datetime.fromisoformat(detail["eta"]["eta_at"])
        assert eta == _cp_eta(detail), (action, eta, _cp_eta(detail))
        pending = [c for c in detail["checkpoints"] if c["status"] == "pending"]
        times = [datetime.fromisoformat(c["expected_at"]) for c in pending]
        assert times == sorted(times) and all(t >= clock.now() for t in times), action


async def test_operations_eta_matches_the_live_shipment(net: Net, clock: MutableClock) -> None:
    """Audit finding: Operations recomputed an hourly estimate for dispatched requests, so the
    hospital saw two different ETAs for one delivery."""
    s, rid, _ = await dispatch_shipment(net)
    sid = s["id"]
    await ship(net.bank, sid, "advance")
    await ship(net.bank, sid, "advance")
    await ship(net.bank, sid, "delay", {"minutes": 18})
    clock.advance(minutes=65)  # cross an hour bucket: the estimate must not drift
    await net.relogin()
    shipment = (await net.hospital.get(f"{API}/shipments/{sid}")).json()
    ops = (await net.hospital.get(f"{API}/operations/requests")).json()
    [own] = [r for r in ops["requests"] if r["id"] == rid]
    assert own["route"]["eta_minutes"] == shipment["eta"]["remaining_minutes"]
    assert own["route"]["status"] == "delayed"
    assert own["route"]["distance_km"] == shipment["distance_km"]
    routing = (await net.hospital.get(f"{API}/operations/routing")).json()
    [active] = routing["routes"]
    assert datetime.fromisoformat(active["expected_at"]) == datetime.fromisoformat(
        shipment["eta"]["eta_at"]
    )


async def test_plain_dispatch_route_is_anchored_to_the_dispatch_time(
    net: Net, clock: MutableClock
) -> None:
    r = await net.hospital.post(
        f"{API}/requests", json=phase2.request_body(net.bank_id), headers=csrf(net.hospital)
    )
    await two_bags(net)
    await net.bank.post(f"{API}/requests/{r.json()['id']}/fulfil", json={}, headers=csrf(net.bank))
    first = (await net.hospital.get(f"{API}/operations/routing")).json()["routes"][0]
    for _ in range(6):  # 84 min: crosses the hourly estimate bucket
        clock.advance(minutes=14)  # sessions last 15 min in tests
        await net.relogin()
        again = (await net.hospital.get(f"{API}/operations/routing")).json()["routes"][0]
        assert again["expected_at"] == first["expected_at"]


# ---------------------------------------------------------------- 8.1 end-to-end integrity


async def test_full_journey_is_consistent_across_every_subsystem(
    net: Net, memdb: MemoryDatabase, clock: MutableClock
) -> None:
    """Donor → donation → bag → inventory → emergency request → priority → recommendation →
    confirmed dispatch → shipment → pickup → transit → checkpoint → cold-chain warning →
    delay → resume → arrival → hospital receipt → final trace."""
    donor_me = (await net.donor.get(f"{API}/auth/me")).json()
    assert donor_me["user"]["role"] == "DONOR"
    older, newer = await two_bags(net)
    inv = (await net.bank.get(f"{API}/inventory/summary")).json()
    assert inv["total_available"] == 2
    await sim(net.bank, newer, "attach")
    await sim(net.bank, newer, "tick", {"count": 1})
    await sim(net.bank, older, "attach")
    await sim(net.bank, older, "excursion")
    await sim(net.bank, older, "tick", {"count": 3})  # older = critical → deprioritised
    req = await emergency(net)
    rid = str(req["id"])
    prio = (await net.bank.get(f"{API}/operations/requests/{rid}/priority")).json()
    assert prio["band"] in ("immediate", "high") and prio["reasons"]
    rec = (await net.bank.get(f"{API}/operations/requests/{rid}/recommendations")).json()
    assert rec["recommended_bag_ids"] == [newer] and rec["fefo_default_bag_ids"] == [older]
    assert (await net.hospital.get(f"{API}/requests/{rid}")).json()["status"] == "pending"
    r = await net.bank.post(
        f"{API}/requests/{rid}/fulfil", json={"bag_public_ids": [newer]}, headers=csrf(net.bank)
    )
    assert r.status_code == 200
    [s] = (await net.hospital.get(f"{API}/shipments")).json()["shipments"]
    sid = s["id"]
    for action in ("advance", "advance", "advance"):
        clock.advance(minutes=2)
        await net.relogin()
        await ship(net.bank, sid, action)
    await sim(net.bank, newer, "excursion")
    await sim(net.bank, newer, "tick", {"count": 1})  # warning in transit
    await ship(net.bank, sid, "delay", {"minutes": 18, "reason": "weather_simulated"})
    await ship(net.bank, sid, "resume")
    await sim(net.bank, newer, "recover")
    await sim(net.bank, newer, "tick", {"count": 2})
    await ship(net.bank, sid, "advance")
    await ship(net.bank, sid, "arrive")
    assert (await net.hospital.get(f"{API}/requests/{rid}")).json()["status"] == "dispatched"
    got = await net.hospital.post(f"{API}/shipments/{sid}/receive", headers=csrf(net.hospital))
    assert got.status_code == 200

    # Request, bag, shipment and inventory agree.
    request = (await net.hospital.get(f"{API}/requests/{rid}")).json()
    assert request["status"] == "fulfilled" and [b["public_id"] for b in request["bags"]] == [newer]
    trace = (await net.hospital.get(f"{API}/bags/{newer}")).json()
    assert trace["bag"]["status"] == "received" and trace["chain"]["valid"] is True
    assert trace["bag"]["current_facility_id"] == net.hospital_id
    types = [e["event_type"] for e in trace["events"]]
    assert types[:3] == ["COLLECTED", "DEVICE_ATTACHED", "DISPATCHED"]
    assert types.index("RECEIVED") < types.index("SHIPMENT_RECEIVED") == len(types) - 1
    for t in ("SHIPMENT_CREATED", "SHIPMENT_PICKED_UP", "SHIPMENT_IN_TRANSIT", "TEMP_EXCURSION",
              "SHIPMENT_DELAYED", "TEMP_RECOVERED", "SHIPMENT_ARRIVED"):  # fmt: skip
        assert t in types, t
    detail = (await net.hospital.get(f"{API}/shipments/{sid}")).json()
    assert detail["status"] == "received" and detail["cold_chain_alert"] == "warning"
    assert detail["trace_valid"] is True and detail["request_status"] == "fulfilled"
    inv = (await net.bank.get(f"{API}/inventory/summary")).json()
    assert inv["total_available"] == 1  # the critical bag stays, flagged, never discarded
    old = (await net.bank.get(f"{API}/bags/{older}")).json()
    assert old["bag"]["status"] == "available" and old["chain"]["valid"] is True

    # Audit trail covers each human and simulated action.
    actions = [a.action for a in memdb.audit]
    for a in ("donation.recorded", "blood_request.created", "telemetry.device_attached",
              "blood_request.dispatched", "shipment.created", "shipment.simulated_advance",
              "shipment.simulated_delay", "shipment.simulated_resume", "shipment.simulated_arrive",
              "shipment.received", "blood_request.fulfilled"):  # fmt: skip
        assert a in actions, a
    # Every broadcast goes only to the two facilities involved (admins see all).
    involved = {net.bank_id, net.hospital_id}
    for e in memdb.outbox:
        if e.topic.startswith(("shipment.", "request.", "routing.", "allocation.")):
            assert {str(x) for x in e.audience if x} <= involved, e.topic
        assert "donor" not in json.dumps(e.payload, default=str).lower()


# ---------------------------------------------------------------- 8.2 cross-phase invariants


async def test_plain_fefo_dispatch_creates_no_shipment_even_for_emergencies(
    net: Net, memdb: MemoryDatabase
) -> None:
    older, _ = await two_bags(net)
    req = await emergency(net)
    r = await net.bank.post(f"{API}/requests/{req['id']}/fulfil", json={}, headers=csrf(net.bank))
    assert [b["public_id"] for b in r.json()["bags"]] == [older]
    assert memdb.shipments == {}
    assert not [e for e in memdb.outbox if e.topic.startswith("shipment.")]
    trace = (await net.bank.get(f"{API}/bags/{older}")).json()
    assert [e["event_type"] for e in trace["events"]] == ["COLLECTED", "DISPATCHED"]
    rec = await net.hospital.post(f"{API}/requests/{req['id']}/receive", headers=csrf(net.hospital))
    assert rec.status_code == 200 and rec.json()["status"] == "fulfilled"


async def test_received_bags_are_never_dispatchable_again(net: Net) -> None:
    s, rid, bag = await dispatch_shipment(net)
    await net.hospital.post(f"{API}/requests/{rid}/receive", headers=csrf(net.hospital))
    again = await emergency(net)
    for body in ({"bag_public_ids": [bag]}, {}):
        r = await net.bank.post(
            f"{API}/requests/{again['id']}/fulfil", json=body, headers=csrf(net.bank)
        )
        if body:
            assert r.status_code == 409 and r.json()["code"] == "bag_not_eligible"
        else:  # strict FEFO may take the other (still available) bag, never the received one
            assert r.status_code == 200 and bag not in [b["public_id"] for b in r.json()["bags"]]
    trace = (await net.hospital.get(f"{API}/bags/{bag}")).json()
    assert trace["bag"]["status"] == "received" and trace["chain"]["valid"] is True
    assert (await net.bank.post(
        f"{API}/simulator/shipments/{s['id']}/advance", headers=csrf(net.bank)
    )).status_code == 409  # fmt: skip


async def test_shipment_actions_never_change_the_bag_lifecycle(net: Net) -> None:
    s, _, bag = await dispatch_shipment(net)
    sid = s["id"]
    steps = [("advance", None), ("advance", None), ("delay", {"minutes": 5}), ("resume", None),
             ("advance", None), ("advance", None), ("arrive", None)]  # fmt: skip
    for action, body in steps:
        await ship(net.bank, sid, action, body)
        trace = (await net.bank.get(f"{API}/bags/{bag}")).json()
        assert trace["bag"]["status"] == "in_transit", action
        assert trace["bag"]["current_facility_id"] == net.bank_id, action  # custody until receipt
        assert trace["chain"]["valid"] is True, action


# ---------------------------------------------------------------- 8.3 security hardening

# Unsafe endpoints that intentionally run before a session exists (or create it). They are
# rate-limited/validated elsewhere; every other unsafe endpoint must enforce CSRF.
PRE_SESSION = {
    ("POST", "/api/v1/auth/register"),
    ("POST", "/api/v1/auth/login"),
    ("POST", "/api/v1/auth/verify"),
    ("POST", "/api/v1/auth/verify/start"),
    ("POST", "/api/v1/auth/invites/accept"),
}


def _unsafe_operations() -> list[tuple[str, str]]:
    spec = json.loads(OPENAPI.read_text(encoding="utf-8"))
    ops = []
    for path, methods in spec["paths"].items():
        for method in methods:
            if method in ("post", "put", "patch", "delete"):
                ops.append((method.upper(), path))
    return sorted(ops)


def _concrete(path: str) -> str:
    return (
        path.replace("{public_id}", _BAG)
        .replace("{request_id}", _UUID)
        .replace("{shipment_id}", _UUID)
        .replace("{facility_id}", _UUID)
        .replace("{camp_id}", _UUID)
        .replace("{registration_id}", _UUID)
        .replace("{action}", "publish")
    )


def test_openapi_lists_every_unsafe_route() -> None:
    ops = _unsafe_operations()
    assert len(ops) >= 30 and PRE_SESSION <= set(ops)


async def test_every_unsafe_endpoint_requires_csrf(net: Net) -> None:
    missing = []
    for method, path in _unsafe_operations():
        if (method, path) in PRE_SESSION:
            continue
        for client in (net.bank, net.hospital, net.admin, net.donor):
            r = await client.request(method, _concrete(path), json={})
            if r.status_code != 403 or r.json().get("code") != "csrf_failed":
                missing.append((method, path, r.status_code))
                break
    assert missing == []


async def test_donor_is_denied_every_operational_read(net: Net) -> None:
    spec = json.loads(OPENAPI.read_text(encoding="utf-8"))
    operational = ("/api/v1/operations", "/api/v1/shipments", "/api/v1/telemetry",
                   "/api/v1/forecast", "/api/v1/inventory", "/api/v1/network",
                   "/api/v1/dashboard/facility", "/api/v1/dashboard/admin", "/api/v1/requests",
                   "/api/v1/admin", "/api/v1/bags", "/api/v1/compatibility")  # fmt: skip
    paths = [p for p, ops in spec["paths"].items() if "get" in ops and p.startswith(operational)]
    assert len(paths) >= 20
    leaks = []
    query = f"?blood_group=O%2B&component=PRBC&source_facility_id={_UUID}"
    query += f"&destination_facility_id={_UUID}"
    for p in paths:
        r = await net.donor.get(_concrete(p) + query)  # valid params: the role check decides
        if r.status_code != 403:
            leaks.append((p, r.status_code))
    assert leaks == []


async def test_unrelated_facilities_get_404_for_every_scoped_resource(net: Net) -> None:
    s, rid, bag = await dispatch_shipment(net)
    sid = s["id"]
    for client in (net.bank2, net.hospital2):
        for path in (f"/requests/{rid}", f"/bags/{bag}", f"/bags/{bag}/telemetry",
                     f"/bags/{bag}/cold-chain", f"/shipments/{sid}", f"/shipments/{sid}/route",
                     f"/shipments/{sid}/timeline", f"/shipments/{sid}/telemetry",
                     f"/operations/requests/{rid}/priority",
                     f"/operations/facilities/{net.bank_id}/pressure"):  # fmt: skip
            r = await client.get(API + path)
            assert r.status_code == 404, (path, r.status_code)
            assert "not found" in r.json()["detail"].lower()
    for path in (f"/simulator/shipments/{sid}/advance", f"/simulator/bags/{bag}/tick"):
        r = await net.bank2.post(API + path, json={"count": 1} if "tick" in path else None,
                                 headers=csrf(net.bank2))  # fmt: skip
        assert r.status_code == 404, path


def test_production_disables_every_simulator_by_default() -> None:
    prod = Settings(  # type: ignore[call-arg]
        _env_file=None, env="production", secret_key="x" * 40, verification_provider="sms"
    )  # fmt: skip
    assert prod.telemetry_simulator_enabled is False
    assert prod.logistics_simulator_enabled is False
    assert prod.mock_blood_banks_enabled is False
    assert prod.telemetry_tick_seconds >= 0
    flags = ("enable_telemetry_simulator", "enable_logistics_simulator", "enable_mock_blood_banks")
    for flag in flags:
        with pytest.raises(ValueError):
            Settings(  # type: ignore[call-arg]
                _env_file=None, env="production", secret_key="x" * 40,
                verification_provider="sms", **{flag: True},
            )  # fmt: skip


async def test_production_app_refuses_simulator_actions(api_app: FastAPI, net: Net) -> None:
    """With the production defaults (flags unset → off) the endpoints answer 403."""
    s, _, bag = await dispatch_shipment(net)
    settings: Settings = api_app.state.settings
    settings.enable_logistics_simulator = False
    settings.enable_telemetry_simulator = False
    try:
        h = csrf(net.bank)
        a = await net.bank.post(f"{API}/simulator/shipments/{s['id']}/advance", headers=h)
        b = await net.bank.post(f"{API}/simulator/bags/{bag}/tick", json={"count": 1}, headers=h)
        assert (a.status_code, a.json()["code"]) == (403, "simulator_disabled")
        assert (b.status_code, b.json()["code"]) == (403, "simulator_disabled")
    finally:
        settings.enable_logistics_simulator = None
        settings.enable_telemetry_simulator = None


# ---------------------------------------------------------------- 8.7 observability


def test_database_errors_never_carry_bound_parameters_into_logs() -> None:
    """Audit finding: an unexpected DB error (e.g. the Phase 7 VARCHAR overflow) was logged by
    the unhandled-error handler with SQLAlchemy's ``[parameters: ...]`` block — identity data
    such as an email or mobile could reach the log. The engine now hides bound parameters."""
    pytest.importorskip("asyncpg")
    from sqlalchemy.exc import DBAPIError

    from app.core.db import Database

    db = Database("postgresql+asyncpg://u:p@localhost:1/x")
    assert db.engine.sync_engine.hide_parameters is True
    err = DBAPIError(
        "INSERT INTO identity.users (email) VALUES ($1)",
        ("arpan@example.in",),
        Exception("value too long"),
        hide_parameters=db.engine.sync_engine.hide_parameters,
    )
    assert "arpan@example.in" not in str(err)


def test_log_formatter_redacts_identity_and_secret_fields() -> None:
    import logging

    from app.core.logging import JsonFormatter

    record = logging.LogRecord("veyra", logging.INFO, __file__, 1, "evt", None, None)
    record.extra_fields = {  # type: ignore[attr-defined]
        "password": "p",
        "token": "t",
        "email": "a@b.in",
        "mobile": "9876543210",
        "Authorization": "Bearer x",
        "rid": "ok",
    }
    out = json.loads(JsonFormatter().format(record))
    for key in ("password", "token", "email", "mobile", "Authorization"):
        assert out[key] == "[REDACTED]", key
    assert out["rid"] == "ok"


# ---------------------------------------------------------------- 8.5 concurrency → 409


async def test_a_concurrent_change_surfacing_in_autoflush_is_a_409_not_a_500(
    api_app: FastAPI, make_client: Any
) -> None:
    """Audit finding (PostgreSQL race): two simultaneous receipts of one shipment. The loser's
    optimistic-version conflict surfaced from an *autoflush* inside a later query, bypassing
    the repository's mapping, so the client got 500 instead of 409. Such errors now map to the
    same conflict problem (the unit of work has already rolled back)."""
    from sqlalchemy.exc import IntegrityError
    from sqlalchemy.orm.exc import StaleDataError

    async def stale() -> None:
        raise StaleDataError("UPDATE statement on table 'blood_bags' expected 1 row; 0 matched")

    async def dup() -> None:
        raise IntegrityError("INSERT", {}, Exception("uq_camp_registrations_camp_id_donor_id"))

    api_app.add_api_route("/__test/stale", stale, methods=["GET"])
    api_app.add_api_route("/__test/dup", dup, methods=["GET"])
    client = make_client()
    r = await client.get("/__test/stale")
    assert (r.status_code, r.json()["code"]) == (409, "conflict")
    assert "blood_bags" not in r.text  # no SQL details leak
    d = await client.get("/__test/dup")
    assert (d.status_code, d.json()["code"]) == (409, "already_registered")
