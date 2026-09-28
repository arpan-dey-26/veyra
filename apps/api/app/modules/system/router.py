from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response, status

from app.core.config import Settings, get_settings
from app.modules.system.schemas import HealthResponse, MetaResponse, ReadinessResponse
from app.modules.system.service import SystemService

ops_router = APIRouter(tags=["ops"])
api_router = APIRouter(tags=["system"])


def get_system_service(
    request: Request, settings: Settings = Depends(get_settings)
) -> SystemService:
    return SystemService(settings, request.app.state.readiness_checks)


@ops_router.get("/healthz", response_model=HealthResponse, summary="Liveness probe")
async def healthz() -> HealthResponse:
    return HealthResponse()


@ops_router.get(
    "/readyz",
    response_model=ReadinessResponse,
    summary="Readiness probe (database, redis)",
    responses={503: {"model": ReadinessResponse}},
)
async def readyz(
    response: Response, service: SystemService = Depends(get_system_service)
) -> ReadinessResponse:
    result = await service.readiness()
    if result.status != "ready":
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return result


@api_router.get("/meta", response_model=MetaResponse, summary="Public product metadata")
async def meta(service: SystemService = Depends(get_system_service)) -> MetaResponse:
    return service.meta()
