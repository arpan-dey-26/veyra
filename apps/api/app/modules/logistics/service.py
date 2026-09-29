"""Simulated logistics (Phase 7): scoped shipment views and demo transport controls.

Scope:
- blood bank → shipments it dispatched (source); simulator only for those (it keeps custody
  of the bags until the hospital confirms receipt)
- hospital   → shipments destined for it; confirms receipt through the existing workflow
- admin      → network overview; donor → 403; unrelated facilities → 404
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Literal
from uuid import UUID

from app.core.clock import Clock
from app.core.errors import AppError, NotFoundError, PermissionDeniedError
from app.core.provenance import SourceKind, SourceMeta
from app.core.rbac import AuthContext, Permission, Role
from app.modules.audit.service import record
from app.modules.bags.service import verify_chain
from app.modules.logistics import engine as L
from app.modules.logistics.hooks import InvalidShipmentTransitionError, apply
from app.modules.logistics.models import Shipment
from app.modules.logistics.schemas import (
    CheckpointOut,
    ColdChainBag,
    CourierOut,
    EtaOut,
    LogisticsResult,
    ShipmentBagOut,
    ShipmentDetail,
    ShipmentList,
    ShipmentRoute,
    ShipmentSummary,
    ShipmentTelemetry,
    ShipmentTimeline,
    TimelineEvent,
)
from app.modules.requests.models import BloodRequest
from app.modules.telemetry.rules import device_status
from app.persistence.repositories import UnitOfWork

LIST_LIMIT = 200


class LogisticsSimulatorDisabledError(AppError):
    status, code, title = 403, "simulator_disabled", "The logistics simulator is disabled"


class ShipmentNotArrivedError(AppError):
    status, code, title = 409, "shipment_not_arrived", "The shipment has not arrived yet"


def _source(now: datetime, note: str) -> SourceMeta:
    return SourceMeta(
        provider="veyra-logistics-sim", kind=SourceKind.SIMULATED, fetched_at=now, note=note
    )


class LogisticsService:
    def __init__(
        self,
        uow: UnitOfWork,
        clock: Clock,
        *,
        simulator_enabled: bool,
        utc_offset_minutes: int = 330,
    ) -> None:
        self._uow = uow
        self._clock = clock
        self._sim = simulator_enabled
        self._tz = timezone(timedelta(minutes=utc_offset_minutes))
        self._names: dict[UUID, str] = {}

    # ------------------------------------------------------------------ scope

    def _is_admin(self, ctx: AuthContext) -> bool:
        return ctx.role is Role.ADMIN and ctx.has(Permission.NETWORK_READ)

    async def _visible(self, ctx: AuthContext, shipment_id: UUID) -> Shipment:
        s = await self._uow.shipments.get(shipment_id)
        if s is None:
            raise NotFoundError("Shipment not found")
        if self._is_admin(ctx):
            return s
        if not ctx.has(Permission.SHIPMENT_READ) or ctx.facility_id is None:
            raise PermissionDeniedError()
        if ctx.facility_id not in (s.source_facility_id, s.destination_facility_id):
            raise NotFoundError("Shipment not found")  # never confirm it exists
        return s

    async def _request(self, s: Shipment) -> BloodRequest:
        req = await self._uow.requests.get(s.request_id)
        if req is None:  # pragma: no cover - the foreign key guarantees it
            raise NotFoundError("Blood request not found")
        return req

    async def _name(self, facility_id: UUID) -> str:
        if facility_id not in self._names:
            f = await self._uow.facilities.get(facility_id)
            self._names[facility_id] = f.name if f else ""
        return self._names[facility_id]

    # ------------------------------------------------------------------ views

    def _eta(self, s: Shipment) -> EtaOut:
        e = L.eta(
            status=s.status,
            eta_at=s.eta_at,
            now=self._clock.now(),
            delay_minutes=s.delay_minutes,
            delay_active=s.delay_active,
        )
        return EtaOut(
            eta_at=e.eta_at,
            remaining_minutes=e.remaining_minutes,
            status=e.status,
            delay_minutes=s.delay_minutes,
            delay_active=s.delay_active,
            delay_reason=s.delay_reason,
            reasons=e.reasons,
        )

    @staticmethod
    def _checkpoints(s: Shipment) -> list[CheckpointOut]:
        return [
            CheckpointOut(
                seq=c["seq"],
                name=c["name"],
                kind=c["kind"],
                distance_km=c["distance_km"],
                expected_at=datetime.fromisoformat(c["expected_at"]),
                actual_at=datetime.fromisoformat(c["actual_at"]) if c["actual_at"] else None,
                status=c["status"],
                current=c["seq"] == s.current_checkpoint,
            )
            for c in s.checkpoints
        ]

    async def _summary(self, s: Shipment) -> ShipmentSummary:
        req = await self._request(s)
        cp = s.current_checkpoint
        return ShipmentSummary(
            id=s.id,
            reference=s.reference,
            request_id=s.request_id,
            request_reference=req.reference,
            source_facility_id=s.source_facility_id,
            source_name=await self._name(s.source_facility_id),
            destination_facility_id=s.destination_facility_id,
            destination_name=await self._name(s.destination_facility_id),
            status=s.status,  # DB check constraint guarantees a ShipmentStatus value
            urgency=s.urgency,
            bag_count=len(await self._uow.shipments.bag_ids(s.id)),
            blood_group=req.blood_group,
            component=req.component,
            courier=CourierOut(
                courier_id=s.courier_id, name=s.courier_name, vehicle_type=s.vehicle_type
            ),
            eta=self._eta(s),
            current_checkpoint=cp,
            current_checkpoint_name=s.checkpoints[cp]["name"]
            if 0 <= cp < len(s.checkpoints)
            else None,
            cold_chain_alert=s.cold_chain_alert,  # DB check constraint
            created_at=s.created_at,
            picked_up_at=s.picked_up_at,
            arrived_at=s.arrived_at,
            received_at=s.received_at,
            last_update_at=s.last_update_at,
        )

    async def _telemetry(self, s: Shipment) -> ShipmentTelemetry:
        now = self._clock.now()
        bags: list[ColdChainBag] = []
        for bag_id in await self._uow.shipments.bag_ids(s.id):
            bag = await self._uow.bags.get(bag_id)
            if bag is None:  # pragma: no cover - FK
                continue
            d = await self._uow.telemetry.device_for_bag(bag.id)
            bags.append(
                ColdChainBag(
                    public_id=bag.public_id,
                    monitored=d is not None,
                    device_id=d.device_id if d else None,
                    cold_chain_status=d.cold_chain_status if d else "unmonitored",
                    excursion_active=bool(d and d.excursion_started_at is not None),
                    latest_temperature_c=d.last_temperature_c if d else None,
                    device_status=(
                        device_status(d.battery_pct, d.last_seen_at, d.sim_running, now)
                        if d
                        else None
                    ),
                    last_telemetry_at=d.last_seen_at if d else None,
                )
            )
        return ShipmentTelemetry(
            shipment_id=s.id,
            reference=s.reference,
            status=s.status,  # DB check constraint
            in_transit=s.status in L.OPEN_TRANSPORT,
            cold_chain_alert=s.cold_chain_alert,  # DB check constraint
            bags=bags,
            source=_source(now, "Simulated IoT telemetry — prototype"),
        )

    async def _detail(self, s: Shipment) -> ShipmentDetail:
        base = await self._summary(s)
        req = await self._request(s)
        bags: list[ShipmentBagOut] = []
        for bag_id in await self._uow.shipments.bag_ids(s.id):
            bag = await self._uow.bags.get(bag_id)
            if bag is None:  # pragma: no cover - FK
                continue
            chain = verify_chain(await self._uow.bags.list_events(bag.id))
            bags.append(
                ShipmentBagOut(
                    public_id=bag.public_id,
                    blood_group=bag.blood_group,
                    component=bag.component,
                    status=bag.status,
                    expires_at=bag.expires_at,
                    chain_valid=chain.valid,
                    chain_length=chain.length,
                )
            )
        return ShipmentDetail(
            **base.model_dump(),
            request_status=req.status,
            bags=bags,
            checkpoints=self._checkpoints(s),
            distance_km=s.distance_km,
            planned_minutes=s.planned_minutes,
            trace_valid=all(b.chain_valid for b in bags),
            telemetry=await self._telemetry(s),
            simulator_enabled=self._sim,
            source=_source(self._clock.now(), L.LOGISTICS_LABEL),
        )

    # ------------------------------------------------------------------ endpoints

    async def list(self, ctx: AuthContext, *, status: str | None) -> ShipmentList:
        scope: Literal["source", "destination", "network"]
        if self._is_admin(ctx):
            scope, src, dst = "network", None, None
        else:
            if not ctx.has(Permission.SHIPMENT_READ) or ctx.facility_id is None:
                raise PermissionDeniedError()
            if ctx.role is Role.HOSPITAL:
                scope, src, dst = "destination", None, ctx.facility_id
            else:
                scope, src, dst = "source", ctx.facility_id, None
        rows = await self._uow.shipments.list_shipments(
            source_facility_id=src, destination_facility_id=dst, status=None, limit=LIST_LIMIT
        )
        summaries = [await self._summary(s) for s in rows]
        today = self._clock.now().astimezone(self._tz).date()
        counts = {
            "awaiting_pickup": sum(1 for s in rows if s.status in ("created", "pickup_pending")),
            "in_transit": sum(1 for s in rows if s.status in ("picked_up", "in_transit")),
            "delayed": sum(1 for s in rows if s.status == "delayed"),
            "arrived": sum(1 for s in rows if s.status == "arrived"),
            "completed_today": sum(
                1
                for s in rows
                if s.received_at is not None and s.received_at.astimezone(self._tz).date() == today
            ),
            "cold_chain_alerts": sum(
                1 for s in rows if s.cold_chain_alert != "none" and s.status != "received"
            ),
            "on_schedule": sum(1 for x in summaries if x.eta.status == "on_schedule"),
            "late": sum(1 for x in summaries if x.eta.status == "late"),
        }
        done = [
            (s.arrived_at - s.created_at).total_seconds() / 60
            for s in rows
            if s.arrived_at is not None
        ]
        return ShipmentList(
            scope=scope,
            shipments=[x for x in summaries if status is None or x.status == status],
            counts=counts,
            average_delivery_minutes=round(sum(done) / len(done), 1) if done else None,
            generated_at=self._clock.now(),
        )

    async def get(self, ctx: AuthContext, shipment_id: UUID) -> ShipmentDetail:
        return await self._detail(await self._visible(ctx, shipment_id))

    async def route(self, ctx: AuthContext, shipment_id: UUID) -> ShipmentRoute:
        s = await self._visible(ctx, shipment_id)
        return ShipmentRoute(
            shipment_id=s.id,
            reference=s.reference,
            status=s.status,  # DB check constraint
            distance_km=s.distance_km,
            current_checkpoint=s.current_checkpoint,
            checkpoints=self._checkpoints(s),
            eta=self._eta(s),
            source=_source(self._clock.now(), L.ROUTE_MAP_LABEL),
        )

    async def timeline(self, ctx: AuthContext, shipment_id: UUID) -> ShipmentTimeline:
        s = await self._visible(ctx, shipment_id)
        return ShipmentTimeline(
            shipment_id=s.id,
            reference=s.reference,
            events=[
                TimelineEvent(
                    seq=e.seq,
                    event_type=e.event_type,
                    status=e.status,  # DB check constraint on shipments at write time
                    occurred_at=e.occurred_at,
                    meta=dict(e.meta),
                )
                for e in await self._uow.shipments.events(s.id)
            ],
        )

    async def telemetry(self, ctx: AuthContext, shipment_id: UUID) -> ShipmentTelemetry:
        return await self._telemetry(await self._visible(ctx, shipment_id))

    async def receivable_request(self, ctx: AuthContext, shipment_id: UUID) -> UUID:
        """The destination hospital confirms receipt of an arrived shipment."""
        s = await self._uow.shipments.get(shipment_id)
        if s is None or ctx.facility_id is None or s.destination_facility_id != ctx.facility_id:
            raise NotFoundError("Shipment not found")
        if s.status != "arrived":
            raise ShipmentNotArrivedError(
                f"A '{s.status}' shipment can't be received here; it must arrive first."
            )
        return s.request_id

    # ------------------------------------------------------------------ simulator (demo)

    async def _held(self, ctx: AuthContext, shipment_id: UUID) -> Shipment:
        if not self._sim:
            raise LogisticsSimulatorDisabledError()
        if not ctx.has(Permission.LOGISTICS_SIMULATE) or ctx.facility_id is None:
            raise PermissionDeniedError()
        s = await self._uow.shipments.get(shipment_id, lock=True)
        if s is None or s.source_facility_id != ctx.facility_id:
            raise NotFoundError("Shipment not found")
        return s

    async def simulate(
        self,
        ctx: AuthContext,
        shipment_id: UUID,
        action: Literal["advance", "delay", "resume", "arrive"],
        *,
        minutes: int = 0,
        reason: str | None = None,
    ) -> LogisticsResult:
        s = await self._held(ctx, shipment_id)
        before = s.status
        try:
            topics = await apply(
                self._uow,
                self._clock,
                s,
                action,
                actor_id=ctx.user_id,
                minutes=minutes,
                reason=reason,
            )
        except InvalidShipmentTransitionError:
            await self._uow.rollback()
            raise
        await record(
            self._uow,
            self._clock,
            action=f"shipment.simulated_{action}",
            resource="shipment",
            resource_id=s.id,
            actor_id=ctx.user_id,
            meta={"from": before, "to": s.status, "simulated": True}
            | ({"minutes": minutes, "reason": reason} if action == "delay" else {}),
        )
        await self._uow.commit()
        return LogisticsResult(shipment=await self._detail(s), action=action, events=topics)
