from __future__ import annotations

from fastapi import APIRouter, Depends, Query, status

from app.core.clock import Clock
from app.core.config import Settings, get_settings
from app.core.pagination import MAX_PAGE_SIZE, Page, PageMeta
from app.core.rbac import AuthContext, Permission
from app.modules.donations.schemas import (
    DonationOut,
    DonorLookupRequest,
    DonorLookupResult,
    MyDonations,
    RecordDonationRequest,
)
from app.modules.donations.service import DonationService
from app.modules.identity.deps import csrf_protect, get_clock, require
from app.persistence.deps import get_uow
from app.persistence.repositories import UnitOfWork

router = APIRouter(tags=["donations"])


def get_donation_service(
    uow: UnitOfWork = Depends(get_uow),
    clock: Clock = Depends(get_clock),
    settings: Settings = Depends(get_settings),
) -> DonationService:
    return DonationService(uow, clock, interval_days=settings.min_donation_interval_days)


@router.post(
    "/donors/lookup",
    response_model=DonorLookupResult,
    dependencies=[Depends(csrf_protect)],
    summary="Find a verified donor by mobile at the donation desk",
    description="POST so the mobile number never appears in URLs or access logs.",
)
async def lookup_donor(
    body: DonorLookupRequest,
    ctx: AuthContext = Depends(require(Permission.DONATION_RECORD)),
    service: DonationService = Depends(get_donation_service),
) -> DonorLookupResult:
    return await service.lookup(ctx, body.mobile)


@router.post(
    "/donations",
    response_model=DonationOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(csrf_protect)],
    summary="Record a donation and create its labelled bags",
)
async def record_donation(
    body: RecordDonationRequest,
    ctx: AuthContext = Depends(require(Permission.DONATION_RECORD)),
    service: DonationService = Depends(get_donation_service),
) -> DonationOut:
    return await service.record_donation(ctx, body)


@router.get("/donations", response_model=Page[DonationOut], summary="Donations at my facility")
async def list_donations(
    limit: int = Query(default=25, ge=1, le=MAX_PAGE_SIZE),
    offset: int = Query(default=0, ge=0, le=100_000),
    ctx: AuthContext = Depends(require(Permission.DONATION_RECORD)),
    service: DonationService = Depends(get_donation_service),
) -> Page[DonationOut]:
    rows, total = await service.list_for_facility(ctx, limit=limit, offset=offset)
    return Page[DonationOut](data=rows, meta=PageMeta(total=total, limit=limit, offset=offset))


@router.get(
    "/donors/me/donations",
    response_model=MyDonations,
    tags=["donors"],
    summary="My donation history and next eligible date",
)
async def my_donations(
    ctx: AuthContext = Depends(require(Permission.DONATION_READ_SELF)),
    service: DonationService = Depends(get_donation_service),
) -> MyDonations:
    return await service.my_donations(ctx)
