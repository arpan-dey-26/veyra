"""Create the demo administrator and demo facilities (DEMO environments only).

Usage:  python -m app.scripts.seed_demo [--email admin@veyra.demo] [--no-network]

Also creates (idempotently) one DEMO blood bank and one DEMO hospital, each with a staff
account that uses the same documented DEMO ONLY password as the admin.
Password: $VEYRA_DEMO_ADMIN_PASSWORD, or a random one printed once.
The bootstrap uses the documented DEMO ONLY credentials below. The password must pass the
normal policy (it may not contain the email name "admin"), which is validated before use.
The account is flagged ``is_demo`` and the script refuses to run in production.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import secrets
import sys

from app.core.clock import Clock, SystemClock
from app.core.config import Settings, get_settings
from app.core.db import Database
from app.core.ids import uuid7
from app.core.rbac import Role
from app.core.security import PasswordHasher
from app.core.validation import normalize_email, validate_new_password
from app.modules.audit.service import record
from app.modules.facilities.models import Facility, FacilityMembership
from app.modules.identity.models import User
from app.persistence.repositories import UnitOfWork
from app.persistence.sql import SqlUnitOfWork

DEMO_ADMIN_MOBILE = "+919000000000"
DEMO_ADMIN_EMAIL = "admin@veyra.demo"
# DEMO ONLY. Documented in README / phase-1 report; used by scripts/bootstrap.ps1.
DEMO_ADMIN_PASSWORD = "veyra-demo-console-2026"  # noqa: S105 - documented DEMO-only credential

# DEMO ONLY facilities + staff (same documented password). Names carry "(Demo)".
DEMO_FACILITIES: tuple[dict[str, str], ...] = (
    {
        "type": "BLOOD_BANK",
        "name": "VEYRA Central Blood Bank (Demo)",
        "registration_number": "DEMO-BB-0001",
        "staff_email": "bank@veyra.demo",
        "staff_name": "Demo Blood Bank Officer",
        "staff_mobile": "+919000000001",
        "address": "1 Demo Blood Bank Road, Salt Lake",
        "pin_code": "700091",
    },
    {
        "type": "HOSPITAL",
        "name": "VEYRA City Hospital (Demo)",
        "registration_number": "DEMO-HOSP-0001",
        "staff_email": "hospital@veyra.demo",
        "staff_name": "Demo Hospital Coordinator",
        "staff_mobile": "+919000000002",
        "address": "2 Demo Hospital Road, Park Street",
        "pin_code": "700016",
    },
)


async def ensure_demo_admin(
    uow: UnitOfWork,
    *,
    hasher: PasswordHasher,
    clock: Clock,
    email: str,
    password: str,
    mobile: str = DEMO_ADMIN_MOBILE,
) -> tuple[User, bool]:
    """Idempotent: returns (user, created)."""
    existing = await uow.users.get_by_email(email)
    if existing is not None:
        return existing, False
    now = clock.now()
    user = User(
        id=uuid7(),
        email=email,
        mobile=mobile,
        full_name="VEYRA Demo Admin",
        password_hash=hasher.hash(password),
        role=Role.ADMIN.value,
        status="active",
        is_demo=True,
        verified_at=now,
        failed_login_count=0,
        locked_until=None,
        last_login_at=None,
        created_at=now,
        updated_at=now,
    )
    await uow.users.add(user)
    await record(
        uow,
        clock,
        action="seed.demo_admin",
        resource="user",
        resource_id=user.id,
        actor_type="system",
    )
    await uow.commit()
    return user, True


async def ensure_demo_network(
    uow: UnitOfWork, *, hasher: PasswordHasher, clock: Clock, password: str
) -> list[tuple[str, bool]]:
    """Idempotent: one DEMO blood bank + one DEMO hospital with a staff login each.

    Returns [(staff_email, created)]. Facilities are internal (real VEYRA workflows on demo
    data), not simulated partners: the simulated partners come from MockBloodBankProvider.
    """
    out: list[tuple[str, bool]] = []
    for spec in DEMO_FACILITIES:
        validate_new_password(password, email=spec["staff_email"])
        if await uow.users.get_by_email(spec["staff_email"]) is not None:
            out.append((spec["staff_email"], False))
            continue
        now = clock.now()
        facility = await uow.facilities.get_by_registration_number(spec["registration_number"])
        if facility is None:
            facility = Facility(
                id=uuid7(),
                type=spec["type"],
                name=spec["name"],
                registration_number=spec["registration_number"],
                address=spec["address"],
                city="Kolkata",
                state="West Bengal",
                pin_code=spec["pin_code"],
                provider_kind="internal",
                is_simulated=False,
                status="active",
                created_at=now,
                updated_at=now,
            )
            await uow.facilities.add(facility)
        user = User(
            id=uuid7(),
            email=spec["staff_email"],
            mobile=spec["staff_mobile"],
            full_name=spec["staff_name"],
            password_hash=hasher.hash(password),
            role=spec["type"],
            status="active",
            is_demo=True,
            verified_at=now,
            failed_login_count=0,
            locked_until=None,
            last_login_at=None,
            created_at=now,
            updated_at=now,
        )
        await uow.users.add(user)
        await uow.facilities.add_membership(
            FacilityMembership(user_id=user.id, facility_id=facility.id, created_at=now)
        )
        await record(
            uow,
            clock,
            action="seed.demo_facility",
            resource="facility",
            resource_id=facility.id,
            actor_type="system",
        )
        out.append((spec["staff_email"], True))
    await uow.commit()
    return out


async def _main(settings: Settings, email: str, *, network: bool = True) -> int:
    if settings.is_production:
        print("Refusing to seed demo accounts in production.", file=sys.stderr)
        return 2
    password = os.environ.get("VEYRA_DEMO_ADMIN_PASSWORD") or f"veyra-demo-{secrets.token_hex(6)}"
    validate_new_password(password, email=email)
    db = Database(settings.database_url)
    try:
        async with db.sessionmaker() as session:
            user, created = await ensure_demo_admin(
                SqlUnitOfWork(session),
                hasher=PasswordHasher.from_settings(settings),
                clock=SystemClock(),
                email=email,
                password=password,
            )
            staff = (
                await ensure_demo_network(
                    SqlUnitOfWork(session),
                    hasher=PasswordHasher.from_settings(settings),
                    clock=SystemClock(),
                    password=password,
                )
                if network
                else []
            )
    finally:
        await db.dispose()
    if created:
        print(f"[DEMO] Admin created: {user.email}")
        print(f"[DEMO] Password: {password}   (shown once; set VEYRA_DEMO_ADMIN_PASSWORD to pick)")
    else:
        print(f"[DEMO] Admin already exists: {user.email} (password unchanged)")
    for staff_email, staff_created in staff:
        state = "created" if staff_created else "already exists (password unchanged)"
        print(f"[DEMO] Facility staff {staff_email}: {state}")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email", default=DEMO_ADMIN_EMAIL)
    parser.add_argument("--no-network", action="store_true", help="admin only, no demo facilities")
    args = parser.parse_args()
    raise SystemExit(
        asyncio.run(_main(get_settings(), normalize_email(args.email), network=not args.no_network))
    )


if __name__ == "__main__":
    main()
