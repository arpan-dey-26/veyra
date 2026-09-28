"""Integration: the full Phase 1 flow through the SQL unit of work on real PostgreSQL.

Needs a migrated database (``alembic upgrade head``). Skipped when Postgres is not
reachable, and FAILS instead when ``VEYRA_REQUIRE_INFRA=1`` (the bootstrap sets it).
"""

from __future__ import annotations

import os
import secrets
import uuid
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app.core.clock import SystemClock
from app.core.config import Settings
from app.main import create_app
from app.persistence.sql import SqlUnitOfWork
from app.scripts.seed_demo import ensure_demo_admin
from tests.conftest import BASE_URL, PASSWORD, csrf, donor_payload

pytestmark = pytest.mark.integration


def _mobile() -> str:
    """A valid Indian mobile that is unique per call: 9 + 9 digits from a fresh UUID4
    (collision odds ~1e-9 per pair, vs. data left behind by earlier runs)."""
    return "9" + f"{uuid.uuid4().int % 10**9:09d}"


@pytest.fixture
async def live_app() -> AsyncIterator[FastAPI]:
    settings = Settings(  # type: ignore[call-arg]
        env="test", password_hash_memory_kib=1024, password_hash_iterations=1
    )
    app = create_app(settings, with_infra=True)
    async with AsyncExitStack() as stack:
        try:
            await stack.enter_async_context(app.router.lifespan_context(app))
            await app.state.db.ping()
            async with app.state.db.engine.connect() as conn:
                await conn.execute(text("SELECT 1 FROM identity.users LIMIT 1"))
        except Exception as exc:  # driver missing, database down, or not migrated
            if os.environ.get("VEYRA_REQUIRE_INFRA") == "1":
                pytest.fail(f"PostgreSQL not available/migrated: {type(exc).__name__}: {exc}")
            pytest.skip(f"PostgreSQL not available: {type(exc).__name__}")
        yield app


def _client(app: FastAPI) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url=BASE_URL)


async def test_donor_lifecycle_on_postgres(live_app: FastAPI) -> None:
    tag = secrets.token_hex(4)
    mobile = _mobile()
    payload = donor_payload(email=f"donor-{tag}@example.in", mobile=mobile)
    async with _client(live_app) as c:
        r = await c.post("/api/v1/auth/register", json=payload)
        assert r.status_code == 201, r.text
        cid = r.json()["verification"]["challenge_id"]

        dup = await c.post("/api/v1/auth/register", json=payload)
        assert dup.status_code == 409 and dup.json()["code"] == "email_taken"

        bad = await c.post("/api/v1/auth/verify", json={"challenge_id": cid, "code": "0000"})
        assert bad.status_code == 400  # the failed attempt must be committed…
        ok = await c.post("/api/v1/auth/verify", json={"challenge_id": cid, "code": mobile[-4:]})
        assert ok.status_code == 200, ok.text  # …and the correct code still works
        assert ok.json()["donor"]["blood_group"] == "O+"

        patched = await c.patch("/api/v1/donors/me", json={"city": "Durgapur"}, headers=csrf(c))
        assert patched.status_code == 200 and patched.json()["city"] == "Durgapur"
        assert (await c.get("/api/v1/donors/me")).json()["city"] == "Durgapur"

        assert (await c.post("/api/v1/auth/refresh", headers=csrf(c))).status_code == 200
        assert (await c.post("/api/v1/auth/logout", headers=csrf(c))).status_code == 204
        assert (await c.get("/api/v1/auth/me")).status_code == 401

        relog = await c.post(
            "/api/v1/auth/login", json={"email": payload["email"], "password": PASSWORD}
        )
        assert relog.status_code == 200


async def test_admin_facility_invite_flow_on_postgres(live_app: FastAPI) -> None:
    tag = secrets.token_hex(4)
    admin_email = f"admin-{tag}@veyra.test"
    async with live_app.state.db.sessionmaker() as session:
        _, created = await ensure_demo_admin(
            SqlUnitOfWork(session),
            hasher=live_app.state.hasher,
            clock=SystemClock(),
            email=admin_email,
            password=PASSWORD,
            mobile="+91" + _mobile(),
        )
        assert created

    async with _client(live_app) as admin, _client(live_app) as staff:
        r = await admin.post(
            "/api/v1/auth/login", json={"email": admin_email, "password": PASSWORD}
        )
        assert r.status_code == 200, r.text
        fac = await admin.post(
            "/api/v1/admin/facilities",
            json={
                "type": "HOSPITAL",
                "name": f"Integration Hospital {tag}",
                "registration_number": f"INT-{tag}",
                "address": "1 Test Road",
                "city": "Kolkata",
                "state": "West Bengal",
                "pin_code": "700001",
            },
            headers=csrf(admin),
        )
        assert fac.status_code == 201, fac.text
        fid = fac.json()["id"]
        inv = await admin.post(
            f"/api/v1/admin/facilities/{fid}/invites",
            json={"email": f"staff-{tag}@hospital.in"},
            headers=csrf(admin),
        )
        assert inv.status_code == 201, inv.text
        token = inv.json()["accept_path"].rsplit("/", 1)[1]
        acc = await staff.post(
            "/api/v1/auth/invites/accept",
            json={
                "token": token,
                "full_name": "Integration Staff",
                "mobile": _mobile(),
                "password": "integration-desk-passphrase",
            },
        )
        assert acc.status_code == 201, acc.text
        assert (await staff.get("/api/v1/facilities/me")).json()["id"] == fid
        assert (await staff.get("/api/v1/donors/me")).status_code == 403
        users = await admin.get("/api/v1/admin/users", params={"role": "HOSPITAL"})
        assert users.status_code == 200 and users.json()["meta"]["total"] >= 1


async def test_audit_log_is_append_only_in_postgres(live_app: FastAPI) -> None:
    async with live_app.state.db.engine.connect() as conn:
        await conn.execute(
            text(
                "INSERT INTO audit.audit_logs (id, actor_type, action, resource, meta, created_at) "
                "VALUES (gen_random_uuid(), 'system', 'test.append_only', 'test', '{}', now())"
            )
        )
        with pytest.raises(Exception, match="append-only"):
            await conn.execute(
                text(
                    "UPDATE audit.audit_logs SET action = 'tampered' "
                    "WHERE action = 'test.append_only'"
                )
            )
        await conn.rollback()
