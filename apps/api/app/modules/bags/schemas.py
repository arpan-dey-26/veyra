from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ComponentInfo(BaseModel):
    code: str
    label: str
    shelf_life_days: int
    storage: str


class InventoryRow(BaseModel):
    blood_group: str
    component: str
    available: int = Field(description="Usable units on hand (not expired)")
    expired: int = Field(description="Past expiry, still on the shelf: discard them")
    expiring_soon: int = Field(description="Usable units expiring within 72 hours")
    next_expiry: datetime | None


class InventorySummary(BaseModel):
    facility_id: UUID
    facility_name: str
    generated_at: datetime
    total_available: int
    rows: list[InventoryRow]
    components: list[ComponentInfo]
    reference_note: str


class BagOut(BaseModel):
    id: UUID
    public_id: str
    qr_payload: str
    blood_group: str
    component: str
    volume_ml: int
    collected_at: datetime
    expires_at: datetime
    status: str
    is_expired: bool
    current_facility_id: UUID
    current_facility_name: str


class BagEventOut(BaseModel):
    seq: int
    event_type: str
    occurred_at: datetime
    from_facility: str | None
    to_facility: str | None
    meta: dict[str, object]
    prev_hash: str
    row_hash: str


class ChainStatus(BaseModel):
    valid: bool
    length: int
    head_hash: str | None
    note: str = (
        "Tamper-evident SHA-256 chain stored in the VEYRA database. "
        "It is not anchored on a blockchain (possible future work)."
    )


class BagTrace(BaseModel):
    bag: BagOut
    events: list[BagEventOut]
    chain: ChainStatus


class DiscardRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: Literal["expired", "damaged", "failed_screening", "other"]
    note: str | None = Field(default=None, max_length=300)


class ScanColdChain(BaseModel):
    monitored: bool
    status: Literal["unmonitored", "unknown", "normal", "warning", "critical"]
    excursion_active: bool
    current_c: float | None
    last_reading_at: datetime | None
    simulated: bool = True


class ScanShipment(BaseModel):
    id: UUID
    reference: str
    status: str
    source_name: str
    destination_name: str
    eta_at: datetime
    delay_active: bool
    simulated: bool = True


class BagScanResult(BaseModel):
    """What an authorized scanner may see. Never donor or patient identity."""

    public_id: str
    qr_payload: str
    bag: BagOut
    lifecycle_status: str
    usable: bool = Field(description="Available and unexpired (still needs human checks)")
    location: str = Field(description="Facility currently holding the bag")
    cold_chain: ScanColdChain
    shipment: ScanShipment | None
    chain: ChainStatus
    events: int
    last_event_type: str | None
    last_event_at: datetime | None
    trace_path: str
    disclaimer: str


class BagQr(BaseModel):
    public_id: str
    payload: str
    size: int = Field(description="Modules per side (quiet zone not included)")
    modules: list[str] = Field(description="Rows of '1' (dark) / '0' (light)")
    error_correction: Literal["M"] = "M"
    disclaimer: str
