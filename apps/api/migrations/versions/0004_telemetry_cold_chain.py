"""Phase 5: simulated smart-bag devices, telemetry readings, cold-chain trace events.

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)
TS = sa.DateTime(timezone=True)
OLD_EVENTS = "event_type IN ('COLLECTED', 'DISPATCHED', 'RECEIVED', 'DISCARDED')"
NEW_EVENTS = (
    "event_type IN ('COLLECTED', 'DISPATCHED', 'RECEIVED', 'DISCARDED', "
    "'DEVICE_ATTACHED', 'TEMP_EXCURSION', 'TEMP_RECOVERED')"
)


def upgrade() -> None:
    op.create_table(
        "devices",
        sa.Column("id", UUID, nullable=False),
        sa.Column("device_id", sa.String(24), nullable=False),
        sa.Column("rfid", sa.String(32), nullable=False),
        sa.Column("bag_id", UUID, nullable=False),
        sa.Column("simulated", sa.Boolean(), nullable=False),
        sa.Column("battery_pct", sa.Float(), nullable=False),
        sa.Column("last_seen_at", TS, nullable=True),
        sa.Column("readings_count", sa.Integer(), nullable=False),
        sa.Column("last_temperature_c", sa.Float(), nullable=True),
        sa.Column("sim_running", sa.Boolean(), nullable=False),
        sa.Column("sim_mode", sa.String(16), nullable=False),
        sa.Column("sim_mode_step", sa.Integer(), nullable=False),
        sa.Column("cold_chain_status", sa.String(16), nullable=False),
        sa.Column("excursion_started_at", TS, nullable=True),
        sa.Column("excursion_severity", sa.String(16), nullable=True),
        sa.Column("excursion_peak_c", sa.Float(), nullable=True),
        sa.Column("attached_at", TS, nullable=False),
        sa.Column("updated_at", TS, nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_devices"),
        sa.CheckConstraint(
            "battery_pct >= 0 AND battery_pct <= 100", name=op.f("ck_devices_battery_valid")
        ),
        sa.CheckConstraint(
            "sim_mode IN ('normal', 'excursion', 'recovering')",
            name=op.f("ck_devices_sim_mode_valid"),
        ),
        sa.CheckConstraint(
            "cold_chain_status IN ('unknown', 'normal', 'warning', 'critical')",
            name=op.f("ck_devices_cold_chain_status_valid"),
        ),
        sa.UniqueConstraint("device_id", name="uq_devices_device_id"),
        sa.UniqueConstraint("rfid", name="uq_devices_rfid"),
        sa.UniqueConstraint("bag_id", name="uq_devices_bag_id"),
        sa.ForeignKeyConstraint(
            ["bag_id"], ["trace.blood_bags.id"], name="fk_devices_bag_id_blood_bags"
        ),
        schema="telemetry",
    )

    op.create_table(
        "readings",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("device_pk", UUID, nullable=False),
        sa.Column("bag_id", UUID, nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("recorded_at", TS, nullable=False),
        sa.Column("temperature_c", sa.Float(), nullable=False),
        sa.Column("battery_pct", sa.Float(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("simulated", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_readings"),
        sa.CheckConstraint(
            "status IN ('normal', 'warning', 'critical')", name=op.f("ck_readings_status_valid")
        ),
        sa.CheckConstraint(
            "battery_pct >= 0 AND battery_pct <= 100", name=op.f("ck_readings_battery_valid")
        ),
        sa.UniqueConstraint("device_pk", "seq", name="uq_readings_device_pk_seq"),
        sa.ForeignKeyConstraint(
            ["device_pk"], ["telemetry.devices.id"], name="fk_readings_device_pk_devices"
        ),
        sa.ForeignKeyConstraint(
            ["bag_id"], ["trace.blood_bags.id"], name="fk_readings_bag_id_blood_bags"
        ),
        schema="telemetry",
    )
    op.create_index(
        "ix_telemetry_readings_device_pk", "readings", ["device_pk"], schema="telemetry"
    )
    op.create_index("ix_telemetry_readings_bag_id", "readings", ["bag_id"], schema="telemetry")

    # Readings are append-only, like the bag trace and the audit log.
    op.execute(
        """
        CREATE FUNCTION telemetry.forbid_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          RAISE EXCEPTION 'telemetry.readings is append-only';
        END;
        $$;
        """
    )
    op.execute(
        "CREATE TRIGGER readings_append_only BEFORE UPDATE OR DELETE ON telemetry.readings "
        "FOR EACH ROW EXECUTE FUNCTION telemetry.forbid_mutation();"
    )

    # Cold-chain observation events join the existing append-only, hash-chained trace.
    op.execute("ALTER TABLE trace.bag_events DROP CONSTRAINT ck_bag_events_event_type_valid")
    op.execute(
        "ALTER TABLE trace.bag_events ADD CONSTRAINT ck_bag_events_event_type_valid "
        f"CHECK ({NEW_EVENTS})"
    )


def downgrade() -> None:
    # The trace is append-only, so cold-chain events can't be deleted. The old constraint is
    # restored NOT VALID: it applies to new rows while existing history stays intact.
    op.execute("ALTER TABLE trace.bag_events DROP CONSTRAINT ck_bag_events_event_type_valid")
    op.execute(
        "ALTER TABLE trace.bag_events ADD CONSTRAINT ck_bag_events_event_type_valid "
        f"CHECK ({OLD_EVENTS}) NOT VALID"
    )
    op.execute("DROP TRIGGER IF EXISTS readings_append_only ON telemetry.readings")
    op.execute("DROP FUNCTION IF EXISTS telemetry.forbid_mutation()")
    op.drop_index("ix_telemetry_readings_bag_id", table_name="readings", schema="telemetry")
    op.drop_index("ix_telemetry_readings_device_pk", table_name="readings", schema="telemetry")
    op.drop_table("readings", schema="telemetry")
    op.drop_table("devices", schema="telemetry")
