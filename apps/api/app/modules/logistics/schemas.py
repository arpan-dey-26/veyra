from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.core.provenance import SourceMeta
from app.modules.logistics.engine import (
    ETA_LABEL,
    LOGISTICS_DISCLAIMER,
    LOGISTICS_LABEL,
    ROUTE_MAP_LABEL,
)

ShipmentStatus = Literal[
    "created", "pickup_pending", "picked_up", "in_transit", "delayed", "arrived", "received"
]
EtaStatus = Literal["on_schedule", "delayed", "late", "arrived", "delivered"]
DelayReason = Literal[
    "traffic_simulated", "vehicle_check_simulated", "handover_wait_simulated", "weather_simulated"
]


class CourierOut(BaseModel):
    courier_id: str
    name: str
    vehicle_type: str
    simulated: bool = True


class EtaOut(BaseModel):
    eta_at: datetime
    remaining_minutes: int
    status: EtaStatus
    delay_minutes: int
    delay_active: bool
    delay_reason: str | None
    reasons: list[str]
    label: str = ETA_LABEL


class CheckpointOut(BaseModel):
    seq: int
    name: str
    kind: Literal["source", "collection", "transit", "destination_area", "destination"]
    distance_km: float = Field(description="Simulated cumulative distance (schematic, not GPS)")
    expected_at: datetime
    actual_at: datetime | None
    status: Literal["pending", "reached", "confirmed_at_receipt"]
    current: bool


class ShipmentSummary(BaseModel):
    id: UUID
    reference: str
    request_id: UUID
    request_reference: str
    source_facility_id: UUID
    source_name: str
    destination_facility_id: UUID
    destination_name: str
    status: ShipmentStatus
    urgency: str
    bag_count: int
    blood_group: str
    component: str
    courier: CourierOut
    eta: EtaOut
    current_checkpoint: int
    current_checkpoint_name: str | None
    cold_chain_alert: Literal["none", "warning", "critical"]
    created_at: datetime
    picked_up_at: datetime | None
    arrived_at: datetime | None
    received_at: datetime | None
    last_update_at: datetime


class ShipmentList(BaseModel):
    scope: Literal["source", "destination", "network"]
    shipments: list[ShipmentSummary]
    counts: dict[str, int] = Field(
        description="awaiting_pickup, in_transit, delayed, arrived, completed_today, "
        "cold_chain_alerts, on_schedule, late"
    )
    average_delivery_minutes: float | None = Field(
        description="Mean simulated created→arrived time of completed shipments in scope"
    )
    generated_at: datetime
    label: str = LOGISTICS_LABEL
    disclaimer: str = LOGISTICS_DISCLAIMER


class ShipmentBagOut(BaseModel):
    public_id: str
    blood_group: str
    component: str
    status: str
    expires_at: datetime
    chain_valid: bool
    chain_length: int


class ColdChainBag(BaseModel):
    public_id: str
    monitored: bool
    device_id: str | None
    cold_chain_status: str
    excursion_active: bool
    latest_temperature_c: float | None
    device_status: str | None
    last_telemetry_at: datetime | None


class ShipmentTelemetry(BaseModel):
    shipment_id: UUID
    reference: str
    status: ShipmentStatus
    in_transit: bool
    cold_chain_alert: Literal["none", "warning", "critical"]
    bags: list[ColdChainBag]
    source: SourceMeta
    note: str = "Simulated IoT telemetry — prototype. Critical bags stay flagged for human review."


class ShipmentDetail(ShipmentSummary):
    request_status: str
    bags: list[ShipmentBagOut]
    checkpoints: list[CheckpointOut]
    distance_km: float
    planned_minutes: int
    trace_valid: bool = Field(description="Every bag's hash-chained trace verifies")
    telemetry: ShipmentTelemetry
    simulator_enabled: bool
    source: SourceMeta
    label: str = LOGISTICS_LABEL
    disclaimer: str = LOGISTICS_DISCLAIMER


class ShipmentRoute(BaseModel):
    shipment_id: UUID
    reference: str
    status: ShipmentStatus
    distance_km: float
    current_checkpoint: int
    checkpoints: list[CheckpointOut]
    eta: EtaOut
    source: SourceMeta
    label: str = ROUTE_MAP_LABEL


class TimelineEvent(BaseModel):
    seq: int
    event_type: str
    status: ShipmentStatus
    occurred_at: datetime
    meta: dict[str, Any]


class ShipmentTimeline(BaseModel):
    shipment_id: UUID
    reference: str
    events: list[TimelineEvent]
    label: str = LOGISTICS_LABEL


class DelayBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    minutes: int = Field(default=18, ge=1, le=240)
    reason: DelayReason = "traffic_simulated"


class LogisticsResult(BaseModel):
    shipment: ShipmentDetail
    action: str
    events: list[str] = Field(description="Shipment events raised by this action")
