"""Integration: Phase 4 forecasts through the real API + SQL unit of work (PostgreSQL)."""

from __future__ import annotations

import secrets

import pytest
from fastapi import FastAPI

from tests.conftest import csrf
from tests.test_integration_phase1 import live_app
from tests.test_integration_phase2 import _admin, _donor, _facility_staff

pytestmark = pytest.mark.integration
__all__ = ["live_app"]  # re-exported fixture

API = "/api/v1"


async def test_forecast_scoping_and_real_stock_on_postgres(live_app: FastAPI) -> None:
    tag = secrets.token_hex(4)
    admin = await _admin(live_app, tag)
    bank = await _facility_staff(live_app, admin, "BLOOD_BANK", tag)
    hospital = await _facility_staff(live_app, admin, "HOSPITAL", tag)
    donor, mobile = await _donor(live_app, tag)
    try:
        bank_id = (await bank.get(f"{API}/facilities/me")).json()["id"]
        hospital_id = (await hospital.get(f"{API}/facilities/me")).json()["id"]
        found = await bank.post(f"{API}/donors/lookup", json={"mobile": mobile}, headers=csrf(bank))
        r = await bank.post(
            f"{API}/donations",
            json={
                "donor_id": found.json()["donor_id"],
                "blood_group": "B+",
                "volume_ml": 450,
                "components": ["PRBC", "FFP"],
            },
            headers=csrf(bank),
        )
        assert r.status_code == 201, r.text

        s = (await bank.get(f"{API}/forecast/summary", params={"horizon": 7})).json()
        assert s["facility_id"] == bank_id and s["source"]["kind"] == "synthetic"
        stock = {(x["blood_group"], x["component"]): x["stock_available"] for x in s["rows"]}
        assert stock[("B+", "PRBC")] == 1 and stock[("B+", "FFP")] == 1

        d = await hospital.get(
            f"{API}/forecast/demand", params={"blood_group": "B+", "component": "PRBC"}
        )
        assert d.status_code == 200 and d.json()["facility_id"] == hospital_id
        assert "not clinical guidance" in d.json()["disclaimer"]
        denied = await hospital.get(
            f"{API}/forecast/demand", params={"blood_group": "B+", "facility_id": bank_id}
        )
        assert denied.status_code == 404

        net = (await admin.get(f"{API}/forecast/demand", params={"blood_group": "B+"})).json()
        assert net["scope"] == "network" and net["facilities_included"] >= 1
        assert (await donor.get(f"{API}/forecast/summary")).status_code == 403
    finally:
        for c in (admin, bank, hospital, donor):
            await c.aclose()
