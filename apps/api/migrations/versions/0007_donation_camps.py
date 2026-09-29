"""Phase 8: donation camps and camp registrations (additive; no existing table changes).

Revision ID: 0007
Revises: 0006
Create Date: 2026-09-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)
TS = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "camps",
        sa.Column("id", UUID, nullable=False),
        sa.Column("code", sa.String(16), nullable=False),
        sa.Column("title", sa.String(120), nullable=False),
        sa.Column("organizer_facility_id", UUID, nullable=False),
        sa.Column("venue", sa.String(160), nullable=False),
        sa.Column("city", sa.String(80), nullable=False),
        sa.Column("state", sa.String(64), nullable=False),
        sa.Column("starts_at", TS, nullable=False),
        sa.Column("ends_at", TS, nullable=False),
        sa.Column("capacity", sa.Integer(), nullable=False),
        sa.Column("registered_count", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("contact_name", sa.String(80), nullable=False),
        sa.Column("contact_phone", sa.String(20), nullable=True),
        sa.Column("contact_email", sa.String(254), nullable=True),
        sa.Column("cancel_reason", sa.String(200), nullable=True),
        sa.Column("created_by", UUID, nullable=True),
        sa.Column("created_at", TS, nullable=False),
        sa.Column("updated_at", TS, nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_camps"),
        sa.UniqueConstraint("code", name="uq_camps_code"),
        sa.CheckConstraint(
            "status IN ('planned', 'published', 'registration_open', 'ongoing', 'completed', "
            "'cancelled')",
            name=op.f("ck_camps_status_valid"),
        ),
        sa.CheckConstraint(
            "capacity >= 1 AND capacity <= 5000", name=op.f("ck_camps_capacity_valid")
        ),
        sa.CheckConstraint(
            "registered_count >= 0 AND registered_count <= capacity",
            name=op.f("ck_camps_registered_valid"),
        ),
        sa.CheckConstraint("ends_at > starts_at", name=op.f("ck_camps_window_valid")),
        sa.ForeignKeyConstraint(
            ["organizer_facility_id"],
            ["network.facilities.id"],
            name="fk_camps_organizer_facility_id_facilities",
        ),
        schema="network",
    )
    op.create_index(
        "ix_network_camps_organizer_facility_id",
        "camps",
        ["organizer_facility_id"],
        schema="network",
    )

    op.create_table(
        "camp_registrations",
        sa.Column("id", UUID, nullable=False),
        sa.Column("camp_id", UUID, nullable=False),
        sa.Column("donor_id", UUID, nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("registered_at", TS, nullable=False),
        sa.Column("cancelled_at", TS, nullable=True),
        sa.Column("attended_at", TS, nullable=True),
        sa.Column("attendance_confirmed_by", UUID, nullable=True),
        sa.Column("donation_id", UUID, nullable=True),
        sa.Column("updated_at", TS, nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_camp_registrations"),
        sa.UniqueConstraint("camp_id", "donor_id", name="uq_camp_registrations_camp_id_donor_id"),
        sa.UniqueConstraint("donation_id", name="uq_camp_registrations_donation_id"),
        sa.CheckConstraint(
            "status IN ('registered', 'cancelled', 'attended', 'no_show')",
            name=op.f("ck_camp_registrations_status_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["camp_id"], ["network.camps.id"], name="fk_camp_registrations_camp_id_camps"
        ),
        sa.ForeignKeyConstraint(
            ["donor_id"], ["network.donors.id"], name="fk_camp_registrations_donor_id_donors"
        ),
        sa.ForeignKeyConstraint(
            ["donation_id"],
            ["network.donations.id"],
            name="fk_camp_registrations_donation_id_donations",
        ),
        schema="network",
    )
    op.create_index(
        "ix_network_camp_registrations_camp_id",
        "camp_registrations",
        ["camp_id"],
        schema="network",
    )
    op.create_index(
        "ix_network_camp_registrations_donor_id",
        "camp_registrations",
        ["donor_id"],
        schema="network",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_network_camp_registrations_donor_id",
        table_name="camp_registrations",
        schema="network",
    )
    op.drop_index(
        "ix_network_camp_registrations_camp_id",
        table_name="camp_registrations",
        schema="network",
    )
    op.drop_table("camp_registrations", schema="network")
    op.drop_index("ix_network_camps_organizer_facility_id", table_name="camps", schema="network")
    op.drop_table("camps", schema="network")
