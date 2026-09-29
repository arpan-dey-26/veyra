from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core import validation as v
from app.modules.bags.domain import Component
from app.modules.bags.schemas import BagOut

BloodGroup = Literal["A+", "A-", "B+", "B-", "AB+", "AB-", "O+", "O-"]


class DonorLookupRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mobile: str

    @field_validator("mobile")
    @classmethod
    def _mobile(cls, value: str) -> str:
        return v.normalize_indian_mobile(value)


class DonorLookupResult(BaseModel):
    """What a donation desk needs, and nothing more (no address, email or full mobile)."""

    donor_id: UUID
    full_name: str
    mobile_masked: str
    blood_group: str
    blood_group_status: str
    last_donation_at: datetime | None
    eligible_from: datetime | None = Field(
        description="Earliest date the donor may donate again (None: eligible now)"
    )
    eligible_now: bool


class RecordDonationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    donor_id: UUID
    blood_group: BloodGroup = Field(description="Group determined by the blood bank at collection")
    volume_ml: Literal[350, 450]
    components: list[Component] = Field(
        default_factory=lambda: [Component.WHOLE_BLOOD], min_length=1, max_length=4
    )
    collected_at: datetime | None = Field(
        default=None, description="Defaults to now; may not be in the future or >48 h old"
    )
    notes: str | None = Field(default=None, max_length=500)
    camp_registration_id: UUID | None = Field(
        default=None, description="Phase 8: link to an attended camp registration (optional)"
    )

    @field_validator("components")
    @classmethod
    def _components(cls, value: list[Component]) -> list[Component]:
        if len(set(value)) != len(value):
            raise ValueError("Each component may be listed once")
        if Component.WHOLE_BLOOD in value and len(value) > 1:
            raise ValueError("Whole blood can't be combined with separated components")
        return value

    @field_validator("notes")
    @classmethod
    def _notes(cls, value: str | None) -> str | None:
        return v.clean_text(value) or None if value is not None else None


class DonationOut(BaseModel):
    id: UUID
    donor_id: UUID
    donor_name: str
    blood_group: str
    volume_ml: int
    collected_at: datetime
    status: str
    notes: str | None
    bags: list[BagOut]


class MyDonation(BaseModel):
    """A donor's view of their own donation: where it was given and how it was used,
    never which hospital or patient received it."""

    id: UUID
    collected_at: datetime
    facility_name: str
    facility_city: str
    volume_ml: int
    components: list[str]
    bags_total: int
    bags_in_stock: int
    bags_sent_to_hospitals: int
    bags_discarded: int


class MyDonations(BaseModel):
    donations: list[MyDonation]
    last_donation_at: datetime | None
    eligible_from: datetime | None
    eligible_now: bool
    interval_days: int
