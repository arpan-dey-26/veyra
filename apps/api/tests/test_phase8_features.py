"""Phase 8 product features: compatibility reference, donation camps, QR bag scanning."""

from __future__ import annotations

import hashlib
import json
from datetime import timedelta
from typing import Any
from uuid import UUID

import pytest
from httpx import AsyncClient

from app.modules.bags import qr as QR
from app.modules.bags.domain import QR_DISCLAIMER as BAG_QR_DISCLAIMER
from app.modules.bags.domain import Component, parse_scan, qr_payload
from app.modules.bags.models import BloodBag
from app.modules.bags.schemas import BagScanResult
from app.modules.bags.service import BagService, InvalidQrError
from app.modules.camps.service import TRANSITIONS, allowed_actions
from app.modules.compatibility import engine as E
from app.persistence.memory import MemoryDatabase
from tests import test_phase2_network as phase2
from tests.conftest import MutableClock, csrf
from tests.test_phase2_network import API, Net, donate, lookup
from tests.test_phase5_telemetry import sim
from tests.test_phase6_operations import two_bags
from tests.test_phase7_logistics import dispatch_shipment, ship

net = phase2.net
COMPAT = (
    "Informational prototype reference only; final transfusion decisions require authorized "
    "clinical confirmation."
)
CAMP = (
    "Prototype camp-management workflow; donor eligibility and medical screening remain "
    "governed by authorized staff."
)
QRD = "QR is a traceability identifier, not an authentication credential or medical authorization."
GROUPS = ["O-", "O+", "A-", "A+", "B-", "B+", "AB-", "AB+"]
COMPONENTS = ["WHOLE_BLOOD", "PRBC", "PLATELETS", "FFP", "CRYO"]


# ================================================================ Feature 1: compatibility


def test_disclaimers_are_verbatim() -> None:
    assert E.COMPATIBILITY_DISCLAIMER == COMPAT
    assert BAG_QR_DISCLAIMER == QRD


def test_red_cell_table_matches_the_classic_reference() -> None:
    c = Component.PRBC
    assert E.compatible_recipients("O-", c) == GROUPS  # universal red-cell donor
    assert E.compatible_donors("AB+", c) == GROUPS  # universal red-cell recipient
    assert E.compatible_donors("O-", c) == ["O-"]
    assert E.compatible_donors("A+", c) == ["O-", "O+", "A-", "A+"]
    assert E.compatible_donors("B-", c) == ["O-", "B-"]
    assert sum(len(E.compatible_donors(g, c)) for g in GROUPS) == 27


def test_plasma_whole_blood_platelet_and_cryo_tables() -> None:
    ffp = Component.FFP
    assert E.compatible_recipients("AB-", ffp) == GROUPS  # universal plasma donor
    assert E.compatible_donors("O+", ffp) == GROUPS  # universal plasma recipient
    assert E.compatible_donors("A-", ffp) == ["A-", "A+", "AB-", "AB+"]  # Rh not considered
    assert sum(len(E.compatible_donors(g, ffp)) for g in GROUPS) == 36
    wb = Component.WHOLE_BLOOD
    assert E.compatible_donors("A+", wb) == ["A-", "A+"]
    assert E.compatible_donors("O-", wb) == ["O-"]
    assert sum(len(E.compatible_donors(g, wb)) for g in GROUPS) == 12
    plt = Component.PLATELETS
    assert E.compatible_donors("A-", plt) == ["A-", "AB-"]
    assert E.compatible_donors("O+", plt) == GROUPS
    assert E.compatible_donors("AB-", Component.CRYO) == ["AB-", "AB+"]


def test_every_pair_has_a_deterministic_explained_verdict() -> None:
    for c in E.COMPONENTS:
        for d in GROUPS:
            for r in GROUPS:
                v = E.check(d, r, c)
                assert v == E.check(d, r, c)
                assert v.reason.startswith("Compatible" if v.compatible else "Not compatible")
    with pytest.raises(ValueError, match="unsupported"):
        E.check("C+", "A+", Component.PRBC)


async def test_matrix_endpoint_covers_all_groups_and_components(net: Net) -> None:
    for client in (net.bank, net.hospital, net.admin):
        r = await client.get(f"{API}/compatibility/matrix")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["blood_groups"] == GROUPS and body["disclaimer"] == COMPAT
        assert body["informational_only"] is True
        assert [m["component"] for m in body["components"]] == COMPONENTS
        for m in body["components"]:
            assert [row["recipient_group"] for row in m["rows"]] == GROUPS
    one = (await net.bank.get(f"{API}/compatibility/matrix?component=FFP")).json()
    assert [m["component"] for m in one["components"]] == ["FFP"]
    assert one["components"][0]["label"] == "Fresh Frozen Plasma (FFP)"


@pytest.mark.parametrize(
    ("donor", "recipient", "component", "ok"),
    [
        ("O-", "AB+", "PRBC", True),
        ("AB+", "O-", "PRBC", False),
        ("O+", "O-", "PRBC", False),
        ("A-", "A+", "PRBC", True),
        ("B+", "A+", "PRBC", False),
        ("AB+", "O+", "FFP", True),
        ("O+", "AB-", "FFP", False),
        ("A+", "A-", "FFP", True),
        ("A+", "A+", "WHOLE_BLOOD", True),
        ("O-", "A+", "WHOLE_BLOOD", False),
        ("A-", "A+", "WHOLE_BLOOD", True),
        ("A+", "A-", "WHOLE_BLOOD", False),
        ("AB-", "A-", "PLATELETS", True),
        ("A+", "A-", "PLATELETS", False),
        ("O-", "A-", "PLATELETS", False),
        ("AB+", "O-", "CRYO", True),
        ("O-", "A+", "CRYO", False),
    ],
)
async def test_check_endpoint_cases(
    net: Net, donor: str, recipient: str, component: str, ok: bool
) -> None:
    r = await net.hospital.get(
        f"{API}/compatibility/check",
        params={"donor_group": donor, "recipient_group": recipient, "component": component},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["compatible"] is ok
    assert body["result"] == ("compatible" if ok else "not_compatible")
    assert body["requires_clinical_confirmation"] is True and body["disclaimer"] == COMPAT
    assert (donor in body["compatible_donors_for_recipient"]) is ok


@pytest.mark.parametrize(
    "params",
    [
        {"donor_group": "C+", "recipient_group": "A+", "component": "PRBC"},
        {"donor_group": "A+", "recipient_group": "A", "component": "PRBC"},
        {"donor_group": "A+", "recipient_group": "A+", "component": "BLOOD"},
        {"donor_group": "A+", "recipient_group": "A+"},
    ],
)
async def test_invalid_group_or_component_is_rejected(net: Net, params: dict[str, str]) -> None:
    r = await net.bank.get(f"{API}/compatibility/check", params=params)
    assert r.status_code == 422
    assert (await net.bank.get(f"{API}/compatibility/matrix?component=XYZ")).status_code == 422


async def test_compatibility_rbac_privacy_and_no_side_effects(
    net: Net, memdb: MemoryDatabase, make_client: Any
) -> None:
    anon: AsyncClient = make_client()
    q = {"donor_group": "O-", "recipient_group": "A+", "component": "PRBC"}
    assert (await anon.get(f"{API}/compatibility/matrix")).status_code == 401
    assert (await anon.get(f"{API}/compatibility/check", params=q)).status_code == 401
    assert (await net.donor.get(f"{API}/compatibility/matrix")).status_code == 403
    assert (await net.donor.get(f"{API}/compatibility/check", params=q)).status_code == 403
    before = (len(memdb.outbox), len(memdb.audit), len(memdb.requests), len(memdb.bags))
    body = (await net.bank.get(f"{API}/compatibility/check", params=q)).json()
    # Reference data only: nothing about facilities, stock, donors or patients.
    text = json.dumps(body).lower()
    for leak in ("facility", "donor_id", "patient", "bag", "arpan", "stock"):
        assert leak not in text, leak
    assert (len(memdb.outbox), len(memdb.audit), len(memdb.requests), len(memdb.bags)) == before


# ================================================================ Feature 2: camps


def _camp_body(clock: MutableClock, **kw: object) -> dict[str, object]:
    start = clock.now() + timedelta(days=3)
    body: dict[str, object] = {
        "title": "Salt Lake Community Camp",
        "venue": "Community Hall, Sector V",
        "city": "Kolkata",
        "state": "West Bengal",
        "starts_at": start.isoformat(),
        "ends_at": (start + timedelta(hours=6)).isoformat(),
        "capacity": 50,
        "description": "Demo camp (fictional).",
        "contact_name": "Camp Desk (demo)",
        "contact_phone": "+91 90000 00000",
        "contact_email": "camps@example.in",
    }
    body.update(kw)
    return body


async def make_camp(net: Net, clock: MutableClock, **kw: object) -> dict[str, Any]:
    r = await net.bank.post(f"{API}/camps", json=_camp_body(clock, **kw), headers=csrf(net.bank))
    assert r.status_code == 201, r.text
    data: dict[str, Any] = r.json()
    return data


async def act(client: AsyncClient, cid: str, action: str, body: object = None) -> Any:
    return await client.post(f"{API}/camps/{cid}/actions/{action}", json=body, headers=csrf(client))


async def open_camp(net: Net, clock: MutableClock, **kw: object) -> str:
    cid = str((await make_camp(net, clock, **kw))["id"])
    for a in ("publish", "open-registration"):
        assert (await act(net.bank, cid, a)).status_code == 200
    return cid


async def register(client: AsyncClient, cid: str) -> Any:
    return await client.post(f"{API}/camps/{cid}/register", headers=csrf(client))


def test_lifecycle_table_is_explicit() -> None:
    assert allowed_actions("planned") == ["publish", "cancel"]
    assert allowed_actions("published") == ["open-registration", "cancel"]
    assert allowed_actions("registration_open") == ["start", "cancel"]
    assert allowed_actions("ongoing") == ["complete"]
    assert allowed_actions("completed") == [] and allowed_actions("cancelled") == []
    assert {t for _, t, _ in TRANSITIONS.values()} == {
        "published", "registration_open", "ongoing", "completed", "cancelled",
    }  # fmt: skip


async def test_camp_lifecycle_and_invalid_transitions(
    net: Net, clock: MutableClock, memdb: MemoryDatabase
) -> None:
    camp = await make_camp(net, clock)
    cid = camp["id"]
    assert camp["status"] == "planned" and camp["code"].startswith("CMP-")
    assert camp["organizer_facility_id"] == net.bank_id and camp["disclaimer"] == CAMP
    for bad in ("open-registration", "start", "complete"):
        r = await act(net.bank, cid, bad)
        assert (r.status_code, r.json()["code"]) == (409, "invalid_camp_transition"), bad
    expected = [("publish", "published"), ("open-registration", "registration_open"),
                ("start", "ongoing"), ("complete", "completed")]  # fmt: skip
    for action, status in expected:
        r = await act(net.bank, cid, action)
        assert r.status_code == 200, r.text
        assert r.json()["status"] == status
    for bad in ("publish", "open-registration", "start", "complete", "cancel"):
        assert (await act(net.bank, cid, bad)).status_code == 409, bad
    assert (await act(net.bank, cid, "explode")).status_code == 422
    actions = [a.action for a in memdb.audit if a.resource == "camp"]
    assert actions == ["camp.created", "camp.published", "camp.registration_opened",
                       "camp.started", "camp.completed"]  # fmt: skip


async def test_cancel_only_before_the_camp_starts(net: Net, clock: MutableClock) -> None:
    cid = await open_camp(net, clock)
    assert (await register(net.donor, cid)).status_code == 201
    r = await act(net.bank, cid, "cancel", {"reason": "Venue unavailable (demo)"})
    assert r.status_code == 200 and r.json()["status"] == "cancelled"
    assert r.json()["registered_count"] == 0 and r.json()["cancel_reason"]
    mine = (await net.donor.get(f"{API}/camps/me/registrations")).json()["registrations"]
    assert mine[0]["status"] == "cancelled" and mine[0]["camp"]["status"] == "cancelled"
    other = str((await make_camp(net, clock))["id"])
    for a in ("publish", "open-registration", "start"):
        await act(net.bank, other, a)
    assert (await act(net.bank, other, "cancel")).status_code == 409


async def test_camp_edit_rules_and_validation(net: Net, clock: MutableClock) -> None:
    cid = await open_camp(net, clock, capacity=2)
    await register(net.donor, cid)
    await register(net.donor2, cid)
    patch = await net.bank.patch(
        f"{API}/camps/{cid}", json={"venue": "Town Hall, Block B"}, headers=csrf(net.bank)
    )
    assert patch.status_code == 200 and patch.json()["venue"] == "Town Hall, Block B"
    low = await net.bank.patch(f"{API}/camps/{cid}", json={"capacity": 1}, headers=csrf(net.bank))
    assert (low.status_code, low.json()["code"]) == (422, "invalid_camp")
    start = clock.now() + timedelta(days=1)
    bad_window = {
        "starts_at": start.isoformat(),
        "ends_at": (start - timedelta(hours=1)).isoformat(),
    }
    r = await net.bank.patch(f"{API}/camps/{cid}", json=bad_window, headers=csrf(net.bank))
    assert r.status_code == 422
    naive = _camp_body(clock, starts_at="2026-10-01T09:00:00")
    assert (
        await net.bank.post(f"{API}/camps", json=naive, headers=csrf(net.bank))
    ).status_code == 422
    for bad in ({"capacity": 0}, {"capacity": 6000}, {"title": "x"}, {"contact_email": "nope"},
                {"extra_field": 1}):  # fmt: skip
        r = await net.bank.post(
            f"{API}/camps", json=_camp_body(clock, **bad), headers=csrf(net.bank)
        )
        assert r.status_code == 422, bad
    await act(net.bank, cid, "start")
    locked = await net.bank.patch(
        f"{API}/camps/{cid}", json={"venue": "Elsewhere"}, headers=csrf(net.bank)
    )
    assert (locked.status_code, locked.json()["code"]) == (409, "camp_not_editable")


async def test_donor_registration_capacity_and_duplicates(
    net: Net, clock: MutableClock, memdb: MemoryDatabase
) -> None:
    cid = str((await make_camp(net, clock, capacity=1))["id"])
    public = (await net.donor.get(f"{API}/camps/public")).json()["camps"]
    assert cid not in [c["id"] for c in public]  # planned camps are not public
    assert (await net.donor.get(f"{API}/camps/public/{cid}")).status_code == 404
    await act(net.bank, cid, "publish")
    listed = (await net.donor.get(f"{API}/camps/public")).json()["camps"]
    assert [c["id"] for c in listed] == [cid] and listed[0]["registration_open"] is False
    closed = await register(net.donor, cid)
    assert (closed.status_code, closed.json()["code"]) == (409, "registration_closed")
    await act(net.bank, cid, "open-registration")
    ok = await register(net.donor, cid)
    assert ok.status_code == 201 and ok.json()["status"] == "registered"
    assert ok.json()["can_cancel"] is True
    dup = await register(net.donor, cid)
    assert (dup.status_code, dup.json()["code"]) == (409, "already_registered")
    full = await register(net.donor2, cid)
    assert (full.status_code, full.json()["code"]) == (409, "camp_full")
    c = await net.donor.post(f"{API}/camps/{cid}/register/cancel", headers=csrf(net.donor))
    assert c.status_code == 200 and c.json()["status"] == "cancelled"
    again = await net.donor.post(f"{API}/camps/{cid}/register/cancel", headers=csrf(net.donor))
    assert (again.status_code, again.json()["code"]) == (409, "invalid_registration_state")
    assert (await register(net.donor2, cid)).status_code == 201  # the freed seat
    assert (await register(net.donor, cid)).json()["code"] == "camp_full"
    detail = (await net.donor.get(f"{API}/camps/public/{cid}")).json()
    assert detail["my_registration_status"] == "cancelled" and detail["seats_left"] == 0
    # One row per donor and camp; counts stay consistent.
    rows = [r for r in memdb.camp_registrations.values() if str(r.camp_id) == cid]
    assert len(rows) == 2
    assert memdb.camps[UUID(cid)].registered_count == 1


async def test_public_search_and_filters(net: Net, clock: MutableClock) -> None:
    a = await open_camp(net, clock, title="Howrah Station Camp", city="Howrah")
    b = await open_camp(net, clock, title="Salt Lake Camp")
    assert {c["id"] for c in (await net.donor.get(f"{API}/camps/public")).json()["camps"]} == {a, b}
    q = (await net.donor.get(f"{API}/camps/public?q=howrah")).json()["camps"]
    assert [c["id"] for c in q] == [a]
    city = (await net.donor.get(f"{API}/camps/public?city=kolkata")).json()["camps"]
    assert [c["id"] for c in city] == [b]
    await act(net.bank, b, "start")
    ongoing = (await net.hospital.get(f"{API}/camps/public?status=ongoing")).json()["camps"]
    assert [c["id"] for c in ongoing] == [b]  # hospitals may read published camps


async def test_camp_privacy_rbac_and_facility_isolation(
    net: Net, clock: MutableClock, make_client: Any, memdb: MemoryDatabase
) -> None:
    cid = await open_camp(net, clock)
    await register(net.donor, cid)
    # Public views never contain other donors.
    for client in (net.donor2, net.hospital):
        text = (await client.get(f"{API}/camps/public/{cid}")).text
        assert "Arpan" not in text and "9876543210" not in text and "donor_id" not in text
    assert (await net.donor2.get(f"{API}/camps/me/registrations")).json()["registrations"] == []
    # Donors and hospitals can't manage camps.
    for client in (net.donor, net.hospital):
        assert (await client.get(f"{API}/camps")).status_code == 403
        assert (await client.get(f"{API}/camps/{cid}")).status_code == 403
        assert (await client.get(f"{API}/camps/{cid}/registrations")).status_code == 403
        assert (await act(client, cid, "start")).status_code == 403
        r = await client.post(f"{API}/camps", json=_camp_body(clock), headers=csrf(client))
        assert r.status_code == 403
    assert (
        await net.hospital.post(f"{API}/camps/{cid}/register", headers=csrf(net.hospital))
    ).status_code == 403
    assert (
        await net.bank.post(f"{API}/camps/{cid}/register", headers=csrf(net.bank))
    ).status_code == 403
    # Another blood bank sees nothing of it.
    assert (await net.bank2.get(f"{API}/camps")).json()["camps"] == []
    for path in (f"/camps/{cid}", f"/camps/{cid}/registrations"):
        assert (await net.bank2.get(API + path)).status_code == 404
    patch = await net.bank2.patch(
        f"{API}/camps/{cid}", json={"venue": "Hijack Hall"}, headers=csrf(net.bank2)
    )
    assert patch.status_code == 404
    assert (await act(net.bank2, cid, "start")).status_code == 404
    spoof = _camp_body(clock, organizer_facility_id=net.bank_id)
    assert (
        await net.bank2.post(f"{API}/camps", json=spoof, headers=csrf(net.bank2))
    ).status_code == 404
    # Admins manage network-wide; they must name an active blood bank.
    net_list = (await net.admin.get(f"{API}/camps")).json()
    assert net_list["scope"] == "network" and [c["id"] for c in net_list["camps"]] == [cid]
    r = await net.admin.post(f"{API}/camps", json=_camp_body(clock), headers=csrf(net.admin))
    assert (r.status_code, r.json()["code"]) == (422, "invalid_camp")
    hosp = _camp_body(clock, organizer_facility_id=net.hospital_id)
    assert (
        await net.admin.post(f"{API}/camps", json=hosp, headers=csrf(net.admin))
    ).status_code == 404
    for_bank = _camp_body(clock, organizer_facility_id=net.bank_id)
    ok = await net.admin.post(f"{API}/camps", json=for_bank, headers=csrf(net.admin))
    assert ok.status_code == 201 and ok.json()["organizer_facility_id"] == net.bank_id
    # Anonymous: nothing.
    anon: AsyncClient = make_client()
    assert (await anon.get(f"{API}/camps/public")).status_code == 401
    assert (await anon.get(f"{API}/camps/public/{cid}")).status_code == 401
    assert (await anon.post(f"{API}/camps", json=_camp_body(clock))).status_code == 401
    assert (await anon.post(f"{API}/camps/{cid}/register")).status_code == 401
    # Staff see desk identification only — no medical data.
    regs = (await net.bank.get(f"{API}/camps/{cid}/registrations")).json()["registrations"]
    assert regs[0]["donor_name"] == "Arpan Dey" and regs[0]["mobile_masked"].endswith("3210")
    assert "98765" not in regs[0]["mobile_masked"]
    assert set(regs[0]) == {
        "id", "donor_id", "donor_name", "mobile_masked", "status",
        "registered_at", "cancelled_at", "attended_at", "donation_id",
    }  # fmt: skip
    # Live updates reach only the organizing bank, with counts, never donor identity.
    events = [e for e in memdb.outbox if e.topic == "camp.updated"]
    assert events and all([str(a) for a in e.audience] == [net.bank_id] for e in events)
    assert all("donor" not in json.dumps(e.payload) for e in events)


async def test_unverified_donor_cannot_register(
    net: Net, clock: MutableClock, memdb: MemoryDatabase
) -> None:
    cid = await open_camp(net, clock)
    user = next(u for u in memdb.users.values() if u.email == "rina@example.in")
    user.status = "pending_verification"
    r = await register(net.donor2, cid)
    assert r.status_code in (401, 403)  # session or registration refused, never a place


async def test_attendance_and_donation_go_through_the_normal_desk(
    net: Net, clock: MutableClock, memdb: MemoryDatabase
) -> None:
    cid = await open_camp(net, clock)
    reg = (await register(net.donor, cid)).json()
    await register(net.donor2, cid)
    donor_id = (await lookup(net.bank))["donor_id"]
    body = {"donor_id": donor_id, "blood_group": "O+", "volume_ml": 450,
            "components": ["PRBC", "FFP"], "camp_registration_id": reg["id"]}  # fmt: skip
    early = await net.bank.post(f"{API}/donations", json=body, headers=csrf(net.bank))
    assert early.status_code == 409  # camp not ongoing yet
    await act(net.bank, cid, "start")
    no_attend = await net.bank.post(f"{API}/donations", json=body, headers=csrf(net.bank))
    assert (no_attend.status_code, no_attend.json()["code"]) == (409, "invalid_registration_state")
    before = len(memdb.donations)
    assert before == 0  # refused links wrote nothing
    attend = await net.bank.post(
        f"{API}/camps/{cid}/registrations/{reg['id']}/attend", headers=csrf(net.bank)
    )
    assert attend.status_code == 200
    again = await net.bank.post(
        f"{API}/camps/{cid}/registrations/{reg['id']}/attend", headers=csrf(net.bank)
    )
    assert again.status_code == 409
    wrong = body | {"donor_id": (await lookup(net.bank, "9812345678"))["donor_id"]}
    assert (
        await net.bank.post(f"{API}/donations", json=wrong, headers=csrf(net.bank))
    ).status_code == 409
    other_bank = await net.bank2.post(f"{API}/donations", json=body, headers=csrf(net.bank2))
    assert other_bank.status_code == 404
    d = await net.bank.post(f"{API}/donations", json=body, headers=csrf(net.bank))
    assert d.status_code == 201, d.text
    bags = d.json()["bags"]
    assert len(bags) == 2 and all(b["qr_payload"] == qr_payload(b["public_id"]) for b in bags)
    twice = await net.bank.post(f"{API}/donations", json=body, headers=csrf(net.bank))
    assert twice.status_code == 409
    camp = (await net.bank.get(f"{API}/camps/{cid}")).json()
    assert camp["stats"] == {
        "registered": 1,
        "attended": 1,
        "cancelled": 0,
        "no_show": 0,
        "donations_recorded": 1,
        "bags_collected": 2,
        "seats_left": 48,
    }
    dash = (await net.bank.get(f"{API}/camps/dashboard")).json()
    assert (dash["active"], dash["donations_recorded"], dash["bags_collected"]) == (1, 1, 2)
    done = (await act(net.bank, cid, "complete")).json()
    assert done["stats"]["no_show"] == 1 and done["stats"]["registered"] == 0
    actions = {a.action for a in memdb.audit}
    assert {"camp.registration_created", "camp.attendance_confirmed", "camp.donation_linked",
            "donation.recorded"} <= actions  # fmt: skip


async def test_camp_donation_keeps_the_donation_interval_control(
    net: Net, clock: MutableClock
) -> None:
    donor_id = (await lookup(net.bank))["donor_id"]
    await donate(net.bank, donor_id)  # an ordinary desk donation today
    cid = await open_camp(net, clock)
    reg = (await register(net.donor, cid)).json()
    await act(net.bank, cid, "start")
    await net.bank.post(
        f"{API}/camps/{cid}/registrations/{reg['id']}/attend", headers=csrf(net.bank)
    )
    body = {"donor_id": donor_id, "blood_group": "O+", "volume_ml": 450,
            "components": ["PRBC"], "camp_registration_id": reg["id"]}  # fmt: skip
    r = await net.bank.post(f"{API}/donations", json=body, headers=csrf(net.bank))
    assert (r.status_code, r.json()["code"]) == (409, "donor_not_eligible")


# ================================================================ Feature 3: QR


def test_parse_scan_accepts_labels_and_typed_ids_only() -> None:
    assert parse_scan("veyra:bag:VYR-7F3K-2QXM") == "VYR-7F3K-2QXM"
    assert parse_scan("  VEYRA:BAG:vyr-7f3k-2qxm ") == "VYR-7F3K-2QXM"
    assert parse_scan("vyr-7f3k-2qxm") == "VYR-7F3K-2QXM"  # manual entry fallback
    for bad in ("", "hello", "VYR-7F3K", "VYR-7F3K-2QXO", "veyra:camp:VYR-7F3K-2QXM",
                "https://evil.example/VYR-7F3K-2QXM", "veyra:bag:" + "A" * 80):  # fmt: skip
        assert parse_scan(bad) is None, bad


def test_qr_encoder_is_deterministic_and_well_formed() -> None:
    payload = "veyra:bag:VYR-7F3K-2QXM"
    rows = QR.encode(payload)
    assert rows == QR.encode(payload) and len(rows) == 25 and {len(r) for r in rows} == {25}
    finder = ["1111111", "1000001", "1011101", "1011101", "1011101", "1000001", "1111111"]
    for oy, ox in ((0, 0), (0, 18), (18, 0)):
        assert [rows[oy + i][ox : ox + 7] for i in range(7)] == finder
    assert rows[6][8:17] == "101010101"  # timing pattern
    assert rows[17][8] == "1"  # the dark module (4V+9, 8)
    # Golden digest (verified to decode back to the payload with an independent decoder).
    digest = hashlib.sha256("".join(rows).encode()).hexdigest()
    assert digest == GOLDEN_QR_SHA256
    assert len(QR.encode("x")) == 21 and len(QR.encode("y" * 62)) == 33
    with pytest.raises(ValueError, match="too long"):
        QR.encode("z" * 63)


GOLDEN_QR_SHA256 = "85137fef4bb9cac16dff2829a6188aecfed25b9f2da7ae2afcfc582f2da26d69"


async def test_scan_valid_label_manual_id_and_trace_integration(net: Net) -> None:
    older, _ = await two_bags(net)
    for payload in (qr_payload(older), older, older.lower(), f"  {qr_payload(older)}  "):
        r = await net.bank.get(f"{API}/bags/scan", params={"payload": payload})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["public_id"] == older and body["disclaimer"] == QRD
    trace = (await net.bank.get(f"{API}/bags/{older}")).json()
    assert body["chain"]["valid"] is True and body["events"] == len(trace["events"])
    assert body["lifecycle_status"] == "available" and body["usable"] is True
    assert body["cold_chain"]["monitored"] is False and body["shipment"] is None
    assert body["trace_path"] == f"/bags/{older}" and body["last_event_type"] == "COLLECTED"


@pytest.mark.parametrize(
    "payload", ["hello", "VYR-7F3K", "VYR-7F3K-2QXO", "veyra:camp:VYR-7F3K-2QXM", "<script>"]
)
async def test_scan_rejects_malformed_payloads(net: Net, payload: str) -> None:
    r = await net.bank.get(f"{API}/bags/scan", params={"payload": payload})
    assert (r.status_code, r.json()["code"]) == (422, "invalid_qr")
    assert "<script>" not in r.text  # the raw input is never echoed back


async def test_scan_nonexistent_and_oversized(net: Net) -> None:
    r = await net.bank.get(f"{API}/bags/scan", params={"payload": "veyra:bag:VYR-0000-0000"})
    assert r.status_code == 404
    assert (await net.bank.get(f"{API}/bags/scan", params={"payload": "V" * 65})).status_code == 422
    assert (await net.bank.get(f"{API}/bags/scan")).status_code == 422


async def test_qr_is_never_a_credential(net: Net, make_client: Any) -> None:
    older, _ = await two_bags(net)
    anon: AsyncClient = make_client()
    assert (
        await anon.get(f"{API}/bags/scan", params={"payload": qr_payload(older)})
    ).status_code == 401
    assert (await anon.get(f"{API}/bags/{older}/qr")).status_code == 401
    assert (await net.donor.get(f"{API}/bags/scan", params={"payload": older})).status_code == 403
    assert (await net.donor.get(f"{API}/bags/{older}/qr")).status_code == 403
    for outsider in (net.bank2, net.hospital, net.hospital2):  # not in the custody chain yet
        r = await outsider.get(f"{API}/bags/scan", params={"payload": qr_payload(older)})
        assert r.status_code == 404
        assert (await outsider.get(f"{API}/bags/{older}/qr")).status_code == 404
    assert (await net.admin.get(f"{API}/bags/scan", params={"payload": older})).status_code == 200


async def test_scan_never_exposes_donor_identity(net: Net) -> None:
    older, newer = await two_bags(net)
    for pid in (older, newer):
        text = (await net.bank.get(f"{API}/bags/scan", params={"payload": pid})).text
        for leak in ("Arpan", "Rina", "9876543210", "9812345678", "example.in", "donor"):
            assert leak not in text, leak
        qr_text = (await net.bank.get(f"{API}/bags/{pid}/qr")).text
        assert "Arpan" not in qr_text and "donor" not in qr_text
    rows = (await net.bank.get(f"{API}/bags/{older}/qr")).json()
    assert rows["payload"] == qr_payload(older) and rows["size"] == 25
    assert rows["modules"] == QR.encode(qr_payload(older)) and rows["disclaimer"] == QRD


async def test_scan_shows_cold_chain_and_shipment(net: Net, clock: MutableClock) -> None:
    s, _, bag = await dispatch_shipment(net, attach_newer=True)
    first = (await net.hospital.get(f"{API}/bags/scan", params={"payload": qr_payload(bag)})).json()
    assert first["shipment"]["reference"] == s["reference"]
    assert first["shipment"]["status"] == "pickup_pending"
    assert first["cold_chain"]["monitored"] is True and first["cold_chain"]["status"] == "normal"
    assert first["lifecycle_status"] == "in_transit" and first["usable"] is False
    await ship(net.bank, s["id"], "advance")
    await ship(net.bank, s["id"], "advance")
    await sim(net.bank, bag, "excursion")
    await sim(net.bank, bag, "tick", {"count": 3})
    now = (await net.hospital.get(f"{API}/bags/scan", params={"payload": bag})).json()
    assert now["shipment"]["status"] == "in_transit"
    assert now["cold_chain"]["excursion_active"] is True
    assert now["cold_chain"]["status"] in ("warning", "critical")
    assert now["chain"]["valid"] is True and now["last_event_type"] == "TEMP_EXCURSION"
    await ship(net.bank, s["id"], "advance")
    await ship(net.bank, s["id"], "advance")
    await ship(net.bank, s["id"], "arrive")
    await net.hospital.post(f"{API}/shipments/{s['id']}/receive", headers=csrf(net.hospital))
    final = (await net.hospital.get(f"{API}/bags/scan", params={"payload": bag})).json()
    assert final["lifecycle_status"] == "received" and final["shipment"]["status"] == "received"
    assert final["location"] and final["chain"]["valid"] is True
    # Scanning is read-only: it never changes the bag.
    again = (await net.hospital.get(f"{API}/bags/scan", params={"payload": bag})).json()
    assert again["events"] == final["events"]


async def test_scan_service_rejects_before_any_lookup(net: Net, memdb: MemoryDatabase) -> None:
    from uuid import uuid4

    from app.core.clock import SystemClock
    from app.core.rbac import AuthContext, Role
    from app.persistence.memory import MemoryUnitOfWork

    svc = BagService(MemoryUnitOfWork(memdb), SystemClock())
    ctx = AuthContext(user_id=uuid4(), role=Role.ADMIN, session_id=uuid4())
    with pytest.raises(InvalidQrError):
        await svc.scan(ctx, "not-a-bag")
    assert isinstance(BloodBag, type) and BagScanResult.model_fields["disclaimer"]
