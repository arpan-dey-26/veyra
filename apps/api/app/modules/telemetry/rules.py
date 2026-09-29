"""Cold-chain rules and the deterministic telemetry simulator (Phase 5).

PROTOTYPE thresholds, chosen to make the demo legible. They are NOT clinical guidance and
must be replaced with validated national guidelines before any real-world use.

For each component: a nominal storage temperature, a normal band, and critical limits.
    normal   normal_low <= t <= normal_high
    warning  outside normal, but critical_low <= t <= critical_high
    critical t < critical_low or t > critical_high
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

Status = Literal["normal", "warning", "critical"]
SimMode = Literal["normal", "excursion", "recovering"]


@dataclass(frozen=True)
class ColdChainRule:
    label: str
    nominal_c: float
    normal_low: float
    normal_high: float
    critical_low: float
    critical_high: float


RULES: dict[str, ColdChainRule] = {
    "WHOLE_BLOOD": ColdChainRule("2 to 6 °C (refrigerated)", 4.0, 2.0, 6.0, 1.0, 8.0),
    "PRBC": ColdChainRule("2 to 6 °C (refrigerated)", 4.0, 2.0, 6.0, 1.0, 8.0),
    "PLATELETS": ColdChainRule("20 to 24 °C (agitated)", 22.0, 20.0, 24.0, 18.0, 26.0),
    "FFP": ColdChainRule("-40 to -18 °C (frozen)", -25.0, -40.0, -18.0, -45.0, -10.0),
    "CRYO": ColdChainRule("-40 to -18 °C (frozen)", -25.0, -40.0, -18.0, -45.0, -10.0),
}

BATTERY_DRAIN_PER_READING = 0.2
LOW_BATTERY_PCT = 20.0
STALE_AFTER = timedelta(minutes=5)
EXCURSION_RAMP_STEPS = 2  # readings from the normal limit to the critical limit
RECOVERY_STEPS = 2  # readings back to nominal


def classify(component: str, temperature_c: float) -> Status:
    r = RULES[component]
    if temperature_c < r.critical_low or temperature_c > r.critical_high:
        return "critical"
    if temperature_c < r.normal_low or temperature_c > r.normal_high:
        return "warning"
    return "normal"


def _noise(device_id: str, seq: int) -> float:
    """Deterministic noise in [-0.25, 0.25] °C for reading ``seq`` of a device."""
    h = hashlib.sha256(f"{device_id}|{seq}".encode()).digest()
    return round((int.from_bytes(h[:4], "big") / 2**32 - 0.5) * 0.5, 3)


def simulated_temperature(
    device_id: str, component: str, seq: int, mode: SimMode, mode_step: int, last_c: float | None
) -> float:
    """Temperature of reading ``seq`` (1-based). ``mode_step`` counts readings in this mode.

    - normal:     nominal + small deterministic noise
    - excursion:  starts just above the normal limit and climbs past the critical limit
                  within EXCURSION_RAMP_STEPS readings, then plateaus (warm excursion)
    - recovering: steps from the last value back to nominal within RECOVERY_STEPS readings
    """
    r = RULES[component]
    noise = _noise(device_id, seq)
    if mode == "excursion":
        span = r.critical_high - r.normal_high
        rise = min(mode_step - 1, EXCURSION_RAMP_STEPS) * span / EXCURSION_RAMP_STEPS
        return round(r.normal_high + 0.5 + rise + abs(noise), 2)
    if mode == "recovering" and last_c is not None and mode_step < RECOVERY_STEPS:
        fraction = mode_step / RECOVERY_STEPS
        # Halfway point stays above the normal limit (visible warning while recovering).
        target = r.normal_high + 0.3 if fraction < 1 else r.nominal_c
        return round(last_c + (target - last_c) * max(fraction, 0.5), 2)
    return round(r.nominal_c + noise, 2)


def initial_battery(device_id: str) -> float:
    h = hashlib.sha256(f"battery|{device_id}".encode()).digest()
    return round(100.0 - (h[0] % 8), 1)  # 93..100 %


def device_status(
    battery_pct: float, last_seen_at: datetime | None, sim_running: bool, now: datetime
) -> Literal["awaiting", "online", "low_battery", "paused", "offline"]:
    if battery_pct <= 0:
        return "offline"
    if last_seen_at is None:
        return "awaiting"
    if not sim_running:
        return "paused"
    if now - last_seen_at > STALE_AFTER:
        return "offline"
    return "low_battery" if battery_pct < LOW_BATTERY_PCT else "online"


def new_device_identity(bag_public_id: str) -> tuple[str, str]:
    """Deterministic simulated identifiers from the bag's public id (no PII)."""
    h = hashlib.sha256(f"device|{bag_public_id}".encode()).hexdigest().upper()
    return f"SIM-{h[:4]}-{h[4:8]}", f"E280-{h[8:12]}-{h[12:16]}-{h[16:20]}"
