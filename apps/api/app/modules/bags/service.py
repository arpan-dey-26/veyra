"""Blood-bag trace (append-only, hash-chained) and facility inventory."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from app.core.clock import Clock
from app.core.errors import AppError, NotFoundError, PermissionDeniedError
from app.core.ids import uuid7
from app.core.rbac import AuthContext, Permission, Role
from app.modules.audit.service import record
from app.modules.bags.domain import (
    COMPONENT_SPECS,
    GENESIS_HASH,
    TRANSITIONS,
    BagEventType,
    BagStatus,
    event_fields,
    event_hash,
    qr_payload,
)
from app.modules.bags.models import BagEvent, BloodBag
from app.modules.bags.schemas import (
    BagEventOut,
    BagOut,
    BagTrace,
    ChainStatus,
    ComponentInfo,
    InventoryRow,
    InventorySummary,
)
from app.modules.outbox.service import emit
from app.persistence.repositories import UnitOfWork

EXPIRING_WINDOW = timedelta(hours=72)
REFERENCE_NOTE = (
    "Shelf lives and storage ranges are prototype defaults; verify against current national "
    "blood-transfusion guidelines before real-world use."
)


class InvalidTransitionError(AppError):
    status, code, title = 409, "invalid_transition", "This bag can't make that transition"


class NoFacilityError(AppError):
    status, code, title = 403, "no_facility", "Your account is not linked to a facility"


def require_facility(ctx: AuthContext) -> UUID:
    if ctx.facility_id is None:
        raise NoFacilityError()
    return ctx.facility_id


def _fields(event: BagEvent) -> dict[str, Any]:
    return event_fields(
        bag_id=str(event.bag_id),
        seq=event.seq,
        event_type=event.event_type,
        from_facility_id=str(event.from_facility_id) if event.from_facility_id else None,
        to_facility_id=str(event.to_facility_id) if event.to_facility_id else None,
        actor_id=str(event.actor_id) if event.actor_id else None,
        occurred_at=event.occurred_at,
        meta=event.meta,
    )


def verify_chain(events: list[BagEvent]) -> ChainStatus:
    """Recompute every hash. Any edited, inserted, removed or reordered event → invalid."""
    prev = GENESIS_HASH
    for expected_seq, event in enumerate(events, start=1):
        if (
            event.seq != expected_seq
            or event.prev_hash != prev
            or event_hash(prev, _fields(event)) != event.row_hash
        ):
            return ChainStatus(valid=False, length=len(events), head_hash=None)
        prev = event.row_hash
    return ChainStatus(
        valid=True, length=len(events), head_hash=events[-1].row_hash if events else None
    )


async def append_event(
    uow: UnitOfWork,
    bag: BloodBag,
    event_type: BagEventType,
    *,
    at: datetime,
    actor_id: UUID | None,
    from_facility_id: UUID | None,
    to_facility_id: UUID | None,
    meta: dict[str, Any] | None = None,
) -> BagEvent:
    """The ONLY way a bag changes state: validates the transition and appends a chained event."""
    if event_type is not BagEventType.COLLECTED:
        allowed_from, to_status = TRANSITIONS[event_type]
        if BagStatus(bag.status) not in allowed_from:
            raise InvalidTransitionError(
                f"A bag that is '{bag.status}' can't be marked {event_type.value.lower()}."
            )
        bag.status = to_status.value
        bag.updated_at = at
    history = await uow.bags.list_events(bag.id)
    prev_hash = history[-1].row_hash if history else GENESIS_HASH
    event = BagEvent(
        id=uuid7(),
        bag_id=bag.id,
        seq=len(history) + 1,
        event_type=event_type.value,
        from_facility_id=from_facility_id,
        to_facility_id=to_facility_id,
        actor_id=actor_id,
        occurred_at=at,
        meta=meta or {},
        prev_hash=prev_hash,
        row_hash="",
    )
    event.row_hash = event_hash(prev_hash, _fields(event))
    await uow.bags.add_event(event)
    return event


class BagService:
    def __init__(self, uow: UnitOfWork, clock: Clock) -> None:
        self._uow = uow
        self._clock = clock
        self._names: dict[UUID, str] = {}

    async def facility_name(self, facility_id: UUID | None) -> str | None:
        if facility_id is None:
            return None
        if facility_id not in self._names:
            facility = await self._uow.facilities.get(facility_id)
            self._names[facility_id] = facility.name if facility else "Unknown facility"
        return self._names[facility_id]

    async def bag_out(self, bag: BloodBag) -> BagOut:
        now = self._clock.now()
        return BagOut(
            id=bag.id,
            public_id=bag.public_id,
            qr_payload=qr_payload(bag.public_id),
            blood_group=bag.blood_group,
            component=bag.component,
            volume_ml=bag.volume_ml,
            collected_at=bag.collected_at,
            expires_at=bag.expires_at,
            status=bag.status,
            is_expired=bag.expires_at <= now,
            current_facility_id=bag.current_facility_id,
            current_facility_name=await self.facility_name(bag.current_facility_id) or "",
        )

    async def inventory(self, ctx: AuthContext) -> InventorySummary:
        facility_id = require_facility(ctx)
        now = self._clock.now()
        counts = await self._uow.bags.inventory_counts(
            facility_id, now=now, soon=now + EXPIRING_WINDOW
        )
        rows = [
            InventoryRow(
                blood_group=c.blood_group,
                component=c.component,
                available=c.available,
                expired=c.expired,
                expiring_soon=c.expiring_soon,
                next_expiry=c.next_expiry,
            )
            for c in counts
        ]
        return InventorySummary(
            facility_id=facility_id,
            facility_name=await self.facility_name(facility_id) or "",
            generated_at=now,
            total_available=sum(r.available for r in rows),
            rows=rows,
            components=[
                ComponentInfo(
                    code=code.value,
                    label=spec.label,
                    shelf_life_days=spec.shelf_life.days,
                    storage=spec.storage,
                )
                for code, spec in COMPONENT_SPECS.items()
            ],
            reference_note=REFERENCE_NOTE,
        )

    async def list_bags(
        self,
        ctx: AuthContext,
        *,
        status: str | None,
        blood_group: str | None,
        component: str | None,
        limit: int,
        offset: int,
    ) -> tuple[list[BagOut], int]:
        facility_id = require_facility(ctx)
        rows, total = await self._uow.bags.list_at_facility(
            facility_id,
            status=status,
            blood_group=blood_group,
            component=component,
            limit=limit,
            offset=offset,
        )
        return [await self.bag_out(b) for b in rows], total

    async def _visible_bag(
        self, ctx: AuthContext, public_id: str
    ) -> tuple[BloodBag, list[BagEvent]]:
        bag = await self._uow.bags.get_by_public_id(public_id.strip().upper())
        if bag is None:
            raise NotFoundError("Blood bag not found")
        events = await self._uow.bags.list_events(bag.id)
        if ctx.role is Role.ADMIN and ctx.has(Permission.NETWORK_READ):
            return bag, events
        facility_id = ctx.facility_id
        touched = {bag.current_facility_id} | {
            f for e in events for f in (e.from_facility_id, e.to_facility_id) if f
        }
        # Scope: only facilities that hold or have held the bag. 404 (not 403) avoids
        # confirming that a bag id exists to facilities outside its custody chain.
        if facility_id is None or facility_id not in touched:
            raise NotFoundError("Blood bag not found")
        return bag, events

    async def trace(self, ctx: AuthContext, public_id: str) -> BagTrace:
        bag, events = await self._visible_bag(ctx, public_id)
        return BagTrace(
            bag=await self.bag_out(bag),
            events=[
                BagEventOut(
                    seq=e.seq,
                    event_type=e.event_type,
                    occurred_at=e.occurred_at,
                    from_facility=await self.facility_name(e.from_facility_id),
                    to_facility=await self.facility_name(e.to_facility_id),
                    meta=dict(e.meta),
                    prev_hash=e.prev_hash,
                    row_hash=e.row_hash,
                )
                for e in events
            ],
            chain=verify_chain(events),
        )

    async def discard(
        self, ctx: AuthContext, public_id: str, reason: str, note: str | None
    ) -> BagOut:
        if not ctx.has(Permission.BAG_TRANSITION):
            raise PermissionDeniedError()
        facility_id = require_facility(ctx)
        bag = await self._uow.bags.get_by_public_id(public_id.strip().upper())
        if bag is None or bag.current_facility_id != facility_id:
            raise NotFoundError("Blood bag not found")  # only the holder may discard
        now = self._clock.now()
        meta: dict[str, Any] = {"reason": reason}
        if note:
            meta["note"] = note
        await append_event(
            self._uow,
            bag,
            BagEventType.DISCARDED,
            at=now,
            actor_id=ctx.user_id,
            from_facility_id=facility_id,
            to_facility_id=None,
            meta=meta,
        )
        await emit(
            self._uow,
            self._clock,
            topic="bag.discarded",
            aggregate_type="bag",
            aggregate_id=bag.public_id,
            audience=[facility_id],
            payload={"public_id": bag.public_id, "reason": reason},
        )
        await record(
            self._uow,
            self._clock,
            action="bag.discarded",
            resource="bag",
            resource_id=bag.id,
            actor_id=ctx.user_id,
            meta={"reason": reason},
        )
        await self._uow.commit()
        return await self.bag_out(bag)
