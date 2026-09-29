"""Phase 3 dashboards: aggregates are correct AND scoped (facility / admin / network graph)."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta, timezone

from app.modules.dashboard.service import day_series, expiry_buckets
from tests import test_phase2_network as phase2
from tests.conftest import MutableClock, csrf
from tests.test_phase2_network import API, Net, donate, lookup, make_request, request_body

# Reuse the Phase 2 network fixture (registered under its own name, "net").
net = phase2.net


async def _flow(net: Net) -> dict[str, object]:
    d1 = (await lookup(net.bank))["donor_id"]
    d2 = (await lookup(net.bank, "9812345678"))["donor_id"]
    await donate(net.bank, d1, components=["PRBC", "FFP"])
    await donate(net.bank, d2, components=["PLATELETS"])
    req = await make_request(net)
    r = await net.bank.post(f"{API}/requests/{req['id']}/fulfil", json={}, headers=csrf(net.bank))
    assert r.status_code == 200
    rec = await net.hospital.post(f"{API}/requests/{req['id']}/receive", headers=csrf(net.hospital))
    assert rec.status_code == 200
    await make_request(net, units=3)  # stays pending
    return req


def _by_status(items: list[dict[str, object]]) -> dict[object, object]:
    return {i["status"]: i["count"] for i in items}


async def test_blood_bank_dashboard_counts_its_own_activity(net: Net) -> None:
    await _flow(net)
    d = (await net.bank.get(f"{API}/dashboard/facility")).json()
    assert d["kind"] == "BLOOD_BANK" and d["requests"]["direction"] == "incoming"
    assert _by_status(d["requests"]["by_status"]) == {
        "pending": 1, "acknowledged": 0, "dispatched": 0, "fulfilled": 1, "rejected": 0,
        "cancelled": 0,
    }  # fmt: skip
    assert d["requests"]["open"] == 1 and d["requests"]["total"] == 2
    assert d["donations"]["applicable"] is True and d["donations"]["today"] == 2
    assert len(d["donations"]["by_day"]) == d["window_days"] == 14
    today = d["movements"][-1]
    assert (today["dispatched"], today["received"]) == (1, 1)
    # Bank still holds FFP + platelets; platelets expire in 5 days.
    assert d["on_hand"] == 2
    buckets = {b["bucket"]: b["count"] for b in d["expiry"]}
    assert buckets["d3_7"] == 1 and buckets["gt_30d"] == 1 and buckets["expired"] == 0
    topics = [a["topic"] for a in d["activity"]]
    assert "request.created" in topics and "inventory.updated" in topics


async def test_hospital_dashboard_is_outgoing_and_has_no_donation_data(net: Net) -> None:
    await _flow(net)
    d = (await net.hospital.get(f"{API}/dashboard/facility")).json()
    assert d["kind"] == "HOSPITAL" and d["requests"]["direction"] == "outgoing"
    assert d["donations"] == {"applicable": False, "today": 0, "window_total": 0, "by_day": []}
    assert d["on_hand"] == 1  # the received PRBC bag
    assert d["movements"][-1]["received"] == 1
    assert all(a["topic"] != "inventory.updated" for a in d["activity"])  # bank-only events


async def test_other_facilities_see_none_of_it(net: Net) -> None:
    await _flow(net)
    for client in (net.bank2, net.hospital2):
        d = (await client.get(f"{API}/dashboard/facility")).json()
        assert d["requests"]["total"] == 0 and d["on_hand"] == 0 and d["activity"] == []
        assert all(m["dispatched"] == 0 and m["received"] == 0 for m in d["movements"])


async def test_dashboards_never_carry_donor_identity(net: Net) -> None:
    await _flow(net)
    for client, path in (
        (net.bank, "/dashboard/facility"),
        (net.hospital, "/dashboard/facility"),
        (net.admin, "/dashboard/admin"),
        (net.hospital, "/network/graph"),
    ):
        text = (await client.get(API + path)).text
        for secret in ("Arpan", "Rina", "9876543210", "3210", "arpan@example.in", "donor_id"):
            assert secret not in text, (path, secret)


async def test_admin_dashboard_counts_and_redacts_audit(net: Net) -> None:
    await _flow(net)
    d = (await net.admin.get(f"{API}/dashboard/admin")).json()
    roles = {u["role"]: u for u in d["users"]}
    assert roles["DONOR"]["active"] == 2 and roles["BLOOD_BANK"]["total"] == 2
    assert d["users_total"] == 7
    assert d["facilities"] == {"blood_banks": 2, "hospitals": 2, "simulated": 0}
    assert _by_status(d["requests_by_status"])["fulfilled"] == 1
    assert _by_status(d["bags_by_status"]) == {
        "available": 2, "in_transit": 0, "received": 1, "discarded": 0,
    }  # fmt: skip
    assert d["donations_by_day"][-1]["count"] == 2
    assert d["audit"]["last_24h"] > 0
    for row in d["audit"]["recent"]:
        assert set(row) == {"action", "resource", "actor_type", "created_at"}  # no ip / meta


async def test_dashboard_rbac(net: Net) -> None:
    assert (await net.donor.get(f"{API}/dashboard/facility")).status_code == 403
    assert (await net.admin.get(f"{API}/dashboard/facility")).status_code == 403
    for c in (net.donor, net.bank, net.hospital):
        assert (await c.get(f"{API}/dashboard/admin")).status_code == 403
    assert (await net.donor.get(f"{API}/network/graph")).status_code == 403


async def test_network_graph_is_scoped_per_role(net: Net) -> None:
    await _flow(net)
    mock = await net.hospital.post(
        f"{API}/requests",
        json=request_body("MOCK-HWH", provider="mock"),
        headers=csrf(net.hospital),
    )
    assert mock.status_code == 201

    h = (await net.hospital.get(f"{API}/network/graph")).json()
    assert "not a geographic map" in h["note"]
    kinds = {(n["kind"], n["is_self"]) for n in h["nodes"]}
    assert ("HOSPITAL", True) in kinds
    hospitals = [n for n in h["nodes"] if n["kind"] == "HOSPITAL"]
    assert [n["id"] for n in hospitals] == [net.hospital_id]  # never other hospitals
    assert sum(1 for n in h["nodes"] if n["kind"] == "BLOOD_BANK" and not n["simulated"]) == 2
    sim = [n for n in h["nodes"] if n["simulated"]]
    assert [n["id"] for n in sim] == ["mock:MOCK-HWH"]
    edge = next(e for e in h["edges"] if e["target"] == net.bank_id)
    assert edge == edge | {"source": net.hospital_id, "requests": 2, "open": 1, "units": 4}

    b = (await net.bank.get(f"{API}/network/graph")).json()
    assert {n["id"] for n in b["nodes"]} == {net.bank_id, net.hospital_id}
    assert [e["source"] for e in b["edges"]] == [net.hospital_id]

    b2 = (await net.bank2.get(f"{API}/network/graph")).json()
    assert len(b2["nodes"]) == 1 and b2["nodes"][0]["is_self"] and b2["edges"] == []

    a = (await net.admin.get(f"{API}/network/graph")).json()
    assert sum(1 for n in a["nodes"] if not n["simulated"]) == 4 and len(a["edges"]) == 2


async def test_request_events_carry_facility_ids_for_live_views(net: Net, memdb: object) -> None:
    await make_request(net)
    events = [e for e in memdb.outbox if e.topic == "request.created"]  # type: ignore[attr-defined]
    assert events[0].payload["hospital_id"] == net.hospital_id
    assert events[0].payload["target_facility_id"] == net.bank_id


def test_day_series_buckets_in_the_configured_offset() -> None:
    ist = timezone(timedelta(minutes=330))
    today = date(2026, 9, 28)
    late_utc = datetime(2026, 9, 27, 19, 0, tzinfo=UTC)  # 00:30 IST on the 28th
    series = day_series([late_utc], days=3, today=today, tz=ist)
    assert [(d.day, d.count) for d in series] == [
        (date(2026, 9, 26), 0), (date(2026, 9, 27), 0), (date(2026, 9, 28), 1),
    ]  # fmt: skip


def test_expiry_buckets_edges(clock: MutableClock) -> None:
    now = clock.now()
    offsets = [timedelta(minutes=-1), timedelta(hours=23), timedelta(days=2)]
    offsets += [timedelta(days=6), timedelta(days=29), timedelta(days=40)]
    exps = [now + o for o in offsets]
    got = {b.bucket: b.count for b in expiry_buckets(exps, now)}
    assert got == {"expired": 1, "lt_1d": 1, "d1_3": 1, "d3_7": 1, "d7_30": 1, "gt_30d": 1}
