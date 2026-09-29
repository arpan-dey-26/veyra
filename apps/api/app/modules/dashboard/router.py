from __future__ import annotations

from fastapi import APIRouter, Depends

from app.core.clock import Clock
from app.core.config import Settings, get_settings
from app.core.rbac import AuthContext, Permission
from app.modules.dashboard.schemas import AdminDashboard, FacilityDashboard, NetworkGraph
from app.modules.dashboard.service import DashboardService
from app.modules.identity.deps import get_clock, require
from app.persistence.deps import get_uow
from app.persistence.repositories import UnitOfWork

router = APIRouter(tags=["dashboard"])


def get_dashboard_service(
    uow: UnitOfWork = Depends(get_uow),
    clock: Clock = Depends(get_clock),
    settings: Settings = Depends(get_settings),
) -> DashboardService:
    return DashboardService(uow, clock, utc_offset_minutes=settings.report_utc_offset_minutes)


@router.get(
    "/dashboard/facility",
    response_model=FacilityDashboard,
    summary="My facility's dashboard aggregates (hospital or blood bank)",
)
async def facility_dashboard(
    ctx: AuthContext = Depends(require(Permission.FACILITY_READ_OWN)),
    service: DashboardService = Depends(get_dashboard_service),
) -> FacilityDashboard:
    return await service.facility(ctx)


@router.get(
    "/dashboard/admin",
    response_model=AdminDashboard,
    summary="Network-wide counts for administrators (no donor data, no audit details)",
)
async def admin_dashboard(
    ctx: AuthContext = Depends(require(Permission.NETWORK_READ)),
    service: DashboardService = Depends(get_dashboard_service),
) -> AdminDashboard:
    return await service.admin(ctx)


@router.get(
    "/network/graph",
    response_model=NetworkGraph,
    summary="Scoped facility graph for the live network visualization",
)
async def network_graph(
    ctx: AuthContext = Depends(require(Permission.EVENTS_SUBSCRIBE)),
    service: DashboardService = Depends(get_dashboard_service),
) -> NetworkGraph:
    return await service.graph(ctx)
