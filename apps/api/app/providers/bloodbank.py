"""Blood-bank provider port.

Services only talk to ``BloodBankProvider``; which implementation answers is configuration.

- ``InternalBloodBankProvider``: blood banks onboarded in VEYRA itself (real data in our DB).
- ``MockBloodBankProvider``: SIMULATED partner banks so the demo runs without any external
  system. Every result carries ``SourceMeta(kind=SIMULATED)`` and the UI labels it. No real
  blood bank is ever contacted, and it is refused in production.

Availability is returned as a band (sufficient / limited / none), never as exact stock:
a hospital must not learn another facility's private inventory.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol
from uuid import UUID

from app.core.config import Settings
from app.core.errors import AppError
from app.core.provenance import SourceKind, SourceMeta
from app.persistence.repositories import UnitOfWork

Band = Literal["sufficient", "limited", "none"]


class UnknownProviderTargetError(AppError):
    status, code, title = 422, "unknown_target", "Unknown blood bank for this provider"


def availability_band(count: int, requested: int) -> Band:
    if count <= 0:
        return "none"
    return "sufficient" if count >= requested else "limited"


@dataclass(frozen=True)
class AvailabilityQuery:
    blood_group: str
    component: str
    units: int
    now: datetime


@dataclass(frozen=True)
class AvailabilityResult:
    provider: str
    target_ref: str
    name: str
    city: str
    state: str
    band: Band
    source: SourceMeta


@dataclass(frozen=True)
class ResolvedTarget:
    name: str
    facility_id: UUID | None
    external_ref: str | None


@dataclass(frozen=True)
class SubmissionAck:
    status: Literal["pending", "acknowledged"]
    note: str | None
    source: SourceMeta


class BloodBankProvider(Protocol):
    name: str
    kind: SourceKind

    async def search(self, uow: UnitOfWork, q: AvailabilityQuery) -> list[AvailabilityResult]: ...

    async def resolve_target(self, uow: UnitOfWork, target_ref: str) -> ResolvedTarget: ...

    async def submit(self, uow: UnitOfWork, reference: str, now: datetime) -> SubmissionAck: ...


class InternalBloodBankProvider:
    name = "internal"
    kind = SourceKind.INTERNAL

    async def search(self, uow: UnitOfWork, q: AvailabilityQuery) -> list[AvailabilityResult]:
        counts = await uow.bags.count_usable_by_facility(
            blood_group=q.blood_group, component=q.component, now=q.now
        )
        banks = await uow.facilities.list_active_by_type("BLOOD_BANK")
        meta = SourceMeta(provider=self.name, kind=self.kind, fetched_at=q.now)
        results = [
            AvailabilityResult(
                provider=self.name,
                target_ref=str(bank.id),
                name=bank.name,
                city=bank.city,
                state=bank.state,
                band=availability_band(counts.get(bank.id, 0), q.units),
                source=meta,
            )
            for bank in banks
            if not bank.is_simulated
        ]
        order = {"sufficient": 0, "limited": 1, "none": 2}
        return sorted(results, key=lambda r: (order[r.band], r.name))

    async def resolve_target(self, uow: UnitOfWork, target_ref: str) -> ResolvedTarget:
        try:
            facility_id = UUID(target_ref)
        except ValueError as exc:
            raise UnknownProviderTargetError() from exc
        facility = await uow.facilities.get(facility_id)
        if facility is None or facility.type != "BLOOD_BANK" or facility.status != "active":
            raise UnknownProviderTargetError()
        return ResolvedTarget(name=facility.name, facility_id=facility.id, external_ref=None)

    async def submit(self, uow: UnitOfWork, reference: str, now: datetime) -> SubmissionAck:
        # The bank sees it in its incoming queue immediately (same database).
        return SubmissionAck(
            status="pending",
            note=None,
            source=SourceMeta(provider=self.name, kind=self.kind, fetched_at=now),
        )


@dataclass(frozen=True)
class _MockBank:
    ref: str
    name: str
    city: str
    state: str


MOCK_BANKS: tuple[_MockBank, ...] = (
    _MockBank("MOCK-HWH", "Howrah Regional Blood Centre", "Howrah", "West Bengal"),
    _MockBank("MOCK-DGP", "Durgapur Community Blood Bank", "Durgapur", "West Bengal"),
    _MockBank("MOCK-SLK", "Salt Lake Blood Services", "Kolkata", "West Bengal"),
)

MOCK_NOTE = "Simulated partner blood bank: no real blood bank was contacted."


class MockBloodBankProvider:
    """Deterministic simulated partners (same query + same day → same answer)."""

    name = "mock"
    kind = SourceKind.SIMULATED

    def _units(self, bank: _MockBank, q: AvailabilityQuery) -> int:
        seed = f"{bank.ref}|{q.blood_group}|{q.component}|{q.now.date().isoformat()}"
        return int(hashlib.sha256(seed.encode()).hexdigest()[:8], 16) % 13  # 0..12 units

    async def search(self, uow: UnitOfWork, q: AvailabilityQuery) -> list[AvailabilityResult]:
        meta = SourceMeta(provider=self.name, kind=self.kind, fetched_at=q.now, note=MOCK_NOTE)
        return [
            AvailabilityResult(
                provider=self.name,
                target_ref=bank.ref,
                name=bank.name,
                city=bank.city,
                state=bank.state,
                band=availability_band(self._units(bank, q), q.units),
                source=meta,
            )
            for bank in MOCK_BANKS
        ]

    async def resolve_target(self, uow: UnitOfWork, target_ref: str) -> ResolvedTarget:
        for bank in MOCK_BANKS:
            if bank.ref == target_ref:
                return ResolvedTarget(name=bank.name, facility_id=None, external_ref=bank.ref)
        raise UnknownProviderTargetError()

    async def submit(self, uow: UnitOfWork, reference: str, now: datetime) -> SubmissionAck:
        return SubmissionAck(
            status="acknowledged",
            note=MOCK_NOTE,
            source=SourceMeta(provider=self.name, kind=self.kind, fetched_at=now, note=MOCK_NOTE),
        )


def build_bloodbank_providers(settings: Settings) -> dict[str, BloodBankProvider]:
    providers: dict[str, BloodBankProvider] = {"internal": InternalBloodBankProvider()}
    if settings.mock_blood_banks_enabled:
        providers["mock"] = MockBloodBankProvider()
    return providers
