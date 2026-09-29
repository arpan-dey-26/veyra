"""Operational intelligence & emergency response (Phase 6).

Read-only views that combine real requests, real inventory, the Phase 4 SYNTHETIC forecast and
the Phase 5 SIMULATED cold-chain state into explainable, human-controlled recommendations.
Nothing here dispatches a bag: the blood bank confirms dispatch through the existing
``POST /requests/{id}/fulfil`` workflow (optionally with the recommended bag ids).

Scope (same rules as requests and dashboards):
- blood bank → requests targeted at it, its own stock and pressure;
- hospital   → its own requests (bank stock only as bands), its own pressure;
- admin      → network level; donor → 403; outsiders → 404 (existence never confirmed).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Literal
from uuid import UUID

from app.core.clock import Clock
from app.core.errors import AppError, NotFoundError, PermissionDeniedError
from app.core.provenance import SourceKind, SourceMeta
from app.core.rbac import AuthContext, Permission, Role
from app.modules.audit.service import record
from app.modules.bags.models import BloodBag
from app.modules.facilities.models import Facility
from app.modules.forecast.model import LoadedModel
from app.modules.forecast.service import (
    FORECAST_COMPONENTS,
    FORECAST_GROUPS,
    facility_daily_mean,
)
from app.modules.logistics.models import Shipment
from app.modules.operations import engine as E
from app.modules.operations.schemas import (
    ActiveRoute,
    AlertOut,
    AlertsOut,
    CandidateBag,
    ChangePriority,
    FacilityPressure,
    OpsRequest,
    OpsRequestList,
    PressureRow,
    PriorityOut,
    ReasonOut,
    Recommendation,
    RouteOut,
    RoutingOverview,
)
from app.modules.outbox.service import emit
from app.modules.requests.models import BloodRequest
from app.modules.telemetry.models import TelemetryDevice
from app.modules.telemetry.rules import device_status
from app.persistence.repositories import UnitOfWork
from app.providers.bloodbank import availability_band

OPEN_STATUSES = ("pending", "acknowledged")
LIST_LIMIT = 200
CANDIDATE_LIMIT = 50
COMPATIBILITY_RULE = (
    "Existing VEYRA rule: same blood group and component, status available, unexpired, "
    "held by this blood bank. No cross-group substitution is suggested."
)
HUMAN_CONFIRMATION = (
    "Nothing is dispatched automatically. Confirm dispatch yourself with the existing "
    "dispatch action; you may pass the recommended bag ids or keep strict FEFO."
)


class InvalidPriorityChangeError(AppError):
    status, code, title = 409, "invalid_priority_change", "The priority can't be changed now"


def _reasons(rs: list[E.Reason]) -> list[ReasonOut]:
    return [ReasonOut(code=r.code, text=r.text, points=r.points, tone=r.tone) for r in rs]


def _viewer(ctx: AuthContext) -> Literal["bank", "hospital", "admin"]:
    if ctx.role is Role.ADMIN:
        return "admin"
    return "bank" if ctx.role is Role.BLOOD_BANK else "hospital"


def _place(f: Facility) -> E.Place:
    return E.Place(id=str(f.id), name=f.name, city=f.city, state=f.state)


def _device_view(d: TelemetryDevice, now: datetime) -> E.DeviceView:
    return E.DeviceView(
        cold_chain_status=d.cold_chain_status,
        device_status=device_status(d.battery_pct, d.last_seen_at, d.sim_running, now),
        excursion_active=d.excursion_started_at is not None,
    )


@dataclass
class _Stock:
    bags: list[BloodBag]
    candidates: list[E.Candidate]

    @property
    def facts(self) -> E.StockFacts:
        good = sum(1 for c in self.candidates if not c.deprioritized)
        return E.StockFacts(
            usable=len(self.candidates),
            usable_without_concern=good,
            flagged=len(self.candidates) - good,
            expiring_soon=sum(
                1 for c in self.candidates if any(r.code == "expires_soon" for r in c.reasons)
            ),
            availability_band=None,
        )


class OperationsService:
    def __init__(
        self, uow: UnitOfWork, clock: Clock, model: LoadedModel, *, utc_offset_minutes: int
    ) -> None:
        self._uow = uow
        self._clock = clock
        self._model = model
        self._tz = timezone(timedelta(minutes=utc_offset_minutes))
        self._facilities: dict[UUID, Facility | None] = {}
        self._devices: dict[UUID | None, dict[str, E.DeviceView]] = {}
        self._device_rows: dict[UUID | None, list[tuple[TelemetryDevice, BloodBag]]] = {}
        self._bags: dict[tuple[UUID, str, str], list[BloodBag]] = {}
        self._means: dict[tuple[UUID, str, str], float | None] = {}
        self._open: dict[UUID, list[BloodRequest]] = {}

    @property
    def uow(self) -> UnitOfWork:
        return self._uow

    @property
    def clock(self) -> Clock:
        return self._clock

    # ------------------------------------------------------------------ lookups (cached)

    def _today(self) -> date:
        return self._clock.now().astimezone(self._tz).date()

    async def facility(self, facility_id: UUID | None) -> Facility | None:
        if facility_id is None:
            return None
        if facility_id not in self._facilities:
            self._facilities[facility_id] = await self._uow.facilities.get(facility_id)
        return self._facilities[facility_id]

    async def _name(self, facility_id: UUID | None) -> str:
        f = await self.facility(facility_id)
        return f.name if f else ""

    async def _device_rows_at(
        self, facility_id: UUID | None
    ) -> list[tuple[TelemetryDevice, BloodBag]]:
        if facility_id not in self._device_rows:
            self._device_rows[facility_id] = await self._uow.telemetry.devices_at(facility_id)
        return self._device_rows[facility_id]

    async def _devices_at(self, facility_id: UUID) -> dict[str, E.DeviceView]:
        if facility_id not in self._devices:
            now = self._clock.now()
            self._devices[facility_id] = {
                b.public_id: _device_view(d, now)
                for d, b in await self._device_rows_at(facility_id)
            }
        return self._devices[facility_id]

    async def _stock_for(self, bank_id: UUID, group: str, component: str, units: int) -> _Stock:
        key = (bank_id, group, component)
        now = self._clock.now()
        if key not in self._bags:
            self._bags[key] = await self._uow.bags.list_usable(
                bank_id, now=now, blood_group=group, component=component, limit=CANDIDATE_LIMIT
            )
        bags = self._bags[key]
        bank = await self.facility(bank_id)
        views = [
            E.BagView(
                public_id=b.public_id,
                blood_group=b.blood_group,
                component=b.component,
                expires_at=b.expires_at,
                facility_id=str(bank_id),
                facility_name=bank.name if bank else "",
            )
            for b in bags
        ]
        # Ranking depends on the requested units, so it is recomputed (cheap) per request.
        ranked = E.rank_candidates(views, await self._devices_at(bank_id), units=units, now=now)
        return _Stock(bags=bags, candidates=ranked)

    async def _open_at(self, bank_id: UUID) -> list[BloodRequest]:
        if bank_id not in self._open:
            rows, _ = await self._uow.requests.list_page(
                hospital_id=None,
                target_facility_id=bank_id,
                status="pending",
                limit=500,
                offset=0,
            )
            self._open[bank_id] = rows
        return self._open[bank_id]

    async def _on_hand(self, facility_id: UUID) -> dict[tuple[str, str], int]:
        now = self._clock.now()
        counts = await self._uow.bags.inventory_counts(facility_id, now=now, soon=now)
        return {(c.blood_group, c.component): c.available for c in counts}

    def _mean(self, facility: Facility, group: str, component: str) -> float | None:
        # Memoised per service instance (= per API request): a queue of many requests for the
        # same group/component would otherwise regenerate the same synthetic series each time.
        key = (facility.id, group, component)
        if key not in self._means:
            self._means[key] = facility_daily_mean(
                self._model, facility, group, component, self._today()
            )
        return self._means[key]

    async def pressure_for(
        self,
        facility: Facility,
        group: str,
        component: str,
        *,
        stock: int | None = None,
        open_units: int | None = None,
    ) -> E.Pressure:
        if stock is None:
            stock = (await self._on_hand(facility.id)).get((group, component), 0)
        if open_units is None:
            open_units = 0
            if facility.type == "BLOOD_BANK":
                open_units = sum(
                    r.units
                    for r in await self._open_at(facility.id)
                    if r.blood_group == group and r.component == component
                )
        return E.pressure(stock, open_units, self._mean(facility, group, component))

    @staticmethod
    def _row(group: str, component: str, p: E.Pressure) -> PressureRow:
        return PressureRow(
            blood_group=group,
            component=component,
            level=p.level,
            stock=p.stock,
            open_units=p.open_units,
            free_stock=p.free_stock,
            forecast_daily_mean=p.forecast_daily_mean,
            coverage_days=p.coverage_days,
            reasons=_reasons(p.reasons),
        )

    # ------------------------------------------------------------------ scope

    def _is_admin(self, ctx: AuthContext) -> bool:
        return ctx.role is Role.ADMIN and ctx.has(Permission.NETWORK_READ)

    def _require_facility_reader(self, ctx: AuthContext) -> UUID:
        if not ctx.has(Permission.OPERATIONS_READ) or ctx.facility_id is None:
            raise PermissionDeniedError()
        return ctx.facility_id

    async def _visible_request(self, ctx: AuthContext, request_id: UUID) -> BloodRequest:
        req = await self._uow.requests.get(request_id)
        if req is None:
            raise NotFoundError("Blood request not found")
        if self._is_admin(ctx):
            return req
        facility_id = self._require_facility_reader(ctx)
        if facility_id not in (req.hospital_id, req.target_facility_id):
            raise NotFoundError("Blood request not found")
        return req

    # ------------------------------------------------------------------ priority

    async def _priority(self, ctx: AuthContext, req: BloodRequest) -> PriorityOut:
        now = self._clock.now()
        viewer = _viewer(ctx)
        # The bank that holds the stock (and admins) see exact facts; a hospital sees bands.
        bank_view = req.target_facility_id is not None and (
            viewer == "admin" or ctx.facility_id == req.target_facility_id
        )
        pressure_level: E.PressureLevel | None = None
        if req.target_facility_id is not None and req.provider == "internal":
            stock = await self._stock_for(
                req.target_facility_id, req.blood_group, req.component, req.units
            )
            if bank_view:
                facts = stock.facts
                bank = await self.facility(req.target_facility_id)
                if bank is not None:
                    pressure_level = (
                        await self.pressure_for(bank, req.blood_group, req.component)
                    ).level
            else:
                facts = E.StockFacts(
                    usable=None,
                    usable_without_concern=None,
                    flagged=None,
                    expiring_soon=None,
                    availability_band=availability_band(len(stock.candidates), req.units),
                )
        else:
            facts = E.StockFacts(None, None, None, None, None)
        p = E.priority(
            E.RequestFacts(
                urgency=req.urgency,
                status=req.status,
                units=req.units,
                created_at=req.created_at,
                needed_by=req.needed_by,
                provider=req.provider,
            ),
            now=now,
            stock=facts,
            pressure_level=pressure_level,
            viewer="bank" if bank_view and viewer == "bank" else viewer,
        )
        return PriorityOut(
            request_id=req.id,
            reference=req.reference,
            score=p.score,
            band=p.band,
            recommendation=p.action,
            action_code=p.action_code,
            reasons=_reasons(p.reasons),
            computed_at=now,
        )

    async def route_for(self, req: BloodRequest) -> RouteOut | None:
        """Route for a request. A live (Phase 7) shipment's ETA wins over the estimate, so the
        Operations view and the shipment never disagree. Otherwise the estimate is anchored to
        the dispatch time (not "now"), so a dispatched request's ETA doesn't drift hourly."""
        src = await self.facility(req.target_facility_id)
        dst = await self.facility(req.hospital_id)
        if src is None or dst is None:
            return None
        shipment = await self._uow.shipments.for_request(req.id)
        if shipment is not None:
            return self._shipment_route(src, dst, req.urgency, shipment)
        at = req.updated_at if req.status == "dispatched" else None
        return self._route_out(src, dst, req.urgency, at=at)

    def _shipment_route(
        self, src: Facility, dst: Facility, urgency: str, shipment: Shipment
    ) -> RouteOut:
        now = self._clock.now()
        remaining = max(0, round((shipment.eta_at - now).total_seconds() / 60))
        done = shipment.status in ("arrived", "received")
        status: Literal["clear", "slow", "delayed"] = (
            "delayed" if shipment.delay_active or (not done and now > shipment.eta_at) else "clear"
        )
        reasons = [
            E.Reason(
                "live_shipment",
                f"Live simulated shipment {shipment.reference} ({shipment.status}); "
                f"{shipment.distance_km} km schematic route",
            )
        ]
        if shipment.delay_minutes:
            reasons.append(
                E.Reason(
                    "shipment_delay",
                    f"Includes +{shipment.delay_minutes} min simulated delay",
                    tone="attention",
                )
            )
        return RouteOut(
            source_facility_id=src.id,
            source_name=src.name,
            destination_facility_id=dst.id,
            destination_name=dst.name,
            urgency=urgency,
            distance_km=shipment.distance_km,
            travel_minutes=remaining,
            handover_minutes=0,
            eta_minutes=0 if done else remaining,
            status=status,
            reasons=_reasons(reasons),
            source=SourceMeta(
                provider="veyra-logistics-sim",
                kind=SourceKind.SIMULATED,
                fetched_at=now,
                note=E.ROUTING_LABEL + ". Live simulated shipment ETA (minutes remaining).",
            ),
        )

    def _route_out(
        self, src: Facility, dst: Facility, urgency: str, *, at: datetime | None = None
    ) -> RouteOut:
        now = self._clock.now()
        r = E.simulated_route(
            _place(src), _place(dst), urgency, hour_bucket=int((at or now).timestamp() // 3600)
        )
        return RouteOut(
            source_facility_id=src.id,
            source_name=src.name,
            destination_facility_id=dst.id,
            destination_name=dst.name,
            urgency=urgency,
            distance_km=r.distance_km,
            travel_minutes=r.travel_minutes,
            handover_minutes=r.handover_minutes,
            eta_minutes=r.eta_minutes,
            status=r.status,
            reasons=_reasons(r.reasons),
            source=SourceMeta(
                provider="veyra-routing-sim",
                kind=SourceKind.SIMULATED,
                fetched_at=now,
                note=E.ROUTING_LABEL + ". Schematic distances; no GPS, maps or traffic data.",
            ),
        )

    async def _ops_request(self, ctx: AuthContext, req: BloodRequest) -> OpsRequest:
        now = self._clock.now()
        return OpsRequest(
            id=req.id,
            reference=req.reference,
            hospital_id=req.hospital_id,
            hospital_name=await self._name(req.hospital_id),
            target_facility_id=req.target_facility_id,
            target_name=req.target_name,
            provider=req.provider,
            blood_group=req.blood_group,
            component=req.component,
            units=req.units,
            urgency=req.urgency,
            status=req.status,
            requested_at=req.created_at,
            needed_by=req.needed_by,
            age_minutes=max(0, int((now - req.created_at).total_seconds() // 60)),
            priority=await self._priority(ctx, req),
            route=await self.route_for(req) if req.status == "dispatched" else None,
        )

    # ------------------------------------------------------------------ endpoints

    async def list_requests(self, ctx: AuthContext) -> OpsRequestList:
        if self._is_admin(ctx):
            scope: Literal["facility", "network"] = "network"
            rows, _ = await self._uow.requests.list_page(
                hospital_id=None, target_facility_id=None, status=None, limit=LIST_LIMIT, offset=0
            )
        else:
            facility_id = self._require_facility_reader(ctx)
            scope = "facility"
            hospital = ctx.role is Role.HOSPITAL
            rows, _ = await self._uow.requests.list_page(
                hospital_id=facility_id if hospital else None,
                target_facility_id=None if hospital else facility_id,
                status=None,
                limit=LIST_LIMIT,
                offset=0,
            )
        now = self._clock.now()
        week_ago = now - timedelta(days=7)
        active = [r for r in rows if r.status in (*OPEN_STATUSES, "dispatched")]
        out = [await self._ops_request(ctx, r) for r in active]
        out.sort(key=lambda o: (-o.priority.score, o.requested_at))
        counts = {
            "open": sum(1 for r in rows if r.status in OPEN_STATUSES),
            "emergency_open": sum(
                1 for r in rows if r.status in OPEN_STATUSES and r.urgency == "emergency"
            ),
            "dispatched": sum(1 for r in rows if r.status == "dispatched"),
            "expected_units": sum(r.units for r in rows if r.status == "dispatched"),
            "received_units_7d": sum(
                r.units for r in rows if r.status == "fulfilled" and r.updated_at >= week_ago
            ),
        }
        return OpsRequestList(scope=scope, requests=out, counts=counts, generated_at=now)

    async def priority(self, ctx: AuthContext, request_id: UUID) -> PriorityOut:
        return await self._priority(ctx, await self._visible_request(ctx, request_id))

    async def recommendations(self, ctx: AuthContext, request_id: UUID) -> Recommendation:
        if not ctx.has(Permission.ALLOCATION_RECOMMEND) or ctx.facility_id is None:
            raise PermissionDeniedError()
        req = await self._uow.requests.get(request_id)
        if req is None or req.target_facility_id != ctx.facility_id:
            raise NotFoundError("Blood request not found")
        bank = await self.facility(ctx.facility_id)
        if bank is None:  # pragma: no cover - membership guarantees the facility
            raise NotFoundError("Facility not found")
        now = self._clock.now()
        stock = await self._stock_for(bank.id, req.blood_group, req.component, req.units)
        devices = {d.bag_id: d for d, _ in await self._device_rows_at(bank.id)}
        by_public = {b.public_id: b for b in stock.bags}
        candidates: list[CandidateBag] = []
        for c in stock.candidates:
            bag = by_public[c.bag.public_id]
            dev = devices.get(bag.id)
            candidates.append(
                CandidateBag(
                    rank=c.rank,
                    public_id=c.bag.public_id,
                    blood_group=c.bag.blood_group,
                    component=c.bag.component,
                    expires_at=c.bag.expires_at,
                    expires_in_hours=round((c.bag.expires_at - now).total_seconds() / 3600, 1),
                    fefo_position=c.fefo_position,
                    cold_chain_state=c.cold,
                    device_id=dev.device_id if dev else None,
                    latest_temperature_c=dev.last_temperature_c if dev else None,
                    current_facility_id=bank.id,
                    current_facility_name=bank.name,
                    recommended=c.recommended,
                    deprioritized=c.deprioritized,
                    reasons=_reasons(c.reasons),
                )
            )
        recommended = [c.public_id for c in candidates if c.recommended]
        fefo = [b.public_id for b in stock.bags[: req.units]]
        priority = await self._priority(ctx, req)
        if req.status != "pending":
            text = priority.recommendation
        elif len(recommended) >= req.units:
            same = recommended == fefo
            text = (
                f"Dispatch {', '.join(recommended)}"
                + (
                    " (same as strict FEFO)"
                    if same
                    else " (FEFO, skipping bags with cold-chain concerns)"
                )
                + " — after your review."
            )
        else:
            text = priority.recommendation
        pressure = await self.pressure_for(bank, req.blood_group, req.component)
        return Recommendation(
            request_id=req.id,
            reference=req.reference,
            status=req.status,
            units=req.units,
            blood_group=req.blood_group,
            component=req.component,
            recommendation=text,
            recommended_bag_ids=recommended if len(recommended) >= req.units else [],
            fefo_default_bag_ids=fefo,
            candidates=candidates,
            compatibility_rule=COMPATIBILITY_RULE,
            priority=priority,
            pressure=self._row(req.blood_group, req.component, pressure),
            route=await self.route_for(req),
            human_confirmation=HUMAN_CONFIRMATION,
            generated_at=now,
        )

    async def facility_pressure(self, ctx: AuthContext, facility_id: UUID) -> FacilityPressure:
        if not self._is_admin(ctx):
            own = self._require_facility_reader(ctx)
            if facility_id != own:
                raise NotFoundError("Facility not found")
        facility = await self.facility(facility_id)
        if facility is None or facility.status != "active":
            raise NotFoundError("Facility not found")
        on_hand = await self._on_hand(facility.id)
        keys = [(g, c) for c in FORECAST_COMPONENTS for g in FORECAST_GROUPS]
        opened: dict[tuple[str, str], int] = {}
        if facility.type == "BLOOD_BANK":
            for r in await self._open_at(facility.id):
                opened[(r.blood_group, r.component)] = (
                    opened.get((r.blood_group, r.component), 0) + r.units
                )
        for extra in sorted({*on_hand, *opened} - set(keys)):
            keys.append(extra)
        rows = []
        for group, component in keys:
            p = await self.pressure_for(
                facility,
                group,
                component,
                stock=on_hand.get((group, component), 0),
                open_units=opened.get((group, component), 0),
            )
            rows.append(self._row(group, component, p))
        order = {"elevated": 0, "watch": 1, "normal": 2}
        rows.sort(key=lambda r: (order[r.level], r.component, r.blood_group))
        counts = {"normal": 0, "watch": 0, "elevated": 0}
        for row in rows:
            counts[row.level] += 1
        return FacilityPressure(
            facility_id=facility.id,
            facility_name=facility.name,
            facility_type=facility.type,
            horizon_days=7,
            rows=rows,
            counts=counts,
            generated_at=self._clock.now(),
            source=SourceMeta(
                provider=f"{self._model.name}@{self._model.version}",
                kind=SourceKind.SYNTHETIC,
                fetched_at=self._clock.now(),
                note=E.FORECAST_INPUT_LABEL + ". Stock and open requests are real VEYRA data.",
            ),
        )

    async def route(
        self, ctx: AuthContext, *, source_id: UUID, destination_id: UUID, urgency: str
    ) -> RouteOut:
        if not self._is_admin(ctx):
            own = self._require_facility_reader(ctx)
            if own not in (source_id, destination_id):
                raise NotFoundError("Facility not found")
        src, dst = await self.facility(source_id), await self.facility(destination_id)
        if src is None or dst is None or src.status != "active" or dst.status != "active":
            raise NotFoundError("Facility not found")
        return self._route_out(src, dst, urgency)

    async def routing_overview(self, ctx: AuthContext) -> RoutingOverview:
        if self._is_admin(ctx):
            scope: Literal["facility", "network"] = "network"
            rows, _ = await self._uow.requests.list_page(
                hospital_id=None,
                target_facility_id=None,
                status="dispatched",
                limit=LIST_LIMIT,
                offset=0,
            )
        else:
            fid = self._require_facility_reader(ctx)
            scope = "facility"
            hospital = ctx.role is Role.HOSPITAL
            rows, _ = await self._uow.requests.list_page(
                hospital_id=fid if hospital else None,
                target_facility_id=None if hospital else fid,
                status="dispatched",
                limit=LIST_LIMIT,
                offset=0,
            )
        routes = []
        for req in rows:
            r = await self.route_for(req)
            if r is not None:
                shipment = await self._uow.shipments.for_request(req.id)
                routes.append(
                    ActiveRoute(
                        request_id=req.id,
                        reference=req.reference,
                        dispatched_at=req.updated_at,
                        expected_at=(
                            shipment.eta_at
                            if shipment is not None
                            else req.updated_at + timedelta(minutes=r.eta_minutes)
                        ),
                        route=r,
                    )
                )
        return RoutingOverview(scope=scope, routes=routes, generated_at=self._clock.now())

    async def alerts(self, ctx: AuthContext) -> AlertsOut:
        now = self._clock.now()
        admin = self._is_admin(ctx)
        fid = None if admin else self._require_facility_reader(ctx)
        alerts: list[AlertOut] = []
        # Emergency requests that are still open.
        requests = await self.list_requests(ctx)
        for r in requests.requests:
            if r.urgency == "emergency" and r.status in OPEN_STATUSES:
                alerts.append(
                    AlertOut(
                        kind="emergency_request",
                        severity="warning",
                        title=f"Emergency request {r.reference}",
                        detail=(
                            f"{r.units} x {r.blood_group} {r.component} · "
                            f"{r.priority.recommendation}"
                        ),
                        ref=str(r.id),
                        facility_name=r.hospital_name
                        if ctx.role is not Role.HOSPITAL
                        else r.target_name,
                        at=r.requested_at,
                    )
                )
        # Cold chain (Phase 5 simulated telemetry) at the facility / network.
        for d, bag in await self._device_rows_at(fid):
            if bag.status not in ("available", "in_transit", "received"):
                continue
            state = E.cold_state(_device_view(d, now))
            if state in ("warning", "critical"):
                alerts.append(
                    AlertOut(
                        kind="cold_chain",
                        severity="warning" if state == "critical" else "attention",
                        title=f"Cold-chain {state}: {bag.public_id}",
                        detail=E.COLD_REASON[state].text,
                        ref=bag.public_id,
                        facility_name=await self._name(bag.current_facility_id),
                        at=d.last_seen_at,
                    )
                )
            elif state == "stale":
                alerts.append(
                    AlertOut(
                        kind="device_stale",
                        severity="attention",
                        title=f"Device offline/stale: {bag.public_id}",
                        detail=E.COLD_REASON["stale"].text,
                        ref=bag.public_id,
                        facility_name=await self._name(bag.current_facility_id),
                        at=d.last_seen_at,
                    )
                )
        # Bags expiring soon and pressure rows (own facility only; admins get counts below).
        if fid is not None:
            facility = await self.facility(fid)
            if facility is not None and facility.type == "BLOOD_BANK":
                for bag in await self._uow.bags.list_usable(
                    fid, now=now, expires_before=now + E.EXPIRY_SOON, limit=50
                ):
                    alerts.append(
                        AlertOut(
                            kind="expiring",
                            severity="attention",
                            title=f"Expires soon: {bag.public_id}",
                            detail=(
                                f"{bag.blood_group} {bag.component} expires within 72 h"
                                " — use first (FEFO)"
                            ),
                            ref=bag.public_id,
                            facility_name=facility.name,
                            at=bag.expires_at,
                        )
                    )
            pressure = await self.facility_pressure(ctx, fid)
            elevated = [r for r in pressure.rows if r.level == "elevated"]
            if elevated:
                # One summary alert (an empty facility would otherwise raise 24).
                shown = ", ".join(f"{r.blood_group} {r.component}" for r in elevated[:3])
                more = f" and {len(elevated) - 3} more" if len(elevated) > 3 else ""
                alerts.append(
                    AlertOut(
                        kind="pressure",
                        severity="attention",
                        title=f"Elevated pressure on {len(elevated)} group/component rows",
                        detail=f"{shown}{more} — real stock and open requests vs the synthetic "
                        "forecast input",
                        ref=f"{elevated[0].blood_group}/{elevated[0].component}",
                        facility_name=pressure.facility_name,
                    )
                )
        elif admin:
            for bank in [
                f for f in await self._uow.stats.active_facilities() if f.type == "BLOOD_BANK"
            ]:
                pressure = await self.facility_pressure(ctx, bank.id)
                n = pressure.counts["elevated"]
                if n:
                    alerts.append(
                        AlertOut(
                            kind="pressure",
                            severity="attention",
                            title=f"{bank.name}: {n} elevated pressure rows",
                            detail="Real stock and open requests vs the synthetic forecast input",
                            ref=str(bank.id),
                            facility_name=bank.name,
                        )
                    )
        counts: dict[str, int] = {}
        for a in alerts:
            counts[a.kind] = counts.get(a.kind, 0) + 1
        sev = {"warning": 0, "attention": 1}
        alerts.sort(key=lambda a: (sev[a.severity], a.kind))
        return AlertsOut(
            scope="network" if admin else "facility", alerts=alerts, counts=counts, generated_at=now
        )

    # ------------------------------------------------------------------ the one mutation

    async def change_priority(
        self, ctx: AuthContext, request_id: UUID, body: ChangePriority
    ) -> PriorityOut:
        """The requesting hospital raises or lowers its own open request's priority."""
        req = await self._uow.requests.get(request_id)
        if req is None or ctx.facility_id is None or req.hospital_id != ctx.facility_id:
            raise NotFoundError("Blood request not found")
        if req.status not in OPEN_STATUSES:
            raise InvalidPriorityChangeError(f"A '{req.status}' request's priority can't change.")
        if req.urgency == body.urgency:
            raise InvalidPriorityChangeError(f"The request is already '{req.urgency}'.")
        previous = req.urgency
        now = self._clock.now()
        req.urgency = body.urgency
        req.updated_at = now
        await record(
            self._uow,
            self._clock,
            action="blood_request.priority_changed",
            resource="blood_request",
            resource_id=req.id,
            actor_id=ctx.user_id,
            meta={"from": previous, "to": body.urgency, "reason": body.reason},
        )
        # Priority never changes stock or open units, so pressure is unaffected here.
        await emit_priority_events(self._uow, self._clock, req, previous=previous)
        await self._uow.commit()
        return await self._priority(ctx, req)


# ---------------------------------------------------------------- events (outbox → SSE)


def request_payload(req: BloodRequest) -> dict[str, object]:
    """Facility ids and request facts only: never donor, patient or user data."""
    return {
        "request_id": str(req.id),
        "reference": req.reference,
        "hospital_id": str(req.hospital_id),
        "target_facility_id": str(req.target_facility_id) if req.target_facility_id else None,
        "status": req.status,
        "urgency": req.urgency,
        "blood_group": req.blood_group,
        "component": req.component,
        "units": req.units,
        "label": E.OPS_LABEL,
    }


async def emit_priority_events(
    uow: UnitOfWork, clock: Clock, req: BloodRequest, *, previous: str | None
) -> None:
    audience = [req.hospital_id, req.target_facility_id]
    payload = request_payload(req)
    if previous is not None:
        await emit(
            uow,
            clock,
            topic="request.priority_changed",
            aggregate_type="blood_request",
            aggregate_id=str(req.id),
            audience=audience,
            payload=payload | {"previous_urgency": previous},
        )
    if req.urgency == "emergency":
        await emit(
            uow,
            clock,
            topic="request.operational_alert",
            aggregate_type="blood_request",
            aggregate_id=str(req.id),
            audience=audience,
            payload=payload | {"alert": "Emergency request — review operational recommendation"},
        )
    if req.target_facility_id is not None and req.provider == "internal":
        await emit(
            uow,
            clock,
            topic="allocation.recommendation_updated",
            aggregate_type="blood_request",
            aggregate_id=str(req.id),
            audience=[req.target_facility_id],
            payload=payload,
        )


async def emit_pressure_if_changed(
    ops: OperationsService,
    bank: Facility,
    group: str,
    component: str,
    *,
    after_open_adjust: int = 0,
    open_delta: int = 0,
    stock_delta: int = 0,
) -> None:
    """Emit ``forecast.pressure_changed`` only when the pressure level actually changes.

    The current state is read from the database; ``after_open_adjust`` corrects it to the
    state after the change (e.g. a request still pending that is being dispatched). The
    deltas describe what the change added: before = after - delta.
    """
    now_state = await ops.pressure_for(bank, group, component)
    after = E.pressure(
        now_state.stock, now_state.open_units + after_open_adjust, now_state.forecast_daily_mean
    )
    before = E.pressure(
        after.stock - stock_delta, after.open_units - open_delta, after.forecast_daily_mean
    )
    if before.level == after.level:
        return
    await emit(
        ops.uow,
        ops.clock,
        topic="forecast.pressure_changed",
        aggregate_type="facility",
        aggregate_id=str(bank.id),
        audience=[bank.id],
        payload={
            "facility_id": str(bank.id),
            "blood_group": group,
            "component": component,
            "previous_level": before.level,
            "level": after.level,
            "coverage_days": after.coverage_days,
            "label": E.FORECAST_INPUT_LABEL,
        },
    )


async def on_request_created(ops: OperationsService, req: BloodRequest) -> None:
    """Emergency requests raise an operational alert and a recommendation update."""
    if req.urgency != "emergency":
        return  # routine/urgent keep exactly the Phase 2 event stream
    await emit_priority_events(ops.uow, ops.clock, req, previous=None)
    if req.target_facility_id is not None and req.provider == "internal":
        bank = await ops.facility(req.target_facility_id)
        if bank is not None:
            await emit_pressure_if_changed(
                ops, bank, req.blood_group, req.component, open_delta=req.units
            )


async def on_request_dispatched(ops: OperationsService, req: BloodRequest, bags: int) -> None:
    """Emergency dispatches publish a simulated ETA and any pressure-level change."""
    if req.urgency != "emergency" or req.target_facility_id is None:
        return
    route = await ops.route_for(req)
    if route is not None:
        await emit(
            ops.uow,
            ops.clock,
            topic="routing.updated",
            aggregate_type="blood_request",
            aggregate_id=str(req.id),
            audience=[req.hospital_id, req.target_facility_id],
            payload=request_payload(req)
            | {
                "eta_minutes": route.eta_minutes,
                "distance_km": route.distance_km,
                "route_status": route.status,
                "simulated": True,
                "label": E.ROUTING_LABEL,
            },
        )
    bank = await ops.facility(req.target_facility_id)
    if bank is not None:
        # Called while the request is still pending: it leaves the open set with this dispatch.
        await emit_pressure_if_changed(
            ops,
            bank,
            req.blood_group,
            req.component,
            after_open_adjust=-req.units,
            open_delta=-req.units,
            stock_delta=-bags,
        )
