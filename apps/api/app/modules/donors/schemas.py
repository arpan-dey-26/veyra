from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core import validation as v


class DonorProfile(BaseModel):
    """The donor's own profile. Only the donor can read it (donor_profile:read:self)."""

    id: UUID
    user_id: UUID
    full_name: str
    email: str
    mobile: str
    blood_group: str
    blood_group_status: str = Field(
        description="'self_declared' until a blood bank confirms it at a donation, then 'confirmed'"
    )
    address: str
    city: str
    state: str
    pin_code: str
    verified_at: datetime | None
    created_at: datetime
    updated_at: datetime


class UpdateDonorProfileRequest(BaseModel):
    """Editable by the donor. Email, mobile and blood group are not self-editable here:
    changing them needs re-verification (mobile/email) or a blood bank (blood group)."""

    model_config = ConfigDict(extra="forbid")

    full_name: str | None = None
    address: str | None = None
    city: str | None = None
    state: str | None = None
    pin_code: str | None = None

    @field_validator("full_name")
    @classmethod
    def _full_name(cls, value: str | None) -> str | None:
        return None if value is None else v.validate_person_name(value)

    @field_validator("address")
    @classmethod
    def _address(cls, value: str | None) -> str | None:
        return None if value is None else v.validate_address(value)

    @field_validator("city")
    @classmethod
    def _city(cls, value: str | None) -> str | None:
        return None if value is None else v.validate_city(value)

    @field_validator("state")
    @classmethod
    def _state(cls, value: str | None) -> str | None:
        return None if value is None else v.validate_state(value)

    @field_validator("pin_code")
    @classmethod
    def _pin_code(cls, value: str | None) -> str | None:
        return None if value is None else v.validate_pin_code(value)


class RegistrationReference(BaseModel):
    blood_groups: list[str]
    states: list[str]
    verification_mode: str
    verification_disclaimer: str | None
