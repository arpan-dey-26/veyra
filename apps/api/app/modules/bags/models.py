"""Blood bags and their append-only trace (schema ``trace``)."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import JSON, CheckConstraint, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import DateTime

from app.core.db import Base
from app.core.ids import uuid7


class BloodBag(Base):
    __tablename__ = "blood_bags"
    __table_args__ = (
        CheckConstraint(
            "component IN ('WHOLE_BLOOD', 'PRBC', 'FFP', 'PLATELETS', 'CRYO')",
            name="component_valid",
        ),
        CheckConstraint(
            "status IN ('available', 'in_transit', 'received', 'discarded')", name="status_valid"
        ),
        CheckConstraint(
            "blood_group IN ('A+', 'A-', 'B+', 'B-', 'AB+', 'AB-', 'O+', 'O-')",
            name="blood_group_valid",
        ),
        CheckConstraint("volume_ml > 0 AND volume_ml <= 600", name="volume_valid"),
        CheckConstraint("expires_at > collected_at", name="expiry_after_collection"),
        {"schema": "trace"},
    )

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid7)
    public_id: Mapped[str] = mapped_column(String(16), unique=True, nullable=False)
    donation_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("network.donations.id"), nullable=False, index=True
    )
    blood_group: Mapped[str] = mapped_column(String(3), nullable=False)
    component: Mapped[str] = mapped_column(String(16), nullable=False)
    volume_ml: Mapped[int] = mapped_column(Integer, nullable=False)
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    current_facility_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("network.facilities.id"), nullable=False, index=True
    )
    # Optimistic concurrency: a concurrent transition of the same bag fails instead of racing.
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __mapper_args__ = {"version_id_col": version}  # noqa: RUF012 - SQLAlchemy mapper config


class BagEvent(Base):
    """Append-only (DB trigger), hash-chained per bag."""

    __tablename__ = "bag_events"
    __table_args__ = (
        UniqueConstraint("bag_id", "seq", name="uq_bag_events_bag_id_seq"),
        CheckConstraint(
            "event_type IN ('COLLECTED', 'DISPATCHED', 'RECEIVED', 'DISCARDED', "
            "'DEVICE_ATTACHED', 'TEMP_EXCURSION', 'TEMP_RECOVERED')",
            name="event_type_valid",
        ),
        {"schema": "trace"},
    )

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid7)
    bag_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("trace.blood_bags.id"), nullable=False, index=True
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(16), nullable=False)
    from_facility_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    to_facility_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    actor_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    meta: Mapped[dict[str, Any]] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"), nullable=False, default=dict
    )
    prev_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    row_hash: Mapped[str] = mapped_column(String(64), nullable=False)
