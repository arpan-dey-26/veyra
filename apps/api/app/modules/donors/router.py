from __future__ import annotations

from fastapi import APIRouter, Depends

from app.core.clock import Clock
from app.core.rbac import AuthContext, Permission
from app.core.validation import BLOOD_GROUPS, INDIAN_STATES_AND_UTS
from app.modules.donors.schemas import (
    DonorProfile,
    RegistrationReference,
    UpdateDonorProfileRequest,
)
from app.modules.donors.service import DonorService
from app.modules.identity.deps import csrf_protect, get_clock, get_verification_provider, require
from app.persistence.deps import get_uow
from app.persistence.repositories import UnitOfWork
from app.providers.verification import VerificationProvider

router = APIRouter(tags=["donors"])


def get_donor_service(
    uow: UnitOfWork = Depends(get_uow), clock: Clock = Depends(get_clock)
) -> DonorService:
    return DonorService(uow, clock)


@router.get("/donors/me", response_model=DonorProfile, summary="My donor profile")
async def get_my_profile(
    ctx: AuthContext = Depends(require(Permission.DONOR_PROFILE_READ_SELF)),
    service: DonorService = Depends(get_donor_service),
) -> DonorProfile:
    return await service.get_own_profile(ctx)


@router.patch(
    "/donors/me",
    response_model=DonorProfile,
    dependencies=[Depends(csrf_protect)],
    summary="Update my donor profile",
)
async def update_my_profile(
    body: UpdateDonorProfileRequest,
    ctx: AuthContext = Depends(require(Permission.DONOR_PROFILE_UPDATE_SELF)),
    service: DonorService = Depends(get_donor_service),
) -> DonorProfile:
    return await service.update_own_profile(ctx, body)


@router.get(
    "/reference/registration",
    response_model=RegistrationReference,
    tags=["reference"],
    summary="Allowed values for donor registration",
)
async def registration_reference(
    provider: VerificationProvider = Depends(get_verification_provider),
) -> RegistrationReference:
    return RegistrationReference(
        blood_groups=list(BLOOD_GROUPS),
        states=list(INDIAN_STATES_AND_UTS),
        verification_mode="demo" if provider.is_demo else "otp",
        verification_disclaimer=provider.disclaimer,
    )
