from __future__ import annotations

from fastapi import APIRouter, Depends, Path, Query

from app.core.clock import Clock
from app.core.config import Settings, get_settings
from app.core.rbac import AuthContext, Permission
from app.modules.identity.deps import csrf_protect, get_clock, require
from app.modules.telemetry.schemas import (
    ColdChainReport,
    DeviceOut,
    MonitoredList,
    SimulatorResult,
    TelemetrySeries,
    TelemetrySummary,
    TickRequest,
)
from app.modules.telemetry.service import MAX_READINGS, TelemetryService
from app.persistence.deps import get_uow
from app.persistence.repositories import UnitOfWork

router = APIRouter(tags=["telemetry"])
simulator = APIRouter(
    prefix="/simulator/bags",
    tags=["telemetry simulator (demo)"],
    dependencies=[Depends(csrf_protect)],
)

PUBLIC_ID = Path(pattern=r"^[A-Za-z0-9-]{3,20}$", description="Bag label id, e.g. VYR-7F3K-2QXM")
_read = require(Permission.BAG_TRACE_READ)
_simulate = require(Permission.TELEMETRY_SIMULATE)


def get_telemetry_service(
    uow: UnitOfWork = Depends(get_uow),
    clock: Clock = Depends(get_clock),
    settings: Settings = Depends(get_settings),
) -> TelemetryService:
    return TelemetryService(uow, clock, simulator_enabled=settings.telemetry_simulator_enabled)


# ---------------------------------------------------------------- reads (scoped like the trace)


@router.get(
    "/telemetry/monitored",
    response_model=MonitoredList,
    summary="Smart bags at my facility (admins: the network) — simulated",
)
async def monitored(
    ctx: AuthContext = Depends(_read), service: TelemetryService = Depends(get_telemetry_service)
) -> MonitoredList:
    return await service.monitored(ctx)


@router.get("/bags/{public_id}/device", response_model=DeviceOut, summary="Simulated device")
async def device(
    public_id: str = PUBLIC_ID,
    ctx: AuthContext = Depends(_read),
    service: TelemetryService = Depends(get_telemetry_service),
) -> DeviceOut:
    return await service.device(ctx, public_id)


@router.get(
    "/bags/{public_id}/telemetry", response_model=TelemetrySeries, summary="Readings (simulated)"
)
async def telemetry(
    public_id: str = PUBLIC_ID,
    limit: int = Query(default=120, ge=1, le=MAX_READINGS),
    ctx: AuthContext = Depends(_read),
    service: TelemetryService = Depends(get_telemetry_service),
) -> TelemetrySeries:
    return await service.telemetry(ctx, public_id, limit)


@router.get(
    "/bags/{public_id}/telemetry/summary",
    response_model=TelemetrySummary,
    summary="Current cold-chain state (simulated)",
)
async def telemetry_summary(
    public_id: str = PUBLIC_ID,
    ctx: AuthContext = Depends(_read),
    service: TelemetryService = Depends(get_telemetry_service),
) -> TelemetrySummary:
    return await service.summary(ctx, public_id)


@router.get(
    "/bags/{public_id}/cold-chain",
    response_model=ColdChainReport,
    summary="Excursions and cold-chain trace entries (simulated)",
)
async def cold_chain(
    public_id: str = PUBLIC_ID,
    ctx: AuthContext = Depends(_read),
    service: TelemetryService = Depends(get_telemetry_service),
) -> ColdChainReport:
    return await service.cold_chain(ctx, public_id)


# ---------------------------------------------------------------- simulator (demo, holder only)


@simulator.post("/{public_id}/attach", response_model=SimulatorResult, status_code=201)
async def attach(
    public_id: str = PUBLIC_ID,
    ctx: AuthContext = Depends(_simulate),
    service: TelemetryService = Depends(get_telemetry_service),
) -> SimulatorResult:
    """Attach a SIMULATED smart-bag device (no hardware)."""
    return await service.attach(ctx, public_id)


@simulator.post("/{public_id}/start", response_model=SimulatorResult)
async def start(
    public_id: str = PUBLIC_ID,
    ctx: AuthContext = Depends(_simulate),
    service: TelemetryService = Depends(get_telemetry_service),
) -> SimulatorResult:
    """Background readings every VEYRA_TELEMETRY_TICK_SECONDS."""
    return await service.set_running(ctx, public_id, True)


@simulator.post("/{public_id}/pause", response_model=SimulatorResult)
async def pause(
    public_id: str = PUBLIC_ID,
    ctx: AuthContext = Depends(_simulate),
    service: TelemetryService = Depends(get_telemetry_service),
) -> SimulatorResult:
    return await service.set_running(ctx, public_id, False)


@simulator.post("/{public_id}/tick", response_model=SimulatorResult)
async def tick(
    body: TickRequest,
    public_id: str = PUBLIC_ID,
    ctx: AuthContext = Depends(_simulate),
    service: TelemetryService = Depends(get_telemetry_service),
) -> SimulatorResult:
    """Generate ``count`` readings now (deterministic)."""
    return await service.tick(ctx, public_id, body.count)


@simulator.post("/{public_id}/excursion", response_model=SimulatorResult)
async def excursion(
    public_id: str = PUBLIC_ID,
    ctx: AuthContext = Depends(_simulate),
    service: TelemetryService = Depends(get_telemetry_service),
) -> SimulatorResult:
    """Inject a simulated warm excursion (warning, then critical on later readings)."""
    return await service.set_mode(ctx, public_id, "excursion")


@simulator.post("/{public_id}/recover", response_model=SimulatorResult)
async def recover(
    public_id: str = PUBLIC_ID,
    ctx: AuthContext = Depends(_simulate),
    service: TelemetryService = Depends(get_telemetry_service),
) -> SimulatorResult:
    """Restore normal temperature over the next readings."""
    return await service.set_mode(ctx, public_id, "recovering")
