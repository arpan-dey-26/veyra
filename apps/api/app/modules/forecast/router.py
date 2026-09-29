from __future__ import annotations

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.core.clock import Clock
from app.core.config import Settings, get_settings
from app.core.rbac import AuthContext, Permission
from app.modules.donations.schemas import BloodGroup
from app.modules.forecast.model import MAX_HORIZON, default_model
from app.modules.forecast.schemas import DemandForecast, ForecastSummary, ModelCard
from app.modules.forecast.service import ForecastService, model_card
from app.modules.identity.deps import get_clock, require_any
from app.persistence.deps import get_uow
from app.persistence.repositories import UnitOfWork

router = APIRouter(tags=["forecast"])

ForecastComponent = Literal["PRBC", "PLATELETS", "FFP"]
_can_forecast = require_any(Permission.FORECAST_READ_OWN, Permission.NETWORK_READ)
HORIZON = Query(default=7, ge=1, le=MAX_HORIZON, description="Days ahead (1-14)")
FACILITY = Query(
    default=None,
    description="Admins: any facility (omit for the network). Others: only their own.",
)


def get_forecast_service(
    uow: UnitOfWork = Depends(get_uow),
    clock: Clock = Depends(get_clock),
    settings: Settings = Depends(get_settings),
) -> ForecastService:
    return ForecastService(
        uow, clock, default_model(), utc_offset_minutes=settings.report_utc_offset_minutes
    )


@router.get(
    "/forecast/demand",
    response_model=DemandForecast,
    summary="Synthetic ML demand forecast for one blood group and component (prototype)",
)
async def demand_forecast(
    blood_group: BloodGroup,
    component: ForecastComponent = "PRBC",
    horizon: int = HORIZON,
    facility_id: UUID | None = FACILITY,
    ctx: AuthContext = Depends(_can_forecast),
    service: ForecastService = Depends(get_forecast_service),
) -> DemandForecast:
    return await service.demand(
        ctx, blood_group=blood_group, component=component, horizon=horizon, facility_id=facility_id
    )


@router.get(
    "/forecast/summary",
    response_model=ForecastSummary,
    summary="Forecast by blood group x component, with supply vs forecast (prototype)",
)
async def forecast_summary(
    horizon: int = HORIZON,
    facility_id: UUID | None = FACILITY,
    ctx: AuthContext = Depends(_can_forecast),
    service: ForecastService = Depends(get_forecast_service),
) -> ForecastSummary:
    return await service.summary(ctx, horizon=horizon, facility_id=facility_id)


@router.get("/forecast/model", response_model=ModelCard, summary="Forecast model card")
async def forecast_model(ctx: AuthContext = Depends(_can_forecast)) -> ModelCard:
    return model_card(default_model())
