from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.core.provenance import SourceMeta

TELEMETRY_DISCLAIMER = (
    "Simulated IoT telemetry — prototype. This is simulated IoT telemetry for a student "
    "engineering prototype and is not a certified medical monitoring system."
)
ColdChainStatus = Literal["unknown", "normal", "warning", "critical"]
DeviceStatus = Literal["awaiting", "online", "low_battery", "paused", "offline"]


class ThresholdsOut(BaseModel):
    label: str
    nominal_c: float
    normal_low: float
    normal_high: float
    critical_low: float
    critical_high: float
    note: str = "Prototype thresholds, not clinical guidance."


class DeviceOut(BaseModel):
    public_id: str
    device_id: str
    rfid: str = Field(description="Simulated RFID/EPC identifier (no real tag)")
    simulated: bool
    battery_pct: float
    device_status: DeviceStatus
    last_seen_at: datetime | None
    readings_count: int
    sim_running: bool
    sim_mode: str
    attached_at: datetime
    source: SourceMeta


class ReadingOut(BaseModel):
    seq: int
    recorded_at: datetime
    temperature_c: float
    battery_pct: float
    status: Literal["normal", "warning", "critical"]


class TelemetrySeries(BaseModel):
    public_id: str
    component: str
    thresholds: ThresholdsOut
    readings: list[ReadingOut]
    source: SourceMeta
    disclaimer: str = TELEMETRY_DISCLAIMER


class ExcursionOut(BaseModel):
    started_at: datetime
    ended_at: datetime | None
    duration_seconds: int
    severity: Literal["warning", "critical"]
    peak_c: float
    readings: int


class TelemetrySummary(BaseModel):
    public_id: str
    component: str
    device_id: str
    cold_chain_status: ColdChainStatus
    device_status: DeviceStatus
    current_c: float | None
    min_c: float | None
    max_c: float | None
    last_reading_at: datetime | None
    battery_pct: float
    readings_count: int
    excursion_active: bool
    excursion_started_at: datetime | None
    excursion_duration_seconds: int | None
    excursion_severity: str | None
    thresholds: ThresholdsOut
    source: SourceMeta
    disclaimer: str = TELEMETRY_DISCLAIMER


class ColdChainEvent(BaseModel):
    seq: int
    event_type: str
    occurred_at: datetime
    meta: dict[str, object]
    row_hash: str


class ColdChainReport(BaseModel):
    public_id: str
    component: str
    cold_chain_status: ColdChainStatus
    thresholds: ThresholdsOut
    excursions: list[ExcursionOut]
    trace_events: list[ColdChainEvent] = Field(
        description="Cold-chain entries in the bag's append-only, hash-chained trace"
    )
    chain_valid: bool
    source: SourceMeta
    disclaimer: str = TELEMETRY_DISCLAIMER


class MonitoredBag(BaseModel):
    public_id: str
    blood_group: str
    component: str
    bag_status: str
    device_id: str
    device_status: DeviceStatus
    cold_chain_status: ColdChainStatus
    current_c: float | None
    last_reading_at: datetime | None
    battery_pct: float
    excursion_duration_seconds: int | None
    sim_running: bool


class MonitoredList(BaseModel):
    scope: Literal["facility", "network"]
    counts: dict[str, int] = Field(
        description="normal / warning / critical / offline / paused / awaiting"
    )
    bags: list[MonitoredBag]
    simulator_enabled: bool
    source: SourceMeta
    disclaimer: str = TELEMETRY_DISCLAIMER


class TickRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    count: int = Field(default=1, ge=1, le=20, description="Readings to generate now")


class SimulatorResult(BaseModel):
    device: DeviceOut
    summary: TelemetrySummary
    generated: int
    transitions: list[str] = Field(description="Cold-chain events raised by this action")
