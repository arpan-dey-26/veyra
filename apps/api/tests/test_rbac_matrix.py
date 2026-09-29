"""RBAC matrix: every Phase 1 and Phase 2 endpoint x every role (+ anonymous) → expected status.

This is the contract for the security boundary. Adding an endpoint means adding a row.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest
from fastapi import FastAPI
from httpx import AsyncClient

from app.core.rbac import ROLE_PERMISSIONS, Permission, Role
from app.persistence.memory import MemoryDatabase
from tests.conftest import csrf, login, register_and_verify, seed_user

ROLES = ("ANON", "DONOR", "HOSPITAL", "BLOOD_BANK", "ADMIN")

FACILITY_BODY = {
    "type": "HOSPITAL",
    "name": "Matrix General Hospital",
    "address": "2 Matrix Road",
    "city": "Kolkata",
    "state": "West Bengal",
    "pin_code": "700002",
}

_UUID = "0190f5d2-0000-7000-8000-000000000000"
_BAG = "VYR-0000-0000"

# (method, path, json body, {role: expected status})
MATRIX: list[tuple[str, str, dict[str, object] | None, dict[str, int]]] = [
    (
        "GET",
        "/api/v1/auth/me",
        None,
        {"ANON": 401, "DONOR": 200, "HOSPITAL": 200, "BLOOD_BANK": 200, "ADMIN": 200},
    ),
    (
        "GET",
        "/api/v1/donors/me",
        None,
        {"ANON": 401, "DONOR": 200, "HOSPITAL": 403, "BLOOD_BANK": 403, "ADMIN": 403},
    ),
    (
        "PATCH",
        "/api/v1/donors/me",
        {"city": "Durgapur"},
        {"ANON": 401, "DONOR": 200, "HOSPITAL": 403, "BLOOD_BANK": 403, "ADMIN": 403},
    ),
    (
        "GET",
        "/api/v1/facilities/me",
        None,
        {"ANON": 401, "DONOR": 403, "HOSPITAL": 200, "BLOOD_BANK": 200, "ADMIN": 403},
    ),
    (
        "GET",
        "/api/v1/admin/users",
        None,
        {"ANON": 401, "DONOR": 403, "HOSPITAL": 403, "BLOOD_BANK": 403, "ADMIN": 200},
    ),
    (
        "GET",
        "/api/v1/admin/facilities",
        None,
        {"ANON": 401, "DONOR": 403, "HOSPITAL": 403, "BLOOD_BANK": 403, "ADMIN": 200},
    ),
    (
        "POST",
        "/api/v1/admin/facilities",
        FACILITY_BODY,
        {"ANON": 401, "DONOR": 403, "HOSPITAL": 403, "BLOOD_BANK": 403, "ADMIN": 201},
    ),
    # ---------------------------------------------------------------- Phase 2
    # Unknown ids give 404 for callers who hold the permission: the scope check runs after it.
    (
        "GET",
        "/api/v1/inventory/summary",
        None,
        {"ANON": 401, "DONOR": 403, "HOSPITAL": 200, "BLOOD_BANK": 200, "ADMIN": 403},
    ),
    (
        "GET",
        "/api/v1/inventory/bags",
        None,
        {"ANON": 401, "DONOR": 403, "HOSPITAL": 200, "BLOOD_BANK": 200, "ADMIN": 403},
    ),
    (
        "GET",
        f"/api/v1/bags/{_BAG}",
        None,
        {"ANON": 401, "DONOR": 403, "HOSPITAL": 404, "BLOOD_BANK": 404, "ADMIN": 404},
    ),
    (
        "POST",
        f"/api/v1/bags/{_BAG}/discard",
        {"reason": "damaged"},
        {"ANON": 401, "DONOR": 403, "HOSPITAL": 403, "BLOOD_BANK": 404, "ADMIN": 403},
    ),
    (
        "POST",
        "/api/v1/donors/lookup",
        {"mobile": "9000000099"},
        {"ANON": 401, "DONOR": 403, "HOSPITAL": 403, "BLOOD_BANK": 404, "ADMIN": 403},
    ),
    (
        "POST",
        "/api/v1/donations",
        {"donor_id": _UUID, "blood_group": "O+", "volume_ml": 450},
        {"ANON": 401, "DONOR": 403, "HOSPITAL": 403, "BLOOD_BANK": 404, "ADMIN": 403},
    ),
    (
        "GET",
        "/api/v1/donations",
        None,
        {"ANON": 401, "DONOR": 403, "HOSPITAL": 403, "BLOOD_BANK": 200, "ADMIN": 403},
    ),
    (
        "GET",
        "/api/v1/donors/me/donations",
        None,
        {"ANON": 401, "DONOR": 200, "HOSPITAL": 403, "BLOOD_BANK": 403, "ADMIN": 403},
    ),
    (
        "GET",
        "/api/v1/network/availability?blood_group=O%2B&component=PRBC&units=2",
        None,
        {"ANON": 401, "DONOR": 403, "HOSPITAL": 200, "BLOOD_BANK": 403, "ADMIN": 403},
    ),
    (
        "POST",
        "/api/v1/requests",
        {
            "target_ref": _UUID,
            "blood_group": "O+",
            "component": "PRBC",
            "units": 1,
            "needed_by": "2026-12-01T00:00:00Z",
        },
        {"ANON": 401, "DONOR": 403, "HOSPITAL": 422, "BLOOD_BANK": 403, "ADMIN": 403},
    ),
    (
        "GET",
        "/api/v1/requests",
        None,
        {"ANON": 401, "DONOR": 403, "HOSPITAL": 200, "BLOOD_BANK": 200, "ADMIN": 403},
    ),
    (
        "GET",
        f"/api/v1/requests/{_UUID}",
        None,
        {"ANON": 401, "DONOR": 403, "HOSPITAL": 404, "BLOOD_BANK": 404, "ADMIN": 403},
    ),
    (
        "POST",
        f"/api/v1/requests/{_UUID}/fulfil",
        {},
        {"ANON": 401, "DONOR": 403, "HOSPITAL": 403, "BLOOD_BANK": 404, "ADMIN": 403},
    ),
    (
        "POST",
        f"/api/v1/requests/{_UUID}/reject",
        {"note": "No stock"},
        {"ANON": 401, "DONOR": 403, "HOSPITAL": 403, "BLOOD_BANK": 404, "ADMIN": 403},
    ),
    (
        "POST",
        f"/api/v1/requests/{_UUID}/cancel",
        None,
        {"ANON": 401, "DONOR": 403, "HOSPITAL": 404, "BLOOD_BANK": 403, "ADMIN": 403},
    ),
    (
        "POST",
        f"/api/v1/requests/{_UUID}/receive",
        None,
        {"ANON": 401, "DONOR": 403, "HOSPITAL": 404, "BLOOD_BANK": 403, "ADMIN": 403},
    ),
    # ---------------------------------------------------------------- Phase 3
    (
        "GET",
        "/api/v1/dashboard/facility",
        None,
        {"ANON": 401, "DONOR": 403, "HOSPITAL": 200, "BLOOD_BANK": 200, "ADMIN": 403},
    ),
    (
        "GET",
        "/api/v1/dashboard/admin",
        None,
        {"ANON": 401, "DONOR": 403, "HOSPITAL": 403, "BLOOD_BANK": 403, "ADMIN": 200},
    ),
    (
        "GET",
        "/api/v1/network/graph",
        None,
        {"ANON": 401, "DONOR": 403, "HOSPITAL": 200, "BLOOD_BANK": 200, "ADMIN": 200},
    ),
    (
        "GET",
        "/api/v1/stream?once=true",
        None,
        {"ANON": 401, "DONOR": 403, "HOSPITAL": 200, "BLOOD_BANK": 200, "ADMIN": 200},
    ),
]


@pytest.fixture
async def clients(
    api_app: FastAPI, memdb: MemoryDatabase, make_client: Callable[[], AsyncClient]
) -> dict[str, AsyncClient]:
    out = {role: make_client() for role in ROLES}
    await register_and_verify(out["DONOR"])
    await seed_user(
        api_app,
        memdb,
        role="HOSPITAL",
        email="h@x.in",
        mobile="+919000000001",
        facility_type="HOSPITAL",
    )
    await seed_user(
        api_app,
        memdb,
        role="BLOOD_BANK",
        email="b@x.in",
        mobile="+919000000002",
        facility_type="BLOOD_BANK",
    )
    await seed_user(api_app, memdb, role="ADMIN", email="a@x.in", mobile="+919000000003")
    await login(out["HOSPITAL"], "h@x.in")
    await login(out["BLOOD_BANK"], "b@x.in")
    await login(out["ADMIN"], "a@x.in")
    return out


@pytest.mark.parametrize("role", ROLES)
@pytest.mark.parametrize(("method", "path", "body", "expected"), MATRIX, ids=lambda x: str(x)[:40])
async def test_rbac_matrix(
    clients: dict[str, AsyncClient],
    role: str,
    method: str,
    path: str,
    body: dict[str, object] | None,
    expected: dict[str, int],
) -> None:
    client = clients[role]
    r = await client.request(method, path, json=body, headers=csrf(client))
    assert r.status_code == expected[role], f"{role} {method} {path}: {r.status_code} {r.text}"


async def test_facility_users_only_see_their_own_facility(
    clients: dict[str, AsyncClient], memdb: MemoryDatabase
) -> None:
    hospital = (await clients["HOSPITAL"].get("/api/v1/facilities/me")).json()
    bank = (await clients["BLOOD_BANK"].get("/api/v1/facilities/me")).json()
    assert hospital["type"] == "HOSPITAL" and bank["type"] == "BLOOD_BANK"
    assert hospital["id"] != bank["id"]
    me = (await clients["HOSPITAL"].get("/api/v1/auth/me")).json()
    assert me["facility"]["id"] == hospital["id"]
    assert me["donor"] is None


async def test_hospital_never_receives_donor_data(clients: dict[str, AsyncClient]) -> None:
    me = (await clients["HOSPITAL"].get("/api/v1/auth/me")).json()
    assert not any(
        p.startswith(("donor_profile", "donation", "eligibility")) for p in me["permissions"]
    )
    assert (await clients["HOSPITAL"].get("/api/v1/donors/me")).status_code == 403


async def test_admin_user_list_never_exposes_secrets(clients: dict[str, AsyncClient]) -> None:
    r = await clients["ADMIN"].get("/api/v1/admin/users")
    assert r.status_code == 200
    page = r.json()
    assert page["meta"]["total"] == 4
    for user in page["data"]:
        assert set(user) == {
            "id",
            "email",
            "full_name",
            "mobile",
            "role",
            "status",
            "is_demo",
            "verified_at",
            "created_at",
        }
    only_donors = await clients["ADMIN"].get("/api/v1/admin/users", params={"role": "DONOR"})
    assert [u["role"] for u in only_donors.json()["data"]] == ["DONOR"]


def test_role_permission_map_is_strictly_separated() -> None:
    donor, hospital, bank, admin = (ROLE_PERMISSIONS[r] for r in Role)
    donor_only = {
        p
        for p in Permission
        if p.value.endswith(":self") and p.value.startswith(("donor", "donation", "eligibility"))
    }
    assert donor_only <= donor
    assert not donor_only & (hospital | bank | admin)
    assert Permission.USER_MANAGE in admin and not {Permission.USER_MANAGE} & (
        donor | hospital | bank
    )
    assert (
        Permission.BLOOD_REQUEST_CREATE in hospital and Permission.BLOOD_REQUEST_CREATE not in bank
    )
    assert (
        Permission.BLOOD_REQUEST_RESPOND in bank
        and Permission.BLOOD_REQUEST_RESPOND not in hospital
    )
    for perm in Permission:
        assert perm.value.count(":") in (1, 2), perm
