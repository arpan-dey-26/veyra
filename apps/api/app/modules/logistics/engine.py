"""Simulated logistics (Phase 7): state machine, fictional couriers, schematic route, ETA.

Pure and deterministic. Nothing here uses GPS, maps, traffic or courier-company data, and
nothing here makes clinical decisions: it only models a transport workflow for a prototype.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Literal

from app.modules.operations.engine import Place, simulated_route

LOGISTICS_LABEL = "Simulated logistics — prototype"
ETA_LABEL = "Simulated ETA — prototype"
ROUTE_MAP_LABEL = "Prototype logistics route — not a geographic map"
LOGISTICS_DISCLAIMER = (
    "Simulated logistics — prototype. This is a simulated logistics prototype. Routes, courier "
    "status and ETAs are not real-world navigation or delivery guarantees."
)

Status = Literal[
    "created", "pickup_pending", "picked_up", "in_transit", "delayed", "arrived", "received"
]
Action = Literal[
    "assign", "pickup", "depart", "checkpoint", "delay", "resume", "arrive", "receive",
    "confirm_receipt",
]  # fmt: skip

OPEN_TRANSPORT: frozenset[str] = frozenset({"pickup_pending", "picked_up", "in_transit", "delayed"})

# action → (allowed from, to). "resume" returns to the status held before the delay.
# "confirm_receipt" is the explicit path for the existing request receipt (a person confirms
# the bags physically arrived); it records ARRIVED (confirmed at receipt) then RECEIVED.
# There is no cancellation: a dispatched request can't be cancelled in the existing lifecycle.
TRANSITIONS: dict[str, tuple[frozenset[str], str | None]] = {
    "assign": (frozenset({"created"}), "pickup_pending"),
    "pickup": (frozenset({"pickup_pending"}), "picked_up"),
    "depart": (frozenset({"picked_up"}), "in_transit"),
    "checkpoint": (frozenset({"in_transit"}), "in_transit"),
    "delay": (frozenset({"picked_up", "in_transit"}), "delayed"),
    "resume": (frozenset({"delayed"}), None),
    "arrive": (frozenset({"in_transit"}), "arrived"),
    "receive": (frozenset({"arrived"}), "received"),
    "confirm_receipt": (OPEN_TRANSPORT | {"arrived"}, "received"),
}
TERMINAL: frozenset[str] = frozenset({"received"})


def can(action: str, status: str) -> bool:
    return status in TRANSITIONS[action][0]


def next_action(status: str, current_checkpoint: int) -> str | None:
    """What the demo "advance" control does from here (None: use another control)."""
    if status == "created":
        return "assign"
    if status == "pickup_pending":
        return "pickup"
    if status == "picked_up":
        return "depart"
    if status == "in_transit" and current_checkpoint < LAST_WAYPOINT:
        return "checkpoint"
    return None


# ---------------------------------------------------------------- simulated courier

COURIERS: tuple[str, ...] = (
    "Demo Courier Alpha",
    "Demo Courier Bravo",
    "Demo Courier Charlie",
    "Demo Courier Delta",
    "Demo Courier Echo",
    "Demo Courier Foxtrot",
)


@dataclass(frozen=True)
class Courier:
    courier_id: str
    name: str
    vehicle_type: str


def _h(*parts: str) -> int:
    return int.from_bytes(hashlib.sha256("|".join(parts).encode()).digest()[:8], "big")


def simulated_courier(key: str, urgency: str) -> Courier:
    """Fictional, deterministic courier for a shipment (no real company or person)."""
    n = _h("courier", key)
    vehicle = (
        "Insulated motorbike box (simulated)"
        if urgency == "emergency"
        else "Refrigerated van (simulated)"
    )
    return Courier(
        courier_id=f"SIM-CR-{n % 10000:04d}",
        name=COURIERS[n % len(COURIERS)],
        vehicle_type=vehicle,
    )


# ---------------------------------------------------------------- schematic route

# Share of the travel distance/time for each leg ending at checkpoint 1..4.
LEG_SHARES: tuple[float, ...] = (0.15, 0.45, 0.30, 0.10)
LAST_WAYPOINT = 3  # the destination area; checkpoint 4 (the facility) is reached by "arrive"
DESTINATION = 4


@dataclass(frozen=True)
class Plan:
    distance_km: float
    travel_minutes: int
    handover_minutes: int
    leg_minutes: tuple[int, ...]  # minutes to reach checkpoints 1..4 from the previous one
    checkpoints: list[dict[str, Any]]
    route_status: str


def plan_route(src: Place, dst: Place, urgency: str, *, start: datetime) -> Plan:
    """Phase 6 simulated route, split into five schematic checkpoints."""
    route = simulated_route(src, dst, urgency, hour_bucket=int(start.timestamp() // 3600))
    travel = route.travel_minutes
    legs = [round(travel * s) for s in LEG_SHARES]
    legs[-1] = max(0, travel - sum(legs[:-1]))
    names = (
        (src.name, "source"),
        ("Collection point (simulated)", "collection"),
        ("Transit checkpoint (simulated)", "transit"),
        (f"{dst.city} destination area (simulated)", "destination_area"),
        (dst.name, "destination"),
    )
    shares = (0.0, *LEG_SHARES)
    checkpoints: list[dict[str, Any]] = []
    t = start + timedelta(minutes=route.handover_minutes)
    cum = 0.0
    for seq, ((name, kind), share) in enumerate(zip(names, shares, strict=True)):
        if seq > 0:
            t += timedelta(minutes=legs[seq - 1])
        cum += route.distance_km * share
        checkpoints.append(
            {
                "seq": seq,
                "name": name,
                "kind": kind,
                "distance_km": round(cum, 1),
                "expected_at": t.isoformat(),
                "actual_at": None,
                "status": "pending",
            }
        )
    return Plan(
        distance_km=route.distance_km,
        travel_minutes=travel,
        handover_minutes=route.handover_minutes,
        leg_minutes=tuple(legs),
        checkpoints=checkpoints,
        route_status=route.status,
    )


def remaining_travel(checkpoints: list[dict[str, Any]], reached: int) -> int:
    """Planned minutes from checkpoint ``reached`` to the destination (schematic legs)."""
    total = 0
    for seq in range(max(reached, 0) + 1, len(checkpoints)):
        prev = datetime.fromisoformat(checkpoints[seq - 1]["expected_at"])
        cur = datetime.fromisoformat(checkpoints[seq]["expected_at"])
        total += round((cur - prev).total_seconds() / 60)
    return total


def reach(
    checkpoints: list[dict[str, Any]], seq: int, at: datetime, *, confirmed_at_receipt: bool = False
) -> list[dict[str, Any]]:
    """A new list (so JSON column changes are detected) with checkpoint ``seq`` reached."""
    out = [dict(c) for c in checkpoints]
    out[seq]["actual_at"] = at.isoformat()
    out[seq]["status"] = "confirmed_at_receipt" if confirmed_at_receipt else "reached"
    return out


def reschedule(
    checkpoints: list[dict[str, Any]], after: int, eta_shift_min: int
) -> list[dict[str, Any]]:
    """Shift the expected time of every checkpoint after ``after`` (e.g. by a delay)."""
    out = [dict(c) for c in checkpoints]
    for c in out[after + 1 :]:
        c["expected_at"] = (
            datetime.fromisoformat(c["expected_at"]) + timedelta(minutes=eta_shift_min)
        ).isoformat()
    return out


@dataclass(frozen=True)
class Eta:
    eta_at: datetime
    remaining_minutes: int
    status: Literal["on_schedule", "delayed", "late", "arrived", "delivered"]
    reasons: list[str]


def eta(
    *,
    status: str,
    eta_at: datetime,
    now: datetime,
    delay_minutes: int,
    delay_active: bool,
) -> Eta:
    remaining = max(0, round((eta_at - now).total_seconds() / 60))
    reasons = [f"Schematic legs at simulated speeds; ETA {eta_at.isoformat(timespec='minutes')}"]
    if delay_minutes:
        reasons.append(f"Includes +{delay_minutes} min of simulated delay")
    if status == "received":
        return Eta(eta_at, 0, "delivered", reasons)
    if status == "arrived":
        return Eta(eta_at, 0, "arrived", reasons)
    if delay_active:
        reasons.append("Delay active (simulated) — ETA holds until resumed")
        return Eta(eta_at, remaining, "delayed", reasons)
    if now > eta_at:
        reasons.append("Past the simulated ETA")
        return Eta(eta_at, 0, "late", reasons)
    return Eta(eta_at, remaining, "on_schedule", reasons)
