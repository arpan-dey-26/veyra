"""Phase 7 endpoints: scoped shipment reads, the receipt confirmation, demo logistics controls."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.core.clock import Clock
from app.core.config import Settings, get_settings
from app.core.rbac import AuthContext, Permission
from app.modules.identity.deps import csrf_protect, get_clock, require, require_any
from app.modules.logistics.schemas import (
    DelayBody,
    LogisticsResult,
    ShipmentDetail,
    ShipmentList,
    ShipmentRoute,
    ShipmentStatus,
    ShipmentTelemetry,
    ShipmentTimeline,
)
from app.modules.logistics.service import LogisticsService
from app.modules.requests.router import get_request_service
from app.modules.requests.service import RequestService
from app.persistence.deps import get_uow
from app.persistence.repositories import UnitOfWork

router = APIRouter(prefix="/shipments", tags=["logistics"])
simulator = APIRouter(
    prefix="/simulator/shipments",
    tags=["logistics"],
    dependencies=[Depends(csrf_protect)],
)

READ = require_any(Permission.SHIPMENT_READ, Permission.NETWORK_READ)
SIMULATE = require(Permission.LOGISTICS_SIMULATE)


def get_logistics_service(
    uow: UnitOfWork = Depends(get_uow),
    clock: Clock = Depends(get_clock),
    settings: Settings = Depends(get_settings),
) -> LogisticsService:
    return LogisticsService(
        uow,
        clock,
        simulator_enabled=settings.logistics_simulator_enabled,
        utc_offset_minutes=settings.report_utc_offset_minutes,
    )


@router.get("", response_model=ShipmentList, summary="Shipments in scope (simulated logistics)")
async def list_shipments(
    status: ShipmentStatus | None = Query(default=None),
    ctx: AuthContext = Depends(READ),
    service: LogisticsService = Depends(get_logistics_service),
) -> ShipmentList:
    return await service.list(ctx, status=status)


@router.get("/{shipment_id}", response_model=ShipmentDetail, summary="One shipment")
async def get_shipment(
    shipment_id: UUID,
    ctx: AuthContext = Depends(READ),
    service: LogisticsService = Depends(get_logistics_service),
) -> ShipmentDetail:
    return await service.get(ctx, shipment_id)


@router.get(
    "/{shipment_id}/route",
    response_model=ShipmentRoute,
    summary="Schematic route checkpoints (not a geographic map)",
)
async def shipment_route(
    shipment_id: UUID,
    ctx: AuthContext = Depends(READ),
    service: LogisticsService = Depends(get_logistics_service),
) -> ShipmentRoute:
    return await service.route(ctx, shipment_id)


@router.get(
    "/{shipment_id}/timeline", response_model=ShipmentTimeline, summary="Append-only timeline"
)
async def shipment_timeline(
    shipment_id: UUID,
    ctx: AuthContext = Depends(READ),
    service: LogisticsService = Depends(get_logistics_service),
) -> ShipmentTimeline:
    return await service.timeline(ctx, shipment_id)


@router.get(
    "/{shipment_id}/telemetry",
    response_model=ShipmentTelemetry,
    summary="Cold-chain state of the shipment's bags (simulated telemetry)",
)
async def shipment_telemetry(
    shipment_id: UUID,
    ctx: AuthContext = Depends(READ),
    service: LogisticsService = Depends(get_logistics_service),
) -> ShipmentTelemetry:
    return await service.telemetry(ctx, shipment_id)


@router.post(
    "/{shipment_id}/receive",
    response_model=ShipmentDetail,
    dependencies=[Depends(csrf_protect)],
    summary="Destination hospital confirms receipt (uses the existing receive workflow)",
)
async def receive_shipment(
    shipment_id: UUID,
    ctx: AuthContext = Depends(require(Permission.BAG_RECEIVE)),
    service: LogisticsService = Depends(get_logistics_service),
    requests: RequestService = Depends(get_request_service),
) -> ShipmentDetail:
    request_id = await service.receivable_request(ctx, shipment_id)
    await requests.receive(ctx, request_id)  # same audit, trace and events as before
    return await service.get(ctx, shipment_id)


async def _sim(
    service: LogisticsService,
    ctx: AuthContext,
    shipment_id: UUID,
    action: Literal["advance", "delay", "resume", "arrive"],
    body: DelayBody | None = None,
) -> LogisticsResult:
    return await service.simulate(
        ctx,
        shipment_id,
        action,
        minutes=body.minutes if body else 0,
        reason=body.reason if body else None,
    )


@simulator.post("/{shipment_id}/advance", response_model=LogisticsResult)
async def advance(
    shipment_id: UUID,
    ctx: AuthContext = Depends(SIMULATE),
    service: LogisticsService = Depends(get_logistics_service),
) -> LogisticsResult:
    return await _sim(service, ctx, shipment_id, "advance")


@simulator.post("/{shipment_id}/delay", response_model=LogisticsResult)
async def delay(
    shipment_id: UUID,
    body: DelayBody | None = None,
    ctx: AuthContext = Depends(SIMULATE),
    service: LogisticsService = Depends(get_logistics_service),
) -> LogisticsResult:
    return await _sim(service, ctx, shipment_id, "delay", body or DelayBody())


@simulator.post("/{shipment_id}/resume", response_model=LogisticsResult)
async def resume(
    shipment_id: UUID,
    ctx: AuthContext = Depends(SIMULATE),
    service: LogisticsService = Depends(get_logistics_service),
) -> LogisticsResult:
    return await _sim(service, ctx, shipment_id, "resume")


@simulator.post("/{shipment_id}/arrive", response_model=LogisticsResult)
async def arrive(
    shipment_id: UUID,
    ctx: AuthContext = Depends(SIMULATE),
    service: LogisticsService = Depends(get_logistics_service),
) -> LogisticsResult:
    return await _sim(service, ctx, shipment_id, "arrive")
