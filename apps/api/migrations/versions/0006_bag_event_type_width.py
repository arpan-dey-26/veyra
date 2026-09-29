"""Phase 7: widen trace.bag_events.event_type for the shipment observation event names.

SHIPMENT_IN_TRANSIT and friends are longer than 16 characters. Widening a varchar keeps every
stored row, and so every trace hash, exactly as it was.

Revision ID: 0006
Revises: 0005
Create Date: 2026-09-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "bag_events",
        "event_type",
        existing_type=sa.String(16),
        type_=sa.String(32),
        existing_nullable=False,
        schema="trace",
    )


def downgrade() -> None:
    # The trace is append-only: narrow the column back only if no stored event needs the width.
    op.execute(
        """
        DO $$
        BEGIN
          IF NOT EXISTS (SELECT 1 FROM trace.bag_events WHERE length(event_type) > 16) THEN
            ALTER TABLE trace.bag_events ALTER COLUMN event_type TYPE VARCHAR(16);
          END IF;
        END;
        $$;
        """
    )
