"""Phase 1: registration → demo verification → sessions (in-memory unit of work)."""

from __future__ import annotations

from collections.abc import Callable

from httpx import AsyncClient

from app.persistence.memory import MemoryDatabase
from app.providers.verification import DEMO_DISCLAIMER
from tests.conftest import (
    PASSWORD,
    MutableClock,
    csrf,
    donor_payload,
    login,
    register_and_verify,
)

REGISTER = "/api/v1/auth/register"
VERIFY = "/api/v1/auth/verify"
LOGIN = "/api/v1/auth/login"
ME = "/api/v1/auth/me"
REFRESH = "/api/v1/auth/refresh"
LOGOUT = "/api/v1/auth/logout"

EXACT_DISCLAIMER = (
    "Demo verification only. The last 4 digits of your mobile number are used for "
    "prototype verification instead of a real OTP."
)


async def test_register_creates_pending_donor_with_labelled_demo_verification(
    api: AsyncClient,
) -> None:
    r = await api.post(REGISTER, json=donor_payload())
    assert r.status_code == 201
    body = r.json()
    assert body["user"]["status"] == "pending_verification"
    assert body["user"]["role"] == "DONOR"
    assert body["user"]["email"] == "arpan@example.in"
    assert body["user"]["mobile"] == "+919876543210"
    v = body["verification"]
    assert v["mode"] == "demo"
    assert v["provider"] == "demo_last4"
    assert v["disclaimer"] == EXACT_DISCLAIMER == DEMO_DISCLAIMER
    assert v["attempts_remaining"] == 5
    assert "3210" not in v["destination_hint"]  # the hint never reveals the demo code
    assert "password" not in r.text and "hash" not in r.text
    assert "veyra_access" not in r.cookies  # no session before verification


async def test_register_rejects_duplicates(api: AsyncClient) -> None:
    assert (await api.post(REGISTER, json=donor_payload())).status_code == 201
    dup_email = await api.post(REGISTER, json=donor_payload(mobile="9123456780"))
    assert dup_email.status_code == 409
    assert dup_email.json()["code"] == "email_taken"
    dup_mobile = await api.post(REGISTER, json=donor_payload(email="other@example.in"))
    assert dup_mobile.status_code == 409
    assert dup_mobile.json()["code"] == "mobile_taken"


async def test_register_validates_every_field_without_echoing_input(api: AsyncClient) -> None:
    bad = donor_payload(
        full_name="X",
        email="not-an-email",
        mobile="12345",
        blood_group="Z+",
        address="abc",
        city="12",
        state="Atlantis",
        pin_code="012345",
        password="short",
    )
    r = await api.post(REGISTER, json=bad)
    assert r.status_code == 422
    fields = {tuple(e["loc"])[-1] for e in r.json()["errors"]}
    assert fields == {
        "full_name",
        "email",
        "mobile",
        "blood_group",
        "address",
        "city",
        "state",
        "pin_code",
        "password",
    }
    assert "Atlantis" not in r.text and "not-an-email" not in r.text


async def test_register_rejects_unknown_fields(api: AsyncClient) -> None:
    r = await api.post(REGISTER, json={**donor_payload(), "role": "ADMIN"})
    assert r.status_code == 422


async def test_login_before_verification_requires_verification(api: AsyncClient) -> None:
    await api.post(REGISTER, json=donor_payload())
    r = await api.post(LOGIN, json={"email": "arpan@example.in", "password": PASSWORD})
    assert r.status_code == 403
    assert r.json()["code"] == "verification_required"
    restart = await api.post(
        "/api/v1/auth/verify/start", json={"email": "arpan@example.in", "password": PASSWORD}
    )
    assert restart.status_code == 200
    assert restart.json()["mode"] == "demo"


async def test_verify_start_requires_the_password(api: AsyncClient) -> None:
    await api.post(REGISTER, json=donor_payload())
    r = await api.post(
        "/api/v1/auth/verify/start", json={"email": "arpan@example.in", "password": "wrong-pass-1"}
    )
    assert r.status_code == 401
    assert r.json()["code"] == "invalid_credentials"


async def test_wrong_codes_are_counted_and_then_locked(api: AsyncClient) -> None:
    challenge = (await api.post(REGISTER, json=donor_payload())).json()["verification"]
    cid = challenge["challenge_id"]
    for remaining in (4, 3, 2, 1):
        r = await api.post(VERIFY, json={"challenge_id": cid, "code": "0000"})
        assert r.status_code == 400
        assert r.json()["code"] == "invalid_code"
        assert f"{remaining} attempt" in r.json()["detail"]
    fifth = await api.post(VERIFY, json={"challenge_id": cid, "code": "0000"})
    assert fifth.status_code == 429
    correct_but_locked = await api.post(VERIFY, json={"challenge_id": cid, "code": "3210"})
    assert correct_but_locked.status_code == 429


async def test_expired_challenge_is_rejected(api: AsyncClient, clock: MutableClock) -> None:
    cid = (await api.post(REGISTER, json=donor_payload())).json()["verification"]["challenge_id"]
    clock.advance(minutes=16)
    r = await api.post(VERIFY, json={"challenge_id": cid, "code": "3210"})
    assert r.status_code == 410
    assert r.json()["code"] == "challenge_expired"


async def test_verify_with_last4_activates_and_signs_in(
    api: AsyncClient, memdb: MemoryDatabase
) -> None:
    me = await register_and_verify(api)
    assert me["user"]["status"] == "active"  # type: ignore[index]
    assert me["donor"] == {"blood_group": "O+", "city": "Kolkata", "state": "West Bengal"}
    assert "donor_profile:read:self" in me["permissions"]  # type: ignore[operator]
    for name in ("veyra_access", "veyra_refresh", "veyra_csrf"):
        assert api.cookies.get(name), name
    r = await api.get(ME)
    assert r.status_code == 200
    assert r.json()["user"]["email"] == "arpan@example.in"
    actions = [a.action for a in memdb.audit]
    assert actions[:2] == ["auth.register", "auth.verify"]
    assert all("password" not in str(a.meta) for a in memdb.audit)


async def test_challenge_cannot_be_reused(api: AsyncClient) -> None:
    cid = (await api.post(REGISTER, json=donor_payload())).json()["verification"]["challenge_id"]
    assert (await api.post(VERIFY, json={"challenge_id": cid, "code": "3210"})).status_code == 200
    again = await api.post(VERIFY, json={"challenge_id": cid, "code": "3210"})
    assert again.status_code == 404


async def test_me_requires_authentication(api: AsyncClient) -> None:
    r = await api.get(ME)
    assert r.status_code == 401
    assert r.json()["code"] == "unauthenticated"


async def test_login_errors_are_generic_and_lock_after_repeated_failures(
    api: AsyncClient, make_client: Callable[[], AsyncClient]
) -> None:
    await register_and_verify(api)
    other = make_client()
    unknown = await other.post(LOGIN, json={"email": "nobody@example.in", "password": PASSWORD})
    wrong = await other.post(LOGIN, json={"email": "arpan@example.in", "password": "Wrong-pass-1"})
    assert unknown.status_code == wrong.status_code == 401
    assert unknown.json()["code"] == wrong.json()["code"] == "invalid_credentials"
    for _ in range(4):  # 1 failure above + 4 = 5 → locked
        await other.post(LOGIN, json={"email": "arpan@example.in", "password": "Wrong-pass-1"})
    locked = await other.post(LOGIN, json={"email": "arpan@example.in", "password": PASSWORD})
    assert locked.status_code == 423
    assert locked.json()["code"] == "account_locked"


async def test_lockout_expires(api: AsyncClient, clock: MutableClock) -> None:
    await register_and_verify(api)
    for _ in range(5):
        await api.post(LOGIN, json={"email": "arpan@example.in", "password": "Wrong-pass-1"})
    clock.advance(minutes=16)
    await login(api, "arpan@example.in")


async def test_refresh_rotates_and_replay_revokes_the_family(
    api: AsyncClient, make_client: Callable[[], AsyncClient]
) -> None:
    await register_and_verify(api)
    old_refresh = api.cookies.get("veyra_refresh", path="/api/v1/auth")
    old_access = api.cookies.get("veyra_access")
    r = await api.post(REFRESH, headers=csrf(api))
    assert r.status_code == 200
    new_refresh = api.cookies.get("veyra_refresh", path="/api/v1/auth")
    assert new_refresh and new_refresh != old_refresh

    # An attacker replays the stolen (already rotated) refresh token…
    attacker = make_client()
    attacker.cookies.set("veyra_refresh", old_refresh or "", path="/api/v1/auth")
    attacker.cookies.set("veyra_csrf", "x" * 20)
    replay = await attacker.post(REFRESH, headers={"x-csrf-token": "x" * 20})
    assert replay.status_code == 401
    assert replay.json()["code"] == "session_invalid"

    # …so every session in that family is revoked, including the legitimate new one.
    assert (await api.get(ME)).status_code == 401
    bearer = await attacker.get(ME, headers={"authorization": f"Bearer {old_access}"})
    assert bearer.status_code == 401


async def test_refresh_requires_csrf_header(api: AsyncClient) -> None:
    await register_and_verify(api)
    r = await api.post(REFRESH)
    assert r.status_code == 403
    assert r.json()["code"] == "csrf_failed"


async def test_access_token_expires_but_refresh_renews(
    api: AsyncClient, clock: MutableClock
) -> None:
    await register_and_verify(api)
    clock.advance(minutes=16)
    assert (await api.get(ME)).status_code == 401
    assert (await api.post(REFRESH, headers=csrf(api))).status_code == 200
    assert (await api.get(ME)).status_code == 200


async def test_logout_revokes_the_server_session(api: AsyncClient) -> None:
    await register_and_verify(api)
    access = api.cookies.get("veyra_access")
    r = await api.post(LOGOUT, headers=csrf(api))
    assert r.status_code == 204
    assert api.cookies.get("veyra_access") is None
    # Even a copied access token stops working: the server-side session is gone.
    reused = await api.get(ME, headers={"authorization": f"Bearer {access}"})
    assert reused.status_code == 401


async def test_logout_requires_csrf_when_cookie_authenticated(api: AsyncClient) -> None:
    await register_and_verify(api)
    r = await api.post(LOGOUT)
    assert r.status_code == 403


async def test_registration_reference_lists_allowed_values(api: AsyncClient) -> None:
    r = await api.get("/api/v1/reference/registration")
    assert r.status_code == 200
    body = r.json()
    assert body["blood_groups"] == ["A+", "A-", "B+", "B-", "AB+", "AB-", "O+", "O-"]
    assert "West Bengal" in body["states"] and len(body["states"]) == 36
    assert body["verification_mode"] == "demo"
    assert body["verification_disclaimer"] == EXACT_DISCLAIMER


async def test_meta_discloses_demo_phone_verification(api: AsyncClient) -> None:
    body = (await api.get("/api/v1/meta")).json()
    components = {d["component"]: d for d in body["disclosures"]}
    assert components["phone_verification"]["detail"] == EXACT_DISCLAIMER
