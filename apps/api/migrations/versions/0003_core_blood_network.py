"""Phase 2: donations, blood bags, bag trace events, blood requests, allocations, outbox.

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)
TS = sa.DateTime(timezone=True)
GROUPS = "blood_group IN ('A+', 'A-', 'B+', 'B-', 'AB+', 'AB-', 'O+', 'O-')"


def upgrade() -> None:
    op.add_column(
        "donors", sa.Column("blood_group_confirmed_at", TS, nullable=True), schema="network"
    )

    op.create_table(
        "donations",
        sa.Column("id", UUID, nullable=False),
        sa.Column("donor_id", UUID, nullable=False),
        sa.Column("collection_facility_id", UUID, nullable=False),
        sa.Column("blood_group", sa.String(3), nullable=False),
        sa.Column("volume_ml", sa.Integer(), nullable=False),
        sa.Column("collected_at", TS, nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("recorded_by", UUID, nullable=False),
        sa.Column("notes", sa.String(500), nullable=True),
        sa.Column("created_at", TS, nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_donations"),
        sa.CheckConstraint("volume_ml IN (350, 450)", name=op.f("ck_donations_volume_valid")),
        sa.CheckConstraint(GROUPS, name=op.f("ck_donations_blood_group_valid")),
        sa.CheckConstraint(
            "status IN ('collected', 'discarded')", name=op.f("ck_donations_status_valid")
        ),
        sa.ForeignKeyConstraint(
            ["donor_id"], ["network.donors.id"], name="fk_donations_donor_id_donors"
        ),
        sa.ForeignKeyConstraint(
            ["collection_facility_id"],
            ["network.facilities.id"],
            name="fk_donations_collection_facility_id_facilities",
        ),
        sa.ForeignKeyConstraint(
            ["recorded_by"], ["identity.users.id"], name="fk_donations_recorded_by_users"
        ),
        schema="network",
    )
    op.create_index("ix_network_donations_donor_id", "donations", ["donor_id"], schema="network")
    op.create_index(
        "ix_network_donations_collection_facility_id",
        "donations",
        ["collection_facility_id"],
        schema="network",
    )

    op.create_table(
        "blood_bags",
        sa.Column("id", UUID, nullable=False),
        sa.Column("public_id", sa.String(16), nullable=False),
        sa.Column("donation_id", UUID, nullable=False),
        sa.Column("blood_group", sa.String(3), nullable=False),
        sa.Column("component", sa.String(16), nullable=False),
        sa.Column("volume_ml", sa.Integer(), nullable=False),
        sa.Column("collected_at", TS, nullable=False),
        sa.Column("expires_at", TS, nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("current_facility_id", UUID, nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", TS, nullable=False),
        sa.Column("updated_at", TS, nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_blood_bags"),
        sa.CheckConstraint(
            "component IN ('WHOLE_BLOOD', 'PRBC', 'FFP', 'PLATELETS', 'CRYO')",
            name=op.f("ck_blood_bags_component_valid"),
        ),
        sa.CheckConstraint(
            "status IN ('available', 'in_transit', 'received', 'discarded')",
            name=op.f("ck_blood_bags_status_valid"),
        ),
        sa.CheckConstraint(GROUPS, name=op.f("ck_blood_bags_blood_group_valid")),
        sa.CheckConstraint(
            "volume_ml > 0 AND volume_ml <= 600", name=op.f("ck_blood_bags_volume_valid")
        ),
        sa.CheckConstraint(
            "expires_at > collected_at", name=op.f("ck_blood_bags_expiry_after_collection")
        ),
        sa.UniqueConstraint("public_id", name="uq_blood_bags_public_id"),
        sa.ForeignKeyConstraint(
            ["donation_id"], ["network.donations.id"], name="fk_blood_bags_donation_id_donations"
        ),
        sa.ForeignKeyConstraint(
            ["current_facility_id"],
            ["network.facilities.id"],
            name="fk_blood_bags_current_facility_id_facilities",
        ),
        schema="trace",
    )
    op.create_index(
        "ix_trace_blood_bags_current_facility_id",
        "blood_bags",
        ["current_facility_id"],
        schema="trace",
    )
    op.create_index(
        "ix_trace_blood_bags_donation_id", "blood_bags", ["donation_id"], schema="trace"
    )

    op.create_table(
        "bag_events",
        sa.Column("id", UUID, nullable=False),
        sa.Column("bag_id", UUID, nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(16), nullable=False),
        sa.Column("from_facility_id", UUID, nullable=True),
        sa.Column("to_facility_id", UUID, nullable=True),
        sa.Column("actor_id", UUID, nullable=True),
        sa.Column("occurred_at", TS, nullable=False),
        sa.Column("meta", postgresql.JSONB(), nullable=False),
        sa.Column("prev_hash", sa.String(64), nullable=False),
        sa.Column("row_hash", sa.String(64), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_bag_events"),
        sa.UniqueConstraint("bag_id", "seq", name="uq_bag_events_bag_id_seq"),
        sa.CheckConstraint(
            "event_type IN ('COLLECTED', 'DISPATCHED', 'RECEIVED', 'DISCARDED')",
            name=op.f("ck_bag_events_event_type_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["bag_id"], ["trace.blood_bags.id"], name="fk_bag_events_bag_id_blood_bags"
        ),
        schema="trace",
    )
    op.create_index("ix_trace_bag_events_bag_id", "bag_events", ["bag_id"], schema="trace")

    op.create_table(
        "blood_requests",
        sa.Column("id", UUID, nullable=False),
        sa.Column("reference", sa.String(16), nullable=False),
        sa.Column("hospital_id", UUID, nullable=False),
        sa.Column("provider", sa.String(16), nullable=False),
        sa.Column("target_facility_id", UUID, nullable=True),
        sa.Column("target_external_ref", sa.String(64), nullable=True),
        sa.Column("target_name", sa.String(160), nullable=False),
        sa.Column("blood_group", sa.String(3), nullable=False),
        sa.Column("component", sa.String(16), nullable=False),
        sa.Column("units", sa.Integer(), nullable=False),
        sa.Column("urgency", sa.String(16), nullable=False),
        sa.Column("needed_by", TS, nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("notes", sa.String(500), nullable=True),
        sa.Column("response_note", sa.String(500), nullable=True),
        sa.Column("idempotency_key", sa.String(64), nullable=True),
        sa.Column("created_by", UUID, nullable=False),
        sa.Column("responded_by", UUID, nullable=True),
        sa.Column("created_at", TS, nullable=False),
        sa.Column("updated_at", TS, nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_blood_requests"),
        sa.CheckConstraint(
            "units >= 1 AND units <= 20", name=op.f("ck_blood_requests_units_valid")
        ),
        sa.CheckConstraint(
            "urgency IN ('routine', 'urgent', 'emergency')",
            name=op.f("ck_blood_requests_urgency_valid"),
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'dispatched', 'fulfilled', 'rejected', 'cancelled', "
            "'acknowledged')",
            name=op.f("ck_blood_requests_status_valid"),
        ),
        sa.CheckConstraint(
            "provider IN ('internal', 'mock')", name=op.f("ck_blood_requests_provider_valid")
        ),
        sa.CheckConstraint(
            "(provider = 'internal' AND target_facility_id IS NOT NULL) OR "
            "(provider = 'mock' AND target_external_ref IS NOT NULL)",
            name=op.f("ck_blood_requests_target_present"),
        ),
        sa.UniqueConstraint(
            "hospital_id", "idempotency_key", name="uq_blood_requests_hospital_id_idem"
        ),
        sa.UniqueConstraint("reference", name="uq_blood_requests_reference"),
        sa.ForeignKeyConstraint(
            ["hospital_id"],
            ["network.facilities.id"],
            name="fk_blood_requests_hospital_id_facilities",
        ),
        sa.ForeignKeyConstraint(
            ["target_facility_id"],
            ["network.facilities.id"],
            name="fk_blood_requests_target_facility_id_facilities",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"], ["identity.users.id"], name="fk_blood_requests_created_by_users"
        ),
        schema="network",
    )
    op.create_index(
        "ix_network_blood_requests_target_facility_id",
        "blood_requests",
        ["target_facility_id"],
        schema="network",
    )
    op.create_index(
        "ix_network_blood_requests_hospital_id", "blood_requests", ["hospital_id"], schema="network"
    )

    op.create_table(
        "request_allocations",
        sa.Column("request_id", UUID, nullable=False),
        sa.Column("bag_id", UUID, nullable=False),
        sa.Column("allocated_at", TS, nullable=False),
        sa.PrimaryKeyConstraint("request_id", "bag_id", name="pk_request_allocations"),
        sa.UniqueConstraint("bag_id", name="uq_request_allocations_bag_id"),
        sa.ForeignKeyConstraint(
            ["request_id"],
            ["network.blood_requests.id"],
            name="fk_request_allocations_request_id_blood_requests",
        ),
        sa.ForeignKeyConstraint(
            ["bag_id"], ["trace.blood_bags.id"], name="fk_request_allocations_bag_id_blood_bags"
        ),
        schema="network",
    )

    op.create_table(
        "outbox_events",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("event_id", UUID, nullable=False),
        sa.Column("topic", sa.String(64), nullable=False),
        sa.Column("aggregate_type", sa.String(32), nullable=False),
        sa.Column("aggregate_id", sa.String(64), nullable=False),
        sa.Column("audience", postgresql.JSONB(), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", TS, nullable=False),
        sa.Column("published_at", TS, nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("last_error", sa.String(255), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_outbox_events"),
        sa.UniqueConstraint("event_id", name="uq_outbox_events_event_id"),
        schema="network",
    )
    op.create_index("ix_network_outbox_events_topic", "outbox_events", ["topic"], schema="network")
    op.create_index(
        "ix_network_outbox_events_published_at", "outbox_events", ["published_at"], schema="network"
    )

    # The custody trail is append-only: block UPDATE and DELETE at the database level
    # (the SHA-256 chain additionally makes out-of-band edits detectable).
    op.execute(
        """
        CREATE FUNCTION trace.forbid_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          RAISE EXCEPTION 'trace.bag_events is append-only';
        END;
        $$;
        """
    )
    op.execute(
        "CREATE TRIGGER bag_events_append_only BEFORE UPDATE OR DELETE ON trace.bag_events "
        "FOR EACH ROW EXECUTE FUNCTION trace.forbid_mutation();"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS bag_events_append_only ON trace.bag_events")
    op.execute("DROP FUNCTION IF EXISTS trace.forbid_mutation()")
    op.drop_table("outbox_events", schema="network")
    op.drop_table("request_allocations", schema="network")
    op.drop_table("blood_requests", schema="network")
    op.drop_table("bag_events", schema="trace")
    op.drop_table("blood_bags", schema="trace")
    op.drop_table("donations", schema="network")
    op.drop_column("donors", "blood_group_confirmed_at", schema="network")
