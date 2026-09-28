"""Donor profile (schema ``network``). Identity fields (name, email, mobile) live on the user.

Medical/screening data is deliberately NOT stored here: it goes to a separate, encrypted,
access-restricted table in a later phase.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import DateTime

from app.core.db import Base
from app.core.ids import uuid7

BLOOD_GROUPS = ("A+", "A-", "B+", "B-", "AB+", "AB-", "O+", "O-")


class Donor(Base):
    __tablename__ = "donors"
    __table_args__ = (
        CheckConstraint(
            "blood_group IN ('A+', 'A-', 'B+', 'B-', 'AB+', 'AB-', 'O+', 'O-')",
            name="blood_group_valid",
        ),
        {"schema": "network"},
    )

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid7)
    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("identity.users.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    # Self-declared at registration; confirmed by a blood bank at first donation (Phase 2).
    blood_group: Mapped[str] = mapped_column(String(3), nullable=False)
    # Set when a blood bank determines the group at a donation (Phase 2).
    blood_group_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    address: Mapped[str] = mapped_column(String(255), nullable=False)
    city: Mapped[str] = mapped_column(String(80), nullable=False)
    state: Mapped[str] = mapped_column(String(64), nullable=False)
    pin_code: Mapped[str] = mapped_column(String(6), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
