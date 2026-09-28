from __future__ import annotations

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request, Response, status

from app.core.clock import Clock
from app.core.config import Settings, get_settings
from app.core.pagination import MAX_PAGE_SIZE, Page, PageMeta
from app.core.rbac import AuthContext, Permission
from app.modules.bags.domain import Component
from app.modules.donations.schemas import BloodGroup
from app.modules.identity.deps import csrf_protect, get_clock, require
from app.modules.requests.schemas import (
    AvailabilityResponse,
    BloodRequestOut,
    CreateBloodRequest,
    RejectRequest,
    RespondRequest,
)
from app.modules.requests.service import RequestService
from app.persistence.deps import get_uow
from app.persistence.repositories import UnitOfWork
from app.providers.bloodbank import BloodBankProvider, build_bloodbank_providers

router = APIRouter(tags=["requests"])

IDEMPOTENCY_KEY = Header(
    default=None,
    alias="Idempotency-Key",
    pattern=r"^[A-Za-z0-9_.:-]{8,64}$",
    description="Retry-safe key: the same key returns the original request instead of a copy.",
)


def get_bloodbank_providers(
    request: Request, settings: Settings = Depends(get_settings)
) -> dict[str, BloodBankProvider]:
    providers: dict[str, BloodBankProvider] | None = getattr(
        request.app.state, "bloodbank_providers", None
    )
    if providers is None:
        providers = build_bloodbank_providers(settings)
        request.app.state.bloodbank_providers = providers
    return providers


def get_request_service(
    uow: UnitOfWork = Depends(get_uow),
    clock: Clock = Depends(get_clock),
    providers: dict[str, BloodBankProvider] = Depends(get_bloodbank_providers),
) -> RequestService:
    return RequestService(uow, clock, providers)


@router.get(
    "/network/availability",
    response_model=AvailabilityResponse,
    summary="Which blood banks can supply this (banded, never exact stock)",
)
async def availability(
    blood_group: BloodGroup,
    component: Component,
    units: int = Query(default=1, ge=1, le=20),
    ctx: AuthContext = Depends(require(Permission.NETWORK_AVAILABILITY_READ)),
    service: RequestService = Depends(get_request_service),
) -> AvailabilityResponse:
    return await service.availability(
        ctx, blood_group=blood_group, component=component.value, units=units
    )


@router.post(
    "/requests",
    response_model=BloodRequestOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(csrf_protect)],
    summary="Request blood from a blood bank",
    responses={200: {"description": "Replay of an earlier request with the same key"}},
)
async def create_request(
    body: CreateBloodRequest,
    response: Response,
    idempotency_key: str | None = IDEMPOTENCY_KEY,
    ctx: AuthContext = Depends(require(Permission.BLOOD_REQUEST_CREATE)),
    service: RequestService = Depends(get_request_service),
) -> BloodRequestOut:
    out, created = await service.create(ctx, body, idempotency_key)
    if not created:
        response.status_code = status.HTTP_200_OK
    return out


@router.get(
    "/requests",
    response_model=Page[BloodRequestOut],
    summary="Outgoing (hospital) or incoming (blood bank) requests",
)
async def list_requests(
    status_filter: (
        Literal["pending", "acknowledged", "dispatched", "fulfilled", "rejected", "cancelled"]
        | None
    ) = Query(default=None, alias="status"),
    limit: int = Query(default=25, ge=1, le=MAX_PAGE_SIZE),
    offset: int = Query(default=0, ge=0, le=100_000),
    ctx: AuthContext = Depends(require(Permission.BLOOD_REQUEST_READ_OWN)),
    service: RequestService = Depends(get_request_service),
) -> Page[BloodRequestOut]:
    rows, total = await service.list(ctx, status=status_filter, limit=limit, offset=offset)
    return Page[BloodRequestOut](data=rows, meta=PageMeta(total=total, limit=limit, offset=offset))


@router.get("/requests/{request_id}", response_model=BloodRequestOut, summary="One request")
async def get_request(
    request_id: UUID,
    ctx: AuthContext = Depends(require(Permission.BLOOD_REQUEST_READ_OWN)),
    service: RequestService = Depends(get_request_service),
) -> BloodRequestOut:
    return await service.get(ctx, request_id)


@router.post(
    "/requests/{request_id}/fulfil",
    response_model=BloodRequestOut,
    dependencies=[Depends(csrf_protect)],
    summary="Dispatch bags (first-expiry-first-out) against a request",
)
async def fulfil_request(
    request_id: UUID,
    body: RespondRequest,
    ctx: AuthContext = Depends(require(Permission.BLOOD_REQUEST_RESPOND)),
    service: RequestService = Depends(get_request_service),
) -> BloodRequestOut:
    return await service.fulfil(ctx, request_id, body.note)


@router.post(
    "/requests/{request_id}/reject",
    response_model=BloodRequestOut,
    dependencies=[Depends(csrf_protect)],
    summary="Decline a request",
)
async def reject_request(
    request_id: UUID,
    body: RejectRequest,
    ctx: AuthContext = Depends(require(Permission.BLOOD_REQUEST_RESPOND)),
    service: RequestService = Depends(get_request_service),
) -> BloodRequestOut:
    return await service.reject(ctx, request_id, body.note)


@router.post(
    "/requests/{request_id}/cancel",
    response_model=BloodRequestOut,
    dependencies=[Depends(csrf_protect)],
    summary="Cancel my hospital's request",
)
async def cancel_request(
    request_id: UUID,
    ctx: AuthContext = Depends(require(Permission.BLOOD_REQUEST_CREATE)),
    service: RequestService = Depends(get_request_service),
) -> BloodRequestOut:
    return await service.cancel(ctx, request_id)


@router.post(
    "/requests/{request_id}/receive",
    response_model=BloodRequestOut,
    dependencies=[Depends(csrf_protect)],
    summary="Confirm the dispatched bags arrived",
)
async def receive_request(
    request_id: UUID,
    ctx: AuthContext = Depends(require(Permission.BAG_RECEIVE)),
    service: RequestService = Depends(get_request_service),
) -> BloodRequestOut:
    return await service.receive(ctx, request_id)
