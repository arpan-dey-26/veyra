from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Path, Query

from app.core.clock import Clock
from app.core.pagination import MAX_PAGE_SIZE, Page, PageMeta
from app.core.rbac import AuthContext, Permission
from app.modules.bags.schemas import (
    BagOut,
    BagQr,
    BagScanResult,
    BagTrace,
    DiscardRequest,
    InventorySummary,
)
from app.modules.bags.service import BagService
from app.modules.donations.schemas import BloodGroup
from app.modules.identity.deps import csrf_protect, get_clock, require
from app.persistence.deps import get_uow
from app.persistence.repositories import UnitOfWork

router = APIRouter(tags=["inventory"])

PUBLIC_ID = Path(pattern=r"^[A-Za-z0-9-]{3,20}$", description="Bag label id, e.g. VYR-7F3K-2QXM")


def get_bag_service(
    uow: UnitOfWork = Depends(get_uow), clock: Clock = Depends(get_clock)
) -> BagService:
    return BagService(uow, clock)


@router.get(
    "/inventory/summary", response_model=InventorySummary, summary="My facility's stock by group"
)
async def inventory_summary(
    ctx: AuthContext = Depends(require(Permission.INVENTORY_READ_OWN)),
    service: BagService = Depends(get_bag_service),
) -> InventorySummary:
    return await service.inventory(ctx)


@router.get("/inventory/bags", response_model=Page[BagOut], summary="Bags at my facility")
async def inventory_bags(
    status: Literal["available", "in_transit", "received", "discarded"] | None = None,
    blood_group: BloodGroup | None = None,
    component: str | None = Query(default=None, pattern=r"^[A-Z_]{2,16}$"),
    limit: int = Query(default=25, ge=1, le=MAX_PAGE_SIZE),
    offset: int = Query(default=0, ge=0, le=100_000),
    ctx: AuthContext = Depends(require(Permission.INVENTORY_READ_OWN)),
    service: BagService = Depends(get_bag_service),
) -> Page[BagOut]:
    rows, total = await service.list_bags(
        ctx,
        status=status,
        blood_group=blood_group,
        component=component,
        limit=limit,
        offset=offset,
    )
    return Page[BagOut](data=rows, meta=PageMeta(total=total, limit=limit, offset=offset))


@router.get(
    "/bags/scan",
    response_model=BagScanResult,
    tags=["trace"],
    summary="Resolve a scanned bag QR (or typed id) to the caller's scoped bag view",
)
async def scan_bag(
    payload: str = Query(min_length=1, max_length=64, description="QR content or bag id"),
    ctx: AuthContext = Depends(require(Permission.BAG_TRACE_READ)),
    service: BagService = Depends(get_bag_service),
) -> BagScanResult:
    return await service.scan(ctx, payload)


@router.get(
    "/bags/{public_id}/qr",
    response_model=BagQr,
    tags=["trace"],
    summary="The bag label QR (public id only) as a module matrix",
)
async def bag_qr(
    public_id: str = PUBLIC_ID,
    ctx: AuthContext = Depends(require(Permission.BAG_TRACE_READ)),
    service: BagService = Depends(get_bag_service),
) -> BagQr:
    return await service.qr(ctx, public_id)


@router.get(
    "/bags/{public_id}",
    response_model=BagTrace,
    tags=["trace"],
    summary="Bag details and its tamper-evident custody trail",
)
async def bag_trace(
    public_id: str = PUBLIC_ID,
    ctx: AuthContext = Depends(require(Permission.BAG_TRACE_READ)),
    service: BagService = Depends(get_bag_service),
) -> BagTrace:
    return await service.trace(ctx, public_id)


@router.post(
    "/bags/{public_id}/discard",
    response_model=BagOut,
    dependencies=[Depends(csrf_protect)],
    tags=["trace"],
    summary="Discard a bag held by my facility",
)
async def discard_bag(
    body: DiscardRequest,
    public_id: str = PUBLIC_ID,
    ctx: AuthContext = Depends(require(Permission.BAG_TRANSITION)),
    service: BagService = Depends(get_bag_service),
) -> BagOut:
    return await service.discard(ctx, public_id, body.reason, body.note)
