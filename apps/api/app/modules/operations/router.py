"""Phase 6 operational endpoints: read-only recommendations + one priority mutation."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.core.clock import Clock
from app.core.config import Settings, get_settings
from app.core.rbac import AuthContext, Permission
from app.modules.forecast.model import default_model
from app.modules.identity.deps import csrf_protect, get_clock, require, require_any
from app.modules.operations.schemas import (
    AlertsOut,
    ChangePriority,
    FacilityPressure,
    OpsRequestList,
    PriorityOut,
    Recommendation,
    RouteOut,
    RoutingOverview,
)
from app.modules.operations.service import OperationsService
from app.modules.requests.schemas import Urgency
from app.persistence.deps import get_uow
from app.persistence.repositories import UnitOfWork

router = APIRouter(prefix="/operations", tags=["operations"])

READ = require_any(Permission.OPERATIONS_READ, Permission.NETWORK_READ)


def get_operations_service(
    uow: UnitOfWork = Depends(get_uow),
    clock: Clock = Depends(get_clock),
    settings: Settings = Depends(get_settings),
) -> OperationsService:
    return OperationsService(
        uow, clock, default_model(), utc_offset_minutes=settings.report_utc_offset_minutes
    )


@router.get(
    "/requests",
    response_model=OpsRequestList,
    summary="Operational request queue with explainable priority (prototype)",
)
async def list_requests(
    ctx: AuthContext = Depends(READ),
    service: OperationsService = Depends(get_operations_service),
) -> OpsRequestList:
    return await service.list_requests(ctx)


@router.get(
    "/requests/{request_id}/priority",
    response_model=PriorityOut,
    summary="Operational priority score, band, action and reasons (not a clinical score)",
)
async def get_priority(
    request_id: UUID,
    ctx: AuthContext = Depends(READ),
    service: OperationsService = Depends(get_operations_service),
) -> PriorityOut:
    return await service.priority(ctx, request_id)


@router.post(
    "/requests/{request_id}/priority",
    response_model=PriorityOut,
    dependencies=[Depends(csrf_protect)],
    summary="The requesting hospital changes its open request's priority (audited)",
)
async def change_priority(
    request_id: UUID,
    body: ChangePriority,
    ctx: AuthContext = Depends(require(Permission.BLOOD_REQUEST_CREATE)),
    service: OperationsService = Depends(get_operations_service),
) -> PriorityOut:
    return await service.change_priority(ctx, request_id, body)


@router.get(
    "/requests/{request_id}/recommendations",
    response_model=Recommendation,
    summary="Ranked candidate bags for a request (never dispatches anything)",
)
async def recommendations(
    request_id: UUID,
    ctx: AuthContext = Depends(require(Permission.ALLOCATION_RECOMMEND)),
    service: OperationsService = Depends(get_operations_service),
) -> Recommendation:
    return await service.recommendations(ctx, request_id)


@router.get(
    "/facilities/{facility_id}/pressure",
    response_model=FacilityPressure,
    summary="Stock vs open requests vs synthetic forecast, per group and component",
)
async def facility_pressure(
    facility_id: UUID,
    ctx: AuthContext = Depends(READ),
    service: OperationsService = Depends(get_operations_service),
) -> FacilityPressure:
    return await service.facility_pressure(ctx, facility_id)


@router.get(
    "/routing",
    response_model=RoutingOverview,
    summary="Simulated ETAs for dispatched requests in scope (prototype)",
)
async def routing_overview(
    ctx: AuthContext = Depends(READ),
    service: OperationsService = Depends(get_operations_service),
) -> RoutingOverview:
    return await service.routing_overview(ctx)


@router.get(
    "/routing/estimate",
    response_model=RouteOut,
    summary="Simulated route estimate between two facilities (no GPS or traffic data)",
)
async def route_estimate(
    source_facility_id: UUID,
    destination_facility_id: UUID,
    urgency: Urgency = Query(default="routine"),
    ctx: AuthContext = Depends(READ),
    service: OperationsService = Depends(get_operations_service),
) -> RouteOut:
    return await service.route(
        ctx, source_id=source_facility_id, destination_id=destination_facility_id, urgency=urgency
    )


@router.get(
    "/alerts",
    response_model=AlertsOut,
    summary="Emergency requests, cold-chain, expiry and pressure alerts in scope",
)
async def alerts(
    ctx: AuthContext = Depends(READ),
    service: OperationsService = Depends(get_operations_service),
) -> AlertsOut:
    return await service.alerts(ctx)
