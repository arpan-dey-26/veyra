from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core import validation as v
from app.core.provenance import SourceMeta
from app.modules.bags.domain import Component
from app.modules.donations.schemas import BloodGroup

Urgency = Literal["routine", "urgent", "emergency"]
RequestStatus = Literal[
    "pending", "acknowledged", "dispatched", "fulfilled", "rejected", "cancelled"
]


class AvailabilityItem(BaseModel):
    provider: str
    target_ref: str
    name: str
    city: str
    state: str
    band: Literal["sufficient", "limited", "none"] = Field(
        description="Banded availability: exact stock of other facilities is never disclosed"
    )
    source: SourceMeta


class AvailabilityResponse(BaseModel):
    blood_group: str
    component: str
    units: int
    results: list[AvailabilityItem]


class CreateBloodRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: Literal["internal", "mock"] = "internal"
    target_ref: str = Field(min_length=1, max_length=64)
    blood_group: BloodGroup
    component: Component
    units: int = Field(ge=1, le=20)
    urgency: Urgency = "routine"
    needed_by: datetime
    notes: str | None = Field(default=None, max_length=500)

    @field_validator("notes")
    @classmethod
    def _notes(cls, value: str | None) -> str | None:
        return (v.clean_text(value) or None) if value is not None else None


class RespondRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    note: str | None = Field(default=None, max_length=500)

    @field_validator("note")
    @classmethod
    def _note(cls, value: str | None) -> str | None:
        return (v.clean_text(value) or None) if value is not None else None


class RejectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    note: str = Field(min_length=3, max_length=500)

    @field_validator("note")
    @classmethod
    def _note(cls, value: str) -> str:
        cleaned = v.clean_text(value)
        if len(cleaned) < 3:
            raise ValueError("Give a short reason")
        return cleaned


class AllocatedBag(BaseModel):
    public_id: str
    component: str
    blood_group: str
    expires_at: datetime
    status: str


class BloodRequestOut(BaseModel):
    id: UUID
    reference: str
    hospital_id: UUID
    hospital_name: str
    provider: str
    target_facility_id: UUID | None
    target_name: str
    blood_group: str
    component: str
    units: int
    urgency: str
    needed_by: datetime
    status: RequestStatus
    notes: str | None
    response_note: str | None
    created_at: datetime
    updated_at: datetime
    bags: list[AllocatedBag]
    source: SourceMeta
