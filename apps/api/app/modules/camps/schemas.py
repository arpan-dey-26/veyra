from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

CAMP_DISCLAIMER = (
    "Prototype camp-management workflow; donor eligibility and medical screening remain "
    "governed by authorized staff."
)

CampStatus = Literal[
    "planned", "published", "registration_open", "ongoing", "completed", "cancelled"
]
RegistrationStatus = Literal["registered", "cancelled", "attended", "no_show"]
CampAction = Literal["publish", "open-registration", "start", "complete", "cancel"]

_PHONE = r"^\+?[0-9][0-9 \-]{5,18}$"
_EMAIL = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"


def _aware(value: datetime | None) -> datetime | None:
    if value is not None and value.tzinfo is None:
        raise ValueError("must include a timezone")
    return value


class CampCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    title: str = Field(min_length=3, max_length=120)
    organizer_facility_id: UUID | None = Field(
        default=None, description="Admins only: the organizing blood bank"
    )
    venue: str = Field(min_length=3, max_length=160)
    city: str = Field(min_length=2, max_length=80)
    state: str = Field(min_length=2, max_length=64)
    starts_at: datetime
    ends_at: datetime
    capacity: int = Field(ge=1, le=5000)
    description: str | None = Field(default=None, max_length=2000)
    contact_name: str = Field(min_length=2, max_length=80)
    contact_phone: str | None = Field(default=None, pattern=_PHONE)
    contact_email: str | None = Field(default=None, max_length=254, pattern=_EMAIL)

    @field_validator("starts_at", "ends_at")
    @classmethod
    def _tz(cls, value: datetime | None) -> datetime | None:
        return _aware(value)


class CampUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    title: str | None = Field(default=None, min_length=3, max_length=120)
    venue: str | None = Field(default=None, min_length=3, max_length=160)
    city: str | None = Field(default=None, min_length=2, max_length=80)
    state: str | None = Field(default=None, min_length=2, max_length=64)
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    capacity: int | None = Field(default=None, ge=1, le=5000)
    description: str | None = Field(default=None, max_length=2000)
    contact_name: str | None = Field(default=None, min_length=2, max_length=80)
    contact_phone: str | None = Field(default=None, pattern=_PHONE)
    contact_email: str | None = Field(default=None, max_length=254, pattern=_EMAIL)

    @field_validator("starts_at", "ends_at")
    @classmethod
    def _tz(cls, value: datetime | None) -> datetime | None:
        return _aware(value)


class CancelCamp(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str | None = Field(default=None, max_length=200)


class CampStats(BaseModel):
    registered: int
    attended: int
    cancelled: int
    no_show: int
    donations_recorded: int
    bags_collected: int
    seats_left: int


class CampOut(BaseModel):
    """Management view (organizing blood bank or admin)."""

    id: UUID
    code: str
    title: str
    organizer_facility_id: UUID
    organizer_name: str
    venue: str
    city: str
    state: str
    starts_at: datetime
    ends_at: datetime
    capacity: int
    registered_count: int
    status: CampStatus
    registration_open: bool
    description: str | None
    contact_name: str
    contact_phone: str | None
    contact_email: str | None
    cancel_reason: str | None
    created_at: datetime
    updated_at: datetime
    allowed_actions: list[CampAction]
    editable: bool
    stats: CampStats
    disclaimer: str = CAMP_DISCLAIMER


class CampList(BaseModel):
    scope: Literal["facility", "network"]
    camps: list[CampOut]
    disclaimer: str = CAMP_DISCLAIMER


class CampDashboard(BaseModel):
    scope: Literal["facility", "network"]
    upcoming: int
    active: int
    completed: int
    cancelled: int
    total_capacity: int
    total_registered: int
    total_attended: int
    donations_recorded: int
    bags_collected: int
    next_camps: list[CampOut]
    disclaimer: str = CAMP_DISCLAIMER


class PublicCampOut(BaseModel):
    """What donors (and hospitals) see: no registrations, no other donors."""

    id: UUID
    code: str
    title: str
    organizer_name: str
    venue: str
    city: str
    state: str
    starts_at: datetime
    ends_at: datetime
    capacity: int
    registered_count: int
    seats_left: int
    status: CampStatus
    registration_open: bool
    description: str | None
    contact_name: str
    contact_phone: str | None
    contact_email: str | None
    my_registration_status: RegistrationStatus | None = None
    disclaimer: str = CAMP_DISCLAIMER


class PublicCampList(BaseModel):
    camps: list[PublicCampOut]
    disclaimer: str = CAMP_DISCLAIMER


class RegistrationOut(BaseModel):
    """Staff view of one registration: identification for the desk, no medical data."""

    id: UUID
    donor_id: UUID
    donor_name: str
    mobile_masked: str
    status: RegistrationStatus
    registered_at: datetime
    cancelled_at: datetime | None
    attended_at: datetime | None
    donation_id: UUID | None


class RegistrationList(BaseModel):
    camp_id: UUID
    code: str
    registrations: list[RegistrationOut]
    disclaimer: str = CAMP_DISCLAIMER


class MyRegistration(BaseModel):
    id: UUID
    status: RegistrationStatus
    registered_at: datetime
    cancelled_at: datetime | None
    attended_at: datetime | None
    donation_recorded: bool
    can_cancel: bool
    camp: PublicCampOut


class MyRegistrations(BaseModel):
    registrations: list[MyRegistration]
    disclaimer: str = CAMP_DISCLAIMER
