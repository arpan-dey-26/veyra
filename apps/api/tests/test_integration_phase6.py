"""Integration: Phase 6 operational queries on PostgreSQL (requests, stock, forecast, telemetry)."""

from __future__ import annotations

import secrets

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import text

from tests.conftest import csrf
from tests.test_integration_phase1 import live_app
from tests.test_integration_phase2 import _admin, _donor, _facility_staff, _needed_by

pytestmark = pytest.mark.integration
__all__ = ["live_app"]  # re-exported fixture

API = "/api/v1"


async def _stream_from(app: FastAPI, client: AsyncClient, aggregate_ids: list[str]) -> str:
    """Replay from just before this test's first event (a shared database has older rows)."""
    async with app.state.db.engine.connect() as conn:
        first = await conn.scalar(
            text("SELECT min(id) FROM network.outbox_events WHERE aggregate_id = ANY(:ids)"),
            {"ids": aggregate_ids},
        )
    assert first is not None
    r = await client.get(f"{API}/stream", params={"once": "true", "after": str(int(first) - 1)})
    return r.text


async def test_emergency_recommendation_and_confirmed_dispatch_on_postgres(
    live_app: FastAPI,
) -> None:
    tag = secrets.token_hex(4)
    admin = await _admin(live_app, tag)
    bank = await _facility_staff(live_app, admin, "BLOOD_BANK", tag)
    hospital = await _facility_staff(live_app, admin, "HOSPITAL", tag)
    other = await _facility_staff(live_app, admin, "HOSPITAL", tag + "x")
    d1, m1 = await _donor(live_app, tag)
    d2, m2 = await _donor(live_app, tag + "y")
    bank_id = (await bank.get(f"{API}/facilities/me")).json()["id"]
    try:
        bags = []
        for mobile in (m1, m2):
            found = await bank.post(
                f"{API}/donors/lookup", json={"mobile": mobile}, headers=csrf(bank)
            )
            d = await bank.post(
                f"{API}/donations",
                json={"donor_id": found.json()["donor_id"], "blood_group": "B-",
                      "volume_ml": 450, "components": ["PRBC"]},
                headers=csrf(bank),
            )  # fmt: skip
            assert d.status_code == 201, d.text
            bags.append(d.json()["bags"][0]["public_id"])
        first, second = bags
        # The FEFO-first bag gets a (simulated) critical excursion.
        for action, body in (("attach", None), ("excursion", None), ("tick", {"count": 3})):
            r = await bank.post(
                f"{API}/simulator/bags/{first}/{action}", json=body, headers=csrf(bank)
            )
            assert r.status_code in (200, 201), r.text

        req = await hospital.post(
            f"{API}/requests",
            json={"provider": "internal", "target_ref": bank_id, "blood_group": "B-",
                  "component": "PRBC", "units": 1, "urgency": "emergency",
                  "needed_by": _needed_by()},
            headers=csrf(hospital),
        )  # fmt: skip
        assert req.status_code == 201, req.text
        rid = req.json()["id"]

        queue = (await bank.get(f"{API}/operations/requests")).json()
        assert queue["requests"][0]["id"] == rid and queue["counts"]["emergency_open"] == 1
        rec = (await bank.get(f"{API}/operations/requests/{rid}/recommendations")).json()
        states = {c["public_id"]: c["cold_chain_state"] for c in rec["candidates"]}
        assert states == {first: "critical", second: "unmonitored"}
        assert rec["fefo_default_bag_ids"] == [first] and rec["recommended_bag_ids"] == [second]
        pressure = (await bank.get(f"{API}/operations/facilities/{bank_id}/pressure")).json()
        row = next(
            r for r in pressure["rows"] if r["blood_group"] == "B-" and r["component"] == "PRBC"
        )
        assert row["stock"] == 2 and row["open_units"] == 1
        alerts = (await bank.get(f"{API}/operations/alerts")).json()
        assert (
            alerts["counts"].get("emergency_request") == 1
            and alerts["counts"].get("cold_chain") == 1
        )

        # Scope on the SQL path.
        assert (await other.get(f"{API}/operations/requests/{rid}/priority")).status_code == 404
        assert (await d1.get(f"{API}/operations/requests")).status_code == 403

        # Human-confirmed dispatch of the recommended bag (row-locked like FEFO).
        r = await bank.post(
            f"{API}/requests/{rid}/fulfil", json={"bag_public_ids": [second]}, headers=csrf(bank)
        )
        assert r.status_code == 200, r.text
        assert [b["public_id"] for b in r.json()["bags"]] == [second]
        mine = (await hospital.get(f"{API}/operations/routing")).json()
        assert [x["request_id"] for x in mine["routes"]] == [rid]
        ids = [rid, first, second]
        stream = await _stream_from(live_app, bank, ids)
        for topic in (
            "request.operational_alert",
            "routing.updated",
            "cold_chain.operational_alert",
        ):
            assert f"event: {topic}" in stream, topic
        assert rid not in await _stream_from(live_app, other, ids)
    finally:
        for c in (admin, bank, hospital, other, d1, d2):
            await c.aclose()
