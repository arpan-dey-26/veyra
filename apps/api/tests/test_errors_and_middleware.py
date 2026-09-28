from __future__ import annotations

from fastapi import FastAPI
from httpx import AsyncClient
from pydantic import BaseModel

from app.core.errors import NotFoundError


class ProbeBody(BaseModel):
    # Module level on purpose: with `from __future__ import annotations`, a model defined
    # inside the function can't be resolved by FastAPI and would be treated as a query param.
    units: int


def _add_probe_routes(app: FastAPI) -> None:
    @app.get("/_probe/boom")
    async def boom() -> None:
        raise RuntimeError("secret internal detail")

    @app.get("/_probe/missing")
    async def missing() -> None:
        raise NotFoundError("Blood bag not found")

    @app.post("/_probe/validate")
    async def validate(body: ProbeBody) -> ProbeBody:
        return body


async def test_unknown_route_is_problem_json(client: AsyncClient) -> None:
    r = await client.get("/api/v1/does-not-exist")
    assert r.status_code == 404
    assert r.headers["content-type"].startswith("application/problem+json")
    body = r.json()
    assert body["code"] == "not_found"
    assert body["status"] == 404
    assert body["request_id"] == r.headers["x-request-id"]


async def test_app_error_maps_to_problem(app: FastAPI, client: AsyncClient) -> None:
    _add_probe_routes(app)
    r = await client.get("/_probe/missing")
    assert r.status_code == 404
    assert r.json()["detail"] == "Blood bag not found"


async def test_unhandled_error_never_leaks_internals(app: FastAPI, client: AsyncClient) -> None:
    _add_probe_routes(app)
    r = await client.get("/_probe/boom")
    assert r.status_code == 500
    assert r.json()["code"] == "internal_error"
    assert "secret internal detail" not in r.text
    assert "Traceback" not in r.text


async def test_validation_error_does_not_echo_input(app: FastAPI, client: AsyncClient) -> None:
    _add_probe_routes(app)
    r = await client.post("/_probe/validate", json={"units": "not-a-number-SENSITIVE"})
    assert r.status_code == 422
    body = r.json()
    assert body["code"] == "validation_error"
    assert body["errors"][0]["loc"] == ["body", "units"]
    assert "SENSITIVE" not in r.text


async def test_request_id_generated_and_propagated(client: AsyncClient) -> None:
    r1 = await client.get("/healthz")
    assert len(r1.headers["x-request-id"]) >= 8
    r2 = await client.get("/healthz", headers={"x-request-id": "trace-abc-12345"})
    assert r2.headers["x-request-id"] == "trace-abc-12345"


async def test_malformed_request_id_is_replaced(client: AsyncClient) -> None:
    r = await client.get("/healthz", headers={"x-request-id": "bad id <script>"})
    assert r.headers["x-request-id"] != "bad id <script>"


async def test_security_headers_present(client: AsyncClient) -> None:
    r = await client.get("/api/v1/meta")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"
    assert r.headers["referrer-policy"] == "no-referrer"
    assert "default-src 'none'" in r.headers["content-security-policy"]


async def test_cors_allows_only_configured_origin(client: AsyncClient) -> None:
    ok = await client.get("/api/v1/meta", headers={"origin": "http://localhost:3000"})
    assert ok.headers.get("access-control-allow-origin") == "http://localhost:3000"
    bad = await client.get("/api/v1/meta", headers={"origin": "https://evil.example"})
    assert "access-control-allow-origin" not in bad.headers
