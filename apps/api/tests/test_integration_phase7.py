"""Integration: Phase 7 simulated shipments on PostgreSQL (lifecycle, scope, trace, telemetry)."""

from __future__ import annotations

import secrets

import pytest
from fastapi import FastAPI
from sqlalchemy import text

from tests.conftest import csrf
from tests.test_integration_phase1 import live_app
from tests.test_integration_phase2 import _admin, _donor, _facility_staff, _needed_by

pytestmark = pytest.mark.integration
__all__ = ["live_app"]  # re-exported fixture

API = "/api/v1"


async def test_shipment_lifecycle_on_postgres(live_app: FastAPI) -> None:
    tag = secrets.token_hex(4)
    admin = await _admin(live_app, tag)
    bank = await _facility_staff(live_app, admin, "BLOOD_BANK", tag)
    hospital = await _facility_staff(live_app, admin, "HOSPITAL", tag)
    other = await _facility_staff(live_app, admin, "HOSPITAL", tag + "x")
    donor, mobile = await _donor(live_app, tag)
    bank_id = (await bank.get(f"{API}/facilities/me")).json()["id"]
    try:
        found = await bank.post(f"{API}/donors/lookup", json={"mobile": mobile}, headers=csrf(bank))
        d = await bank.post(
            f"{API}/donations",
            json={"donor_id": found.json()["donor_id"], "blood_group": "A+", "volume_ml": 450,
                  "components": ["PRBC"]},
            headers=csrf(bank),
        )  # fmt: skip
        bag = d.json()["bags"][0]["public_id"]
        for action, body in (("attach", None), ("tick", {"count": 1})):
            r = await bank.post(
                f"{API}/simulator/bags/{bag}/{action}", json=body, headers=csrf(bank)
            )
            assert r.status_code in (200, 201), r.text
        req = await hospital.post(
            f"{API}/requests",
            json={"provider": "internal", "target_ref": bank_id, "blood_group": "A+",
                  "component": "PRBC", "units": 1, "urgency": "emergency",
                  "needed_by": _needed_by()},
            headers=csrf(hospital),
        )  # fmt: skip
        rid = req.json()["id"]
        rec = (await bank.get(f"{API}/operations/requests/{rid}/recommendations")).json()
        assert rec["recommended_bag_ids"] == [bag]
        r = await bank.post(
            f"{API}/requests/{rid}/fulfil", json={"bag_public_ids": [bag]}, headers=csrf(bank)
        )
        assert r.status_code == 200, r.text
        [s] = (await hospital.get(f"{API}/shipments")).json()["shipments"]
        sid = s["id"]
        assert s["status"] == "pickup_pending" and s["request_id"] == rid

        async def ship(action: str, body: object = None) -> dict[str, object]:
            resp = await bank.post(
                f"{API}/simulator/shipments/{sid}/{action}", json=body, headers=csrf(bank)
            )
            assert resp.status_code == 200, resp.text
            out: dict[str, object] = resp.json()
            return out

        await ship("advance")
        await ship("advance")
        # A cold-chain excursion while in transit flags the shipment (SQL path).
        for action, body in (("excursion", None), ("tick", {"count": 3})):
            r = await bank.post(
                f"{API}/simulator/bags/{bag}/{action}", json=body, headers=csrf(bank)
            )
            assert r.status_code == 200, r.text
        tele = (await hospital.get(f"{API}/shipments/{sid}/telemetry")).json()
        assert tele["cold_chain_alert"] == "critical" and tele["bags"][0]["excursion_active"]
        await ship("delay", {"minutes": 18})
        await ship("resume")
        await ship("advance")
        await ship("advance")
        await ship("arrive")
        route = (await hospital.get(f"{API}/shipments/{sid}/route")).json()
        assert [c["status"] for c in route["checkpoints"]] == ["reached"] * 5

        assert (await other.get(f"{API}/shipments/{sid}")).status_code == 404
        assert (await donor.get(f"{API}/shipments")).status_code == 403
        r = await hospital.post(f"{API}/shipments/{sid}/receive", headers=csrf(hospital))
        assert r.status_code == 200, r.text
        detail = r.json()
        assert detail["status"] == "received" and detail["request_status"] == "fulfilled"
        assert detail["bags"][0]["status"] == "received" and detail["trace_valid"] is True
        trace = (await hospital.get(f"{API}/bags/{bag}")).json()
        types = [e["event_type"] for e in trace["events"]]
        for t in (
            "SHIPMENT_CREATED", "SHIPMENT_PICKED_UP", "SHIPMENT_IN_TRANSIT",
            "SHIPMENT_DELAYED", "SHIPMENT_ARRIVED", "RECEIVED", "SHIPMENT_RECEIVED",
        ):  # fmt: skip
            assert t in types, t
        assert trace["chain"]["valid"] is True

        async with live_app.state.db.engine.connect() as conn:
            with pytest.raises(Exception, match="append-only"):
                await conn.execute(text("UPDATE network.shipment_events SET status = 'created'"))
            await conn.rollback()
    finally:
        for c in (admin, bank, hospital, other, donor):
            await c.aclose()
