"""Phase 8: donation camps. Banks manage their own, admins network-wide, donors register."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Body, Depends, Query

from app.core.clock import Clock
from app.core.rbac import AuthContext, Permission
from app.modules.camps.schemas import (
    CampCreate,
    CampDashboard,
    CampList,
    CampOut,
    CampStatus,
    CampUpdate,
    CancelCamp,
    MyRegistration,
    MyRegistrations,
    PublicCampList,
    PublicCampOut,
    RegistrationList,
)
from app.modules.camps.service import CampService
from app.modules.identity.deps import csrf_protect, get_clock, require, require_any
from app.persistence.deps import get_uow
from app.persistence.repositories import UnitOfWork

router = APIRouter(prefix="/camps", tags=["camps"])

MANAGE = require_any(Permission.CAMP_MANAGE_OWN, Permission.CAMP_MANAGE_ANY)
PUBLIC = require(Permission.CAMP_READ_PUBLIC)
DONOR = require(Permission.CAMP_REGISTER_SELF)
Action = Literal["publish", "open-registration", "start", "complete", "cancel"]


def get_camp_service(
    uow: UnitOfWork = Depends(get_uow), clock: Clock = Depends(get_clock)
) -> CampService:
    return CampService(uow, clock)


# ---------------------------------------------------------------- static paths first


@router.get("", response_model=CampList, summary="Camps I manage (own bank; admins: network)")
async def list_camps(
    status: CampStatus | None = Query(default=None),
    ctx: AuthContext = Depends(MANAGE),
    service: CampService = Depends(get_camp_service),
) -> CampList:
    return await service.list_managed(ctx, status)


@router.post(
    "",
    response_model=CampOut,
    status_code=201,
    dependencies=[Depends(csrf_protect)],
    summary="Create a camp (planned)",
)
async def create_camp(
    body: CampCreate,
    ctx: AuthContext = Depends(MANAGE),
    service: CampService = Depends(get_camp_service),
) -> CampOut:
    return await service.create(ctx, body)


@router.get("/dashboard", response_model=CampDashboard, summary="Camp dashboard (scoped)")
async def camp_dashboard(
    ctx: AuthContext = Depends(MANAGE), service: CampService = Depends(get_camp_service)
) -> CampDashboard:
    return await service.dashboard(ctx)


@router.get("/public", response_model=PublicCampList, summary="Published camps (search / filter)")
async def public_camps(
    q: str | None = Query(default=None, max_length=80),
    city: str | None = Query(default=None, max_length=80),
    status: Literal["published", "registration_open", "ongoing"] | None = Query(default=None),
    ctx: AuthContext = Depends(PUBLIC),
    service: CampService = Depends(get_camp_service),
) -> PublicCampList:
    return await service.public_list(ctx, q=q, city=city, status=status)


@router.get("/public/{camp_id}", response_model=PublicCampOut, summary="Published camp detail")
async def public_camp(
    camp_id: UUID,
    ctx: AuthContext = Depends(PUBLIC),
    service: CampService = Depends(get_camp_service),
) -> PublicCampOut:
    return await service.public_get(ctx, camp_id)


@router.get("/me/registrations", response_model=MyRegistrations, summary="My camp registrations")
async def my_registrations(
    ctx: AuthContext = Depends(DONOR), service: CampService = Depends(get_camp_service)
) -> MyRegistrations:
    return await service.my_registrations(ctx)


# ---------------------------------------------------------------- one camp


@router.get("/{camp_id}", response_model=CampOut, summary="Camp management detail + stats")
async def get_camp(
    camp_id: UUID,
    ctx: AuthContext = Depends(MANAGE),
    service: CampService = Depends(get_camp_service),
) -> CampOut:
    return await service.get_managed(ctx, camp_id)


@router.patch(
    "/{camp_id}",
    response_model=CampOut,
    dependencies=[Depends(csrf_protect)],
    summary="Edit a camp (planned / published / registration open)",
)
async def update_camp(
    camp_id: UUID,
    body: CampUpdate,
    ctx: AuthContext = Depends(MANAGE),
    service: CampService = Depends(get_camp_service),
) -> CampOut:
    return await service.update(ctx, camp_id, body)


@router.post(
    "/{camp_id}/actions/{action}",
    response_model=CampOut,
    dependencies=[Depends(csrf_protect)],
    summary="Lifecycle: publish, open-registration, start, complete, cancel",
)
async def camp_action(
    camp_id: UUID,
    action: Action,
    body: CancelCamp | None = Body(default=None),
    ctx: AuthContext = Depends(MANAGE),
    service: CampService = Depends(get_camp_service),
) -> CampOut:
    return await service.transition(ctx, camp_id, action, body.reason if body else None)


@router.get(
    "/{camp_id}/registrations",
    response_model=RegistrationList,
    summary="Registrations for a camp I manage (no medical data)",
)
async def camp_registrations(
    camp_id: UUID,
    ctx: AuthContext = Depends(MANAGE),
    service: CampService = Depends(get_camp_service),
) -> RegistrationList:
    return await service.registrations(ctx, camp_id)


@router.post(
    "/{camp_id}/registrations/{registration_id}/attend",
    response_model=RegistrationList,
    dependencies=[Depends(csrf_protect)],
    summary="Staff confirm a registered donor attended (not an eligibility decision)",
)
async def confirm_attendance(
    camp_id: UUID,
    registration_id: UUID,
    ctx: AuthContext = Depends(MANAGE),
    service: CampService = Depends(get_camp_service),
) -> RegistrationList:
    return await service.confirm_attendance(ctx, camp_id, registration_id)


@router.post(
    "/{camp_id}/register",
    response_model=MyRegistration,
    status_code=201,
    dependencies=[Depends(csrf_protect)],
    summary="Donor: register for a camp with open registration",
)
async def register(
    camp_id: UUID,
    ctx: AuthContext = Depends(DONOR),
    service: CampService = Depends(get_camp_service),
) -> MyRegistration:
    return await service.register(ctx, camp_id)


@router.post(
    "/{camp_id}/register/cancel",
    response_model=MyRegistration,
    dependencies=[Depends(csrf_protect)],
    summary="Donor: cancel my registration",
)
async def cancel_registration(
    camp_id: UUID,
    ctx: AuthContext = Depends(DONOR),
    service: CampService = Depends(get_camp_service),
) -> MyRegistration:
    return await service.cancel_registration(ctx, camp_id)
