"""Phase 5: simulated smart-bag telemetry, cold-chain rules, trace integration, SSE, scope."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI
from httpx import AsyncClient

from app.core.config import Settings
from app.modules.outbox.service import relay_once
from app.modules.telemetry.rules import (
    RULES,
    STALE_AFTER,
    classify,
    device_status,
    initial_battery,
    new_device_identity,
    simulated_temperature,
)
from app.modules.telemetry.service import excursions
from app.modules.telemetry.ticker import tick_running_devices
from app.persistence.memory import MemoryDatabase, memory_uow_factory
from tests import test_phase2_network as phase2
from tests.conftest import MutableClock, csrf
from tests.test_phase2_network import API, Net, donate, lookup, make_request

net = phase2.net  # reuse the Phase 2 network fixture (name "net")
NOW = datetime(2026, 9, 28, 9, 0, tzinfo=UTC)


async def _bag(net: Net, components: list[str] | None = None) -> str:
    donor_id = (await lookup(net.bank))["donor_id"]
    donation = await donate(net.bank, donor_id, components=components or ["PRBC"])
    bags = donation["bags"]
    assert isinstance(bags, list)
    return str(bags[0]["public_id"])


async def sim(client: AsyncClient, pid: str, action: str, body: object = None) -> dict[str, object]:
    r = await client.post(f"{API}/simulator/bags/{pid}/{action}", json=body, headers=csrf(client))
    assert r.status_code in (200, 201), r.text
    data: dict[str, object] = r.json()
    return data


# ---------------------------------------------------------------- rules & simulator (pure)


@pytest.mark.parametrize(
    ("component", "temp", "status"),
    [
        ("PRBC", 4.0, "normal"),
        ("PRBC", 6.0, "normal"),
        ("PRBC", 6.5, "warning"),
        ("PRBC", 1.5, "warning"),
        ("PRBC", 8.1, "critical"),
        ("PRBC", 0.5, "critical"),
        ("PLATELETS", 22.0, "normal"),
        ("PLATELETS", 25.0, "warning"),
        ("PLATELETS", 17.0, "critical"),
        ("FFP", -25.0, "normal"),
        ("FFP", -15.0, "warning"),
        ("FFP", -8.0, "critical"),
    ],
)
def test_thresholds_classify(component: str, temp: float, status: str) -> None:
    assert classify(component, temp) == status


def test_simulator_is_deterministic_and_walks_normal_warning_critical_recovery() -> None:
    def run() -> list[tuple[str, float, str]]:
        out: list[tuple[str, float, str]] = []
        seq, last = 0, None
        for mode, n in (("normal", 3), ("excursion", 4), ("recovering", 3)):
            for step in range(1, n + 1):
                seq += 1
                t = simulated_temperature("SIM-TEST", "PRBC", seq, mode, step, last)  # type: ignore[arg-type]
                last = t
                out.append((mode, t, classify("PRBC", t)))
        return out

    a = run()
    assert a == run()  # same inputs → identical readings
    statuses = [s for _, _, s in a]
    assert statuses[:3] == ["normal"] * 3
    assert statuses[3] == "warning" and "critical" in statuses[4:7]
    assert statuses[7] == "warning" and statuses[8:] == ["normal", "normal"]
    for mode, t, _ in a:  # normal readings stay near nominal (small deterministic noise)
        if mode == "normal":
            assert abs(t - RULES["PRBC"].nominal_c) <= 0.25


def test_device_identity_battery_and_status() -> None:
    dev, rfid = new_device_identity("VYR-7F3K-2QXM")
    assert (dev, rfid) == new_device_identity("VYR-7F3K-2QXM")
    assert dev.startswith("SIM-") and rfid.startswith("E280-")
    assert 93.0 <= initial_battery(dev) <= 100.0
    assert device_status(90, None, False, NOW) == "awaiting"
    assert device_status(90, NOW, False, NOW) == "paused"
    assert device_status(90, NOW, True, NOW) == "online"
    assert device_status(10, NOW, True, NOW) == "low_battery"
    assert device_status(90, NOW - STALE_AFTER - timedelta(seconds=1), True, NOW) == "offline"
    assert device_status(0, NOW, True, NOW) == "offline"


# ---------------------------------------------------------------- API: attach, read, simulate


async def test_attach_creates_a_simulated_device_and_a_trace_entry(net: Net) -> None:
    pid = await _bag(net)
    before = (await net.bank.get(f"{API}/bags/{pid}/device")).json()
    assert before["code"] == "no_device"
    res = await sim(net.bank, pid, "attach")
    dev = res["device"]
    assert isinstance(dev, dict)
    assert dev["simulated"] is True and dev["device_id"].startswith("SIM-")
    assert dev["device_status"] == "awaiting" and dev["source"]["simulated"] is True
    again = await net.bank.post(f"{API}/simulator/bags/{pid}/attach", headers=csrf(net.bank))
    assert again.status_code == 409 and again.json()["code"] == "device_already_attached"
    trace = (await net.bank.get(f"{API}/bags/{pid}")).json()
    assert [e["event_type"] for e in trace["events"]] == ["COLLECTED", "DEVICE_ATTACHED"]
    assert trace["chain"]["valid"] is True
    assert trace["bag"]["status"] == "available"  # observation events never change status
    assert trace["bag"]["qr_payload"] == f"veyra:bag:{pid}"  # QR/public id unchanged


async def test_full_excursion_lifecycle_is_traced_and_hash_chained(
    net: Net, clock: MutableClock
) -> None:
    pid = await _bag(net)
    await sim(net.bank, pid, "attach")
    r = await sim(net.bank, pid, "tick", {"count": 3})
    assert r["generated"] == 3 and r["transitions"] == []
    summary = r["summary"]
    assert isinstance(summary, dict) and summary["cold_chain_status"] == "normal"

    await sim(net.bank, pid, "excursion")
    clock.advance(seconds=60)
    r = await sim(net.bank, pid, "tick", {"count": 1})
    assert r["transitions"] == ["temperature.warning"]
    clock.advance(seconds=60)
    r = await sim(net.bank, pid, "tick", {"count": 2})
    assert r["transitions"] == ["temperature.critical"]
    s = r["summary"]
    assert isinstance(s, dict)
    assert s["cold_chain_status"] == "critical" and s["excursion_active"] is True
    assert s["excursion_severity"] == "critical" and s["excursion_duration_seconds"] == 60

    await sim(net.bank, pid, "recover")
    clock.advance(seconds=120)
    r = await sim(net.bank, pid, "tick", {"count": 1})
    assert r["transitions"] == []  # halfway: still a warning, excursion ongoing
    r = await sim(net.bank, pid, "tick", {"count": 1})
    assert r["transitions"] == ["temperature.recovered"]
    s = r["summary"]
    assert isinstance(s, dict)
    assert s["cold_chain_status"] == "normal" and s["excursion_active"] is False
    assert s["min_c"] < 6 and s["max_c"] > 8
    assert s["readings_count"] == 8

    cc = (await net.bank.get(f"{API}/bags/{pid}/cold-chain")).json()
    assert cc["chain_valid"] is True
    types = [e["event_type"] for e in cc["trace_events"]]
    assert types == ["DEVICE_ATTACHED", "TEMP_EXCURSION", "TEMP_EXCURSION", "TEMP_RECOVERED"]
    assert [e["meta"].get("severity") for e in cc["trace_events"][1:3]] == ["warning", "critical"]
    recovered = cc["trace_events"][3]["meta"]
    assert recovered["max_severity"] == "critical" and recovered["duration_seconds"] == 180
    [exc] = cc["excursions"]
    assert exc["severity"] == "critical" and exc["ended_at"] is not None and exc["readings"] == 4
    assert cc["thresholds"]["note"] == "Prototype thresholds, not clinical guidance."

    series = (await net.bank.get(f"{API}/bags/{pid}/telemetry")).json()
    assert [x["seq"] for x in series["readings"]] == list(range(1, 9))
    assert series["readings"][3]["status"] == "warning"
    assert "not a certified medical monitoring system" in series["disclaimer"]
    batteries = [x["battery_pct"] for x in series["readings"]]
    assert batteries == sorted(batteries, reverse=True)  # battery drains per reading


async def test_pause_start_and_background_ticker(
    net: Net, memdb: MemoryDatabase, clock: MutableClock
) -> None:
    pid = await _bag(net)
    await sim(net.bank, pid, "attach")
    started = await sim(net.bank, pid, "start")
    assert started["device"]["sim_running"] is True  # type: ignore[index]
    assert await tick_running_devices(memory_uow_factory(memdb), clock) == 1
    dev = (await net.bank.get(f"{API}/bags/{pid}/device")).json()
    assert dev["readings_count"] == 1 and dev["device_status"] == "online"
    await sim(net.bank, pid, "pause")
    assert await tick_running_devices(memory_uow_factory(memdb), clock) == 0
    assert (await net.bank.get(f"{API}/bags/{pid}/device")).json()["device_status"] == "paused"


async def test_monitored_list_counts_by_state(net: Net, clock: MutableClock) -> None:
    a = await _bag(net)
    donor2 = (await lookup(net.bank, "9812345678"))["donor_id"]
    b = str((await donate(net.bank, donor2, components=["PLATELETS"]))["bags"][0]["public_id"])  # type: ignore[index]
    for pid in (a, b):
        await sim(net.bank, pid, "attach")
    await sim(net.bank, a, "tick", {"count": 1})
    await sim(net.bank, b, "excursion")
    await sim(net.bank, b, "tick", {"count": 1})
    m = (await net.bank.get(f"{API}/telemetry/monitored")).json()
    assert m["scope"] == "facility" and m["simulator_enabled"] is True
    assert {x["public_id"]: x["cold_chain_status"] for x in m["bags"]} == {
        a: "normal",
        b: "warning",
    }
    assert m["counts"]["normal"] == 1 and m["counts"]["warning"] == 1
    assert "not a certified medical monitoring system" in m["disclaimer"]
    other = (await net.bank2.get(f"{API}/telemetry/monitored")).json()
    assert other["bags"] == []
    net_view = (await net.admin.get(f"{API}/telemetry/monitored")).json()
    assert net_view["scope"] == "network" and len(net_view["bags"]) == 2


# ---------------------------------------------------------------- scope, RBAC, privacy


async def test_telemetry_is_scoped_to_the_custody_chain(net: Net) -> None:
    pid = await _bag(net)
    await sim(net.bank, pid, "attach")
    await sim(net.bank, pid, "tick", {"count": 2})
    paths = [
        f"/bags/{pid}/device",
        f"/bags/{pid}/telemetry",
        f"/bags/{pid}/telemetry/summary",
        f"/bags/{pid}/cold-chain",
    ]
    for path in paths:
        assert (await net.bank.get(API + path)).status_code == 200
        assert (await net.admin.get(API + path)).status_code == 200  # network oversight
        for outsider in (net.bank2, net.hospital, net.hospital2):
            assert (await outsider.get(API + path)).status_code == 404, path
        assert (await net.donor.get(API + path)).status_code == 403
    # Once dispatched to a hospital, that hospital (and only it) may see the telemetry.
    req = await make_request(net)
    await net.bank.post(f"{API}/requests/{req['id']}/fulfil", json={}, headers=csrf(net.bank))
    assert (await net.hospital.get(f"{API}/bags/{pid}/telemetry")).status_code == 200
    assert (await net.hospital2.get(f"{API}/bags/{pid}/telemetry")).status_code == 404


async def test_only_the_current_holder_can_drive_the_simulator(net: Net) -> None:
    pid = await _bag(net)
    await sim(net.bank, pid, "attach")
    for actor, code in ((net.bank2, 404), (net.hospital, 404), (net.admin, 403), (net.donor, 403)):
        r = await actor.post(f"{API}/simulator/bags/{pid}/excursion", headers=csrf(actor))
        assert r.status_code == code, (code, r.text)
    no_csrf = await net.bank.post(f"{API}/simulator/bags/{pid}/tick", json={"count": 1})
    assert no_csrf.status_code == 403  # CSRF enforced on simulator controls
    too_many = await net.bank.post(
        f"{API}/simulator/bags/{pid}/tick", json={"count": 21}, headers=csrf(net.bank)
    )
    assert too_many.status_code == 422


async def test_simulator_is_disabled_when_configured_off(api_app: FastAPI, net: Net) -> None:
    pid = await _bag(net)
    settings: Settings = api_app.state.settings
    settings.enable_telemetry_simulator = False
    try:
        r = await net.bank.post(f"{API}/simulator/bags/{pid}/attach", headers=csrf(net.bank))
        assert r.status_code == 403 and r.json()["code"] == "simulator_disabled"
    finally:
        settings.enable_telemetry_simulator = None
    with pytest.raises(ValueError, match="telemetry simulator"):
        Settings(  # type: ignore[call-arg]
            _env_file=None, env="production", secret_key="x" * 40,
            verification_provider="sms", enable_telemetry_simulator=True,
        )  # fmt: skip


async def test_discarded_bags_cannot_take_readings(net: Net) -> None:
    pid = await _bag(net)
    await sim(net.bank, pid, "attach")
    await net.bank.post(
        f"{API}/bags/{pid}/discard", json={"reason": "damaged"}, headers=csrf(net.bank)
    )
    r = await net.bank.post(
        f"{API}/simulator/bags/{pid}/tick", json={"count": 1}, headers=csrf(net.bank)
    )
    assert r.status_code == 409 and r.json()["code"] == "device_unavailable"


async def test_telemetry_carries_no_personal_data_and_is_audited(
    net: Net, memdb: MemoryDatabase
) -> None:
    pid = await _bag(net)
    await sim(net.bank, pid, "attach")
    await sim(net.bank, pid, "excursion")
    await sim(net.bank, pid, "tick", {"count": 3})
    for path in (
        f"/bags/{pid}/device",
        f"/bags/{pid}/telemetry",
        f"/bags/{pid}/cold-chain",
        "/telemetry/monitored",
    ):
        text = (await net.bank.get(API + path)).text
        for secret in ("Arpan", "9876543210", "arpan@example.in", "donor", "patient"):
            assert secret not in text, (path, secret)
    for e in memdb.outbox:
        if e.topic.startswith(("telemetry.", "temperature.")):
            assert "donor" not in str(e.payload)
    actions = {a.action for a in memdb.audit}
    assert {
        "telemetry.device_attached",
        "telemetry.excursion_injected",
        "telemetry.readings_generated",
    } <= actions


# ---------------------------------------------------------------- SSE


async def test_telemetry_events_flow_through_the_outbox_to_sse(
    net: Net, api_app: FastAPI, memdb: MemoryDatabase, clock: MutableClock
) -> None:
    pid = await _bag(net)
    await sim(net.bank, pid, "attach")
    await sim(net.bank, pid, "tick", {"count": 1})
    await sim(net.bank, pid, "excursion")
    await sim(net.bank, pid, "tick", {"count": 3})
    await sim(net.bank, pid, "recover")
    await sim(net.bank, pid, "tick", {"count": 2})
    topics = [e.topic for e in memdb.outbox if e.aggregate_id == pid]
    for t in (
        "telemetry.updated",
        "temperature.warning",
        "temperature.critical",
        "temperature.recovered",
    ):
        assert t in topics, t
    assert topics.count("telemetry.updated") == 6  # one per reading
    recovered = next(e for e in memdb.outbox if e.topic == "temperature.recovered")
    assert recovered.payload["duration_seconds"] == 0  # same fake instant in this test
    await relay_once(memory_uow_factory(memdb), api_app.state.broker, clock)

    stream = (await net.bank.get(f"{API}/stream", params={"once": "true"})).text
    blocks = [
        b for b in stream.split("\n\n") if "event: temperature." in b or "event: telemetry." in b
    ]
    events = [
        line.split(": ", 1)[1]
        for b in blocks
        for line in b.splitlines()
        if line.startswith("event: ")
    ]
    assert events.count("temperature.warning") == 1 and events.count("temperature.recovered") == 1
    ids = [
        int(line.split(": ", 1)[1])
        for b in blocks
        for line in b.splitlines()
        if line.startswith("id: ")
    ]
    assert ids == sorted(ids) and len(ids) == len(set(ids))  # ordered, no duplicates
    # Replay after the critical event only returns what came later.
    crit_id = next(
        int(line.split(": ", 1)[1])
        for b in blocks
        if "event: temperature.critical" in b
        for line in b.splitlines()
        if line.startswith("id: ")
    )
    resumed = (
        await net.bank.get(
            f"{API}/stream", params={"once": "true"}, headers={"Last-Event-ID": str(crit_id)}
        )
    ).text
    assert "temperature.critical" not in resumed and "temperature.recovered" in resumed
    # Other facilities receive none of it.
    other = (await net.bank2.get(f"{API}/stream", params={"once": "true"})).text
    assert "temperature." not in other and "telemetry." not in other


def test_excursion_grouping_from_readings() -> None:
    from app.modules.telemetry.models import TelemetryReading

    def r(seq: int, temp: float) -> TelemetryReading:
        return TelemetryReading(
            device_pk=None, bag_id=None, seq=seq, recorded_at=NOW + timedelta(minutes=seq),
            temperature_c=temp, battery_pct=90, status=classify("PRBC", temp), simulated=True,
        )  # fmt: skip

    rows = [r(1, 4), r(2, 7), r(3, 9), r(4, 4), r(5, 6.8)]
    [first, ongoing] = excursions(rows, "PRBC")
    # Starts at minute 2, ends at the first normal reading (minute 4): 120 s.
    assert first.severity == "critical" and first.peak_c == 9 and first.duration_seconds == 120
    assert first.readings == 2 and first.ended_at == NOW + timedelta(minutes=4)
    assert ongoing.ended_at is None and ongoing.severity == "warning"
