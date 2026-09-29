"""Vercel build step (``[tool.vercel.scripts] build``): runs after dependencies are installed.

Production builds apply the Alembic migrations to the connected database (the platform's
Postgres URL is read by ``Settings``) and seed the labelled DEMO accounts/facilities when
``VEYRA_DEMO_ADMIN_PASSWORD`` is configured. Both steps are idempotent; nothing runs for
preview builds, so previews never migrate the shared database.
"""

from __future__ import annotations

import os
import subprocess
import sys


def run(*args: str) -> None:
    print("$", " ".join(args), flush=True)
    subprocess.run([sys.executable, *args], check=True)  # noqa: S603 - fixed argv


def main() -> None:
    if os.environ.get("VERCEL_ENV") != "production":
        print("Preview build: migrations and demo seeding skipped.")
        return
    run("-m", "alembic", "upgrade", "head")
    if os.environ.get("VEYRA_DEMO_ADMIN_PASSWORD"):
        run("-m", "app.scripts.seed_demo")
    else:
        print("VEYRA_DEMO_ADMIN_PASSWORD not set: demo accounts not seeded.")


if __name__ == "__main__":
    main()
