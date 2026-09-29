"""Integration: Phase 5 simulated telemetry through the SQL unit of work (PostgreSQL)."""

from __future__ import annotations

import secrets

import pytest
from fastapi import FastAPI
from sqlalchemy import text

from app.modules.telemetry.ticker import tick_running_devices
from tests.conftest import csrf
from tests.test_integration_phase1 import live_app
from tests.test_integration_phase2 import _admin, _donor, _facility_staff

pytestmark = pytest.mark.integration
__all__ = ["live_app"]  # re-exported fixture

API = "/api/v1"


async def test_cold_chain_excursion_on_postgres(live_app: FastAPI) -> None:
    tag = secrets.token_hex(4)
    admin = await _admin(live_app, tag)
    bank = await _facility_staff(live_app, admin, "BLOOD_BANK", tag)
    other = await _facility_staff(live_app, admin, "BLOOD_BANK", tag + "x")
    donor, mobile = await _donor(live_app, tag)
    try:
        found = await bank.post(f"{API}/donors/lookup", json={"mobile": mobile}, headers=csrf(bank))
        d = await bank.post(
            f"{API}/donations",
            json={"donor_id": found.json()["donor_id"], "blood_group": "A-", "volume_ml": 450,
                  "components": ["PRBC"]},
            headers=csrf(bank),
        )  # fmt: skip
        pid = d.json()["bags"][0]["public_id"]

        async def sim(action: str, body: object = None) -> dict[str, object]:
            r = await bank.post(
                f"{API}/simulator/bags/{pid}/{action}", json=body, headers=csrf(bank)
            )
            assert r.status_code in (200, 201), r.text
            out: dict[str, object] = r.json()
            return out

        await sim("attach")
        await sim("tick", {"count": 2})
        await sim("excursion")
        r = await sim("tick", {"count": 3})
        assert r["transitions"] == ["temperature.warning", "temperature.critical"]
        await sim("recover")
        r = await sim("tick", {"count": 2})
        assert r["transitions"] == ["temperature.recovered"]

        cc = (await bank.get(f"{API}/bags/{pid}/cold-chain")).json()
        assert cc["chain_valid"] is True and len(cc["excursions"]) == 1
        types = [e["event_type"] for e in cc["trace_events"]]
        assert types == ["DEVICE_ATTACHED", "TEMP_EXCURSION", "TEMP_EXCURSION", "TEMP_RECOVERED"]
        series = (await bank.get(f"{API}/bags/{pid}/telemetry")).json()
        assert [x["seq"] for x in series["readings"]] == list(range(1, 8))

        # Background ticker (SQL path, FOR UPDATE SKIP LOCKED).
        await sim("start")
        assert await tick_running_devices(live_app.state.uow_factory, live_app.state.clock) >= 1
        await sim("pause")

        for outsider in (other, donor):
            code = (await outsider.get(f"{API}/bags/{pid}/telemetry")).status_code
            assert code in (403, 404)
        blocked = await other.post(f"{API}/simulator/bags/{pid}/excursion", headers=csrf(other))
        assert blocked.status_code == 404

        async with live_app.state.db.engine.connect() as conn:
            with pytest.raises(Exception, match="append-only"):
                await conn.execute(text("UPDATE telemetry.readings SET temperature_c = 0"))
            await conn.rollback()
    finally:
        for c in (admin, bank, other, donor):
            await c.aclose()
