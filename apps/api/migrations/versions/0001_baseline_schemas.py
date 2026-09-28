"""Baseline: create VEYRA domain schemas (no tables yet).

Revision ID: 0001
Revises:
Create Date: 2026-09-28
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMAS = ("identity", "network", "trace", "telemetry", "ai", "ml", "audit")


def upgrade() -> None:
    for schema in SCHEMAS:
        op.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')


def downgrade() -> None:
    for schema in reversed(SCHEMAS):
        # RESTRICT: never silently drop data-bearing schemas.
        op.execute(f'DROP SCHEMA IF EXISTS "{schema}" RESTRICT')
