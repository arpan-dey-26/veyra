"""Integration: the Phase 2 blood network through the SQL unit of work on real PostgreSQL.

Needs a migrated database (``alembic upgrade head``). Skipped when Postgres is not
reachable, and FAILS instead when ``VEYRA_REQUIRE_INFRA=1`` (the bootstrap sets it).
"""

from __future__ import annotations

import asyncio
import secrets
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import text

from app.core.clock import SystemClock
from app.persistence.sql import SqlUnitOfWork
from app.scripts.seed_demo import ensure_demo_admin
from tests.conftest import PASSWORD, csrf, donor_payload
from tests.test_integration_phase1 import _client, _mobile, live_app

pytestmark = pytest.mark.integration
__all__ = ["live_app"]  # re-exported fixture

API = "/api/v1"


async def _admin(app: FastAPI, tag: str) -> AsyncClient:
    email = f"admin2-{tag}@veyra.test"
    async with app.state.db.sessionmaker() as session:
        await ensure_demo_admin(
            SqlUnitOfWork(session),
            hasher=app.state.hasher,
            clock=SystemClock(),
            email=email,
            password=PASSWORD,
            mobile="+91" + _mobile(),
        )
    admin = _client(app)
    r = await admin.post(f"{API}/auth/login", json={"email": email, "password": PASSWORD})
    assert r.status_code == 200, r.text
    return admin


async def _facility_staff(app: FastAPI, admin: AsyncClient, kind: str, tag: str) -> AsyncClient:
    fac = await admin.post(
        f"{API}/admin/facilities",
        json={
            "type": kind,
            "name": f"Integration {kind.title()} {tag}",
            "registration_number": f"INT2-{kind[:1]}-{tag}",
            "address": "1 Test Road",
            "city": "Kolkata",
            "state": "West Bengal",
            "pin_code": "700001",
        },
        headers=csrf(admin),
    )
    assert fac.status_code == 201, fac.text
    inv = await admin.post(
        f"{API}/admin/facilities/{fac.json()['id']}/invites",
        json={"email": f"{kind.lower()}-{tag}@staff.in"},
        headers=csrf(admin),
    )
    assert inv.status_code == 201, inv.text
    staff = _client(app)
    acc = await staff.post(
        f"{API}/auth/invites/accept",
        json={
            "token": inv.json()["accept_path"].rsplit("/", 1)[1],
            "full_name": "Integration Staff",
            "mobile": _mobile(),
            "password": "integration-desk-passphrase",
        },
    )
    assert acc.status_code == 201, acc.text
    return staff


async def _donor(app: FastAPI, tag: str) -> tuple[AsyncClient, str]:
    mobile = _mobile()
    c = _client(app)
    r = await c.post(
        f"{API}/auth/register",
        json=donor_payload(email=f"donor2-{tag}-{secrets.token_hex(2)}@example.in", mobile=mobile),
    )
    assert r.status_code == 201, r.text
    cid = r.json()["verification"]["challenge_id"]
    ok = await c.post(f"{API}/auth/verify", json={"challenge_id": cid, "code": mobile[-4:]})
    assert ok.status_code == 200, ok.text
    return c, mobile


def _needed_by() -> str:
    return (datetime.now(UTC) + timedelta(hours=6)).isoformat()


async def test_blood_network_vertical_slice_on_postgres(live_app: FastAPI) -> None:
    tag = secrets.token_hex(4)
    admin = await _admin(live_app, tag)
    bank = await _facility_staff(live_app, admin, "BLOOD_BANK", tag)
    hospital = await _facility_staff(live_app, admin, "HOSPITAL", tag)
    donor, mobile = await _donor(live_app, tag)
    bank_id = (await bank.get(f"{API}/facilities/me")).json()["id"]
    try:
        found = await bank.post(f"{API}/donors/lookup", json={"mobile": mobile}, headers=csrf(bank))
        assert found.status_code == 200, found.text
        donation = await bank.post(
            f"{API}/donations",
            json={
                "donor_id": found.json()["donor_id"],
                "blood_group": "B-",
                "volume_ml": 450,
                "components": ["PRBC", "FFP"],
            },
            headers=csrf(bank),
        )
        assert donation.status_code == 201, donation.text
        bags = donation.json()["bags"]
        prbc = next(b for b in bags if b["component"] == "PRBC")["public_id"]

        summary = (await bank.get(f"{API}/inventory/summary")).json()
        rows = {(r["blood_group"], r["component"]): r["available"] for r in summary["rows"]}
        assert rows[("B-", "PRBC")] == 1 and rows[("B-", "FFP")] == 1

        avail = await hospital.get(
            f"{API}/network/availability",
            params={"blood_group": "B-", "component": "PRBC", "units": 1},
        )
        bands = {x["target_ref"]: x["band"] for x in avail.json()["results"]}
        assert bands[bank_id] == "sufficient"

        key = f"int-{tag}"
        body = {
            "target_ref": bank_id,
            "blood_group": "B-",
            "component": "PRBC",
            "units": 1,
            "urgency": "emergency",
            "needed_by": _needed_by(),
        }
        headers = csrf(hospital) | {"Idempotency-Key": key}
        created = await hospital.post(f"{API}/requests", json=body, headers=headers)
        assert created.status_code == 201, created.text
        replay = await hospital.post(f"{API}/requests", json=body, headers=headers)
        assert replay.status_code == 200 and replay.json()["id"] == created.json()["id"]
        rid = created.json()["id"]

        fulfil = await bank.post(f"{API}/requests/{rid}/fulfil", json={}, headers=csrf(bank))
        assert fulfil.status_code == 200, fulfil.text
        assert [b["public_id"] for b in fulfil.json()["bags"]] == [prbc]
        received = await hospital.post(f"{API}/requests/{rid}/receive", headers=csrf(hospital))
        assert received.status_code == 200 and received.json()["status"] == "fulfilled"

        trace = (await hospital.get(f"{API}/bags/{prbc}")).json()
        assert [e["event_type"] for e in trace["events"]] == ["COLLECTED", "DISPATCHED", "RECEIVED"]
        assert trace["chain"]["valid"] is True
        assert (await donor.get(f"{API}/donors/me")).json()["blood_group_status"] == "confirmed"

        stream = await hospital.get(f"{API}/stream", params={"once": "true", "after": 0})
        assert stream.status_code == 200
        assert "event: request.created" in stream.text and rid in stream.text
        assert "event: request.fulfilled" in stream.text
    finally:
        for c in (admin, bank, hospital, donor):
            await c.aclose()


async def test_concurrent_fulfilment_never_double_allocates_a_bag(live_app: FastAPI) -> None:
    """Two requests race for one bag: FOR UPDATE SKIP LOCKED gives it to exactly one."""
    tag = secrets.token_hex(4)
    admin = await _admin(live_app, tag)
    bank = await _facility_staff(live_app, admin, "BLOOD_BANK", tag)
    hospital = await _facility_staff(live_app, admin, "HOSPITAL", tag)
    donor, mobile = await _donor(live_app, tag)
    bank2 = _client(live_app)
    try:
        bank_id = (await bank.get(f"{API}/facilities/me")).json()["id"]
        found = await bank.post(f"{API}/donors/lookup", json={"mobile": mobile}, headers=csrf(bank))
        await bank.post(
            f"{API}/donations",
            json={
                "donor_id": found.json()["donor_id"],
                "blood_group": "AB-",
                "volume_ml": 350,
                "components": ["CRYO"],
            },
            headers=csrf(bank),
        )
        ids = []
        for _ in range(2):
            r = await hospital.post(
                f"{API}/requests",
                json={
                    "target_ref": bank_id,
                    "blood_group": "AB-",
                    "component": "CRYO",
                    "units": 1,
                    "needed_by": _needed_by(),
                },
                headers=csrf(hospital),
            )
            assert r.status_code == 201, r.text
            ids.append(r.json()["id"])
        # A second, independent session for the same bank user (separate connection).
        bank2.cookies.update(bank.cookies)
        results = await asyncio.gather(
            bank.post(f"{API}/requests/{ids[0]}/fulfil", json={}, headers=csrf(bank)),
            bank2.post(f"{API}/requests/{ids[1]}/fulfil", json={}, headers=csrf(bank2)),
        )
        codes = sorted(r.status_code for r in results)
        assert codes == [200, 409], [r.text for r in results]
        loser = next(r for r in results if r.status_code == 409)
        assert loser.json()["code"] == "insufficient_stock"
    finally:
        for c in (admin, bank, hospital, donor, bank2):
            await c.aclose()


async def test_bag_events_are_append_only_in_postgres(live_app: FastAPI) -> None:
    async with live_app.state.db.engine.connect() as conn:
        exists = await conn.scalar(text("SELECT count(*) FROM trace.bag_events"))
        if not exists:
            pytest.skip("no bag events yet (runs after the vertical-slice test)")
        with pytest.raises(Exception, match="append-only"):
            await conn.execute(text("UPDATE trace.bag_events SET meta = '{}'::jsonb"))
        await conn.rollback()
        with pytest.raises(Exception, match="append-only"):
            await conn.execute(text("DELETE FROM trace.bag_events"))
        await conn.rollback()
