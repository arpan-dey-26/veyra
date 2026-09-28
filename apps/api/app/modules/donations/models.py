"""Donations (schema ``network``): one collection event that produces one or more bags."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import DateTime

from app.core.db import Base
from app.core.ids import uuid7


class Donation(Base):
    __tablename__ = "donations"
    __table_args__ = (
        CheckConstraint("volume_ml IN (350, 450)", name="volume_valid"),
        CheckConstraint(
            "blood_group IN ('A+', 'A-', 'B+', 'B-', 'AB+', 'AB-', 'O+', 'O-')",
            name="blood_group_valid",
        ),
        CheckConstraint("status IN ('collected', 'discarded')", name="status_valid"),
        {"schema": "network"},
    )

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid7)
    donor_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("network.donors.id"), nullable=False, index=True
    )
    collection_facility_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("network.facilities.id"), nullable=False, index=True
    )
    # Group determined at collection by the blood bank (the donor's registration is self-declared).
    blood_group: Mapped[str] = mapped_column(String(3), nullable=False)
    volume_ml: Mapped[int] = mapped_column(Integer, nullable=False)
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    recorded_by: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("identity.users.id"), nullable=False
    )
    notes: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
