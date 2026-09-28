from __future__ import annotations

from fastapi import FastAPI
from httpx import AsyncClient


async def test_healthz(client: AsyncClient) -> None:
    r = await client.get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


async def test_meta_uses_veyra_branding_and_discloses_demo(client: AsyncClient) -> None:
    r = await client.get("/api/v1/meta")
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == "VEYRA"
    assert body["tagline"] == "Intelligent Blood Network"
    assert body["environment"] == "test"
    assert body["demo_mode"] is True
    assert body["api_version"] == "v1"
    assert any(d["component"] == "environment" for d in body["disclosures"])


async def test_readyz_ready_when_all_checks_pass(app: FastAPI, client: AsyncClient) -> None:
    async def ok() -> None:
        return None

    app.state.readiness_checks = {"database": ok, "redis": ok}
    r = await client.get("/readyz")
    assert r.status_code == 200
    assert r.json() == {"status": "ready", "checks": {"database": "ok", "redis": "ok"}}


async def test_readyz_degraded_hides_error_details(app: FastAPI, client: AsyncClient) -> None:
    async def ok() -> None:
        return None

    async def broken() -> None:
        raise ConnectionError("password=hunter2 host=10.0.0.5")

    app.state.readiness_checks = {"database": broken, "redis": ok}
    r = await client.get("/readyz")
    assert r.status_code == 503
    assert r.json()["checks"] == {"database": "unavailable", "redis": "ok"}
    assert "hunter2" not in r.text and "10.0.0.5" not in r.text


async def test_meta_reflects_the_apps_own_settings_not_the_global_cache() -> None:
    """Regression: /meta once read the process-global settings and ignored create_app(settings)."""
    from httpx import ASGITransport

    from app.core.config import Settings
    from app.main import create_app

    for env in ("demo", "test"):
        settings = Settings(_env_file=None, env=env)  # type: ignore[call-arg]
        app = create_app(settings, with_infra=False)
        async with app.router.lifespan_context(app):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as c:
                body = (await c.get("/api/v1/meta")).json()
        assert body["environment"] == env
