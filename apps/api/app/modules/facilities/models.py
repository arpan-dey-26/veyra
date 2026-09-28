"""Facility tables (schema ``network``): hospitals / blood banks and their staff."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import DateTime

from app.core.db import Base
from app.core.ids import uuid7

FACILITY_TYPES = ("HOSPITAL", "BLOOD_BANK")


class Facility(Base):
    __tablename__ = "facilities"
    __table_args__ = (
        CheckConstraint("type IN ('HOSPITAL', 'BLOOD_BANK')", name="type_valid"),
        CheckConstraint("status IN ('active', 'suspended')", name="status_valid"),
        {"schema": "network"},
    )

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid7)
    type: Mapped[str] = mapped_column(String(16), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    registration_number: Mapped[str | None] = mapped_column(String(64), unique=True)
    address: Mapped[str] = mapped_column(String(255), nullable=False)
    city: Mapped[str] = mapped_column(String(80), nullable=False)
    state: Mapped[str] = mapped_column(String(64), nullable=False)
    pin_code: Mapped[str] = mapped_column(String(6), nullable=False)
    # 'internal' = onboarded in VEYRA itself; 'mock' = simulated partner (Phase 2+).
    provider_kind: Mapped[str] = mapped_column(String(16), nullable=False, default="internal")
    is_simulated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class FacilityMembership(Base):
    """Links a facility user to exactly one facility."""

    __tablename__ = "facility_memberships"
    __table_args__ = ({"schema": "network"},)

    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("identity.users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    facility_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("network.facilities.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
