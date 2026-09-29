"""Integration: Phase 3 dashboard aggregates through the SQL stats repository (PostgreSQL)."""

from __future__ import annotations

import secrets

import pytest
from fastapi import FastAPI

from tests.conftest import csrf
from tests.test_integration_phase1 import live_app
from tests.test_integration_phase2 import _admin, _donor, _facility_staff, _needed_by

pytestmark = pytest.mark.integration
__all__ = ["live_app"]  # re-exported fixture

API = "/api/v1"


async def test_dashboards_and_graph_on_postgres(live_app: FastAPI) -> None:
    tag = secrets.token_hex(4)
    admin = await _admin(live_app, tag)
    bank = await _facility_staff(live_app, admin, "BLOOD_BANK", tag)
    hospital = await _facility_staff(live_app, admin, "HOSPITAL", tag)
    donor, mobile = await _donor(live_app, tag)
    try:
        bank_id = (await bank.get(f"{API}/facilities/me")).json()["id"]
        hospital_id = (await hospital.get(f"{API}/facilities/me")).json()["id"]
        found = await bank.post(f"{API}/donors/lookup", json={"mobile": mobile}, headers=csrf(bank))
        donation = await bank.post(
            f"{API}/donations",
            json={
                "donor_id": found.json()["donor_id"],
                "blood_group": "A+",
                "volume_ml": 450,
                "components": ["PRBC", "PLATELETS"],
            },
            headers=csrf(bank),
        )
        assert donation.status_code == 201, donation.text
        req = await hospital.post(
            f"{API}/requests",
            json={
                "target_ref": bank_id,
                "blood_group": "A+",
                "component": "PRBC",
                "units": 1,
                "urgency": "emergency",
                "needed_by": _needed_by(),
            },
            headers=csrf(hospital),
        )
        assert req.status_code == 201, req.text
        rid = req.json()["id"]

        d = (await bank.get(f"{API}/dashboard/facility")).json()
        assert d["kind"] == "BLOOD_BANK" and d["donations"]["today"] == 1
        assert d["requests"]["open"] == 1 and d["requests"]["emergency_open"] == 1
        assert d["on_hand"] == 2
        assert {b["bucket"]: b["count"] for b in d["expiry"]}["d3_7"] == 1  # platelets
        assert any(a["topic"] == "request.created" for a in d["activity"])

        fulfil = await bank.post(f"{API}/requests/{rid}/fulfil", json={}, headers=csrf(bank))
        assert fulfil.status_code == 200, fulfil.text
        await hospital.post(f"{API}/requests/{rid}/receive", headers=csrf(hospital))

        h = (await hospital.get(f"{API}/dashboard/facility")).json()
        assert h["requests"]["direction"] == "outgoing" and h["on_hand"] == 1
        assert h["movements"][-1]["received"] >= 1

        g = (await hospital.get(f"{API}/network/graph")).json()
        edge = next(e for e in g["edges"] if e["target"] == bank_id)
        assert edge["source"] == hospital_id and edge["requests"] == 1 and edge["open"] == 0
        assert all(n["kind"] != "HOSPITAL" or n["id"] == hospital_id for n in g["nodes"])

        a = (await admin.get(f"{API}/dashboard/admin")).json()
        assert a["users_total"] >= 4 and a["facilities"]["blood_banks"] >= 1
        assert sum(s["count"] for s in a["requests_by_status"]) >= 1
        assert a["audit"]["last_24h"] >= 1
        keys = {"action", "resource", "actor_type", "created_at"}
        assert all(set(r) == keys for r in a["audit"]["recent"])  # no ip / meta
    finally:
        for c in (admin, bank, hospital, donor):
            await c.aclose()
