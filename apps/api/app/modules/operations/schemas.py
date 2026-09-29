from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.core.provenance import SourceMeta
from app.modules.operations.engine import (
    FORECAST_INPUT_LABEL,
    OPS_DISCLAIMER,
    OPS_LABEL,
    ROUTING_LABEL,
)
from app.modules.requests.schemas import Urgency

PriorityBandOut = Literal["immediate", "high", "standard"]
PressureLevelOut = Literal["normal", "watch", "elevated"]
ColdStateOut = Literal["unmonitored", "normal", "warning", "critical", "stale"]


class ReasonOut(BaseModel):
    code: str
    text: str
    points: int = Field(description="Contribution to the operational priority score (0 = info)")
    tone: Literal["info", "positive", "attention", "warning"]


class PriorityOut(BaseModel):
    request_id: UUID
    reference: str
    score: int = Field(ge=0, le=100, description="Operational priority score, not a clinical score")
    band: PriorityBandOut
    recommendation: str
    action_code: str
    reasons: list[ReasonOut]
    computed_at: datetime
    label: str = OPS_LABEL
    disclaimer: str = OPS_DISCLAIMER


class RouteOut(BaseModel):
    source_facility_id: UUID
    source_name: str
    destination_facility_id: UUID
    destination_name: str
    urgency: str
    distance_km: float
    travel_minutes: int
    handover_minutes: int
    eta_minutes: int
    status: Literal["clear", "slow", "delayed"]
    reasons: list[ReasonOut]
    source: SourceMeta
    label: str = ROUTING_LABEL


class OpsRequest(BaseModel):
    id: UUID
    reference: str
    hospital_id: UUID
    hospital_name: str
    target_facility_id: UUID | None
    target_name: str
    provider: str
    blood_group: str
    component: str
    units: int
    urgency: str
    status: str
    requested_at: datetime
    needed_by: datetime
    age_minutes: int
    priority: PriorityOut
    route: RouteOut | None = Field(default=None, description="Simulated ETA while dispatched")


class OpsRequestList(BaseModel):
    scope: Literal["facility", "network"]
    requests: list[OpsRequest]
    counts: dict[str, int] = Field(
        description="open, emergency_open, dispatched, expected_units, received_units_7d"
    )
    generated_at: datetime
    label: str = OPS_LABEL
    disclaimer: str = OPS_DISCLAIMER


class PressureRow(BaseModel):
    blood_group: str
    component: str
    level: PressureLevelOut
    stock: int
    open_units: int
    free_stock: int
    forecast_daily_mean: float | None
    coverage_days: float | None
    reasons: list[ReasonOut]


class FacilityPressure(BaseModel):
    facility_id: UUID
    facility_name: str
    facility_type: str
    horizon_days: int
    rows: list[PressureRow]
    counts: dict[str, int]
    generated_at: datetime
    source: SourceMeta
    forecast_label: str = FORECAST_INPUT_LABEL
    disclaimer: str = OPS_DISCLAIMER


class CandidateBag(BaseModel):
    rank: int
    public_id: str
    blood_group: str
    component: str
    expires_at: datetime
    expires_in_hours: float
    fefo_position: int
    cold_chain_state: ColdStateOut
    device_id: str | None
    latest_temperature_c: float | None
    current_facility_id: UUID
    current_facility_name: str
    recommended: bool
    deprioritized: bool
    reasons: list[ReasonOut]


class Recommendation(BaseModel):
    request_id: UUID
    reference: str
    status: str
    units: int
    blood_group: str
    component: str
    recommendation: str
    recommended_bag_ids: list[str]
    fefo_default_bag_ids: list[str] = Field(
        description="What a plain dispatch (no bag selection) would pick: strict FEFO"
    )
    candidates: list[CandidateBag]
    compatibility_rule: str
    priority: PriorityOut
    pressure: PressureRow
    route: RouteOut | None
    human_confirmation: str
    generated_at: datetime
    label: str = OPS_LABEL
    disclaimer: str = OPS_DISCLAIMER


class ActiveRoute(BaseModel):
    request_id: UUID
    reference: str
    dispatched_at: datetime
    expected_at: datetime
    route: RouteOut


class RoutingOverview(BaseModel):
    scope: Literal["facility", "network"]
    routes: list[ActiveRoute]
    generated_at: datetime
    label: str = ROUTING_LABEL


class AlertOut(BaseModel):
    kind: Literal["emergency_request", "cold_chain", "pressure", "expiring", "device_stale"]
    severity: Literal["warning", "attention"]
    title: str
    detail: str
    ref: str = Field(description="Request id, bag public id, or group/component")
    facility_name: str | None = None
    at: datetime | None = None


class AlertsOut(BaseModel):
    scope: Literal["facility", "network"]
    alerts: list[AlertOut]
    counts: dict[str, int]
    generated_at: datetime
    label: str = OPS_LABEL
    disclaimer: str = OPS_DISCLAIMER


ChangeReason = Literal[
    "escalated_by_requesting_team", "situation_resolved", "entered_in_error", "other"
]


class ChangePriority(BaseModel):
    model_config = ConfigDict(extra="forbid")

    urgency: Urgency
    reason: ChangeReason = Field(
        description="A reason code (no free text, so no personal details reach the audit log)"
    )
