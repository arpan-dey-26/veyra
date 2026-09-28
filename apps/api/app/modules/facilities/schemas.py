from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core import validation as v


class CreateFacilityRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["HOSPITAL", "BLOOD_BANK"]
    name: str = Field(min_length=3, max_length=160)
    registration_number: str | None = Field(default=None, max_length=64)
    address: str
    city: str
    state: str
    pin_code: str

    @field_validator("name")
    @classmethod
    def _name(cls, value: str) -> str:
        name = v.clean_text(value)
        if len(name) < 3:
            raise ValueError("Facility name must be at least 3 characters")
        return name

    @field_validator("registration_number")
    @classmethod
    def _reg(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = v.clean_text(value).upper()
        return cleaned or None

    @field_validator("address")
    @classmethod
    def _address(cls, value: str) -> str:
        return v.validate_address(value)

    @field_validator("city")
    @classmethod
    def _city(cls, value: str) -> str:
        return v.validate_city(value)

    @field_validator("state")
    @classmethod
    def _state(cls, value: str) -> str:
        return v.validate_state(value)

    @field_validator("pin_code")
    @classmethod
    def _pin(cls, value: str) -> str:
        return v.validate_pin_code(value)


class FacilityOut(BaseModel):
    id: UUID
    type: str
    name: str
    registration_number: str | None
    address: str
    city: str
    state: str
    pin_code: str
    provider_kind: str
    is_simulated: bool
    status: str
    created_at: datetime


class CreateInviteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str

    @field_validator("email")
    @classmethod
    def _email(cls, value: str) -> str:
        return v.normalize_email(value)


class InviteDelivery(BaseModel):
    mode: Literal["demo_link"]
    note: str


class InviteOut(BaseModel):
    id: UUID
    facility_id: UUID
    email: str
    role: str
    status: Literal["pending", "accepted", "expired", "revoked"]
    expires_at: datetime
    created_at: datetime


class CreatedInvite(InviteOut):
    accept_path: str = Field(description="One-time link path; shown once, never stored in clear")
    delivery: InviteDelivery
