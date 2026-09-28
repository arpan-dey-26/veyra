from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator

from app.core import validation as v


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid", str_max_length=512)


class RegisterDonorRequest(_In):
    full_name: str
    email: str
    mobile: str = Field(description="Indian mobile number, e.g. 98765 43210 or +919876543210")
    blood_group: str = Field(description="One of A+, A-, B+, B-, AB+, AB-, O+, O-")
    address: str
    city: str
    state: str = Field(description="Indian state or union territory")
    pin_code: str
    password: str = Field(repr=False, description="10-128 characters")

    @field_validator("full_name")
    @classmethod
    def _full_name(cls, value: str) -> str:
        return v.validate_person_name(value)

    @field_validator("email")
    @classmethod
    def _email(cls, value: str) -> str:
        return v.normalize_email(value)

    @field_validator("mobile")
    @classmethod
    def _mobile(cls, value: str) -> str:
        return v.normalize_indian_mobile(value)

    @field_validator("blood_group")
    @classmethod
    def _blood_group(cls, value: str) -> str:
        return v.validate_blood_group(value)

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
    def _pin_code(cls, value: str) -> str:
        return v.validate_pin_code(value)

    @field_validator("password")
    @classmethod
    def _password(cls, value: str, info: ValidationInfo) -> str:
        email = info.data.get("email") if isinstance(info.data, dict) else None
        return v.validate_new_password(value, email=email if isinstance(email, str) else None)


class LoginRequest(_In):
    email: str
    password: str = Field(repr=False, max_length=v.PASSWORD_MAX)

    @field_validator("email")
    @classmethod
    def _email(cls, value: str) -> str:
        # Don't reveal format rules on login; just normalise.
        return value.strip().lower()


class VerifyRequest(_In):
    challenge_id: UUID
    code: str = Field(min_length=1, max_length=12, repr=False)

    @field_validator("code")
    @classmethod
    def _code(cls, value: str) -> str:
        return value.strip().replace(" ", "")


class AcceptInviteRequest(_In):
    token: str = Field(min_length=20, max_length=128, repr=False)
    full_name: str
    mobile: str
    password: str = Field(repr=False)

    @field_validator("full_name")
    @classmethod
    def _full_name(cls, value: str) -> str:
        return v.validate_person_name(value)

    @field_validator("mobile")
    @classmethod
    def _mobile(cls, value: str) -> str:
        return v.normalize_indian_mobile(value)

    @field_validator("password")
    @classmethod
    def _password(cls, value: str) -> str:
        return v.validate_new_password(value)


class UserOut(BaseModel):
    id: UUID
    email: str
    full_name: str
    mobile: str
    role: str
    status: str
    is_demo: bool
    verified_at: datetime | None
    created_at: datetime


class VerificationOut(BaseModel):
    challenge_id: UUID
    mode: Literal["demo", "otp"] = Field(
        description="'demo' = prototype verification, NOT a real OTP. The UI must say so."
    )
    provider: str
    channel: str
    destination_hint: str
    expires_at: datetime
    attempts_remaining: int
    disclaimer: str | None = Field(description="Mandatory UI text when mode is 'demo'")


class RegisterResponse(BaseModel):
    user: UserOut
    verification: VerificationOut


class DonorSummary(BaseModel):
    blood_group: str
    city: str
    state: str


class FacilitySummary(BaseModel):
    id: UUID
    name: str
    type: str
    city: str
    state: str
    is_simulated: bool


class MeResponse(BaseModel):
    user: UserOut
    permissions: list[str]
    donor: DonorSummary | None = None
    facility: FacilitySummary | None = None


class InvitePreview(BaseModel):
    email: str
    role: str
    facility: FacilitySummary
    expires_at: datetime
