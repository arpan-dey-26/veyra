from __future__ import annotations

from collections.abc import AsyncIterator, Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.core.config import Settings
from app.core.ids import uuid7
from app.main import create_app
from app.modules.facilities.models import Facility, FacilityMembership
from app.modules.identity.models import User
from app.persistence.memory import MemoryDatabase, memory_uow_factory


@pytest.fixture
def settings() -> Settings:
    return Settings(  # type: ignore[call-arg]
        _env_file=None, env="test", cors_allowed_origins=["http://localhost:3000"]
    )


@pytest.fixture
def app(settings: Settings) -> Iterator[FastAPI]:
    yield create_app(settings, with_infra=False)


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app, raise_app_exceptions=False)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            yield c


# ---------------------------------------------------------------- Phase 1 fixtures
# An app wired to the in-memory unit of work (no database), with cheap password hashing.


BASE_URL = "http://api.veyra.test"
PASSWORD = "correct-horse-battery-staple"


class MutableClock:
    def __init__(self) -> None:
        self._now = datetime(2026, 9, 28, 9, 0, tzinfo=UTC)

    def now(self) -> datetime:
        return self._now

    def advance(self, **kwargs: float) -> None:
        self._now += timedelta(**kwargs)


@pytest.fixture
def fast_settings() -> Settings:
    return Settings(  # type: ignore[call-arg]
        _env_file=None,
        env="test",
        password_hash_memory_kib=1024,
        password_hash_iterations=1,
    )


@pytest.fixture
def memdb() -> MemoryDatabase:
    return MemoryDatabase()


@pytest.fixture
def clock() -> MutableClock:
    return MutableClock()


@pytest.fixture
def api_app(fast_settings: Settings, memdb: MemoryDatabase, clock: MutableClock) -> FastAPI:
    app = create_app(fast_settings, with_infra=False)
    app.state.uow_factory = memory_uow_factory(memdb)
    app.state.clock = clock
    return app


@pytest.fixture
async def make_client(api_app: FastAPI) -> AsyncIterator[Callable[[], AsyncClient]]:
    clients: list[AsyncClient] = []

    def _make() -> AsyncClient:
        c = AsyncClient(
            transport=ASGITransport(app=api_app, raise_app_exceptions=False), base_url=BASE_URL
        )
        clients.append(c)
        return c

    async with api_app.router.lifespan_context(api_app):
        yield _make
    for c in clients:
        await c.aclose()


@pytest.fixture
async def api(make_client: Callable[[], AsyncClient]) -> AsyncClient:
    return make_client()


def donor_payload(**overrides: str) -> dict[str, str]:
    data = {
        "full_name": "Arpan Dey",
        "email": "arpan@example.in",
        "mobile": "98765 43210",
        "blood_group": "O+",
        "address": "12 Park Street",
        "city": "Kolkata",
        "state": "West Bengal",
        "pin_code": "700016",
        "password": PASSWORD,
    }
    data.update(overrides)
    return data


def csrf(client: AsyncClient) -> dict[str, str]:
    token = client.cookies.get("veyra_csrf")
    return {"x-csrf-token": token} if token else {}


async def register_and_verify(client: AsyncClient, **overrides: str) -> dict[str, object]:
    payload = donor_payload(**overrides)
    r = await client.post("/api/v1/auth/register", json=payload)
    assert r.status_code == 201, r.text
    challenge = r.json()["verification"]["challenge_id"]
    last4 = "".join(ch for ch in payload["mobile"] if ch.isdigit())[-4:]
    v = await client.post("/api/v1/auth/verify", json={"challenge_id": challenge, "code": last4})
    assert v.status_code == 200, v.text
    body: dict[str, object] = v.json()
    return body


@dataclass
class Seeded:
    user: User
    facility: Facility | None


async def seed_user(
    app: FastAPI,
    db: MemoryDatabase,
    *,
    role: str,
    email: str,
    mobile: str,
    facility_type: str | None = None,
) -> Seeded:
    """Insert an active user directly (roles that cannot self-register)."""
    now = app.state.clock.now()
    user = User(
        id=uuid7(),
        email=email,
        mobile=mobile,
        full_name=f"Seed {role.title()}",
        password_hash=app.state.hasher.hash(PASSWORD),
        role=role,
        status="active",
        is_demo=True,
        verified_at=now,
        failed_login_count=0,
        locked_until=None,
        last_login_at=None,
        created_at=now,
        updated_at=now,
    )
    db.users[user.id] = user
    facility = None
    if facility_type:
        facility = Facility(
            id=uuid7(),
            type=facility_type,
            name=f"Seed {facility_type.title()} {email.split('@')[0]}",
            registration_number=None,
            address="1 Hospital Road",
            city="Kolkata",
            state="West Bengal",
            pin_code="700001",
            provider_kind="internal",
            is_simulated=False,
            status="active",
            created_at=now,
            updated_at=now,
        )
        db.facilities[facility.id] = facility
        db.memberships[user.id] = FacilityMembership(
            user_id=user.id, facility_id=facility.id, created_at=now
        )
    return Seeded(user=user, facility=facility)


async def login(client: AsyncClient, email: str, password: str = PASSWORD) -> None:
    r = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
