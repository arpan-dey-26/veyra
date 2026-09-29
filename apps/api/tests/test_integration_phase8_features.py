"""Integration (Phase 8 features) on PostgreSQL: camps (+ races), QR scan, compatibility."""

from __future__ import annotations

import asyncio
import secrets
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import text

from tests.conftest import csrf
from tests.test_integration_phase1 import _client, live_app
from tests.test_integration_phase2 import _admin, _donor, _facility_staff, _needed_by

pytestmark = pytest.mark.integration
__all__ = ["live_app"]  # re-exported fixture

API = "/api/v1"


def _camp(capacity: int) -> dict[str, object]:
    start = datetime.now(UTC) + timedelta(days=2)
    return {
        "title": f"Integration Camp {secrets.token_hex(3)}",
        "venue": "Integration Hall",
        "city": "Kolkata",
        "state": "West Bengal",
        "starts_at": start.isoformat(),
        "ends_at": (start + timedelta(hours=5)).isoformat(),
        "capacity": capacity,
        "contact_name": "Camp Desk (demo)",
    }


async def _act(client: AsyncClient, cid: str, action: str) -> None:
    r = await client.post(f"{API}/camps/{cid}/actions/{action}", headers=csrf(client))
    assert r.status_code == 200, r.text


async def test_camp_to_qr_trace_on_postgres(live_app: FastAPI) -> None:
    tag = secrets.token_hex(4)
    admin = await _admin(live_app, tag)
    bank = await _facility_staff(live_app, admin, "BLOOD_BANK", tag)
    other = await _facility_staff(live_app, admin, "BLOOD_BANK", tag + "o")
    hospital = await _facility_staff(live_app, admin, "HOSPITAL", tag)
    donor, mobile = await _donor(live_app, tag)
    clients = [admin, bank, other, hospital, donor]
    try:
        bank_id = (await bank.get(f"{API}/facilities/me")).json()["id"]
        r = await bank.post(f"{API}/camps", json=_camp(10), headers=csrf(bank))
        assert r.status_code == 201, r.text
        cid = r.json()["id"]
        for action in ("publish", "open-registration"):
            await _act(bank, cid, action)
        listed = (await donor.get(f"{API}/camps/public")).json()["camps"]
        assert cid in [c["id"] for c in listed]
        reg = await donor.post(f"{API}/camps/{cid}/register", headers=csrf(donor))
        assert reg.status_code == 201, reg.text
        assert (await other.get(f"{API}/camps/{cid}")).status_code == 404
        await _act(bank, cid, "start")
        rid = reg.json()["id"]
        att = await bank.post(f"{API}/camps/{cid}/registrations/{rid}/attend", headers=csrf(bank))
        assert att.status_code == 200, att.text
        found = await bank.post(f"{API}/donors/lookup", json={"mobile": mobile}, headers=csrf(bank))
        d = await bank.post(
            f"{API}/donations",
            json={"donor_id": found.json()["donor_id"], "blood_group": "B+", "volume_ml": 450,
                  "components": ["PRBC"], "camp_registration_id": rid},
            headers=csrf(bank),
        )  # fmt: skip
        assert d.status_code == 201, d.text
        bag = d.json()["bags"][0]["public_id"]
        stats = (await bank.get(f"{API}/camps/{cid}")).json()["stats"]
        assert (stats["donations_recorded"], stats["bags_collected"]) == (1, 1)

        # Compatibility reference for the case at hand (informational only).
        chk = await hospital.get(
            f"{API}/compatibility/check",
            params={"donor_group": "B+", "recipient_group": "AB+", "component": "PRBC"},
        )
        assert chk.status_code == 200 and chk.json()["compatible"] is True

        # QR scan: scoped, public id only, trace valid.
        scan = await bank.get(f"{API}/bags/scan", params={"payload": f"veyra:bag:{bag}"})
        assert scan.status_code == 200, scan.text
        assert scan.json()["chain"]["valid"] is True and scan.json()["shipment"] is None
        assert (await other.get(f"{API}/bags/scan", params={"payload": bag})).status_code == 404
        assert (await donor.get(f"{API}/bags/scan", params={"payload": bag})).status_code == 403
        qr = (await bank.get(f"{API}/bags/{bag}/qr")).json()
        assert qr["size"] == 25 and qr["payload"] == f"veyra:bag:{bag}"

        # The bag then follows the existing request → dispatch → shipment → receipt flow.
        req = await hospital.post(
            f"{API}/requests",
            json={"provider": "internal", "target_ref": bank_id, "blood_group": "B+",
                  "component": "PRBC", "units": 1, "urgency": "emergency",
                  "needed_by": _needed_by()},
            headers=csrf(hospital),
        )  # fmt: skip
        assert req.status_code == 201, req.text
        ful = await bank.post(
            f"{API}/requests/{req.json()['id']}/fulfil",
            json={"bag_public_ids": [bag]},
            headers=csrf(bank),
        )
        assert ful.status_code == 200, ful.text
        mid = (await hospital.get(f"{API}/bags/scan", params={"payload": bag})).json()
        assert mid["shipment"]["status"] == "pickup_pending"
        sid = mid["shipment"]["id"]
        for action in ("advance", "advance", "advance", "advance", "arrive"):
            s = await bank.post(f"{API}/simulator/shipments/{sid}/{action}", headers=csrf(bank))
            assert s.status_code == 200, s.text
        rcv = await hospital.post(f"{API}/shipments/{sid}/receive", headers=csrf(hospital))
        assert rcv.status_code == 200, rcv.text
        final = (await hospital.get(f"{API}/bags/scan", params={"payload": bag})).json()
        assert final["lifecycle_status"] == "received" and final["chain"]["valid"] is True
        assert final["shipment"]["status"] == "received"
        await _act(bank, cid, "complete")
        async with live_app.state.db.engine.connect() as conn:
            actions = {
                row[0]
                for row in await conn.execute(
                    text("SELECT action FROM audit.audit_logs WHERE resource_id = :r"),
                    {"r": str(rid)},
                )
            }
        assert {"camp.registration_created", "camp.attendance_confirmed",
                "camp.donation_linked"} <= actions  # fmt: skip
    finally:
        for c in clients:
            await c.aclose()


async def test_last_camp_seat_goes_to_exactly_one_donor(live_app: FastAPI) -> None:
    tag = secrets.token_hex(4)
    admin = await _admin(live_app, tag)
    bank = await _facility_staff(live_app, admin, "BLOOD_BANK", tag)
    d1, _ = await _donor(live_app, tag)
    d2, _ = await _donor(live_app, tag + "b")
    twin = _client(live_app)
    twin.cookies.update(d1.cookies)
    clients = [admin, bank, d1, d2, twin]
    try:
        cid = (await bank.post(f"{API}/camps", json=_camp(1), headers=csrf(bank))).json()["id"]
        for action in ("publish", "open-registration"):
            await _act(bank, cid, action)
        results = await asyncio.gather(
            d1.post(f"{API}/camps/{cid}/register", headers=csrf(d1)),
            d2.post(f"{API}/camps/{cid}/register", headers=csrf(d2)),
        )
        assert sorted(r.status_code for r in results) == [201, 409], [r.text for r in results]
        loser = next(r for r in results if r.status_code == 409)
        assert loser.json()["code"] == "camp_full"
        camp = (await bank.get(f"{API}/camps/{cid}")).json()
        assert camp["registered_count"] == 1 and camp["stats"]["registered"] == 1
        # The same donor twice at once: one place, never two rows.
        cid2 = (await bank.post(f"{API}/camps", json=_camp(5), headers=csrf(bank))).json()["id"]
        for action in ("publish", "open-registration"):
            await _act(bank, cid2, action)
        dup = await asyncio.gather(
            d1.post(f"{API}/camps/{cid2}/register", headers=csrf(d1)),
            twin.post(f"{API}/camps/{cid2}/register", headers=csrf(twin)),
        )
        assert sorted(r.status_code for r in dup) == [201, 409], [r.text for r in dup]
        assert (await bank.get(f"{API}/camps/{cid2}")).json()["registered_count"] == 1
        async with live_app.state.db.engine.connect() as conn:
            rows = await conn.scalar(
                text("SELECT count(*) FROM network.camp_registrations WHERE camp_id = :c"),
                {"c": cid2},
            )
        assert rows == 1
    finally:
        for c in clients:
            await c.aclose()


async def test_camp_constraints_hold_in_the_database(live_app: FastAPI) -> None:
    async with live_app.state.db.engine.connect() as conn:
        names = {
            r[0]
            for r in await conn.execute(
                text(
                    "SELECT conname FROM pg_constraint c JOIN pg_namespace n "
                    "ON n.oid = c.connamespace WHERE n.nspname = 'network' "
                    "AND conrelid::regclass::text LIKE 'network.camp%'"
                )
            )
        }
    for expected in ("ck_camps_status_valid", "ck_camps_capacity_valid",
                     "ck_camps_registered_valid", "ck_camps_window_valid", "uq_camps_code",
                     "uq_camp_registrations_camp_id_donor_id",
                     "ck_camp_registrations_status_valid"):  # fmt: skip
        assert expected in names, expected
