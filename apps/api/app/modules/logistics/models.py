"""Simulated logistics (Phase 7): shipments of dispatched bags (schema ``network``).

Everything about transport here is SIMULATED: fictional couriers, schematic checkpoints and
deterministic ETAs. No GPS, maps, traffic or courier-company data is used.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    Float,
    ForeignKey,
    Identity,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import DateTime

from app.core.db import Base
from app.core.ids import uuid7

SHIPMENT_STATUSES = (
    "created",
    "pickup_pending",
    "picked_up",
    "in_transit",
    "delayed",
    "arrived",
    "received",
)
_JSON = JSON().with_variant(JSONB(), "postgresql")


class Shipment(Base):
    """One shipment per human-confirmed dispatch. Operational data only (no people)."""

    __tablename__ = "shipments"
    __table_args__ = (
        CheckConstraint(
            "status IN ('created', 'pickup_pending', 'picked_up', 'in_transit', 'delayed', "
            "'arrived', 'received')",
            name="status_valid",
        ),
        CheckConstraint("delay_minutes >= 0", name="delay_valid"),
        CheckConstraint(
            "cold_chain_alert IN ('none', 'warning', 'critical')", name="cold_chain_alert_valid"
        ),
        {"schema": "network"},
    )

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid7)
    reference: Mapped[str] = mapped_column(String(16), unique=True, nullable=False)
    request_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("network.blood_requests.id"), unique=True, nullable=False
    )
    source_facility_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("network.facilities.id"), nullable=False, index=True
    )
    destination_facility_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("network.facilities.id"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    status_before_delay: Mapped[str | None] = mapped_column(String(16))
    urgency: Mapped[str] = mapped_column(String(16), nullable=False)
    simulated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    courier_id: Mapped[str] = mapped_column(String(24), nullable=False)
    courier_name: Mapped[str] = mapped_column(String(64), nullable=False)
    vehicle_type: Mapped[str] = mapped_column(String(48), nullable=False)
    distance_km: Mapped[float] = mapped_column(Float, nullable=False)
    planned_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    checkpoints: Mapped[list[dict[str, Any]]] = mapped_column(_JSON, nullable=False, default=list)
    current_checkpoint: Mapped[int] = mapped_column(Integer, nullable=False, default=-1)
    eta_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    delay_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    delay_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    delay_reason: Mapped[str | None] = mapped_column(String(32))
    cold_chain_alert: Mapped[str] = mapped_column(String(16), nullable=False, default="none")
    last_update_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    picked_up_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    arrived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    __mapper_args__ = {"version_id_col": version}  # noqa: RUF012 - SQLAlchemy mapper config


class ShipmentBag(Base):
    __tablename__ = "shipment_bags"
    __table_args__ = ({"schema": "network"},)

    shipment_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("network.shipments.id"), primary_key=True
    )
    bag_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("trace.blood_bags.id"), primary_key=True, unique=True
    )


class ShipmentEvent(Base):
    """Append-only shipment timeline (a database trigger forbids UPDATE/DELETE)."""

    __tablename__ = "shipment_events"
    __table_args__ = (
        UniqueConstraint("shipment_id", "seq", name="uq_shipment_events_shipment_id_seq"),
        {"schema": "network"},
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=False), primary_key=True)
    shipment_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("network.shipments.id"), nullable=False, index=True
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    actor_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    meta: Mapped[dict[str, Any]] = mapped_column(_JSON, nullable=False, default=dict)
