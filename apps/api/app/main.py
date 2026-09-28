"""VEYRA API application factory."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core import redis as redis_mod
from app.core.config import PRODUCT_NAME, PRODUCT_TAGLINE, Settings, get_settings
from app.core.db import Database
from app.core.errors import register_error_handlers
from app.core.logging import configure_logging
from app.core.middleware import RequestIdMiddleware, SecurityHeadersMiddleware
from app.core.readiness import Check
from app.modules.system.router import api_router as system_api_router
from app.modules.system.router import ops_router


def create_app(settings: Settings | None = None, *, with_infra: bool = True) -> FastAPI:
    """Build the app. ``with_infra=False`` skips DB/Redis wiring (unit tests, OpenAPI export)."""
    settings = settings or get_settings()
    configure_logging(settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        checks: dict[str, Check] = {}
        db: Database | None = None
        rds = None
        if with_infra:
            db = Database(settings.database_url)
            rds = redis_mod.create_redis(settings.redis_url)
            app.state.db = db
            app.state.redis = rds
            checks["database"] = db.ping
            checks["redis"] = lambda: redis_mod.ping(rds)
        # Tests may pre-populate readiness_checks before startup.
        if not getattr(app.state, "readiness_checks", None):
            app.state.readiness_checks = checks
        try:
            yield
        finally:
            if rds is not None:
                await rds.aclose()
            if db is not None:
                await db.dispose()

    app = FastAPI(
        title=f"{PRODUCT_NAME} API",
        summary=f"{PRODUCT_NAME} — {PRODUCT_TAGLINE}",
        description=(
            "Prototype API for the VEYRA intelligent blood network. "
            "Responses built from simulated or demo providers are labelled with `source.kind`."
        ),
        version=settings.app_version,
        lifespan=lifespan,
        docs_url="/docs" if settings.docs_enabled else None,
        redoc_url=None,
        openapi_url="/openapi.json" if settings.docs_enabled else None,
    )
    app.state.settings = settings
    # Routes depend on the shared `get_settings` dependency; bind it to this app's settings
    # so an app built with explicit settings (tests, OpenAPI export) never reads the global cache.
    app.dependency_overrides[get_settings] = lambda: settings
    app.state.readiness_checks = {}

    register_error_handlers(app)

    # Middleware order: last added runs first.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allowed_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["content-type", "x-request-id", "x-csrf-token", "idempotency-key"],
        expose_headers=["x-request-id"],
    )
    app.add_middleware(SecurityHeadersMiddleware, hsts=settings.is_production)
    app.add_middleware(RequestIdMiddleware)

    app.include_router(ops_router)
    app.include_router(system_api_router, prefix=settings.api_prefix)
    return app


app = create_app()
