"""Simulated smart-bag telemetry and cold-chain tracking (Phase 5).

- Reads: any caller who may trace the bag (its custody chain, or a network admin). Others
  get the same 404 as the bag trace, so existence is never disclosed.
- Simulator controls: only the facility that currently HOLDS the bag, only when the
  simulator is enabled (never in production), CSRF-protected and audited.
- Cold-chain transitions (warning/critical start, escalation, recovery) are appended to
  the bag's existing hash-chained trace and emitted through the transactional outbox.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from app.core.clock import Clock
from app.core.errors import NotFoundError, PermissionDeniedError
from app.core.ids import uuid7
from app.core.provenance import SourceKind, SourceMeta
from app.core.rbac import AuthContext, Permission, Role
from app.modules.audit.service import record
from app.modules.bags.domain import BagEventType, BagStatus
from app.modules.bags.models import BagEvent, BloodBag
from app.modules.bags.service import BagService, append_event, require_facility, verify_chain
from app.modules.outbox.service import emit
from app.modules.telemetry.errors import (
    DeviceUnavailableError,
    NoDeviceError,
    SimulatorDisabledError,
)
from app.modules.telemetry.models import TelemetryDevice, TelemetryReading
from app.modules.telemetry.rules import (
    BATTERY_DRAIN_PER_READING,
    RULES,
    classify,
    device_status,
    initial_battery,
    new_device_identity,
    simulated_temperature,
)
from app.modules.telemetry.schemas import (
    TELEMETRY_DISCLAIMER,
    ColdChainEvent,
    ColdChainReport,
    DeviceOut,
    ExcursionOut,
    MonitoredBag,
    MonitoredList,
    ReadingOut,
    SimulatorResult,
    TelemetrySeries,
    TelemetrySummary,
    ThresholdsOut,
)
from app.persistence.repositories import UnitOfWork

COLD_CHAIN_EVENTS = frozenset(
    {BagEventType.DEVICE_ATTACHED, BagEventType.TEMP_EXCURSION, BagEventType.TEMP_RECOVERED}
)
MAX_READINGS = 500


def thresholds(component: str) -> ThresholdsOut:
    r = RULES[component]
    return ThresholdsOut(
        label=r.label,
        nominal_c=r.nominal_c,
        normal_low=r.normal_low,
        normal_high=r.normal_high,
        critical_low=r.critical_low,
        critical_high=r.critical_high,
    )


def source(now: datetime) -> SourceMeta:
    return SourceMeta(
        provider="veyra-telemetry-simulator",
        kind=SourceKind.SIMULATED,
        fetched_at=now,
        note=TELEMETRY_DISCLAIMER,
    )


def excursions(readings: list[TelemetryReading], component: str) -> list[ExcursionOut]:
    """Group consecutive non-normal readings into excursions (the last may be ongoing)."""
    nominal = RULES[component].nominal_c
    out: list[ExcursionOut] = []
    run: list[TelemetryReading] = []

    def close(end: TelemetryReading | None) -> None:
        start = run[0]
        last = end or run[-1]
        peak = max(run, key=lambda r: abs(r.temperature_c - nominal))
        out.append(
            ExcursionOut(
                started_at=start.recorded_at,
                ended_at=end.recorded_at if end else None,
                duration_seconds=int((last.recorded_at - start.recorded_at).total_seconds()),
                severity="critical" if any(r.status == "critical" for r in run) else "warning",
                peak_c=peak.temperature_c,
                readings=len(run),
            )
        )

    for r in readings:
        if r.status != "normal":
            run.append(r)
        elif run:
            close(r)
            run = []
    if run:
        close(None)
    return out


class TelemetryService:
    def __init__(self, uow: UnitOfWork, clock: Clock, *, simulator_enabled: bool) -> None:
        self._uow = uow
        self._clock = clock
        self._simulator_enabled = simulator_enabled
        self._bags = BagService(uow, clock)

    # ------------------------------------------------------------------ helpers

    async def _visible(self, ctx: AuthContext, public_id: str) -> tuple[BloodBag, list[BagEvent]]:
        return await self._bags.visible_bag(ctx, public_id)

    async def _device(self, bag: BloodBag, *, lock: bool = False) -> TelemetryDevice:
        device = await self._uow.telemetry.device_for_bag(bag.id, lock=lock)
        if device is None:
            raise NoDeviceError()
        return device

    def _device_out(self, device: TelemetryDevice, bag: BloodBag) -> DeviceOut:
        now = self._clock.now()
        return DeviceOut(
            public_id=bag.public_id,
            device_id=device.device_id,
            rfid=device.rfid,
            simulated=device.simulated,
            battery_pct=round(device.battery_pct, 1),
            device_status=device_status(
                device.battery_pct, device.last_seen_at, device.sim_running, now
            ),
            last_seen_at=device.last_seen_at,
            readings_count=device.readings_count,
            sim_running=device.sim_running,
            sim_mode=device.sim_mode,
            attached_at=device.attached_at,
            source=source(now),
        )

    async def _summary(self, device: TelemetryDevice, bag: BloodBag) -> TelemetrySummary:
        now = self._clock.now()
        lo, hi = await self._uow.telemetry.reading_range(device.id)
        active = device.excursion_started_at is not None
        return TelemetrySummary(
            public_id=bag.public_id,
            component=bag.component,
            device_id=device.device_id,
            cold_chain_status=device.cold_chain_status,
            device_status=device_status(
                device.battery_pct, device.last_seen_at, device.sim_running, now
            ),
            current_c=device.last_temperature_c,
            min_c=lo,
            max_c=hi,
            last_reading_at=device.last_seen_at,
            battery_pct=round(device.battery_pct, 1),
            readings_count=device.readings_count,
            excursion_active=active,
            excursion_started_at=device.excursion_started_at,
            excursion_duration_seconds=(
                int((now - device.excursion_started_at).total_seconds())
                if device.excursion_started_at
                else None
            ),
            excursion_severity=device.excursion_severity,
            thresholds=thresholds(bag.component),
            source=source(now),
        )

    # ------------------------------------------------------------------ reads

    async def device(self, ctx: AuthContext, public_id: str) -> DeviceOut:
        bag, _ = await self._visible(ctx, public_id)
        return self._device_out(await self._device(bag), bag)

    async def telemetry(self, ctx: AuthContext, public_id: str, limit: int) -> TelemetrySeries:
        bag, _ = await self._visible(ctx, public_id)
        device = await self._device(bag)
        readings = await self._uow.telemetry.readings(device.id, limit=limit)
        return TelemetrySeries(
            public_id=bag.public_id,
            component=bag.component,
            thresholds=thresholds(bag.component),
            readings=[
                ReadingOut(
                    seq=r.seq,
                    recorded_at=r.recorded_at,
                    temperature_c=r.temperature_c,
                    battery_pct=round(r.battery_pct, 1),
                    status=r.status,
                )
                for r in readings
            ],
            source=source(self._clock.now()),
        )

    async def summary(self, ctx: AuthContext, public_id: str) -> TelemetrySummary:
        bag, _ = await self._visible(ctx, public_id)
        return await self._summary(await self._device(bag), bag)

    async def cold_chain(self, ctx: AuthContext, public_id: str) -> ColdChainReport:
        bag, events = await self._visible(ctx, public_id)
        device = await self._device(bag)
        readings = await self._uow.telemetry.readings(device.id, limit=MAX_READINGS)
        return ColdChainReport(
            public_id=bag.public_id,
            component=bag.component,
            cold_chain_status=device.cold_chain_status,
            thresholds=thresholds(bag.component),
            excursions=excursions(readings, bag.component),
            trace_events=[
                ColdChainEvent(
                    seq=e.seq,
                    event_type=e.event_type,
                    occurred_at=e.occurred_at,
                    meta=dict(e.meta),
                    row_hash=e.row_hash,
                )
                for e in events
                if e.event_type in COLD_CHAIN_EVENTS
            ],
            chain_valid=verify_chain(events).valid,
            source=source(self._clock.now()),
        )

    async def monitored(self, ctx: AuthContext) -> MonitoredList:
        is_admin = ctx.role is Role.ADMIN and ctx.has(Permission.NETWORK_READ)
        facility_id = None if is_admin else require_facility(ctx)
        now = self._clock.now()
        rows: list[MonitoredBag] = []
        counts = {k: 0 for k in ("normal", "warning", "critical", "offline", "paused", "awaiting")}
        for device, bag in await self._uow.telemetry.devices_at(facility_id):
            dstatus = device_status(
                device.battery_pct, device.last_seen_at, device.sim_running, now
            )
            rows.append(
                MonitoredBag(
                    public_id=bag.public_id,
                    blood_group=bag.blood_group,
                    component=bag.component,
                    bag_status=bag.status,
                    device_id=device.device_id,
                    device_status=dstatus,
                    cold_chain_status=device.cold_chain_status,
                    current_c=device.last_temperature_c,
                    last_reading_at=device.last_seen_at,
                    battery_pct=round(device.battery_pct, 1),
                    excursion_duration_seconds=(
                        int((now - device.excursion_started_at).total_seconds())
                        if device.excursion_started_at
                        else None
                    ),
                    sim_running=device.sim_running,
                )
            )
            if dstatus in ("offline", "paused", "awaiting"):
                counts[dstatus] += 1
            if device.cold_chain_status in ("normal", "warning", "critical"):
                counts[device.cold_chain_status] += 1
        return MonitoredList(
            scope="network" if is_admin else "facility",
            counts=counts,
            bags=rows,
            simulator_enabled=self._simulator_enabled,
            source=source(now),
        )

    # ------------------------------------------------------------------ simulator

    async def _held(self, ctx: AuthContext, public_id: str) -> BloodBag:
        if not self._simulator_enabled:
            raise SimulatorDisabledError()
        if not ctx.has(Permission.TELEMETRY_SIMULATE):
            raise PermissionDeniedError()
        facility_id = require_facility(ctx)
        bag = await self._uow.bags.get_by_public_id(public_id.strip().upper())
        if bag is None or bag.current_facility_id != facility_id:
            raise NotFoundError("Blood bag not found")  # only the current holder drives it
        return bag

    async def _result(
        self, device: TelemetryDevice, bag: BloodBag, generated: int, transitions: list[str]
    ) -> SimulatorResult:
        return SimulatorResult(
            device=self._device_out(device, bag),
            summary=await self._summary(device, bag),
            generated=generated,
            transitions=transitions,
        )

    async def attach(self, ctx: AuthContext, public_id: str) -> SimulatorResult:
        bag = await self._held(ctx, public_id)
        if bag.status == BagStatus.DISCARDED.value:
            raise DeviceUnavailableError("A discarded bag can't be monitored.")
        now = self._clock.now()
        device_id, rfid = new_device_identity(bag.public_id)
        device = TelemetryDevice(
            id=uuid7(),
            device_id=device_id,
            rfid=rfid,
            bag_id=bag.id,
            simulated=True,
            battery_pct=initial_battery(device_id),
            last_seen_at=None,
            readings_count=0,
            last_temperature_c=None,
            sim_running=False,
            sim_mode="normal",
            sim_mode_step=0,
            cold_chain_status="unknown",
            excursion_started_at=None,
            excursion_severity=None,
            excursion_peak_c=None,
            attached_at=now,
            updated_at=now,
        )
        await self._uow.telemetry.add_device(device)
        await append_event(
            self._uow,
            bag,
            BagEventType.DEVICE_ATTACHED,
            at=now,
            actor_id=ctx.user_id,
            from_facility_id=bag.current_facility_id,
            to_facility_id=bag.current_facility_id,
            meta={"device_id": device_id, "simulated": True},
        )
        await self._audit(ctx, "telemetry.device_attached", bag, {"device_id": device_id})
        await self._uow.commit()
        return await self._result(device, bag, 0, ["DEVICE_ATTACHED"])

    async def set_running(self, ctx: AuthContext, public_id: str, running: bool) -> SimulatorResult:
        bag = await self._held(ctx, public_id)
        device = await self._device(bag, lock=True)
        device.sim_running = running
        device.updated_at = self._clock.now()
        await self._audit(ctx, "telemetry.simulator_" + ("started" if running else "paused"), bag)
        await self._uow.commit()
        return await self._result(device, bag, 0, [])

    async def set_mode(self, ctx: AuthContext, public_id: str, mode: str) -> SimulatorResult:
        """``excursion`` injects a warm excursion; ``recovering`` restores normal temperature."""
        bag = await self._held(ctx, public_id)
        device = await self._device(bag, lock=True)
        device.sim_mode = mode
        device.sim_mode_step = 0
        device.updated_at = self._clock.now()
        action = "excursion_injected" if mode == "excursion" else "recovery_started"
        await self._audit(ctx, f"telemetry.{action}", bag)
        await self._uow.commit()
        return await self._result(device, bag, 0, [])

    async def tick(self, ctx: AuthContext, public_id: str, count: int) -> SimulatorResult:
        bag = await self._held(ctx, public_id)
        device = await self._device(bag, lock=True)
        transitions: list[str] = []
        generated = 0
        for i in range(count):
            if device.battery_pct <= 0 or bag.status == BagStatus.DISCARDED.value:
                break
            at = self._clock.now() + timedelta(milliseconds=i)
            transitions += await take_reading(self._uow, self._clock, device, bag, at=at)
            generated += 1
        if generated == 0:
            raise DeviceUnavailableError("The device has no battery or the bag was discarded.")
        await self._audit(ctx, "telemetry.readings_generated", bag, {"count": generated})
        await self._uow.commit()
        return await self._result(device, bag, generated, transitions)

    async def _audit(
        self, ctx: AuthContext, action: str, bag: BloodBag, meta: dict[str, Any] | None = None
    ) -> None:
        await record(
            self._uow,
            self._clock,
            action=action,
            resource="bag",
            resource_id=bag.id,
            actor_id=ctx.user_id,
            meta={"simulated": True, **(meta or {})},
        )


async def _audience(uow: UnitOfWork, bag: BloodBag) -> list[UUID | None]:
    """Current holder, plus the destination while a bag is in transit."""
    audience: list[UUID | None] = [bag.current_facility_id]
    if bag.status == BagStatus.IN_TRANSIT.value:
        events = await uow.bags.list_events(bag.id)
        dispatched = [e for e in events if e.event_type == BagEventType.DISPATCHED.value]
        if dispatched:
            audience.append(dispatched[-1].to_facility_id)
    return audience


async def take_reading(
    uow: UnitOfWork, clock: Clock, device: TelemetryDevice, bag: BloodBag, *, at: datetime
) -> list[str]:
    """Generate one simulated reading and apply the cold-chain state machine.

    Returns the cold-chain transitions raised (``temperature.warning`` etc.).
    Shared by the manual ``tick`` control and the background simulator.
    """
    seq = device.readings_count + 1
    step = device.sim_mode_step + 1
    temp = simulated_temperature(
        device.device_id,
        bag.component,
        seq,
        device.sim_mode,  # type: ignore[arg-type]
        step,
        device.last_temperature_c,
    )
    status = classify(bag.component, temp)
    battery = max(0.0, round(device.battery_pct - BATTERY_DRAIN_PER_READING, 2))
    await uow.telemetry.add_reading(
        TelemetryReading(
            device_pk=device.id,
            bag_id=bag.id,
            seq=seq,
            recorded_at=at,
            temperature_c=temp,
            battery_pct=battery,
            status=status,
            simulated=True,
        )
    )
    previous = device.cold_chain_status
    device.readings_count = seq
    device.sim_mode_step = step
    device.last_seen_at = at
    device.last_temperature_c = temp
    device.battery_pct = battery
    device.updated_at = at
    if device.sim_mode == "recovering" and status == "normal":
        device.sim_mode, device.sim_mode_step = "normal", 0

    audience = await _audience(uow, bag)
    rule = RULES[bag.component]
    transitions: list[str] = []
    recovery_duration: int | None = None
    event_meta: dict[str, Any] = {"device_id": device.device_id, "temperature_c": temp}
    if status != "normal" and previous in ("unknown", "normal"):
        device.excursion_started_at = at
        device.excursion_severity = status
        device.excursion_peak_c = temp
        transitions.append(f"temperature.{status}")
        await _trace(uow, bag, at, BagEventType.TEMP_EXCURSION, event_meta | {"severity": status})
    elif status == "critical" and previous == "warning":
        device.excursion_severity = "critical"
        transitions.append("temperature.critical")
        await _trace(uow, bag, at, BagEventType.TEMP_EXCURSION, event_meta | {"severity": status})
    elif status == "normal" and previous in ("warning", "critical"):
        started = device.excursion_started_at or at
        duration = recovery_duration = int((at - started).total_seconds())
        transitions.append("temperature.recovered")
        await _trace(
            uow,
            bag,
            at,
            BagEventType.TEMP_RECOVERED,
            event_meta
            | {
                "duration_seconds": duration,
                "max_severity": device.excursion_severity or "warning",
                "peak_c": device.excursion_peak_c,
            },
        )
        device.excursion_started_at = None
        device.excursion_severity = None
        device.excursion_peak_c = None
    if status != "normal" and device.excursion_peak_c is not None:
        if abs(temp - rule.nominal_c) > abs(device.excursion_peak_c - rule.nominal_c):
            device.excursion_peak_c = temp
    device.cold_chain_status = status

    payload = {
        "public_id": bag.public_id,
        "device_id": device.device_id,
        "temperature_c": temp,
        "status": status,
        "battery_pct": battery,
        "recorded_at": at.isoformat(),
        "simulated": True,
    }
    for topic in transitions:
        extra: dict[str, Any] = {}
        if topic == "temperature.recovered":
            extra["duration_seconds"] = recovery_duration
        await emit(
            uow,
            clock,
            topic=topic,
            aggregate_type="bag",
            aggregate_id=bag.public_id,
            audience=audience,
            payload=payload | extra,
        )
    concern = next(
        (t for t in transitions if t in ("temperature.warning", "temperature.critical")), None
    )
    if concern is not None and bag.status in ("available", "in_transit"):
        # Phase 6: the bag is flagged (never discarded) in allocation recommendations.
        await emit(
            uow,
            clock,
            topic="cold_chain.operational_alert",
            aggregate_type="bag",
            aggregate_id=bag.public_id,
            audience=audience,
            payload=payload
            | {
                "blood_group": bag.blood_group,
                "component": bag.component,
                "bag_status": bag.status,
                "action": "Deprioritised in allocation recommendations; review before dispatch",
                "label": "Operational recommendation — prototype",
            },
        )
    await emit(
        uow,
        clock,
        topic="telemetry.updated",
        aggregate_type="bag",
        aggregate_id=bag.public_id,
        audience=audience,
        payload=payload,
    )
    return transitions


async def _trace(
    uow: UnitOfWork, bag: BloodBag, at: datetime, event: BagEventType, meta: dict[str, Any]
) -> None:
    await append_event(
        uow,
        bag,
        event,
        at=at,
        actor_id=None,  # the (simulated) device, not a person
        from_facility_id=bag.current_facility_id,
        to_facility_id=bag.current_facility_id,
        meta={k: v for k, v in meta.items() if v is not None},
    )
