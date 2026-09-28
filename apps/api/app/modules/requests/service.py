"""Blood requests: hospital → blood bank, fulfilled first-expiry-first-out.

Lifecycle (internal provider):  pending → dispatched → fulfilled
                                pending → rejected | cancelled
Mock provider (SIMULATED):      acknowledged → cancelled   (nothing is ever dispatched)
"""

from __future__ import annotations

import secrets
from datetime import UTC, timedelta
from typing import Literal
from uuid import UUID

from app.core.clock import Clock
from app.core.errors import AppError, NotFoundError
from app.core.ids import uuid7
from app.core.provenance import SourceKind, SourceMeta
from app.core.rbac import AuthContext, Role
from app.modules.audit.service import record
from app.modules.bags.domain import BagEventType
from app.modules.bags.service import BagService, append_event, require_facility
from app.modules.outbox.service import emit
from app.modules.requests.models import BloodRequest, RequestAllocation
from app.modules.requests.schemas import (
    AllocatedBag,
    AvailabilityItem,
    AvailabilityResponse,
    BloodRequestOut,
    CreateBloodRequest,
)
from app.persistence.repositories import UnitOfWork
from app.providers.bloodbank import (
    MOCK_NOTE,
    AvailabilityQuery,
    BloodBankProvider,
    UnknownProviderTargetError,
)

_REF_CHARS = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


class InsufficientStockError(AppError):
    status, code, title = 409, "insufficient_stock", "Not enough usable units in stock"


class InvalidRequestStateError(AppError):
    status, code, title = 409, "invalid_request_state", "The request can't do that now"


class IdempotencyMismatchError(AppError):
    status, code, title = (
        422,
        "idempotency_key_reused",
        "This Idempotency-Key was already used for a different request",
    )


class ProviderUnavailableError(AppError):
    status, code, title = 422, "provider_unavailable", "This provider is not enabled"


def new_reference() -> str:
    return "RQ-" + "".join(secrets.choice(_REF_CHARS) for _ in range(8))


def _fingerprint(b: CreateBloodRequest) -> tuple[object, ...]:
    return (b.provider, b.target_ref, b.blood_group, b.component.value, b.units, b.urgency)


class RequestService:
    def __init__(
        self, uow: UnitOfWork, clock: Clock, providers: dict[str, BloodBankProvider]
    ) -> None:
        self._uow = uow
        self._clock = clock
        self._providers = providers
        self._bags = BagService(uow, clock)

    def _provider(self, name: str) -> BloodBankProvider:
        provider = self._providers.get(name)
        if provider is None:
            raise ProviderUnavailableError()
        return provider

    # ------------------------------------------------------------------ search

    async def availability(
        self, ctx: AuthContext, *, blood_group: str, component: str, units: int
    ) -> AvailabilityResponse:
        require_facility(ctx)
        q = AvailabilityQuery(
            blood_group=blood_group, component=component, units=units, now=self._clock.now()
        )
        results: list[AvailabilityItem] = []
        for provider in self._providers.values():
            for r in await provider.search(self._uow, q):
                if r.target_ref == str(ctx.facility_id):
                    continue
                results.append(
                    AvailabilityItem(
                        provider=r.provider,
                        target_ref=r.target_ref,
                        name=r.name,
                        city=r.city,
                        state=r.state,
                        band=r.band,
                        source=r.source,
                    )
                )
        return AvailabilityResponse(
            blood_group=blood_group, component=component, units=units, results=results
        )

    # ------------------------------------------------------------------ views

    async def _out(self, req: BloodRequest) -> BloodRequestOut:
        bag_ids = await self._uow.requests.allocated_bag_ids(req.id)
        bags = []
        for bag_id in bag_ids:
            bag = await self._uow.bags.get(bag_id)
            if bag is not None:
                bags.append(
                    AllocatedBag(
                        public_id=bag.public_id,
                        component=bag.component,
                        blood_group=bag.blood_group,
                        expires_at=bag.expires_at,
                        status=bag.status,
                    )
                )
        simulated = req.provider == "mock"
        return BloodRequestOut(
            id=req.id,
            reference=req.reference,
            hospital_id=req.hospital_id,
            hospital_name=await self._bags.facility_name(req.hospital_id) or "",
            provider=req.provider,
            target_facility_id=req.target_facility_id,
            target_name=req.target_name,
            blood_group=req.blood_group,
            component=req.component,
            units=req.units,
            urgency=req.urgency,
            needed_by=req.needed_by,
            status=req.status,  # DB check constraint guarantees a RequestStatus value
            notes=req.notes,
            response_note=req.response_note,
            created_at=req.created_at,
            updated_at=req.updated_at,
            bags=bags,
            source=SourceMeta(
                provider=req.provider,
                kind=SourceKind.SIMULATED if simulated else SourceKind.INTERNAL,
                note=MOCK_NOTE if simulated else None,
            ),
        )

    async def _visible(self, ctx: AuthContext, request_id: UUID) -> BloodRequest:
        req = await self._uow.requests.get(request_id)
        facility_id = ctx.facility_id
        # Scope: only the requesting hospital and the target bank. Others get 404.
        if (
            req is None
            or facility_id is None
            or facility_id
            not in (
                req.hospital_id,
                req.target_facility_id,
            )
        ):
            raise NotFoundError("Blood request not found")
        return req

    async def get(self, ctx: AuthContext, request_id: UUID) -> BloodRequestOut:
        return await self._out(await self._visible(ctx, request_id))

    async def list(
        self, ctx: AuthContext, *, status: str | None, limit: int, offset: int
    ) -> tuple[list[BloodRequestOut], int]:
        facility_id = require_facility(ctx)
        hospital = ctx.role is Role.HOSPITAL
        rows, total = await self._uow.requests.list_page(
            hospital_id=facility_id if hospital else None,
            target_facility_id=None if hospital else facility_id,
            status=status,
            limit=limit,
            offset=offset,
        )
        return [await self._out(r) for r in rows], total

    # ------------------------------------------------------------------ hospital

    async def create(
        self, ctx: AuthContext, body: CreateBloodRequest, idempotency_key: str | None
    ) -> tuple[BloodRequestOut, bool]:
        """Returns (request, created). A replayed Idempotency-Key returns the original."""
        hospital_id = require_facility(ctx)
        provider = self._provider(body.provider)
        if idempotency_key:
            existing = await self._uow.requests.get_by_idempotency_key(hospital_id, idempotency_key)
            if existing is not None:
                stored = (
                    existing.provider,
                    existing.target_external_ref or str(existing.target_facility_id),
                    existing.blood_group,
                    existing.component,
                    existing.units,
                    existing.urgency,
                )
                if stored != _fingerprint(body):
                    raise IdempotencyMismatchError()
                return await self._out(existing), False

        now = self._clock.now()
        if body.needed_by.tzinfo is None:
            raise InvalidRequestStateError("needed_by must include a timezone")
        if body.needed_by < now - timedelta(minutes=5):
            raise InvalidRequestStateError("needed_by can't be in the past")
        needed_by = body.needed_by.astimezone(UTC)
        target = await provider.resolve_target(self._uow, body.target_ref)
        if target.facility_id == hospital_id:
            raise UnknownProviderTargetError("A facility can't request from itself")

        req = BloodRequest(
            id=uuid7(),
            reference=new_reference(),
            hospital_id=hospital_id,
            provider=provider.name,
            target_facility_id=target.facility_id,
            target_external_ref=target.external_ref,
            target_name=target.name,
            blood_group=body.blood_group,
            component=body.component.value,
            units=body.units,
            urgency=body.urgency,
            needed_by=needed_by,
            status="pending",
            notes=body.notes,
            response_note=None,
            idempotency_key=idempotency_key,
            created_by=ctx.user_id,
            responded_by=None,
            created_at=now,
            updated_at=now,
        )
        ack = await provider.submit(self._uow, req.reference, now)
        req.status = ack.status
        req.response_note = ack.note
        await self._uow.requests.add(req)
        await emit(
            self._uow,
            self._clock,
            topic="request.created",
            aggregate_type="blood_request",
            aggregate_id=str(req.id),
            audience=[hospital_id, target.facility_id],
            payload=self._event_payload(req),
        )
        await record(
            self._uow,
            self._clock,
            action="blood_request.created",
            resource="blood_request",
            resource_id=req.id,
            actor_id=ctx.user_id,
            meta={"provider": req.provider, "units": req.units, "urgency": req.urgency},
        )
        await self._uow.commit()
        return await self._out(req), True

    async def cancel(self, ctx: AuthContext, request_id: UUID) -> BloodRequestOut:
        req = await self._visible(ctx, request_id)
        if req.hospital_id != ctx.facility_id:
            raise NotFoundError("Blood request not found")
        return await self._transition(
            ctx, req, {"pending", "acknowledged"}, "cancelled", "request.cancelled", None
        )

    async def receive(self, ctx: AuthContext, request_id: UUID) -> BloodRequestOut:
        req = await self._visible(ctx, request_id)
        hospital_id = req.hospital_id
        if hospital_id != ctx.facility_id:
            raise NotFoundError("Blood request not found")
        if req.status != "dispatched":
            raise InvalidRequestStateError(f"A '{req.status}' request can't be received.")
        now = self._clock.now()
        for bag_id in await self._uow.requests.allocated_bag_ids(req.id):
            bag = await self._uow.bags.get(bag_id)
            if bag is None:  # pragma: no cover - FK guarantees presence
                continue
            await append_event(
                self._uow,
                bag,
                BagEventType.RECEIVED,
                at=now,
                actor_id=ctx.user_id,
                from_facility_id=bag.current_facility_id,
                to_facility_id=hospital_id,
                meta={"request": req.reference},
            )
            bag.current_facility_id = hospital_id
        return await self._transition(
            ctx, req, {"dispatched"}, "fulfilled", "request.fulfilled", None
        )

    # ------------------------------------------------------------------ blood bank

    async def _own_incoming(self, ctx: AuthContext, request_id: UUID) -> BloodRequest:
        req = await self._visible(ctx, request_id)
        if req.target_facility_id != ctx.facility_id:
            raise NotFoundError("Blood request not found")
        return req

    async def reject(self, ctx: AuthContext, request_id: UUID, note: str) -> BloodRequestOut:
        req = await self._own_incoming(ctx, request_id)
        return await self._transition(ctx, req, {"pending"}, "rejected", "request.rejected", note)

    async def fulfil(self, ctx: AuthContext, request_id: UUID, note: str | None) -> BloodRequestOut:
        req = await self._own_incoming(ctx, request_id)
        bank_id = require_facility(ctx)
        if req.status != "pending":
            raise InvalidRequestStateError(f"A '{req.status}' request can't be fulfilled.")
        now = self._clock.now()
        bags = await self._uow.bags.usable_fefo(
            bank_id,
            blood_group=req.blood_group,
            component=req.component,
            now=now,
            limit=req.units,
        )
        if len(bags) < req.units:
            raise InsufficientStockError(
                f"{len(bags)} of {req.units} usable {req.blood_group} {req.component} units "
                "are in stock."
            )
        for bag in bags:
            await append_event(
                self._uow,
                bag,
                BagEventType.DISPATCHED,
                at=now,
                actor_id=ctx.user_id,
                from_facility_id=bank_id,
                to_facility_id=req.hospital_id,
                meta={"request": req.reference},
            )
            await self._uow.requests.add_allocation(
                RequestAllocation(request_id=req.id, bag_id=bag.id, allocated_at=now)
            )
        await emit(
            self._uow,
            self._clock,
            topic="inventory.updated",
            aggregate_type="facility",
            aggregate_id=str(bank_id),
            audience=[bank_id],
            payload={"reason": "request_dispatched", "bags_removed": len(bags)},
        )
        return await self._transition(
            ctx, req, {"pending"}, "dispatched", "request.dispatched", note
        )

    # ------------------------------------------------------------------ shared

    @staticmethod
    def _event_payload(req: BloodRequest) -> dict[str, object]:
        return {
            "request_id": str(req.id),
            "reference": req.reference,
            "status": req.status,
            "blood_group": req.blood_group,
            "component": req.component,
            "units": req.units,
            "urgency": req.urgency,
        }

    async def _transition(
        self,
        ctx: AuthContext,
        req: BloodRequest,
        allowed: set[str],
        to: Literal["cancelled", "rejected", "dispatched", "fulfilled"],
        topic: str,
        note: str | None,
    ) -> BloodRequestOut:
        if req.status not in allowed:
            raise InvalidRequestStateError(f"A '{req.status}' request can't become '{to}'.")
        now = self._clock.now()
        req.status = to
        req.updated_at = now
        if note is not None:
            req.response_note = note
        if to in ("rejected", "dispatched"):
            req.responded_by = ctx.user_id
        await emit(
            self._uow,
            self._clock,
            topic=topic,
            aggregate_type="blood_request",
            aggregate_id=str(req.id),
            audience=[req.hospital_id, req.target_facility_id],
            payload=self._event_payload(req),
        )
        await record(
            self._uow,
            self._clock,
            action=f"blood_request.{to}",
            resource="blood_request",
            resource_id=req.id,
            actor_id=ctx.user_id,
        )
        await self._uow.commit()
        return await self._out(req)
