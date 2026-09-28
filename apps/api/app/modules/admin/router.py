"""Admin endpoints. Admins manage accounts and facilities; they do not get donor health data."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from app.core.pagination import MAX_PAGE_SIZE, Page, PageMeta
from app.core.rbac import AuthContext, Permission
from app.modules.facilities.router import get_facility_service
from app.modules.facilities.schemas import (
    CreatedInvite,
    CreateFacilityRequest,
    CreateInviteRequest,
    FacilityOut,
    InviteOut,
)
from app.modules.facilities.service import FacilityService
from app.modules.identity.deps import csrf_protect, require
from app.modules.identity.presenter import user_out
from app.modules.identity.schemas import UserOut
from app.persistence.deps import get_uow
from app.persistence.repositories import UnitOfWork

router = APIRouter(prefix="/admin", tags=["admin"])

RoleFilter = Literal["DONOR", "HOSPITAL", "BLOOD_BANK", "ADMIN"]


@router.get("/users", response_model=Page[UserOut], summary="List user accounts")
async def list_users(
    role: RoleFilter | None = None,
    limit: int = Query(default=25, ge=1, le=MAX_PAGE_SIZE),
    offset: int = Query(default=0, ge=0),
    _: AuthContext = Depends(require(Permission.USER_READ)),
    uow: UnitOfWork = Depends(get_uow),
) -> Page[UserOut]:
    rows, total = await uow.users.list_page(role=role, limit=limit, offset=offset)
    return Page[UserOut](
        data=[user_out(u) for u in rows], meta=PageMeta(total=total, limit=limit, offset=offset)
    )


@router.get("/facilities", response_model=Page[FacilityOut], summary="List facilities")
async def list_facilities(
    limit: int = Query(default=25, ge=1, le=MAX_PAGE_SIZE),
    offset: int = Query(default=0, ge=0),
    _: AuthContext = Depends(require(Permission.FACILITY_MANAGE)),
    service: FacilityService = Depends(get_facility_service),
) -> Page[FacilityOut]:
    rows, total = await service.list_page(limit=limit, offset=offset)
    return Page[FacilityOut](data=rows, meta=PageMeta(total=total, limit=limit, offset=offset))


@router.post(
    "/facilities",
    response_model=FacilityOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(csrf_protect)],
    summary="Onboard a hospital or blood bank",
)
async def create_facility(
    body: CreateFacilityRequest,
    ctx: AuthContext = Depends(require(Permission.FACILITY_MANAGE)),
    service: FacilityService = Depends(get_facility_service),
) -> FacilityOut:
    return await service.create(ctx, body)


@router.get(
    "/facilities/{facility_id}/invites",
    response_model=list[InviteOut],
    summary="Invitations for a facility",
)
async def list_invites(
    facility_id: UUID,
    _: AuthContext = Depends(require(Permission.FACILITY_MANAGE)),
    service: FacilityService = Depends(get_facility_service),
) -> list[InviteOut]:
    return await service.list_invites(facility_id)


@router.post(
    "/facilities/{facility_id}/invites",
    response_model=CreatedInvite,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(csrf_protect)],
    summary="Invite a staff member to a facility (demo: link returned instead of email)",
)
async def create_invite(
    facility_id: UUID,
    body: CreateInviteRequest,
    ctx: AuthContext = Depends(require(Permission.FACILITY_MANAGE)),
    service: FacilityService = Depends(get_facility_service),
) -> CreatedInvite:
    return await service.create_invite(ctx, facility_id, body.email)
