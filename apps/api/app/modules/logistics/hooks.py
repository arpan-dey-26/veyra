"""Shipment state changes shared by the dispatch, receipt, telemetry and simulator paths.

Every change here: validates the explicit state machine, appends to the append-only shipment
timeline, adds observation events to each bag's hash-chained trace where the spec lists one,
and emits a scoped outbox event (source bank + destination hospital). No personal data.
"""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta
from typing import Any

from app.core.clock import Clock
from app.core.errors import AppError
from app.core.ids import uuid7
from app.modules.audit.service import record
from app.modules.bags.domain import BagEventType
from app.modules.bags.models import BloodBag
from app.modules.bags.service import append_event
from app.modules.logistics import engine as L
from app.modules.logistics.models import Shipment, ShipmentBag, ShipmentEvent
from app.modules.operations.engine import Place
from app.modules.outbox.service import emit
from app.modules.requests.models import BloodRequest
from app.persistence.repositories import UnitOfWork

_REF_CHARS = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"

TRACE_EVENT: dict[str, BagEventType] = {
    "SHIPMENT_CREATED": BagEventType.SHIPMENT_CREATED,
    "SHIPMENT_PICKED_UP": BagEventType.SHIPMENT_PICKED_UP,
    "SHIPMENT_IN_TRANSIT": BagEventType.SHIPMENT_IN_TRANSIT,
    "SHIPMENT_DELAYED": BagEventType.SHIPMENT_DELAYED,
    "SHIPMENT_ARRIVED": BagEventType.SHIPMENT_ARRIVED,
    "SHIPMENT_RECEIVED": BagEventType.SHIPMENT_RECEIVED,
}
SEVERITY = {"none": 0, "warning": 1, "critical": 2}


class InvalidShipmentTransitionError(AppError):
    status, code, title = 409, "invalid_shipment_transition", "The shipment can't do that now"


def new_reference() -> str:
    return "SH-" + "".join(secrets.choice(_REF_CHARS) for _ in range(8))


def shipment_payload(s: Shipment) -> dict[str, object]:
    """Operational facts only: facility ids, status, ETA. Never donor, patient or user data."""
    return {
        "shipment_id": str(s.id),
        "reference": s.reference,
        "request_id": str(s.request_id),
        "source_facility_id": str(s.source_facility_id),
        "destination_facility_id": str(s.destination_facility_id),
        "status": s.status,
        "urgency": s.urgency,
        "eta_at": s.eta_at.isoformat(),
        "current_checkpoint": s.current_checkpoint,
        "delay_minutes": s.delay_minutes,
        "delay_active": s.delay_active,
        "cold_chain_alert": s.cold_chain_alert,
        "simulated": True,
        "label": L.LOGISTICS_LABEL,
    }


async def _bags(uow: UnitOfWork, s: Shipment) -> list[BloodBag]:
    out = []
    for bag_id in await uow.shipments.bag_ids(s.id):
        bag = await uow.bags.get(bag_id)
        if bag is not None:
            out.append(bag)
    return out


async def record_event(
    uow: UnitOfWork,
    clock: Clock,
    s: Shipment,
    event_type: str,
    *,
    actor_id: Any,
    meta: dict[str, Any] | None = None,
    topic: str | None = None,
) -> None:
    """Timeline entry (+ trace observation for the listed types) (+ scoped SSE event)."""
    now = clock.now()
    seq = len(await uow.shipments.events(s.id)) + 1
    await uow.shipments.add_event(
        ShipmentEvent(
            shipment_id=s.id,
            seq=seq,
            event_type=event_type,
            status=s.status,
            occurred_at=now,
            actor_id=actor_id,
            meta=meta or {},
        )
    )
    if event_type in TRACE_EVENT:
        for bag in await _bags(uow, s):
            await append_event(
                uow,
                bag,
                TRACE_EVENT[event_type],
                at=now,
                actor_id=actor_id,
                from_facility_id=bag.current_facility_id,
                to_facility_id=s.destination_facility_id,
                meta={"shipment": s.reference, "simulated": True} | (meta or {}),
            )
    if topic is not None:
        await emit(
            uow,
            clock,
            topic=topic,
            aggregate_type="shipment",
            aggregate_id=str(s.id),
            audience=[s.source_facility_id, s.destination_facility_id],
            payload=shipment_payload(s) | {"event": event_type} | (meta or {}),
        )


def _require(s: Shipment, action: str) -> None:
    if not L.can(action, s.status):
        raise InvalidShipmentTransitionError(
            f"A '{s.status}' shipment can't {action.replace('_', ' ')}."
        )


def _touch(s: Shipment, now: datetime) -> None:
    s.last_update_at = now


# ---------------------------------------------------------------- creation (dispatch)


async def create_for_dispatch(
    uow: UnitOfWork, clock: Clock, req: BloodRequest, bags: list[BloodBag], *, actor_id: Any
) -> Shipment:
    """Human-confirmed dispatch → shipment ``created`` → courier assigned (``pickup_pending``)."""
    src = await uow.facilities.get(req.target_facility_id) if req.target_facility_id else None
    dst = await uow.facilities.get(req.hospital_id)
    if src is None or dst is None:  # pragma: no cover - internal requests always have both
        raise InvalidShipmentTransitionError("Shipments need an internal source and destination")
    now = clock.now()
    plan = L.plan_route(
        Place(str(src.id), src.name, src.city, src.state),
        Place(str(dst.id), dst.name, dst.city, dst.state),
        req.urgency,
        start=now,
    )
    courier = L.simulated_courier(str(req.id), req.urgency)
    s = Shipment(
        id=uuid7(),
        reference=new_reference(),
        request_id=req.id,
        source_facility_id=src.id,
        destination_facility_id=dst.id,
        status="created",
        status_before_delay=None,
        urgency=req.urgency,
        simulated=True,
        courier_id=courier.courier_id,
        courier_name=courier.name,
        vehicle_type=courier.vehicle_type,
        distance_km=plan.distance_km,
        planned_minutes=plan.handover_minutes + plan.travel_minutes,
        checkpoints=plan.checkpoints,
        current_checkpoint=-1,
        eta_at=now + timedelta(minutes=plan.handover_minutes + plan.travel_minutes),
        delay_minutes=0,
        delay_active=False,
        delay_reason=None,
        cold_chain_alert="none",
        last_update_at=now,
        created_at=now,
        picked_up_at=None,
        arrived_at=None,
        received_at=None,
    )
    await uow.shipments.add(s)
    for bag in bags:
        await uow.shipments.add_bag(ShipmentBag(shipment_id=s.id, bag_id=bag.id))
    await record_event(
        uow, clock, s, "SHIPMENT_CREATED", actor_id=actor_id,
        meta={"bags": len(bags), "route_status": plan.route_status}, topic="shipment.created",
    )  # fmt: skip
    s.status = "pickup_pending"
    await record_event(
        uow, clock, s, "COURIER_ASSIGNED", actor_id=None,
        meta={"courier_id": courier.courier_id, "vehicle_type": courier.vehicle_type},
    )  # fmt: skip
    await record(
        uow,
        clock,
        action="shipment.created",
        resource="shipment",
        resource_id=s.id,
        actor_id=actor_id,
        meta={"bags": len(bags), "simulated": True},
    )
    return s


# ---------------------------------------------------------------- simulated transport


async def apply(
    uow: UnitOfWork,
    clock: Clock,
    s: Shipment,
    action: str,
    *,
    actor_id: Any,
    minutes: int = 0,
    reason: str | None = None,
) -> list[str]:
    """One simulator action. Returns the SSE topics it raised."""
    now = clock.now()
    topics: list[str] = []
    if action == "advance":
        nxt = L.next_action(s.status, s.current_checkpoint)
        if nxt is None:
            if s.status == "delayed":
                raise InvalidShipmentTransitionError("The shipment is delayed — resume it first.")
            if s.status == "in_transit":
                raise InvalidShipmentTransitionError(
                    "The destination area is reached — use arrive."
                )
            raise InvalidShipmentTransitionError(f"A '{s.status}' shipment can't advance.")
        action = nxt
    _require(s, action)
    if action == "assign":
        s.status = "pickup_pending"
        await record_event(uow, clock, s, "COURIER_ASSIGNED", actor_id=actor_id)
    elif action == "pickup":
        s.status, s.current_checkpoint, s.picked_up_at = "picked_up", 0, now
        s.checkpoints = L.reach(L.replan(s.checkpoints, 0, now), 0, now)
        s.eta_at = L.destination_eta(s.checkpoints)
        await record_event(
            uow, clock, s, "SHIPMENT_PICKED_UP", actor_id=actor_id,
            meta={"checkpoint": 0}, topic="shipment.picked_up",
        )  # fmt: skip
        topics.append("shipment.picked_up")
    elif action in ("depart", "checkpoint"):
        seq = s.current_checkpoint + 1
        s.status, s.current_checkpoint = "in_transit", seq
        s.checkpoints = L.reach(L.replan(s.checkpoints, seq, now), seq, now)
        s.eta_at = L.destination_eta(s.checkpoints)
        meta = {"checkpoint": seq, "checkpoint_name": s.checkpoints[seq]["name"]}
        if action == "depart":
            await record_event(
                uow, clock, s, "SHIPMENT_IN_TRANSIT", actor_id=actor_id, meta=meta,
                topic="shipment.in_transit",
            )  # fmt: skip
            topics.append("shipment.in_transit")
        await record_event(
            uow, clock, s, "CHECKPOINT_REACHED", actor_id=actor_id, meta=meta,
            topic="shipment.checkpoint_reached",
        )  # fmt: skip
        topics.append("shipment.checkpoint_reached")
    elif action == "delay":
        s.status_before_delay, s.status = s.status, "delayed"
        s.delay_active, s.delay_reason = True, reason
        s.delay_minutes += minutes
        s.eta_at += timedelta(minutes=minutes)
        s.checkpoints = L.reschedule(s.checkpoints, s.current_checkpoint, minutes)
        await record_event(
            uow, clock, s, "SHIPMENT_DELAYED", actor_id=actor_id,
            meta={"minutes": minutes, "reason": reason}, topic="shipment.delayed",
        )  # fmt: skip
        topics.append("shipment.delayed")
    elif action == "resume":
        s.status = s.status_before_delay or "in_transit"
        s.status_before_delay, s.delay_active = None, False
        earliest = now + timedelta(minutes=L.remaining_travel(s.checkpoints, s.current_checkpoint))
        if earliest > s.eta_at:  # the delay lasted longer than announced: re-anchor to now
            s.checkpoints = L.replan(s.checkpoints, s.current_checkpoint, now)
            s.eta_at = L.destination_eta(s.checkpoints)
        await record_event(
            uow, clock, s, "SHIPMENT_RESUMED", actor_id=actor_id,
            meta={"total_delay_minutes": s.delay_minutes}, topic="shipment.resumed",
        )  # fmt: skip
        topics.append("shipment.resumed")
    elif action == "arrive":
        if s.current_checkpoint != L.LAST_WAYPOINT:
            raise InvalidShipmentTransitionError(
                "Advance through every checkpoint before arriving."
            )
        await _arrive(uow, clock, s, actor_id=actor_id, confirmed_at_receipt=False)
        topics.append("shipment.arrived")
    else:  # pragma: no cover - receive paths go through on_request_receipt
        raise InvalidShipmentTransitionError(f"Unknown action {action}")
    _touch(s, now)
    return topics


async def _arrive(
    uow: UnitOfWork, clock: Clock, s: Shipment, *, actor_id: Any, confirmed_at_receipt: bool
) -> None:
    now = clock.now()
    s.status, s.current_checkpoint, s.arrived_at = "arrived", L.DESTINATION, now
    s.status_before_delay, s.delay_active = None, False
    s.checkpoints = L.reach(
        s.checkpoints, L.DESTINATION, now, confirmed_at_receipt=confirmed_at_receipt
    )
    s.eta_at = now
    await record_event(
        uow, clock, s, "SHIPMENT_ARRIVED", actor_id=actor_id,
        meta={"confirmed_at_receipt": confirmed_at_receipt}, topic="shipment.arrived",
    )  # fmt: skip


# ---------------------------------------------------------------- receipt (existing workflow)


async def before_request_receipt(
    uow: UnitOfWork, clock: Clock, req: BloodRequest, *, actor_id: Any
) -> Shipment | None:
    """Called by the existing receive flow before the bags' RECEIVED events.

    An arrived shipment just proceeds. A shipment still in transport is marked arrived
    (``confirmed_at_receipt``): the person receiving confirms the bags physically arrived.
    """
    s = await uow.shipments.for_request(req.id)
    if s is None:
        return None
    _require(s, "confirm_receipt")
    if s.status != "arrived":
        await _arrive(uow, clock, s, actor_id=actor_id, confirmed_at_receipt=True)
    return s


async def after_request_receipt(
    uow: UnitOfWork, clock: Clock, s: Shipment | None, *, actor_id: Any
) -> None:
    if s is None:
        return
    now = clock.now()
    s.status, s.received_at = "received", now
    _touch(s, now)
    await record_event(
        uow, clock, s, "SHIPMENT_RECEIVED", actor_id=actor_id, topic="shipment.received"
    )
    await record(
        uow,
        clock,
        action="shipment.received",
        resource="shipment",
        resource_id=s.id,
        actor_id=actor_id,
        meta={"delay_minutes": s.delay_minutes},
    )


# ---------------------------------------------------------------- cold chain during transit


async def on_cold_chain_transition(
    uow: UnitOfWork, clock: Clock, bag: BloodBag, transition: str, payload: dict[str, Any]
) -> None:
    """A Phase 5 warning/critical/recovered reading on a bag that is in a shipment.

    The existing telemetry events are unchanged; this adds a logistics-scoped alert. The bag
    is never discarded or received automatically: it stays flagged for human review.
    """
    s = await uow.shipments.for_bag(bag.id)
    if s is None or s.status in L.TERMINAL or bag.status != "in_transit":
        return
    level = transition.removeprefix("temperature.")
    meta = {
        "bag": bag.public_id,
        "cold_chain_status": payload.get("status"),
        "temperature_c": payload.get("temperature_c"),
    }
    if level in ("warning", "critical"):
        if SEVERITY[level] > SEVERITY[s.cold_chain_alert]:
            s.cold_chain_alert = level
        _touch(s, clock.now())
        await record_event(
            uow, clock, s, f"COLD_CHAIN_{level.upper()}", actor_id=None,
            meta=meta | {"action": "Flagged for human review; nothing is discarded or received"},
            topic="shipment.cold_chain_alert",
        )  # fmt: skip
    elif level == "recovered":
        await record_event(
            uow, clock, s, "COLD_CHAIN_RECOVERED", actor_id=None,
            meta=meta | {"note": "Alert kept for review"},
        )  # fmt: skip
