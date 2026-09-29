"""Simulated IoT devices on blood bags and their telemetry (schema ``telemetry``).

Everything here is SIMULATED: no physical sensor, RFID reader or hardware API is involved.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
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
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import DateTime

from app.core.db import Base
from app.core.ids import uuid7

COLD_CHAIN_STATUSES = ("normal", "warning", "critical")


class TelemetryDevice(Base):
    """One simulated smart-bag tag per bag. Carries no donor or patient data."""

    __tablename__ = "devices"
    __table_args__ = (
        CheckConstraint("battery_pct >= 0 AND battery_pct <= 100", name="battery_valid"),
        CheckConstraint("sim_mode IN ('normal', 'excursion', 'recovering')", name="sim_mode_valid"),
        CheckConstraint(
            "cold_chain_status IN ('unknown', 'normal', 'warning', 'critical')",
            name="cold_chain_status_valid",
        ),
        {"schema": "telemetry"},
    )

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid7)
    device_id: Mapped[str] = mapped_column(String(24), unique=True, nullable=False)
    rfid: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    bag_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("trace.blood_bags.id"), unique=True, nullable=False
    )
    simulated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    battery_pct: Mapped[float] = mapped_column(Float, nullable=False)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    readings_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_temperature_c: Mapped[float | None] = mapped_column(Float)
    # Simulator state (deterministic: readings depend on the sequence number, not wall time).
    sim_running: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    sim_mode: Mapped[str] = mapped_column(String(16), nullable=False, default="normal")
    sim_mode_step: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Cold-chain state machine.
    cold_chain_status: Mapped[str] = mapped_column(String(16), nullable=False, default="unknown")
    excursion_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    excursion_severity: Mapped[str | None] = mapped_column(String(16))
    excursion_peak_c: Mapped[float | None] = mapped_column(Float)
    attached_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    __mapper_args__ = {"version_id_col": version}  # noqa: RUF012 - SQLAlchemy mapper config


class TelemetryReading(Base):
    """Append-only (DB trigger): one simulated reading."""

    __tablename__ = "readings"
    __table_args__ = (
        CheckConstraint("status IN ('normal', 'warning', 'critical')", name="status_valid"),
        CheckConstraint("battery_pct >= 0 AND battery_pct <= 100", name="battery_valid"),
        UniqueConstraint("device_pk", "seq", name="uq_readings_device_pk_seq"),
        {"schema": "telemetry"},
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=False), primary_key=True)
    device_pk: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("telemetry.devices.id"), nullable=False, index=True
    )
    bag_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("trace.blood_bags.id"), nullable=False, index=True
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    temperature_c: Mapped[float] = mapped_column(Float, nullable=False)
    battery_pct: Mapped[float] = mapped_column(Float, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    simulated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
