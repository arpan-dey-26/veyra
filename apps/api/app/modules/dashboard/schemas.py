from __future__ import annotations

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class StatusCount(BaseModel):
    status: str
    count: int


class DayCount(BaseModel):
    day: date
    count: int


class MovementDay(BaseModel):
    day: date
    dispatched: int = Field(description="Bags dispatched from or to this facility that day")
    received: int = Field(description="Bags confirmed received from or at this facility")


class ExpiryBucket(BaseModel):
    bucket: Literal["expired", "lt_1d", "d1_3", "d3_7", "d7_30", "gt_30d"]
    label: str
    count: int


class ActivityItem(BaseModel):
    """One network event (from the outbox). Carries no donor identity or health data."""

    event_id: str
    topic: str
    created_at: datetime
    reference: str | None = None
    status: str | None = None
    blood_group: str | None = None
    component: str | None = None
    units: int | None = None
    urgency: str | None = None
    reason: str | None = None


class RequestSummary(BaseModel):
    direction: Literal["outgoing", "incoming"]
    total: int
    open: int = Field(description="pending + acknowledged + dispatched")
    emergency_open: int
    by_status: list[StatusCount]


class DonationSummary(BaseModel):
    applicable: bool = Field(description="False for hospitals (they don't collect donations)")
    today: int
    window_total: int
    by_day: list[DayCount]


class FacilityDashboard(BaseModel):
    facility_id: UUID
    facility_name: str
    kind: Literal["HOSPITAL", "BLOOD_BANK"]
    generated_at: datetime
    window_days: int
    utc_offset_minutes: int
    requests: RequestSummary
    donations: DonationSummary
    movements: list[MovementDay]
    on_hand: int
    expiry: list[ExpiryBucket]
    activity: list[ActivityItem]


class RoleCount(BaseModel):
    role: str
    active: int
    pending_verification: int
    disabled: int
    total: int


class AuditItem(BaseModel):
    """Audit summary row: no IP, no meta, no actor id (those stay in the audit table)."""

    action: str
    resource: str
    actor_type: str
    created_at: datetime


class AuditSummary(BaseModel):
    last_24h: int
    top_actions: list[StatusCount]
    recent: list[AuditItem]


class FacilityTotals(BaseModel):
    blood_banks: int
    hospitals: int
    simulated: int


class AdminDashboard(BaseModel):
    generated_at: datetime
    window_days: int
    utc_offset_minutes: int
    users: list[RoleCount]
    users_total: int
    facilities: FacilityTotals
    requests_by_status: list[StatusCount]
    bags_by_status: list[StatusCount]
    donations_by_day: list[DayCount]
    movements: list[MovementDay]
    audit: AuditSummary
    activity: list[ActivityItem]


class NetworkNode(BaseModel):
    id: str = Field(description="Facility UUID, or 'mock:<ref>' for a simulated partner bank")
    name: str
    kind: Literal["HOSPITAL", "BLOOD_BANK"]
    city: str
    simulated: bool
    is_self: bool


class NetworkEdge(BaseModel):
    source: str = Field(description="Hospital node id")
    target: str = Field(description="Blood bank node id")
    requests: int
    open: int
    units: int
    last_status: str
    last_at: datetime


class NetworkGraph(BaseModel):
    generated_at: datetime
    window_days: int
    nodes: list[NetworkNode]
    edges: list[NetworkEdge]
    note: str = "Prototype network visualization — not a geographic map."
