"""Phase 1: donor profile, facility onboarding and staff invitations."""

from __future__ import annotations

from collections.abc import Callable

from fastapi import FastAPI
from httpx import AsyncClient

from app.persistence.memory import MemoryDatabase
from tests.conftest import MutableClock, csrf, login, register_and_verify, seed_user

FACILITY = {
    "type": "BLOOD_BANK",
    "name": "  Durgapur   Central Blood Bank ",
    "registration_number": "wb-bb-0042",
    "address": "City Centre, Durgapur",
    "city": "Durgapur",
    "state": "west bengal",
    "pin_code": "713216",
}


async def _admin(api_app: FastAPI, memdb: MemoryDatabase, client: AsyncClient) -> AsyncClient:
    await seed_user(api_app, memdb, role="ADMIN", email="admin@veyra.test", mobile="+919000000009")
    await login(client, "admin@veyra.test")
    return client


async def test_donor_reads_own_profile(api: AsyncClient) -> None:
    await register_and_verify(api)
    r = await api.get("/api/v1/donors/me")
    assert r.status_code == 200
    p = r.json()
    assert p["full_name"] == "Arpan Dey"
    assert p["blood_group"] == "O+"
    assert p["blood_group_status"] == "self_declared"
    assert p["pin_code"] == "700016"
    assert p["verified_at"] is not None


async def test_donor_updates_allowed_fields(api: AsyncClient, memdb: MemoryDatabase) -> None:
    await register_and_verify(api)
    r = await api.patch(
        "/api/v1/donors/me",
        json={"full_name": "Arpan  K. Dey", "city": "Durgapur", "pin_code": "713216"},
        headers=csrf(api),
    )
    assert r.status_code == 200, r.text
    p = r.json()
    assert (p["full_name"], p["city"], p["pin_code"]) == ("Arpan K. Dey", "Durgapur", "713216")
    assert (await api.get("/api/v1/auth/me")).json()["user"]["full_name"] == "Arpan K. Dey"
    assert memdb.audit[-1].action == "donor.profile_updated"
    assert memdb.audit[-1].meta == {"fields": ["city", "full_name", "pin_code"]}


async def test_donor_cannot_change_identity_or_blood_group_here(api: AsyncClient) -> None:
    await register_and_verify(api)
    for field, value in (("email", "x@y.in"), ("mobile", "9123456789"), ("blood_group", "AB-")):
        r = await api.patch("/api/v1/donors/me", json={field: value}, headers=csrf(api))
        assert r.status_code == 422, field


async def test_donor_update_validates_and_requires_csrf(api: AsyncClient) -> None:
    await register_and_verify(api)
    assert (await api.patch("/api/v1/donors/me", json={"city": "Durgapur"})).status_code == 403
    bad = await api.patch("/api/v1/donors/me", json={"pin_code": "12"}, headers=csrf(api))
    assert bad.status_code == 422


async def test_admin_onboards_facility_and_invites_staff(
    api_app: FastAPI,
    memdb: MemoryDatabase,
    make_client: Callable[[], AsyncClient],
) -> None:
    admin = await _admin(api_app, memdb, make_client())
    created = await admin.post("/api/v1/admin/facilities", json=FACILITY, headers=csrf(admin))
    assert created.status_code == 201, created.text
    facility = created.json()
    assert facility["name"] == "Durgapur Central Blood Bank"
    assert facility["state"] == "West Bengal"
    assert facility["registration_number"] == "WB-BB-0042"
    assert facility["provider_kind"] == "internal" and facility["is_simulated"] is False

    dup = await admin.post("/api/v1/admin/facilities", json=FACILITY, headers=csrf(admin))
    assert dup.status_code == 409

    invite = await admin.post(
        f"/api/v1/admin/facilities/{facility['id']}/invites",
        json={"email": "Staff@Bank.in"},
        headers=csrf(admin),
    )
    assert invite.status_code == 201, invite.text
    inv = invite.json()
    assert inv["email"] == "staff@bank.in"
    assert inv["role"] == "BLOOD_BANK"
    assert inv["status"] == "pending"
    assert inv["delivery"]["mode"] == "demo_link"
    assert "no email is sent" in inv["delivery"]["note"]
    token = inv["accept_path"].rsplit("/", 1)[1]
    assert all(token not in str(v.__dict__) for v in memdb.invites.values())  # only the hash

    listed = await admin.get(f"/api/v1/admin/facilities/{facility['id']}/invites")
    assert [i["status"] for i in listed.json()] == ["pending"]
    assert "accept_path" not in listed.text

    staff = make_client()
    preview = await staff.get(f"/api/v1/auth/invites/{token}")
    assert preview.status_code == 200
    assert preview.json()["facility"]["name"] == "Durgapur Central Blood Bank"

    accepted = await staff.post(
        "/api/v1/auth/invites/accept",
        json={
            "token": token,
            "full_name": "Rina Sen",
            "mobile": "9830012345",
            "password": "bank-desk-passphrase",
        },
    )
    assert accepted.status_code == 201, accepted.text
    me = accepted.json()
    assert me["user"]["role"] == "BLOOD_BANK"
    assert me["user"]["status"] == "active"
    assert me["facility"]["id"] == facility["id"]
    assert (await staff.get("/api/v1/facilities/me")).json()["id"] == facility["id"]

    reused = await make_client().post(
        "/api/v1/auth/invites/accept",
        json={
            "token": token,
            "full_name": "Eve Das",
            "mobile": "9830099999",
            "password": "another-valid-passphrase",
        },
    )
    assert reused.status_code == 404
    assert reused.json()["code"] == "invite_invalid"
    listed_after = await admin.get(f"/api/v1/admin/facilities/{facility['id']}/invites")
    assert [i["status"] for i in listed_after.json()] == ["accepted"]


async def test_invites_expire(
    api_app: FastAPI,
    memdb: MemoryDatabase,
    clock: MutableClock,
    make_client: Callable[[], AsyncClient],
) -> None:
    admin = await _admin(api_app, memdb, make_client())
    fac = (await admin.post("/api/v1/admin/facilities", json=FACILITY, headers=csrf(admin))).json()
    inv = await admin.post(
        f"/api/v1/admin/facilities/{fac['id']}/invites",
        json={"email": "late@bank.in"},
        headers=csrf(admin),
    )
    token = inv.json()["accept_path"].rsplit("/", 1)[1]
    clock.advance(hours=73)
    assert (await make_client().get(f"/api/v1/auth/invites/{token}")).status_code == 404


async def test_cannot_invite_an_existing_account(
    api_app: FastAPI, memdb: MemoryDatabase, make_client: Callable[[], AsyncClient]
) -> None:
    admin = await _admin(api_app, memdb, make_client())
    fac = (await admin.post("/api/v1/admin/facilities", json=FACILITY, headers=csrf(admin))).json()
    r = await admin.post(
        f"/api/v1/admin/facilities/{fac['id']}/invites",
        json={"email": "admin@veyra.test"},
        headers=csrf(admin),
    )
    assert r.status_code == 409


async def test_invite_for_unknown_facility_is_404(
    api_app: FastAPI, memdb: MemoryDatabase, make_client: Callable[[], AsyncClient]
) -> None:
    admin = await _admin(api_app, memdb, make_client())
    r = await admin.post(
        "/api/v1/admin/facilities/0199c82c-c000-7dd2-8d9b-f32ffe017404/invites",
        json={"email": "a@b.in"},
        headers=csrf(admin),
    )
    assert r.status_code == 404


async def test_invite_accept_applies_the_password_policy_as_422(
    api_app: FastAPI, memdb: MemoryDatabase, make_client: Callable[[], AsyncClient]
) -> None:
    """Regression: a policy failure here used to surface as a 500."""
    admin = await _admin(api_app, memdb, make_client())
    fac = (await admin.post("/api/v1/admin/facilities", json=FACILITY, headers=csrf(admin))).json()
    inv = await admin.post(
        f"/api/v1/admin/facilities/{fac['id']}/invites",
        json={"email": "staff@bank.in"},
        headers=csrf(admin),
    )
    token = inv.json()["accept_path"].rsplit("/", 1)[1]
    body = {"token": token, "full_name": "Rina Sen", "mobile": "9830012345"}
    r = await make_client().post(
        "/api/v1/auth/invites/accept", json={**body, "password": "my-staff-passphrase"}
    )
    assert r.status_code == 422
    assert r.json()["errors"][0]["loc"] == ["body", "password"]
    assert "staff@bank.in" not in r.text


async def test_seed_demo_admin_is_idempotent_and_flagged(
    api_app: FastAPI, memdb: MemoryDatabase, api: AsyncClient
) -> None:
    from app.persistence.memory import MemoryUnitOfWork
    from app.scripts.seed_demo import ensure_demo_admin

    kwargs = {
        "hasher": api_app.state.hasher,
        "clock": api_app.state.clock,
        "email": "admin@veyra.demo",
        "password": "demo-admin-passphrase",
    }
    user, created = await ensure_demo_admin(MemoryUnitOfWork(memdb), **kwargs)
    again, created_again = await ensure_demo_admin(MemoryUnitOfWork(memdb), **kwargs)
    assert created and not created_again and again.id == user.id
    assert user.is_demo and user.role == "ADMIN" and user.status == "active"
    await login(api, "admin@veyra.demo", "demo-admin-passphrase")
    assert (await api.get("/api/v1/admin/users")).status_code == 200
