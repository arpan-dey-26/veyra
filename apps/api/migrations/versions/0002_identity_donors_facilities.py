"""Phase 1: users, sessions, verification, facilities, invites, donors, audit log.

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)
TS = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", UUID, nullable=False),
        sa.Column("email", sa.String(254), nullable=False),
        sa.Column("mobile", sa.String(16), nullable=False),
        sa.Column("full_name", sa.String(120), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("is_demo", sa.Boolean(), nullable=False),
        sa.Column("verified_at", TS, nullable=True),
        sa.Column("failed_login_count", sa.Integer(), nullable=False),
        sa.Column("locked_until", TS, nullable=True),
        sa.Column("last_login_at", TS, nullable=True),
        sa.Column("created_at", TS, nullable=False),
        sa.Column("updated_at", TS, nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_users"),
        sa.CheckConstraint(
            "role IN ('DONOR', 'HOSPITAL', 'BLOOD_BANK', 'ADMIN')", name=op.f("ck_users_role_valid")
        ),
        sa.CheckConstraint(
            "status IN ('pending_verification', 'active', 'disabled')",
            name=op.f("ck_users_status_valid"),
        ),
        sa.UniqueConstraint("email", name="uq_users_email"),
        sa.UniqueConstraint("mobile", name="uq_users_mobile"),
        schema="identity",
    )

    op.create_table(
        "facilities",
        sa.Column("id", UUID, nullable=False),
        sa.Column("type", sa.String(16), nullable=False),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("registration_number", sa.String(64), nullable=True),
        sa.Column("address", sa.String(255), nullable=False),
        sa.Column("city", sa.String(80), nullable=False),
        sa.Column("state", sa.String(64), nullable=False),
        sa.Column("pin_code", sa.String(6), nullable=False),
        sa.Column("provider_kind", sa.String(16), nullable=False),
        sa.Column("is_simulated", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("created_at", TS, nullable=False),
        sa.Column("updated_at", TS, nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_facilities"),
        sa.CheckConstraint(
            "type IN ('HOSPITAL', 'BLOOD_BANK')", name=op.f("ck_facilities_type_valid")
        ),
        sa.CheckConstraint(
            "status IN ('active', 'suspended')", name=op.f("ck_facilities_status_valid")
        ),
        sa.UniqueConstraint("registration_number", name="uq_facilities_registration_number"),
        schema="network",
    )

    op.create_table(
        "sessions",
        sa.Column("id", UUID, nullable=False),
        sa.Column("user_id", UUID, nullable=False),
        sa.Column("family_id", UUID, nullable=False),
        sa.Column("refresh_token_hash", sa.String(64), nullable=False),
        sa.Column("expires_at", TS, nullable=False),
        sa.Column("revoked_at", TS, nullable=True),
        sa.Column("revoked_reason", sa.String(32), nullable=True),
        sa.Column("replaced_by", UUID, nullable=True),
        sa.Column("user_agent", sa.String(255), nullable=True),
        sa.Column("ip", sa.String(64), nullable=True),
        sa.Column("created_at", TS, nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_sessions"),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["identity.users.id"],
            name="fk_sessions_user_id_users",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("refresh_token_hash", name="uq_sessions_refresh_token_hash"),
        schema="identity",
    )
    op.create_index("ix_identity_sessions_user_id", "sessions", ["user_id"], schema="identity")
    op.create_index("ix_identity_sessions_family_id", "sessions", ["family_id"], schema="identity")

    op.create_table(
        "verification_challenges",
        sa.Column("id", UUID, nullable=False),
        sa.Column("user_id", UUID, nullable=False),
        sa.Column("purpose", sa.String(32), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("code_hash", sa.String(64), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("expires_at", TS, nullable=False),
        sa.Column("consumed_at", TS, nullable=True),
        sa.Column("created_at", TS, nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_verification_challenges"),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["identity.users.id"],
            name="fk_verification_challenges_user_id_users",
            ondelete="CASCADE",
        ),
        schema="identity",
    )
    op.create_index(
        "ix_identity_verification_challenges_user_id",
        "verification_challenges",
        ["user_id"],
        schema="identity",
    )

    op.create_table(
        "facility_invites",
        sa.Column("id", UUID, nullable=False),
        sa.Column("facility_id", UUID, nullable=False),
        sa.Column("email", sa.String(254), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("invited_by", UUID, nullable=False),
        sa.Column("expires_at", TS, nullable=False),
        sa.Column("accepted_at", TS, nullable=True),
        sa.Column("accepted_user_id", UUID, nullable=True),
        sa.Column("revoked_at", TS, nullable=True),
        sa.Column("created_at", TS, nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_facility_invites"),
        sa.CheckConstraint(
            "role IN ('HOSPITAL', 'BLOOD_BANK')", name=op.f("ck_facility_invites_role_valid")
        ),
        sa.ForeignKeyConstraint(
            ["facility_id"],
            ["network.facilities.id"],
            name="fk_facility_invites_facility_id_facilities",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["invited_by"], ["identity.users.id"], name="fk_facility_invites_invited_by_users"
        ),
        sa.UniqueConstraint("token_hash", name="uq_facility_invites_token_hash"),
        schema="identity",
    )
    op.create_index(
        "ix_identity_facility_invites_facility_id",
        "facility_invites",
        ["facility_id"],
        schema="identity",
    )

    op.create_table(
        "facility_memberships",
        sa.Column("user_id", UUID, nullable=False),
        sa.Column("facility_id", UUID, nullable=False),
        sa.Column("created_at", TS, nullable=False),
        sa.PrimaryKeyConstraint("user_id", name="pk_facility_memberships"),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["identity.users.id"],
            name="fk_facility_memberships_user_id_users",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["facility_id"],
            ["network.facilities.id"],
            name="fk_facility_memberships_facility_id_facilities",
            ondelete="CASCADE",
        ),
        schema="network",
    )
    op.create_index(
        "ix_network_facility_memberships_facility_id",
        "facility_memberships",
        ["facility_id"],
        schema="network",
    )

    op.create_table(
        "donors",
        sa.Column("id", UUID, nullable=False),
        sa.Column("user_id", UUID, nullable=False),
        sa.Column("blood_group", sa.String(3), nullable=False),
        sa.Column("address", sa.String(255), nullable=False),
        sa.Column("city", sa.String(80), nullable=False),
        sa.Column("state", sa.String(64), nullable=False),
        sa.Column("pin_code", sa.String(6), nullable=False),
        sa.Column("created_at", TS, nullable=False),
        sa.Column("updated_at", TS, nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_donors"),
        sa.CheckConstraint(
            "blood_group IN ('A+', 'A-', 'B+', 'B-', 'AB+', 'AB-', 'O+', 'O-')",
            name=op.f("ck_donors_blood_group_valid"),
        ),
        sa.UniqueConstraint("user_id", name="uq_donors_user_id"),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["identity.users.id"],
            name="fk_donors_user_id_users",
            ondelete="CASCADE",
        ),
        schema="network",
    )

    op.create_table(
        "audit_logs",
        sa.Column("id", UUID, nullable=False),
        sa.Column("actor_id", UUID, nullable=True),
        sa.Column("actor_type", sa.String(16), nullable=False),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("resource", sa.String(64), nullable=False),
        sa.Column("resource_id", sa.String(64), nullable=True),
        sa.Column("ip", sa.String(64), nullable=True),
        sa.Column("meta", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", TS, nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_audit_logs"),
        schema="audit",
    )
    op.create_index("ix_audit_audit_logs_action", "audit_logs", ["action"], schema="audit")
    op.create_index("ix_audit_audit_logs_actor_id", "audit_logs", ["actor_id"], schema="audit")

    # The audit log is append-only: block UPDATE and DELETE at the database level.
    op.execute(
        """
        CREATE FUNCTION audit.forbid_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          RAISE EXCEPTION 'audit.audit_logs is append-only';
        END;
        $$;
        """
    )
    op.execute(
        "CREATE TRIGGER audit_logs_append_only BEFORE UPDATE OR DELETE ON audit.audit_logs "
        "FOR EACH ROW EXECUTE FUNCTION audit.forbid_mutation();"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS audit_logs_append_only ON audit.audit_logs")
    op.execute("DROP FUNCTION IF EXISTS audit.forbid_mutation()")
    op.drop_table("audit_logs", schema="audit")
    op.drop_table("donors", schema="network")
    op.drop_table("facility_memberships", schema="network")
    op.drop_table("facility_invites", schema="identity")
    op.drop_table("verification_challenges", schema="identity")
    op.drop_table("sessions", schema="identity")
    op.drop_table("facilities", schema="network")
    op.drop_table("users", schema="identity")
