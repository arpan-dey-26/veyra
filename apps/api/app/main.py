"""VEYRA API application factory."""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core import redis as redis_mod
from app.core.clock import SystemClock
from app.core.config import PRODUCT_NAME, PRODUCT_TAGLINE, Settings, get_settings
from app.core.db import Database
from app.core.errors import register_error_handlers
from app.core.logging import configure_logging
from app.core.middleware import RequestIdMiddleware, SecurityHeadersMiddleware
from app.core.readiness import Check
from app.core.security import AccessTokenCodec, PasswordHasher
from app.modules.admin.router import router as admin_router
from app.modules.bags.router import router as bags_router
from app.modules.camps.router import router as camps_router
from app.modules.compatibility.router import router as compatibility_router
from app.modules.dashboard.router import router as dashboard_router
from app.modules.donations.router import router as donations_router
from app.modules.donors.router import router as donors_router
from app.modules.facilities.router import router as facilities_router
from app.modules.forecast.router import router as forecast_router
from app.modules.identity.router import router as identity_router
from app.modules.logistics.router import router as logistics_router
from app.modules.logistics.router import simulator as logistics_simulator_router
from app.modules.operations.router import router as operations_router
from app.modules.outbox.router import router as events_router
from app.modules.outbox.service import EventBroker, run_relay
from app.modules.requests.router import router as requests_router
from app.modules.system.router import api_router as system_api_router
from app.modules.system.router import ops_router
from app.modules.telemetry.router import router as telemetry_router
from app.modules.telemetry.router import simulator as telemetry_simulator_router
from app.modules.telemetry.ticker import run_ticker
from app.persistence.sql import register_persistence_errors, sql_uow_factory
from app.providers.bloodbank import build_bloodbank_providers
from app.providers.verification import build_verification_provider


def create_app(settings: Settings | None = None, *, with_infra: bool = True) -> FastAPI:
    """Build the app. ``with_infra=False`` skips DB/Redis wiring (unit tests, OpenAPI export)."""
    settings = settings or get_settings()
    configure_logging(settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        checks: dict[str, Check] = {}
        db: Database | None = None
        rds = None
        relay: asyncio.Task[None] | None = None
        ticker: asyncio.Task[None] | None = None
        if with_infra:
            db = Database(settings.database_url)
            rds = redis_mod.create_redis(settings.redis_url)
            app.state.db = db
            app.state.redis = rds
            app.state.uow_factory = sql_uow_factory(db.sessionmaker)
            # Fail fast at real startup if the verification provider can't be built.
            app.state.verification = build_verification_provider(settings)
            checks["database"] = db.ping
            checks["redis"] = lambda: redis_mod.ping(rds)
            # Outbox → SSE relay for this process (at-least-once, SKIP LOCKED across replicas).
            relay = asyncio.create_task(
                run_relay(
                    app.state.uow_factory,
                    app.state.broker,
                    app.state.clock,
                    interval=settings.outbox_relay_interval_seconds,
                ),
                name="outbox-relay",
            )
            if settings.telemetry_simulator_enabled and settings.telemetry_tick_seconds > 0:
                # SIMULATED IoT telemetry for devices set to "running" (demo only).
                ticker = asyncio.create_task(
                    run_ticker(
                        app.state.uow_factory,
                        app.state.clock,
                        interval=settings.telemetry_tick_seconds,
                    ),
                    name="telemetry-simulator",
                )
        # Tests may pre-populate readiness_checks before startup.
        if not getattr(app.state, "readiness_checks", None):
            app.state.readiness_checks = checks
        try:
            yield
        finally:
            for task in (relay, ticker):
                if task is not None:
                    task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await task
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
    app.state.clock = SystemClock()
    app.state.hasher = PasswordHasher.from_settings(settings)
    app.state.tokens = AccessTokenCodec.from_settings(settings)
    app.state.verification = None  # built lazily (or eagerly at startup when with_infra)
    app.state.uow_factory = None  # SQL unit of work at startup; tests inject an in-memory one
    app.state.broker = EventBroker()
    # Fails fast (at build time) if mock blood banks are enabled in production.
    app.state.bloodbank_providers = build_bloodbank_providers(settings)

    register_error_handlers(app)
    register_persistence_errors(app)

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
    for router in (
        identity_router,
        donors_router,
        facilities_router,
        admin_router,
        bags_router,
        donations_router,
        requests_router,
        events_router,
        dashboard_router,
        forecast_router,
        telemetry_router,
        telemetry_simulator_router,
        operations_router,
        logistics_router,
        logistics_simulator_router,
        compatibility_router,
        camps_router,
    ):
        app.include_router(router, prefix=settings.api_prefix)
    return app


app = create_app()
