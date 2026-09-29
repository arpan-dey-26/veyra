"""Phase 6: explainable operational priority, allocation recommendations, pressure, routing."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI
from httpx import AsyncClient

from app.modules.forecast.model import default_model
from app.modules.forecast.service import facility_daily_mean
from app.modules.operations import engine as E
from app.modules.outbox.service import relay_once
from app.persistence.memory import MemoryDatabase, memory_uow_factory
from tests import test_phase2_network as phase2
from tests.conftest import MutableClock, csrf
from tests.test_phase2_network import API, Net, donate, lookup, request_body
from tests.test_phase5_telemetry import sim

net = phase2.net
NOW = datetime(2026, 9, 28, 9, 0, tzinfo=UTC)
DISCLAIMER = (
    "This is an operational engineering prototype. Recommendations are not clinical "
    "decisions or medical advice."
)


async def two_bags(net: Net, *, group: str = "O+") -> tuple[str, str]:
    """(older, newer) PRBC bags of ``group`` at the demo bank, from two donors."""
    d1 = (await lookup(net.bank))["donor_id"]
    d2 = (await lookup(net.bank, "9812345678"))["donor_id"]
    older = await donate(
        net.bank, d1, group=group, components=["PRBC"], collected_at="2026-09-26T09:00:00Z"
    )
    newer = await donate(net.bank, d2, group=group, components=["PRBC"])
    return older["bags"][0]["public_id"], newer["bags"][0]["public_id"]  # type: ignore[index]


async def emergency(net: Net, units: int = 1, **kw: object) -> dict[str, object]:
    body = request_body(net.bank_id, units) | {"urgency": "emergency"} | kw
    r = await net.hospital.post(f"{API}/requests", json=body, headers=csrf(net.hospital))
    assert r.status_code == 201, r.text
    data: dict[str, object] = r.json()
    return data


async def make_critical(net: Net, pid: str) -> None:
    await sim(net.bank, pid, "attach")
    await sim(net.bank, pid, "excursion")
    await sim(net.bank, pid, "tick", {"count": 3})


def reason_codes(obj: object) -> list[str]:
    assert isinstance(obj, dict)
    return [r["code"] for r in obj["reasons"]]


# ---------------------------------------------------------------- engine (pure)


def _req(urgency: str = "routine", **kw: object) -> E.RequestFacts:
    base: dict[str, object] = {
        "urgency": urgency,
        "status": "pending",
        "units": 1,
        "created_at": NOW,
        "needed_by": NOW + timedelta(hours=24),
        "provider": "internal",
    }
    return E.RequestFacts(**(base | kw))  # type: ignore[arg-type]


GOOD = E.StockFacts(
    usable=3, usable_without_concern=3, flagged=0, expiring_soon=0, availability_band=None
)


def test_priority_is_deterministic_explainable_and_banded() -> None:
    a = E.priority(_req("emergency"), now=NOW, stock=GOOD, pressure_level=None, viewer="bank")
    assert a == E.priority(
        _req("emergency"), now=NOW, stock=GOOD, pressure_level=None, viewer="bank"
    )
    assert a.score == 50 and a.band == "high" and a.action_code == "review_and_dispatch"
    assert a.reasons[0].text == "Emergency request"
    assert sum(r.points for r in a.reasons) == a.score  # the score IS the sum of its reasons
    worst = E.priority(
        _req(
            "emergency",
            units=5,
            created_at=NOW - timedelta(hours=3),
            needed_by=NOW - timedelta(minutes=1),
        ),
        now=NOW,
        stock=E.StockFacts(6, 2, 4, 1, None),
        pressure_level="elevated",
        viewer="bank",
    )
    codes = [r.code for r in worst.reasons]
    for code in ("urgency_emergency", "overdue", "waiting_2h", "large", "stock_short",
                 "cold_chain_flagged", "bag_expires_soon", "pressure_elevated"):  # fmt: skip
        assert code in codes, code
    assert worst.score == 100 and worst.band == "immediate"  # capped
    assert worst.action_code == "review_flagged"
    routine = E.priority(_req(), now=NOW, stock=GOOD, pressure_level=None, viewer="bank")
    assert routine.band == "standard" and routine.score == 10
    short = E.priority(
        _req(units=4),
        now=NOW,
        stock=E.StockFacts(1, 1, 0, 0, None),
        pressure_level="watch",
        viewer="bank",
    )
    assert short.action_code == "insufficient_stock" and "pressure_watch" in [
        r.code for r in short.reasons
    ]


def test_priority_for_hospitals_uses_bands_and_never_exact_stock() -> None:
    p = E.priority(
        _req("urgent"), now=NOW, stock=E.StockFacts(None, None, None, None, "limited"),
        pressure_level=None, viewer="hospital",
    )  # fmt: skip
    assert p.action_code == "await_bank"
    texts = " ".join(r.text for r in p.reasons)
    assert "banded" in texts
    assert not any(ch.isdigit() for ch in texts)  # no stock counts leak to hospitals
    closed = E.priority(
        _req(status="fulfilled"), now=NOW, stock=GOOD, pressure_level=None, viewer="bank"
    )
    assert closed.score == 0 and closed.action_code == "none"
    mock = E.priority(
        _req(provider="mock"), now=NOW, stock=GOOD, pressure_level=None, viewer="bank"
    )
    assert mock.action_code == "simulated_partner"


@pytest.mark.parametrize(
    ("stock", "open_units", "mean", "level"),
    [
        (20, 0, 2.0, "normal"),  # 10 days
        (10, 0, 2.0, "watch"),  # 5 days
        (4, 0, 2.0, "elevated"),  # 2 days
        (10, 6, 2.0, "elevated"),  # free 4 → 2 days
        (3, 5, 2.0, "elevated"),  # open > stock
        (5, 0, None, "normal"),  # no forecast for this component
        (0, 2, None, "elevated"),
    ],
)
def test_pressure_levels(stock: int, open_units: int, mean: float | None, level: str) -> None:
    p = E.pressure(stock, open_units, mean)
    assert p.level == level and p.free_stock == stock - open_units
    assert p.reasons and p.reasons[0].code == "stock"


def test_candidates_rank_cold_chain_then_fefo_and_never_drop_bags() -> None:
    def bag(pid: str, hours: int) -> E.BagView:
        return E.BagView(pid, "O+", "PRBC", NOW + timedelta(hours=hours), "b", "Bank")

    bags = [bag("A", 30), bag("B", 100), bag("C", 200), bag("D", 300)]
    devices = {
        "A": E.DeviceView("critical", "online", True),
        "B": E.DeviceView("normal", "offline", False),  # stale
        "D": E.DeviceView("normal", "online", False),
    }
    out = E.rank_candidates(bags, devices, units=2, now=NOW)
    assert [c.bag.public_id for c in out] == ["C", "D", "B", "A"]  # C unmonitored = no concern
    assert [c.recommended for c in out] == [True, True, False, False]
    assert {c.bag.public_id: c.cold for c in out} == {
        "A": "critical",
        "B": "stale",
        "C": "unmonitored",
        "D": "normal",
    }
    a = next(c for c in out if c.bag.public_id == "A")
    assert a.deprioritized and "cold_chain_critical" in [r.code for r in a.reasons]
    assert "expires_soon" in [r.code for r in a.reasons] and a.fefo_position == 1
    assert len(out) == len(bags)  # flagged, never silently discarded
    assert E.rank_candidates(bags, devices, units=2, now=NOW)[0].rank == 1


def test_simulated_routing_is_deterministic_and_labelled() -> None:
    bank = E.Place("b1", "Bank", "Kolkata", "West Bengal")
    near = E.Place("h1", "Hospital", "Kolkata", "West Bengal")
    far = E.Place("h2", "Far", "Siliguri", "West Bengal")
    other = E.Place("h3", "Other", "Patna", "Bihar")
    r = E.simulated_route(bank, near, "emergency", hour_bucket=1)
    assert r == E.simulated_route(bank, near, "emergency", hour_bucket=1)
    assert 3 <= r.distance_km <= 15
    assert 40 <= E.simulated_route(bank, far, "urgent", hour_bucket=1).distance_km <= 200
    assert E.simulated_route(bank, other, "urgent", hour_bucket=1).distance_km >= 250
    assert (
        E.simulated_route(near, bank, "urgent", hour_bucket=1).distance_km
        == E.simulated_route(bank, near, "urgent", hour_bucket=1).distance_km
    )
    fast = E.simulated_route(bank, far, "emergency", hour_bucket=1)
    slow = E.simulated_route(bank, far, "routine", hour_bucket=1)
    assert fast.eta_minutes < slow.eta_minutes
    assert {
        x.status for x in (E.simulated_route(bank, far, "urgent", hour_bucket=h) for h in range(24))
    } > {"clear"}
    assert r.eta_minutes == r.travel_minutes + r.handover_minutes and r.reasons


# ---------------------------------------------------------------- API: emergency workflow


async def test_emergency_request_recommendation_and_confirmed_dispatch(
    net: Net, memdb: MemoryDatabase, clock: MutableClock
) -> None:
    older, newer = await two_bags(net)
    await make_critical(net, older)
    req = await emergency(net)

    queue = (await net.bank.get(f"{API}/operations/requests")).json()
    assert queue["scope"] == "facility" and queue["counts"]["emergency_open"] == 1
    assert (
        DISCLAIMER in queue["disclaimer"]
        and queue["label"] == "Operational recommendation — prototype"
    )
    [item] = queue["requests"]
    assert item["reference"] == req["reference"] and item["urgency"] == "emergency"
    assert item["units"] == 1 and item["blood_group"] == "O+" and item["age_minutes"] == 0
    assert item["priority"]["reasons"][0]["text"] == "Emergency request"
    assert "cold_chain_flagged" in reason_codes(item["priority"])

    rec = (await net.bank.get(f"{API}/operations/requests/{req['id']}/recommendations")).json()
    assert rec["recommended_bag_ids"] == [newer] and rec["fefo_default_bag_ids"] == [older]
    assert "skipping bags with cold-chain concerns" in rec["recommendation"]
    assert "Nothing is dispatched automatically" in rec["human_confirmation"]
    cands = {c["public_id"]: c for c in rec["candidates"]}
    assert cands[older]["cold_chain_state"] == "critical" and cands[older]["deprioritized"] is True
    assert cands[older]["device_id"].startswith("SIM-") and cands[older]["latest_temperature_c"] > 8
    assert "cold_chain_critical" in reason_codes(cands[older])
    assert cands[newer]["recommended"] is True and cands[newer]["rank"] == 1
    assert cands[newer]["current_facility_id"] == net.bank_id
    assert rec["pressure"]["blood_group"] == "O+" and rec["pressure"]["open_units"] == 1
    assert rec["route"]["label"] == "Simulated routing — prototype"
    assert rec["route"]["source"]["simulated"] is True
    # Reading recommendations dispatches nothing.
    assert (await net.hospital.get(f"{API}/requests/{req['id']}")).json()["status"] == "pending"

    # Selection is validated like FEFO: count and eligibility.
    wrong = await net.bank.post(
        f"{API}/requests/{req['id']}/fulfil",
        json={"bag_public_ids": [older, newer]},
        headers=csrf(net.bank),
    )
    assert wrong.status_code == 409 and wrong.json()["code"] == "bag_not_eligible"
    alien = await net.bank.post(
        f"{API}/requests/{req['id']}/fulfil",
        json={"bag_public_ids": ["VYR-0000-0000"]},
        headers=csrf(net.bank),
    )
    assert alien.status_code == 409 and alien.json()["code"] == "bag_not_eligible"

    clock.advance(minutes=5)
    r = await net.bank.post(
        f"{API}/requests/{req['id']}/fulfil",
        json={"bag_public_ids": [newer]},
        headers=csrf(net.bank),
    )
    assert r.status_code == 200, r.text
    assert [b["public_id"] for b in r.json()["bags"]] == [newer]
    audit = [a for a in memdb.audit if a.action == "blood_request.dispatched"]
    assert audit[-1].meta == {"selection": "confirmed_bags"}

    mine = (await net.hospital.get(f"{API}/operations/requests")).json()
    [own] = mine["requests"]
    assert own["status"] == "dispatched" and own["route"]["eta_minutes"] > 0
    assert mine["counts"]["expected_units"] == 1
    assert own["priority"]["action_code"] == "await_receipt"
    routes = (await net.hospital.get(f"{API}/operations/routing")).json()
    assert [x["reference"] for x in routes["routes"]] == [req["reference"]]
    topics = [e.topic for e in memdb.outbox]
    for t in ("request.operational_alert", "allocation.recommendation_updated", "routing.updated",
              "cold_chain.operational_alert"):  # fmt: skip
        assert t in topics, t


async def test_plain_dispatch_keeps_strict_fefo(net: Net, memdb: MemoryDatabase) -> None:
    older, _ = await two_bags(net)
    req = await emergency(net)
    r = await net.bank.post(f"{API}/requests/{req['id']}/fulfil", json={}, headers=csrf(net.bank))
    assert [b["public_id"] for b in r.json()["bags"]] == [older]
    assert [a for a in memdb.audit if a.action == "blood_request.dispatched"][-1].meta == {
        "selection": "fefo"
    }


async def test_scope_and_rbac_on_operational_endpoints(net: Net, api_app: FastAPI) -> None:
    await two_bags(net)
    req = await emergency(net)
    rid = req["id"]
    # Hospital: its own priority (banded), never bag candidates.
    hp = (await net.hospital.get(f"{API}/operations/requests/{rid}/priority")).json()
    assert "band_sufficient" in reason_codes(hp) and "stock_ok" not in reason_codes(hp)
    assert (
        await net.hospital.get(f"{API}/operations/requests/{rid}/recommendations")
    ).status_code == 403
    # Unrelated facilities: 404, existence never confirmed.
    assert (await net.hospital2.get(f"{API}/operations/requests/{rid}/priority")).status_code == 404
    assert (await net.bank2.get(f"{API}/operations/requests/{rid}/priority")).status_code == 404
    assert (
        await net.bank2.get(f"{API}/operations/requests/{rid}/recommendations")
    ).status_code == 404
    assert (await net.hospital2.get(f"{API}/operations/requests")).json()["requests"] == []
    assert (await net.bank2.get(f"{API}/operations/requests")).json()["requests"] == []
    assert (
        await net.hospital.get(f"{API}/operations/facilities/{net.bank_id}/pressure")
    ).status_code == 404
    # Admin: network level.
    adm = (await net.admin.get(f"{API}/operations/requests")).json()
    assert adm["scope"] == "network" and adm["counts"]["emergency_open"] == 1
    assert (await net.admin.get(f"{API}/operations/requests/{rid}/priority")).status_code == 200
    assert (
        await net.admin.get(f"{API}/operations/requests/{rid}/recommendations")
    ).status_code == 403
    # Donor 403, anonymous 401.
    for path in (
        "/operations/requests",
        "/operations/alerts",
        f"/operations/requests/{rid}/priority",
    ):
        assert (await net.donor.get(API + path)).status_code == 403
    from tests.conftest import BASE_URL

    async with AsyncClient(
        transport=__import__("httpx").ASGITransport(app=api_app), base_url=BASE_URL
    ) as anon:
        assert (await anon.get(f"{API}/operations/requests")).status_code == 401


async def test_priority_change_is_audited_scoped_and_evented(
    net: Net, memdb: MemoryDatabase
) -> None:
    await two_bags(net)
    r = await net.hospital.post(
        f"{API}/requests", json=request_body(net.bank_id), headers=csrf(net.hospital)
    )
    rid = r.json()["id"]
    body = {"urgency": "emergency", "reason": "escalated_by_requesting_team"}
    assert (
        await net.bank.post(
            f"{API}/operations/requests/{rid}/priority", json=body, headers=csrf(net.bank)
        )
    ).status_code == 403
    assert (
        await net.hospital2.post(
            f"{API}/operations/requests/{rid}/priority", json=body, headers=csrf(net.hospital2)
        )
    ).status_code == 404
    free_text = await net.hospital.post(
        f"{API}/operations/requests/{rid}/priority",
        json={"urgency": "emergency", "reason": "patient Rina is worse"},
        headers=csrf(net.hospital),
    )
    assert free_text.status_code == 422  # reason codes only: nothing personal reaches the audit log
    no_csrf = await net.hospital.post(f"{API}/operations/requests/{rid}/priority", json=body)
    assert no_csrf.status_code == 403
    before = len(memdb.outbox)
    ok = await net.hospital.post(
        f"{API}/operations/requests/{rid}/priority", json=body, headers=csrf(net.hospital)
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["reasons"][0]["code"] == "urgency_emergency"
    new_topics = [e.topic for e in memdb.outbox[before:]]
    assert new_topics == [
        "request.priority_changed",
        "request.operational_alert",
        "allocation.recommendation_updated",
    ]
    changed = memdb.outbox[before]
    assert (
        changed.payload["previous_urgency"] == "urgent"
        and changed.payload["urgency"] == "emergency"
    )
    [a] = [x for x in memdb.audit if x.action == "blood_request.priority_changed"]
    assert a.meta == {"from": "urgent", "to": "emergency", "reason": "escalated_by_requesting_team"}
    same = await net.hospital.post(
        f"{API}/operations/requests/{rid}/priority", json=body, headers=csrf(net.hospital)
    )
    assert same.status_code == 409
    await net.bank.post(f"{API}/requests/{rid}/fulfil", json={}, headers=csrf(net.bank))
    late = await net.hospital.post(
        f"{API}/operations/requests/{rid}/priority",
        json={"urgency": "routine", "reason": "other"},
        headers=csrf(net.hospital),
    )
    assert late.status_code == 409 and late.json()["code"] == "invalid_priority_change"
    assert (await net.hospital.get(f"{API}/requests/{rid}")).json()["urgency"] == "emergency"


async def test_pressure_combines_real_stock_open_requests_and_synthetic_forecast(
    net: Net, memdb: MemoryDatabase, api_app: FastAPI
) -> None:
    await two_bags(net)
    await emergency(net, units=1)
    p = (await net.bank.get(f"{API}/operations/facilities/{net.bank_id}/pressure")).json()
    assert p["forecast_label"] == "Synthetic forecast input — prototype"
    assert p["source"]["kind"] == "synthetic" and DISCLAIMER in p["disclaimer"]
    assert len(p["rows"]) == 24 and sum(p["counts"].values()) == 24
    row = next(r for r in p["rows"] if r["blood_group"] == "O+" and r["component"] == "PRBC")
    assert row["stock"] == 2 and row["open_units"] == 1 and row["free_stock"] == 1
    bank = next(f for f in memdb.facilities.values() if str(f.id) == net.bank_id)
    today = (NOW + timedelta(minutes=330)).date()
    mean = facility_daily_mean(default_model(), bank, "O+", "PRBC", today)
    assert row["level"] == E.pressure(2, 1, mean).level
    assert row["forecast_daily_mean"] == round(mean or 0, 2)
    order = {"elevated": 0, "watch": 1, "normal": 2}
    assert [order[r["level"]] for r in p["rows"]] == sorted(order[r["level"]] for r in p["rows"])
    own = (await net.hospital.get(f"{API}/operations/facilities/{net.hospital_id}/pressure")).json()
    assert own["facility_type"] == "HOSPITAL"
    assert (
        await net.admin.get(f"{API}/operations/facilities/{net.bank_id}/pressure")
    ).status_code == 200
    assert (
        await net.bank2.get(f"{API}/operations/facilities/{net.bank_id}/pressure")
    ).status_code == 404


async def test_pressure_changed_event_only_when_the_level_changes(
    net: Net, memdb: MemoryDatabase
) -> None:
    await two_bags(net)
    bank = next(f for f in memdb.facilities.values() if str(f.id) == net.bank_id)
    mean = facility_daily_mean(
        default_model(), bank, "O+", "PRBC", (NOW + timedelta(minutes=330)).date()
    )
    expected = E.pressure(2, 0, mean).level != E.pressure(2, 2, mean).level
    await emergency(net, units=2)
    changed = [e for e in memdb.outbox if e.topic == "forecast.pressure_changed"]
    assert bool(changed) == expected
    for e in changed:
        assert e.payload["label"] == "Synthetic forecast input — prototype"
        assert e.payload["previous_level"] != e.payload["level"]


async def test_alerts_cover_emergency_cold_chain_and_expiry(net: Net) -> None:
    d1 = (await lookup(net.bank))["donor_id"]
    d2 = (await lookup(net.bank, "9812345678"))["donor_id"]
    prbc = (await donate(net.bank, d1, components=["PRBC"]))["bags"][0]["public_id"]  # type: ignore[index]
    # Platelets keep 5 days: collected 48 h ago (the backdating limit) → expires in 72 h.
    await donate(net.bank, d2, components=["PLATELETS"], collected_at="2026-09-26T09:00:00Z")
    await make_critical(net, prbc)
    await emergency(net)
    a = (await net.bank.get(f"{API}/operations/alerts")).json()
    kinds = a["counts"]
    assert kinds.get("emergency_request") == 1 and kinds.get("expiring") == 1
    assert kinds.get("cold_chain") == 1
    assert a["alerts"][0]["kind"] in (
        "emergency_request",
        "cold_chain",
    )  # warnings first
    assert all(x["severity"] in ("warning", "attention") for x in a["alerts"])
    admin = (await net.admin.get(f"{API}/operations/alerts")).json()
    assert admin["scope"] == "network" and admin["counts"].get("emergency_request") == 1
    assert admin["counts"].get("cold_chain") == 1
    hospital = (await net.hospital.get(f"{API}/operations/alerts")).json()
    assert hospital["counts"].get("emergency_request") == 1  # its own request
    assert "cold_chain" not in hospital["counts"] and "expiring" not in hospital["counts"]
    other = (await net.hospital2.get(f"{API}/operations/alerts")).json()
    assert {x["kind"] for x in other["alerts"]} <= {"pressure"}  # only its own (empty) stock
    assert kinds.get("pressure", 0) <= 1  # summarised, never one alert per row


async def test_cold_chain_alert_lists_the_bag_while_monitored(net: Net) -> None:
    older, _ = await two_bags(net)
    await make_critical(net, older)
    a = (await net.bank.get(f"{API}/operations/alerts")).json()
    [cold] = [x for x in a["alerts"] if x["kind"] == "cold_chain"]
    assert cold["ref"] == older and cold["severity"] == "warning" and "critical" in cold["title"]
    other = (await net.bank2.get(f"{API}/operations/alerts")).json()
    assert {x["kind"] for x in other["alerts"]} <= {"pressure"}


async def test_route_estimate_scope(net: Net) -> None:
    q = {
        "source_facility_id": net.bank_id,
        "destination_facility_id": net.hospital_id,
        "urgency": "emergency",
    }
    r = (await net.bank.get(f"{API}/operations/routing/estimate", params=q)).json()
    assert r["label"] == "Simulated routing — prototype" and r["source"]["kind"] == "simulated"
    assert r == (await net.hospital.get(f"{API}/operations/routing/estimate", params=q)).json() | {
        "source": r["source"]
    }
    assert (
        await net.hospital2.get(f"{API}/operations/routing/estimate", params=q)
    ).status_code == 404
    assert (await net.admin.get(f"{API}/operations/routing/estimate", params=q)).status_code == 200
    bad = await net.bank.get(f"{API}/operations/routing/estimate", params=q | {"urgency": "asap"})
    assert bad.status_code == 422


async def test_operational_payloads_carry_no_personal_data(net: Net, memdb: MemoryDatabase) -> None:
    older, _ = await two_bags(net)
    await make_critical(net, older)
    req = await emergency(net)
    for client, path in (
        (net.bank, "/operations/requests"),
        (net.bank, f"/operations/requests/{req['id']}/recommendations"),
        (net.bank, "/operations/alerts"),
        (net.bank, f"/operations/facilities/{net.bank_id}/pressure"),
        (net.hospital, "/operations/requests"),
        (net.admin, "/operations/requests"),
    ):
        text = (await client.get(API + path)).text
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
        assert "donor" not in str(e.payload).lower()


# ---------------------------------------------------------------- SSE


async def test_operational_events_are_scoped_replayable_and_unique(
    net: Net, api_app: FastAPI, memdb: MemoryDatabase, clock: MutableClock
) -> None:
    older, newer = await two_bags(net)
    await make_critical(net, older)
    req = await emergency(net)
    await net.bank.post(
        f"{API}/requests/{req['id']}/fulfil",
        json={"bag_public_ids": [newer]},
        headers=csrf(net.bank),
    )
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

    bank = events((await net.bank.get(f"{API}/stream", params={"once": "true"})).text)
    names = [n for _, n in bank]
    for t in ("request.operational_alert", "allocation.recommendation_updated", "routing.updated",
              "cold_chain.operational_alert"):  # fmt: skip
        assert t in names, t
    ids = [i for i, _ in bank]
    assert ids == sorted(ids) and len(ids) == len(set(ids))
    hosp = [
        n
        for _, n in events((await net.hospital.get(f"{API}/stream", params={"once": "true"})).text)
    ]
    assert "request.operational_alert" in hosp and "routing.updated" in hosp
    assert "allocation.recommendation_updated" not in hosp  # bank-only
    assert "cold_chain.operational_alert" not in hosp  # the bag was at the bank then
    alert_id = next(i for i, n in bank if n == "request.operational_alert")
    resumed = [
        n
        for _, n in events(
            (
                await net.bank.get(
                    f"{API}/stream",
                    params={"once": "true"},
                    headers={"Last-Event-ID": str(alert_id)},
                )
            ).text
        )
    ]
    assert "request.operational_alert" not in resumed and "routing.updated" in resumed
    for other in (net.bank2, net.hospital2):
        text = (await other.get(f"{API}/stream", params={"once": "true"})).text
        assert "operational" not in text and "routing.updated" not in text
