from __future__ import annotations

from fastapi import APIRouter, Depends

from app.core.clock import Clock
from app.core.rbac import AuthContext, Permission
from app.modules.facilities.schemas import FacilityOut
from app.modules.facilities.service import FacilityService
from app.modules.identity.deps import get_clock, require
from app.persistence.deps import get_uow
from app.persistence.repositories import UnitOfWork

router = APIRouter(tags=["facilities"])


def get_facility_service(
    uow: UnitOfWork = Depends(get_uow), clock: Clock = Depends(get_clock)
) -> FacilityService:
    return FacilityService(uow, clock)


@router.get("/facilities/me", response_model=FacilityOut, summary="My facility")
async def my_facility(
    ctx: AuthContext = Depends(require(Permission.FACILITY_READ_OWN)),
    service: FacilityService = Depends(get_facility_service),
) -> FacilityOut:
    return await service.get_own(ctx)
