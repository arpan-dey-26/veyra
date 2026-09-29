"""Deterministic SYNTHETIC blood-demand generator (Phase 4).

No real patient, donor or hospital data is used. Every value is generated from documented,
hand-chosen assumptions (see docs/model-cards/demand-forecast.md):

- level        units/day of red cells for the facility (seeded by the facility key)
- group share  approximate ABO/Rh mix; component share relative to packed red cells
- day of week  weekday elective surgery > weekend
- season       smooth annual cycle, plus a late-monsoon platelet bump (dengue-season pattern)
- spikes       rare multi-day demand surges (e.g. mass-casualty days), shared by a facility
- noise        Poisson counts around the expected value

Stateless by date: each (series, day) draws from its own seeded RNG, so any date range is
reproducible and a day's value never changes when the window moves.
"""

from __future__ import annotations

import hashlib
import math
import random
from dataclasses import dataclass
from datetime import date, timedelta

GENERATOR_VERSION = "synthetic-demand-v1"
DEFAULT_SEED = 2026

# Approximate shares (synthetic assumption, rounded; not a clinical reference).
GROUP_SHARE: dict[str, float] = {
    "O+": 0.36, "B+": 0.32, "A+": 0.21, "AB+": 0.07,
    "O-": 0.015, "B-": 0.012, "A-": 0.008, "AB-": 0.005,
}  # fmt: skip
COMPONENT_SHARE: dict[str, float] = {
    "PRBC": 1.0, "PLATELETS": 0.45, "FFP": 0.35, "WHOLE_BLOOD": 0.15, "CRYO": 0.08,
}  # fmt: skip
DOW_FACTOR = (1.08, 1.06, 1.04, 1.02, 1.00, 0.86, 0.74)  # Monday .. Sunday
SPIKE_START_P = 0.012
SPIKE_MAX_DAYS = 3
# Transcendental results (sin/exp) are rounded to 12 decimals so the data, and therefore the
# trained trees, are bit-identical across C math libraries (glibc on Linux, MSVC on Windows).
_DIGITS = 12


def _unit(*parts: object) -> float:
    """Deterministic uniform [0, 1) from any key (stable across Python processes)."""
    h = hashlib.sha256("|".join(str(p) for p in parts).encode()).digest()
    return int.from_bytes(h[:8], "big") / 2**64


def facility_level(facility_key: str, kind: str, seed: int = DEFAULT_SEED) -> float:
    """Red-cell units/day for a facility's synthetic profile."""
    u = _unit(seed, "level", facility_key)
    lo, hi = (6.0, 30.0) if kind == "HOSPITAL" else (18.0, 60.0)
    return round(lo + (hi - lo) * u, 2)


def season_factor(day: date, component: str) -> float:
    doy = day.timetuple().tm_yday
    base = 1.0 + 0.10 * round(math.sin(2 * math.pi * (doy - 80) / 365.25), _DIGITS)
    if component == "PLATELETS":  # late-monsoon bump, peak ~ mid September
        base += 0.45 * round(math.exp(-(((doy - 258) / 24.0) ** 2)), _DIGITS)
    return round(base, _DIGITS)


def spike_factor(facility_key: str, day: date, seed: int = DEFAULT_SEED) -> float:
    """Multi-day surge shared by all series of a facility (1.0 on normal days)."""
    for back in range(SPIKE_MAX_DAYS):
        start = day - timedelta(days=back)
        if _unit(seed, "spike", facility_key, start.isoformat()) < SPIKE_START_P:
            length = 1 + int(_unit(seed, "len", facility_key, start.isoformat()) * SPIKE_MAX_DAYS)
            if back < length:
                return 1.6 + 0.8 * _unit(seed, "mag", facility_key, start.isoformat())
    return 1.0


def expected_demand(
    facility_key: str, level: float, group: str, component: str, day: date, seed: int
) -> float:
    lam = (
        level
        * GROUP_SHARE[group]
        * COMPONENT_SHARE[component]
        * DOW_FACTOR[day.weekday()]
        * season_factor(day, component)
        * spike_factor(facility_key, day, seed)
    )
    return round(lam, _DIGITS)


def _knuth(lam: float, rng: random.Random) -> int:
    limit, k, p = round(math.exp(-lam), _DIGITS), 0, 1.0
    while True:
        p *= rng.random()
        if p <= limit:
            return k
        k += 1


def _poisson(lam: float, rng: random.Random) -> int:
    """Exact Poisson draw. Large rates are split into chunks (Poisson additivity) so only
    ``exp`` is needed: no normal approximation, no platform-dependent gauss()."""
    if lam <= 0:
        return 0
    total, remaining = 0, lam
    while remaining > 20.0:
        total += _knuth(20.0, rng)
        remaining -= 20.0
    return total + _knuth(round(remaining, _DIGITS), rng)


@dataclass(frozen=True)
class SeriesKey:
    facility_key: str
    kind: str  # HOSPITAL | BLOOD_BANK
    blood_group: str
    component: str


def daily_demand(key: SeriesKey, day: date, seed: int = DEFAULT_SEED) -> int:
    level = facility_level(key.facility_key, key.kind, seed)
    lam = expected_demand(key.facility_key, level, key.blood_group, key.component, day, seed)
    # Seeded simulation RNG (synthetic data only; never used for security).
    rng = random.Random(  # noqa: S311
        int.from_bytes(
            hashlib.sha256(
                f"{seed}|d|{key.facility_key}|{key.blood_group}|{key.component}|{day}".encode()
            ).digest()[:8],
            "big",
        )
    )
    return _poisson(lam, rng)


def generate(key: SeriesKey, start: date, days: int, seed: int = DEFAULT_SEED) -> list[int]:
    """Demand for ``days`` consecutive days starting at ``start`` (inclusive)."""
    return [daily_demand(key, start + timedelta(days=i), seed) for i in range(days)]
