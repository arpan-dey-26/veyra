"""Create the demo administrator (DEMO environments only).

Usage:  python -m app.scripts.seed_demo [--email admin@veyra.demo]
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
from app.modules.identity.models import User
from app.persistence.repositories import UnitOfWork
from app.persistence.sql import SqlUnitOfWork

DEMO_ADMIN_MOBILE = "+919000000000"
DEMO_ADMIN_EMAIL = "admin@veyra.demo"
# DEMO ONLY. Documented in README / phase-1 report; used by scripts/bootstrap.ps1.
DEMO_ADMIN_PASSWORD = "veyra-demo-console-2026"  # noqa: S105 - documented DEMO-only credential


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


async def _main(settings: Settings, email: str) -> int:
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
    finally:
        await db.dispose()
    if created:
        print(f"[DEMO] Admin created: {user.email}")
        print(f"[DEMO] Password: {password}   (shown once; set VEYRA_DEMO_ADMIN_PASSWORD to pick)")
    else:
        print(f"[DEMO] Admin already exists: {user.email} (password unchanged)")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email", default=DEMO_ADMIN_EMAIL)
    args = parser.parse_args()
    raise SystemExit(asyncio.run(_main(get_settings(), normalize_email(args.email))))


if __name__ == "__main__":
    main()
