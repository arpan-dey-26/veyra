"""Integration: real Postgres + Redis. Skipped automatically when they are not running."""

from __future__ import annotations

import os

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import Settings
from app.main import create_app

pytestmark = pytest.mark.integration


async def test_readyz_against_real_infra() -> None:
    settings = Settings(env="test")
    app = create_app(settings, with_infra=True)
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            r = await c.get("/readyz")
    if r.json()["status"] != "ready":
        msg = f"infra not available: {r.json()['checks']}"
        if os.environ.get("VEYRA_REQUIRE_INFRA") == "1":
            pytest.fail(msg)  # verification runs must not silently skip
        pytest.skip(msg)
    assert r.status_code == 200
