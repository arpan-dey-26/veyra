"""Phase 7: simulated logistics — shipments, shipment bags, append-only shipment timeline.

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)
TS = sa.DateTime(timezone=True)
OLD_EVENTS = (
    "event_type IN ('COLLECTED', 'DISPATCHED', 'RECEIVED', 'DISCARDED', "
    "'DEVICE_ATTACHED', 'TEMP_EXCURSION', 'TEMP_RECOVERED')"
)
NEW_EVENTS = (
    "event_type IN ('COLLECTED', 'DISPATCHED', 'RECEIVED', 'DISCARDED', "
    "'DEVICE_ATTACHED', 'TEMP_EXCURSION', 'TEMP_RECOVERED', "
    "'SHIPMENT_CREATED', 'SHIPMENT_PICKED_UP', 'SHIPMENT_IN_TRANSIT', "
    "'SHIPMENT_DELAYED', 'SHIPMENT_ARRIVED', 'SHIPMENT_RECEIVED')"
)
STATUSES = (
    "status IN ('created', 'pickup_pending', 'picked_up', 'in_transit', 'delayed', "
    "'arrived', 'received')"
)


def upgrade() -> None:
    op.create_table(
        "shipments",
        sa.Column("id", UUID, nullable=False),
        sa.Column("reference", sa.String(16), nullable=False),
        sa.Column("request_id", UUID, nullable=False),
        sa.Column("source_facility_id", UUID, nullable=False),
        sa.Column("destination_facility_id", UUID, nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("status_before_delay", sa.String(16), nullable=True),
        sa.Column("urgency", sa.String(16), nullable=False),
        sa.Column("simulated", sa.Boolean(), nullable=False),
        sa.Column("courier_id", sa.String(24), nullable=False),
        sa.Column("courier_name", sa.String(64), nullable=False),
        sa.Column("vehicle_type", sa.String(48), nullable=False),
        sa.Column("distance_km", sa.Float(), nullable=False),
        sa.Column("planned_minutes", sa.Integer(), nullable=False),
        sa.Column("checkpoints", postgresql.JSONB(), nullable=False),
        sa.Column("current_checkpoint", sa.Integer(), nullable=False),
        sa.Column("eta_at", TS, nullable=False),
        sa.Column("delay_minutes", sa.Integer(), nullable=False),
        sa.Column("delay_active", sa.Boolean(), nullable=False),
        sa.Column("delay_reason", sa.String(32), nullable=True),
        sa.Column("cold_chain_alert", sa.String(16), nullable=False),
        sa.Column("last_update_at", TS, nullable=False),
        sa.Column("created_at", TS, nullable=False),
        sa.Column("picked_up_at", TS, nullable=True),
        sa.Column("arrived_at", TS, nullable=True),
        sa.Column("received_at", TS, nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_shipments"),
        sa.CheckConstraint(STATUSES, name=op.f("ck_shipments_status_valid")),
        sa.CheckConstraint("delay_minutes >= 0", name=op.f("ck_shipments_delay_valid")),
        sa.CheckConstraint(
            "cold_chain_alert IN ('none', 'warning', 'critical')",
            name=op.f("ck_shipments_cold_chain_alert_valid"),
        ),
        sa.UniqueConstraint("reference", name="uq_shipments_reference"),
        sa.UniqueConstraint("request_id", name="uq_shipments_request_id"),
        sa.ForeignKeyConstraint(
            ["request_id"],
            ["network.blood_requests.id"],
            name="fk_shipments_request_id_blood_requests",
        ),
        sa.ForeignKeyConstraint(
            ["source_facility_id"],
            ["network.facilities.id"],
            name="fk_shipments_source_facility_id_facilities",
        ),
        sa.ForeignKeyConstraint(
            ["destination_facility_id"],
            ["network.facilities.id"],
            name="fk_shipments_destination_facility_id_facilities",
        ),
        schema="network",
    )
    op.create_index(
        "ix_network_shipments_source_facility_id",
        "shipments",
        ["source_facility_id"],
        schema="network",
    )
    op.create_index(
        "ix_network_shipments_destination_facility_id",
        "shipments",
        ["destination_facility_id"],
        schema="network",
    )

    op.create_table(
        "shipment_bags",
        sa.Column("shipment_id", UUID, nullable=False),
        sa.Column("bag_id", UUID, nullable=False),
        sa.PrimaryKeyConstraint("shipment_id", "bag_id", name="pk_shipment_bags"),
        sa.UniqueConstraint("bag_id", name="uq_shipment_bags_bag_id"),
        sa.ForeignKeyConstraint(
            ["shipment_id"], ["network.shipments.id"], name="fk_shipment_bags_shipment_id_shipments"
        ),
        sa.ForeignKeyConstraint(
            ["bag_id"], ["trace.blood_bags.id"], name="fk_shipment_bags_bag_id_blood_bags"
        ),
        schema="network",
    )

    op.create_table(
        "shipment_events",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("shipment_id", UUID, nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(32), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("occurred_at", TS, nullable=False),
        sa.Column("actor_id", UUID, nullable=True),
        sa.Column("meta", postgresql.JSONB(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_shipment_events"),
        sa.UniqueConstraint("shipment_id", "seq", name="uq_shipment_events_shipment_id_seq"),
        sa.ForeignKeyConstraint(
            ["shipment_id"],
            ["network.shipments.id"],
            name="fk_shipment_events_shipment_id_shipments",
        ),
        schema="network",
    )
    op.create_index(
        "ix_network_shipment_events_shipment_id",
        "shipment_events",
        ["shipment_id"],
        schema="network",
    )
    # The shipment timeline is append-only, like the bag trace and telemetry readings.
    op.execute(
        """
        CREATE FUNCTION network.forbid_shipment_event_mutation() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
          RAISE EXCEPTION 'network.shipment_events is append-only';
        END;
        $$;
        """
    )
    op.execute(
        "CREATE TRIGGER shipment_events_append_only BEFORE UPDATE OR DELETE "
        "ON network.shipment_events FOR EACH ROW "
        "EXECUTE FUNCTION network.forbid_shipment_event_mutation();"
    )

    # Shipment observation events join the existing append-only, hash-chained bag trace.
    op.execute("ALTER TABLE trace.bag_events DROP CONSTRAINT ck_bag_events_event_type_valid")
    op.execute(
        "ALTER TABLE trace.bag_events ADD CONSTRAINT ck_bag_events_event_type_valid "
        f"CHECK ({NEW_EVENTS})"
    )


def downgrade() -> None:
    # Trace history is append-only: restore the previous constraint NOT VALID so existing
    # shipment observations stay intact while new rows follow the old rule.
    op.execute("ALTER TABLE trace.bag_events DROP CONSTRAINT ck_bag_events_event_type_valid")
    op.execute(
        "ALTER TABLE trace.bag_events ADD CONSTRAINT ck_bag_events_event_type_valid "
        f"CHECK ({OLD_EVENTS}) NOT VALID"
    )
    op.execute("DROP TRIGGER IF EXISTS shipment_events_append_only ON network.shipment_events")
    op.execute("DROP FUNCTION IF EXISTS network.forbid_shipment_event_mutation()")
    op.drop_index(
        "ix_network_shipment_events_shipment_id", table_name="shipment_events", schema="network"
    )
    op.drop_table("shipment_events", schema="network")
    op.drop_table("shipment_bags", schema="network")
    op.drop_index(
        "ix_network_shipments_destination_facility_id", table_name="shipments", schema="network"
    )
    op.drop_index(
        "ix_network_shipments_source_facility_id", table_name="shipments", schema="network"
    )
    op.drop_table("shipments", schema="network")
