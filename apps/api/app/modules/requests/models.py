"""Blood requests from hospitals to blood banks (schema ``network``)."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import DateTime

from app.core.db import Base
from app.core.ids import uuid7

REQUEST_STATUSES = ("pending", "dispatched", "fulfilled", "rejected", "cancelled", "acknowledged")


class BloodRequest(Base):
    __tablename__ = "blood_requests"
    __table_args__ = (
        CheckConstraint("units >= 1 AND units <= 20", name="units_valid"),
        CheckConstraint("urgency IN ('routine', 'urgent', 'emergency')", name="urgency_valid"),
        CheckConstraint(
            "status IN ('pending', 'dispatched', 'fulfilled', 'rejected', 'cancelled', "
            "'acknowledged')",
            name="status_valid",
        ),
        CheckConstraint("provider IN ('internal', 'mock')", name="provider_valid"),
        CheckConstraint(
            "(provider = 'internal' AND target_facility_id IS NOT NULL) OR "
            "(provider = 'mock' AND target_external_ref IS NOT NULL)",
            name="target_present",
        ),
        UniqueConstraint(
            "hospital_id", "idempotency_key", name="uq_blood_requests_hospital_id_idem"
        ),
        {"schema": "network"},
    )

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid7)
    reference: Mapped[str] = mapped_column(String(16), unique=True, nullable=False)
    hospital_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("network.facilities.id"), nullable=False, index=True
    )
    provider: Mapped[str] = mapped_column(String(16), nullable=False)
    target_facility_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("network.facilities.id"), index=True
    )
    target_external_ref: Mapped[str | None] = mapped_column(String(64))
    target_name: Mapped[str] = mapped_column(String(160), nullable=False)
    blood_group: Mapped[str] = mapped_column(String(3), nullable=False)
    component: Mapped[str] = mapped_column(String(16), nullable=False)
    units: Mapped[int] = mapped_column(Integer, nullable=False)
    urgency: Mapped[str] = mapped_column(String(16), nullable=False)
    needed_by: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    notes: Mapped[str | None] = mapped_column(String(500))
    response_note: Mapped[str | None] = mapped_column(String(500))
    idempotency_key: Mapped[str | None] = mapped_column(String(64))
    created_by: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("identity.users.id"), nullable=False
    )
    responded_by: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    __mapper_args__ = {"version_id_col": version}  # noqa: RUF012 - SQLAlchemy mapper config


class RequestAllocation(Base):
    """A bag dispatched against a request. A bag can serve at most one request."""

    __tablename__ = "request_allocations"
    __table_args__ = ({"schema": "network"},)

    request_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("network.blood_requests.id"), primary_key=True
    )
    bag_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("trace.blood_bags.id"), primary_key=True, unique=True
    )
    allocated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
