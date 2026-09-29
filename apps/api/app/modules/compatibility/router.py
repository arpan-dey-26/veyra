"""Phase 8: read-only compatibility reference. It never allocates, approves or dispatches."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.core.rbac import AuthContext, Permission
from app.modules.bags.domain import Component
from app.modules.compatibility import engine as E
from app.modules.compatibility.schemas import (
    CompatibilityCheck,
    CompatibilityMatrix,
    ComponentCode,
    ComponentMatrix,
    MatrixRow,
)
from app.modules.donations.schemas import BloodGroup
from app.modules.identity.deps import require

router = APIRouter(prefix="/compatibility", tags=["compatibility"])

READ = require(Permission.COMPATIBILITY_READ)


def _matrix(component: Component) -> ComponentMatrix:
    rule = E.RULES[component]
    return ComponentMatrix(
        component=component.value,
        label=E.component_label(component),
        rule=rule.summary,
        rh_considered=rule.rh_matters,
        rows=[
            MatrixRow(recipient_group=g, compatible_donors=E.compatible_donors(g, component))
            for g in E.BLOOD_GROUPS
        ],
    )


@router.get(
    "/matrix",
    response_model=CompatibilityMatrix,
    summary="ABO/Rh compatibility reference matrix (informational prototype, not clinical)",
)
async def matrix(
    component: ComponentCode | None = Query(default=None),
    ctx: AuthContext = Depends(READ),
) -> CompatibilityMatrix:
    chosen = [Component(component)] if component else list(E.COMPONENTS)
    return CompatibilityMatrix(
        blood_groups=list(E.BLOOD_GROUPS), components=[_matrix(c) for c in chosen]
    )


@router.get(
    "/check",
    response_model=CompatibilityCheck,
    summary="Is a donor group compatible with a recipient group for a component? (reference)",
)
async def check(
    donor_group: BloodGroup,
    recipient_group: BloodGroup,
    component: ComponentCode,
    ctx: AuthContext = Depends(READ),
) -> CompatibilityCheck:
    comp = Component(component)
    verdict = E.check(donor_group, recipient_group, comp)
    return CompatibilityCheck(
        donor_group=donor_group,
        recipient_group=recipient_group,
        component=component,
        component_label=E.component_label(comp),
        compatible=verdict.compatible,
        result="compatible" if verdict.compatible else "not_compatible",
        reason=verdict.reason,
        rule=E.RULES[comp].summary,
        compatible_donors_for_recipient=E.compatible_donors(recipient_group, comp),
        compatible_recipients_for_donor=E.compatible_recipients(donor_group, comp),
    )
