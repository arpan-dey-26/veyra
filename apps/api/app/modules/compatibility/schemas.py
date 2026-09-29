from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from app.modules.compatibility.engine import COMPATIBILITY_DISCLAIMER, COMPATIBILITY_LABEL

ComponentCode = Literal["WHOLE_BLOOD", "PRBC", "PLATELETS", "FFP", "CRYO"]


class MatrixRow(BaseModel):
    recipient_group: str
    compatible_donors: list[str]


class ComponentMatrix(BaseModel):
    component: ComponentCode
    label: str
    rule: str = Field(description="Plain-language summary of the simplified reference rule")
    rh_considered: bool
    rows: list[MatrixRow]


class CompatibilityMatrix(BaseModel):
    blood_groups: list[str]
    components: list[ComponentMatrix]
    label: str = COMPATIBILITY_LABEL
    disclaimer: str = COMPATIBILITY_DISCLAIMER
    informational_only: bool = True


class CompatibilityCheck(BaseModel):
    donor_group: str
    recipient_group: str
    component: ComponentCode
    component_label: str
    compatible: bool
    result: Literal["compatible", "not_compatible"]
    reason: str
    rule: str
    compatible_donors_for_recipient: list[str]
    compatible_recipients_for_donor: list[str]
    label: str = COMPATIBILITY_LABEL
    disclaimer: str = COMPATIBILITY_DISCLAIMER
    informational_only: bool = True
    requires_clinical_confirmation: bool = True
