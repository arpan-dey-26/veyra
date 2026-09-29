"""Phase 8: blood donation camps and donor registrations (schema ``network``).

Prototype camp-management workflow; donor eligibility and medical screening remain governed
by authorized staff. Registrations deliberately store NO medical or screening data: only who
registered, when, and whether staff confirmed attendance.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import DateTime

from app.core.db import Base
from app.core.ids import uuid7

CAMP_STATUSES = (
    "planned",
    "published",
    "registration_open",
    "ongoing",
    "completed",
    "cancelled",
)
REGISTRATION_STATUSES = ("registered", "cancelled", "attended", "no_show")


class Camp(Base):
    __tablename__ = "camps"
    __table_args__ = (
        CheckConstraint(
            "status IN ('planned', 'published', 'registration_open', 'ongoing', 'completed', "
            "'cancelled')",
            name="status_valid",
        ),
        CheckConstraint("capacity >= 1 AND capacity <= 5000", name="capacity_valid"),
        CheckConstraint(
            "registered_count >= 0 AND registered_count <= capacity", name="registered_valid"
        ),
        CheckConstraint("ends_at > starts_at", name="window_valid"),
        {"schema": "network"},
    )

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid7)
    code: Mapped[str] = mapped_column(String(16), unique=True, nullable=False)
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    organizer_facility_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("network.facilities.id"), nullable=False, index=True
    )
    venue: Mapped[str] = mapped_column(String(160), nullable=False)
    city: Mapped[str] = mapped_column(String(80), nullable=False)
    state: Mapped[str] = mapped_column(String(64), nullable=False)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    capacity: Mapped[int] = mapped_column(Integer, nullable=False)
    # Active registrations (registered + attended); kept in step under a row lock.
    registered_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="planned")
    description: Mapped[str | None] = mapped_column(Text)
    contact_name: Mapped[str] = mapped_column(String(80), nullable=False)
    contact_phone: Mapped[str | None] = mapped_column(String(20))
    contact_email: Mapped[str | None] = mapped_column(String(254))
    cancel_reason: Mapped[str | None] = mapped_column(String(200))
    created_by: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    __mapper_args__ = {"version_id_col": version}  # noqa: RUF012 - SQLAlchemy mapper config


class CampRegistration(Base):
    """A donor's place at a camp. No medical/screening data, ever."""

    __tablename__ = "camp_registrations"
    __table_args__ = (
        UniqueConstraint("camp_id", "donor_id", name="uq_camp_registrations_camp_id_donor_id"),
        CheckConstraint(
            "status IN ('registered', 'cancelled', 'attended', 'no_show')", name="status_valid"
        ),
        {"schema": "network"},
    )

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid7)
    camp_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("network.camps.id"), nullable=False, index=True
    )
    donor_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("network.donors.id"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="registered")
    registered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attendance_confirmed_by: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    # Set when staff record the donation through the normal donation desk (all its controls).
    donation_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("network.donations.id"), unique=True
    )
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    __mapper_args__ = {"version_id_col": version}  # noqa: RUF012 - SQLAlchemy mapper config
