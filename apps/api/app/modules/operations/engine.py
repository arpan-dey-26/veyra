"""Operational intelligence (Phase 6): deterministic, explainable rules. Pure functions only.

Everything here is an OPERATIONAL recommendation for a student engineering prototype. It is
not a clinical risk score, it never decides anything on its own, and every output carries the
structured reasons that produced it (no hidden model).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Literal

OPS_LABEL = "Operational recommendation — prototype"
OPS_DISCLAIMER = (
    "Operational recommendation — prototype. This is an operational engineering prototype. "
    "Recommendations are not clinical decisions or medical advice."
)
FORECAST_INPUT_LABEL = "Synthetic forecast input — prototype"
ROUTING_LABEL = "Simulated routing — prototype"

PriorityBand = Literal["immediate", "high", "standard"]
PressureLevel = Literal["normal", "watch", "elevated"]
ColdState = Literal["unmonitored", "normal", "warning", "critical", "stale"]
RouteStatus = Literal["clear", "slow", "delayed"]

EXPIRY_SOON = timedelta(hours=72)
IMMEDIATE_AT, HIGH_AT = 65, 45
URGENCY_POINTS = {"emergency": 50, "urgent": 30, "routine": 10}
URGENCY_TEXT = {
    "emergency": "Emergency request",
    "urgent": "Urgent request",
    "routine": "Routine request",
}
# Coverage (days of synthetic forecast demand the free stock covers) → pressure level.
ELEVATED_BELOW_DAYS, WATCH_BELOW_DAYS = 3.0, 7.0


@dataclass(frozen=True)
class Reason:
    """One explanation line. ``points`` is its contribution to the priority score (0 = info)."""

    code: str
    text: str
    points: int = 0
    tone: Literal["info", "positive", "attention", "warning"] = "info"


# ---------------------------------------------------------------- cold chain


@dataclass(frozen=True)
class DeviceView:
    """What the engine needs from a Phase 5 (simulated) device."""

    cold_chain_status: str  # unknown | normal | warning | critical
    device_status: str  # awaiting | online | low_battery | paused | offline
    excursion_active: bool


def cold_state(device: DeviceView | None) -> ColdState:
    if device is None:
        return "unmonitored"
    if device.cold_chain_status == "critical":
        return "critical"
    if device.cold_chain_status == "warning" or device.excursion_active:
        return "warning"
    if device.device_status == "offline":
        return "stale"
    return "normal"


# 0 = no concern, 1 = review, 2 = strong concern. Used for ranking, never to discard a bag.
COLD_RANK: dict[ColdState, int] = {
    "normal": 0,
    "unmonitored": 0,
    "stale": 1,
    "warning": 1,
    "critical": 2,
}

COLD_REASON: dict[ColdState, Reason] = {
    "normal": Reason(
        "cold_chain_normal", "Cold chain normal (simulated telemetry)", tone="positive"
    ),
    "unmonitored": Reason("cold_chain_unmonitored", "No simulated device attached"),
    "stale": Reason(
        "cold_chain_stale",
        "Device offline or stale — deprioritised until a fresh reading",
        tone="attention",
    ),
    "warning": Reason(
        "cold_chain_warning",
        "Cold-chain warning — deprioritised; review before dispatch",
        tone="attention",
    ),
    "critical": Reason(
        "cold_chain_critical",
        "Cold-chain critical — deprioritised; review before any dispatch",
        tone="warning",
    ),
}


@dataclass(frozen=True)
class BagView:
    public_id: str
    blood_group: str
    component: str
    expires_at: datetime
    facility_id: str
    facility_name: str


@dataclass
class Candidate:
    bag: BagView
    cold: ColdState
    rank: int = 0
    recommended: bool = False
    deprioritized: bool = False
    fefo_position: int = 0
    reasons: list[Reason] = field(default_factory=list)


def rank_candidates(
    bags: list[BagView], devices: dict[str, DeviceView], *, units: int, now: datetime
) -> list[Candidate]:
    """Order usable, exactly matching bags: cold-chain concern first, then FEFO.

    ``bags`` must already satisfy the existing compatibility rule (same blood group and
    component, available, unexpired, at the facility), ordered FEFO. Nothing is removed.
    """
    out = [
        Candidate(bag=b, cold=cold_state(devices.get(b.public_id)), fefo_position=i + 1)
        for i, b in enumerate(bags)
    ]
    out.sort(key=lambda c: (COLD_RANK[c.cold], c.fefo_position))
    picked = 0
    for rank, c in enumerate(out, start=1):
        c.rank = rank
        c.deprioritized = COLD_RANK[c.cold] > 0
        if not c.deprioritized and picked < units:
            c.recommended = True
            picked += 1
        c.reasons.append(
            Reason("fefo", f"First-expiry-first-out position {c.fefo_position}", tone="info")
        )
        if c.bag.expires_at - now <= EXPIRY_SOON:
            c.reasons.append(
                Reason("expires_soon", "Bag expires within 72 h — use first", tone="attention")
            )
        c.reasons.append(COLD_REASON[c.cold])
        if c.recommended:
            c.reasons.insert(
                0, Reason("recommended", "Recommended for this request", tone="positive")
            )
    return out


# ---------------------------------------------------------------- forecast + inventory pressure


@dataclass(frozen=True)
class Pressure:
    level: PressureLevel
    stock: int
    open_units: int
    free_stock: int
    forecast_daily_mean: float | None
    coverage_days: float | None
    reasons: list[Reason]


def pressure(stock: int, open_units: int, forecast_daily_mean: float | None) -> Pressure:
    """Real stock minus open requested units, against the synthetic daily forecast."""
    free = stock - open_units
    reasons: list[Reason] = [
        Reason("stock", f"{stock} usable units in stock", tone="info"),
    ]
    if open_units:
        reasons.append(Reason("open_requests", f"{open_units} units in open requests", tone="info"))
    coverage: float | None = None
    if free < 0 or (open_units > 0 and stock == 0):
        level: PressureLevel = "elevated"
        reasons.append(
            Reason("short", "Open requests exceed usable stock", points=10, tone="warning")
        )
    elif forecast_daily_mean is None or forecast_daily_mean < 0.1:
        level = "normal"
        reasons.append(
            Reason(
                "no_forecast", "No synthetic forecast for this component; stock vs requests only"
            )
        )
    else:
        coverage = round(free / forecast_daily_mean, 1)
        text = f"Free stock covers {coverage} days of synthetic forecast demand"
        if coverage < ELEVATED_BELOW_DAYS:
            level = "elevated"
            reasons.append(
                Reason("low_coverage", "Low projected coverage — " + text, 10, "warning")
            )
        elif coverage < WATCH_BELOW_DAYS:
            level = "watch"
            reasons.append(
                Reason(
                    "watch_coverage", "Projected coverage under 7 days — " + text, 5, "attention"
                )
            )
        else:
            level = "normal"
            reasons.append(Reason("coverage_ok", text, tone="positive"))
    return Pressure(
        level=level,
        stock=stock,
        open_units=open_units,
        free_stock=free,
        forecast_daily_mean=None if forecast_daily_mean is None else round(forecast_daily_mean, 2),
        coverage_days=coverage,
        reasons=reasons,
    )


# ---------------------------------------------------------------- request priority


@dataclass(frozen=True)
class RequestFacts:
    urgency: str
    status: str
    units: int
    created_at: datetime
    needed_by: datetime
    provider: str


@dataclass(frozen=True)
class StockFacts:
    """Bank-side facts. ``None`` fields are unknown to the viewer (e.g. a hospital)."""

    usable: int | None
    usable_without_concern: int | None
    flagged: int | None
    expiring_soon: int | None
    availability_band: str | None  # hospital view: sufficient | limited | none


@dataclass(frozen=True)
class Priority:
    score: int
    band: PriorityBand
    action_code: str
    action: str
    reasons: list[Reason]


def band_for(score: int) -> PriorityBand:
    return "immediate" if score >= IMMEDIATE_AT else "high" if score >= HIGH_AT else "standard"


def priority(
    req: RequestFacts,
    *,
    now: datetime,
    stock: StockFacts,
    pressure_level: PressureLevel | None,
    viewer: Literal["bank", "hospital", "admin"],
) -> Priority:
    reasons: list[Reason] = [
        Reason(
            f"urgency_{req.urgency}",
            URGENCY_TEXT.get(req.urgency, req.urgency),
            URGENCY_POINTS.get(req.urgency, 10),
            "warning"
            if req.urgency == "emergency"
            else "attention"
            if req.urgency == "urgent"
            else "info",
        )
    ]
    open_ = req.status in ("pending", "acknowledged")
    if open_:
        to_needed = req.needed_by - now
        if to_needed <= timedelta(0):
            reasons.append(Reason("overdue", "Past the needed-by time", 15, "warning"))
        elif to_needed <= timedelta(hours=2):
            reasons.append(Reason("needed_2h", "Needed within 2 hours", 10, "attention"))
        elif to_needed <= timedelta(hours=6):
            reasons.append(Reason("needed_6h", "Needed within 6 hours", 5, "attention"))
        waited = now - req.created_at
        if waited >= timedelta(hours=2):
            reasons.append(Reason("waiting_2h", "Waiting over 2 hours", 10, "attention"))
        elif waited >= timedelta(minutes=30):
            reasons.append(Reason("waiting_30m", "Waiting over 30 minutes", 5, "attention"))
    if req.units >= 4:
        reasons.append(Reason("large", f"Large request ({req.units} units)", 5, "attention"))

    if stock.usable is not None and stock.usable_without_concern is not None:
        good = stock.usable_without_concern
        if good >= req.units:
            reasons.append(
                Reason(
                    "stock_ok",
                    f"Available compatible stock ({good} units without cold-chain concern)",
                    tone="positive",
                )
            )
        else:
            reasons.append(
                Reason(
                    "stock_short",
                    "Not enough compatible stock without cold-chain concern "
                    f"({good} of {req.units})",
                    10,
                    "warning",
                )
            )
        if stock.flagged:
            reasons.append(
                Reason(
                    "cold_chain_flagged",
                    f"Cold-chain concern on {stock.flagged} compatible bags",
                    3,
                    "attention",
                )
            )
        if stock.expiring_soon:
            reasons.append(
                Reason(
                    "bag_expires_soon",
                    f"{stock.expiring_soon} compatible bags expire within 72 h",
                    tone="attention",
                )
            )
    elif stock.availability_band is not None:
        text = {
            "sufficient": "Target blood bank reports sufficient stock (banded)",
            "limited": "Target blood bank reports limited stock (banded)",
            "none": "Target blood bank reports no matching stock (banded)",
        }[stock.availability_band]
        pts = 0 if stock.availability_band == "sufficient" else 10
        tone: Literal["positive", "warning"] = "positive" if pts == 0 else "warning"
        reasons.append(Reason(f"band_{stock.availability_band}", text, pts, tone))

    if pressure_level == "elevated":
        reasons.append(
            Reason(
                "pressure_elevated",
                "Low projected coverage (synthetic forecast input)",
                10,
                "warning",
            )
        )
    elif pressure_level == "watch":
        reasons.append(
            Reason(
                "pressure_watch",
                "Projected coverage under 7 days (synthetic forecast input)",
                5,
                "attention",
            )
        )

    score = min(100, sum(r.points for r in reasons)) if open_ else 0
    code, action = _action(req, stock, viewer)
    return Priority(
        score=score, band=band_for(score), action_code=code, action=action, reasons=reasons
    )


def _action(req: RequestFacts, stock: StockFacts, viewer: str) -> tuple[str, str]:
    if req.provider == "mock":
        return "simulated_partner", "Simulated partner blood bank — nothing will be dispatched"
    if req.status == "dispatched":
        return "await_receipt", "In transit — the hospital confirms receipt on arrival"
    if req.status != "pending":
        return "none", f"No action — the request is {req.status}"
    if viewer != "bank":
        return "await_bank", "Awaiting the blood bank's response"
    good = stock.usable_without_concern or 0
    if good >= req.units:
        return "review_and_dispatch", "Review the recommended bags, then confirm dispatch"
    if (stock.usable or 0) >= req.units:
        return (
            "review_flagged",
            "Only bags with cold-chain concerns can cover this request — "
            "review them before any dispatch",
        )
    return (
        "insufficient_stock",
        "Insufficient compatible stock — contact the hospital or decline with a reason",
    )


# ---------------------------------------------------------------- routing simulation


@dataclass(frozen=True)
class Place:
    id: str
    name: str
    city: str
    state: str


@dataclass(frozen=True)
class Route:
    distance_km: float
    travel_minutes: int
    handover_minutes: int
    eta_minutes: int
    status: RouteStatus
    reasons: list[Reason]


SPEED_KMH = {"emergency": 45.0, "urgent": 38.0, "routine": 32.0}
HANDOVER_MIN = {"emergency": 10, "urgent": 15, "routine": 20}
STATUS_FACTOR: dict[RouteStatus, float] = {"clear": 1.0, "slow": 1.2, "delayed": 1.45}


def _h(*parts: str) -> int:
    return int.from_bytes(hashlib.sha256("|".join(parts).encode()).digest()[:8], "big")


def simulated_route(src: Place, dst: Place, urgency: str, *, hour_bucket: int) -> Route:
    """Deterministic schematic estimate. No GPS, maps or traffic data are used.

    Distance comes from a hash of the facility pair within a band set by city/state
    (same city 3-15 km, same state 40-200 km, otherwise 250-1150 km). The simulated route
    status changes with the hour bucket so the demo can show variation, deterministically.
    """
    pair = "|".join(sorted((src.id, dst.id)))
    if src.id == dst.id:
        distance = 0.0
        scope = "Same facility"
    elif src.city.strip().lower() == dst.city.strip().lower():
        distance = 3 + _h(pair) % 1200 / 100
        scope = f"Same city ({src.city})"
    elif src.state.strip().lower() == dst.state.strip().lower():
        distance = 40 + _h(pair) % 16000 / 100
        scope = f"Same state ({src.state})"
    else:
        distance = 250 + _h(pair) % 90000 / 100
        scope = "Inter-state"
    distance = round(distance, 1)
    status: RouteStatus = ("clear", "clear", "slow", "delayed")[_h(pair, str(hour_bucket)) % 4]
    speed = SPEED_KMH.get(urgency, SPEED_KMH["routine"])
    travel = round(distance / speed * 60 * STATUS_FACTOR[status])
    handover = HANDOVER_MIN.get(urgency, HANDOVER_MIN["routine"])
    reasons = [
        Reason("scope", f"{scope}: simulated distance {distance} km"),
        Reason(
            "speed",
            f"{URGENCY_TEXT.get(urgency, urgency)}: simulated average {speed:.0f} km/h",
        ),
        Reason("handover", f"{handover} min simulated dispatch and handover time"),
    ]
    if status != "clear":
        reasons.append(
            Reason(
                f"route_{status}",
                f"Simulated route status '{status}' "
                f"(+{round((STATUS_FACTOR[status] - 1) * 100)}% travel time)",
                tone="attention",
            )
        )
    return Route(
        distance_km=distance,
        travel_minutes=travel,
        handover_minutes=handover,
        eta_minutes=travel + handover,
        status=status,
        reasons=reasons,
    )
