"""Guards the model registry used by Alembic (a missing import = phantom remove_table)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "app"

EXPECTED_TABLES = {
    "identity.users", "identity.sessions", "identity.verification_challenges",
    "identity.facility_invites", "network.facilities", "network.facility_memberships",
    "network.donors", "audit.audit_logs", "network.donations", "trace.blood_bags",
    "trace.bag_events", "network.blood_requests", "network.request_allocations",
    "network.outbox_events", "telemetry.devices", "telemetry.readings",
    "network.shipments", "network.shipment_bags", "network.shipment_events",
}  # fmt: skip


def test_every_models_module_is_registered() -> None:
    from app.models_registry import MODEL_MODULES

    on_disk = {
        "app." + ".".join(p.relative_to(APP).with_suffix("").parts)
        for p in APP.glob("modules/*/models.py")
    }
    assert on_disk == set(MODEL_MODULES)


def test_registry_alone_yields_the_complete_metadata() -> None:
    """Fresh interpreter: import ONLY what migrations/env.py imports."""
    code = "from app.models_registry import metadata\nprint('\\n'.join(sorted(metadata.tables)))\n"
    out = subprocess.run(  # noqa: S603 - fixed argv: this interpreter + a literal snippet
        [sys.executable, "-c", code],
        cwd=APP.parent,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    assert set(out) == EXPECTED_TABLES


def test_alembic_env_uses_the_registry() -> None:
    env = (APP.parent / "migrations" / "env.py").read_text(encoding="utf-8")
    assert "from app.models_registry import metadata as target_metadata" in env
