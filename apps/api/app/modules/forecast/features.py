"""Explicit, testable forecasting features.

A row describes "predict day t" from the demand history strictly BEFORE t (no leakage):
values are scaled by the series' trailing 28-day level, so one model serves small and large
facilities alike. The model predicts ``y_t / level`` and the caller multiplies back.
"""

from __future__ import annotations

import math
from datetime import date

WINDOW = 28  # history days required before the first predictable day
LEVEL_FLOOR = 0.25  # keeps ratios finite for rare groups with near-zero demand
_DIGITS = 12  # transcendental features rounded: identical across math libraries

# Exact reductions only (math.fsum): built-in sum() of floats changed in Python 3.12
# (compensated summation) and statistics.pstdev's rounding changed too, which would make
# the trained trees differ between interpreter versions.


def fmean(values: list[float]) -> float:
    return math.fsum(values) / len(values)


def pstdev(values: list[float]) -> float:
    mu = fmean(values)
    return math.sqrt(math.fsum((v - mu) * (v - mu) for v in values) / len(values))


FEATURES: tuple[str, ...] = (
    "lag1",  # yesterday / level
    "lag7",  # same weekday last week / level
    "lag14",  # same weekday two weeks ago / level
    "roll7",  # mean of the last 7 days / level
    "roll7_sd",  # standard deviation of the last 7 days / level
    "max28",  # largest day in the window / level (recent spike memory)
    "log_level",  # log1p(level): Poisson noise is relatively larger at small levels
    "dow",  # day of week of t, 0 = Monday
    "weekend",  # 1 if t is Saturday/Sunday
    "doy_sin",  # annual seasonality of t
    "doy_cos",
    "component",  # component index (see COMPONENT_INDEX)
)
COMPONENT_INDEX = {"PRBC": 0, "PLATELETS": 1, "FFP": 2, "WHOLE_BLOOD": 3, "CRYO": 4}


def level_of(history: list[float]) -> float:
    return max(fmean(history[-WINDOW:]), LEVEL_FLOOR)


def feature_row(history: list[float], day: date, component: str) -> list[float]:
    """Features for predicting ``day`` given ``history`` (the days immediately before it)."""
    if len(history) < WINDOW:
        raise ValueError(f"need at least {WINDOW} days of history")
    level = level_of(history)
    last7 = history[-7:]
    doy = day.timetuple().tm_yday
    return [
        history[-1] / level,
        history[-7] / level,
        history[-14] / level,
        fmean(last7) / level,
        pstdev(last7) / level,
        max(history[-WINDOW:]) / level,
        round(math.log1p(level), _DIGITS),
        float(day.weekday()),
        1.0 if day.weekday() >= 5 else 0.0,
        round(math.sin(2 * math.pi * doy / 365.25), _DIGITS),
        round(math.cos(2 * math.pi * doy / 365.25), _DIGITS),
        float(COMPONENT_INDEX[component]),
    ]


def seasonal_baseline(history: list[float]) -> float:
    """Transparent baseline: mean of the same weekday over the last 4 weeks."""
    if len(history) < WINDOW:
        raise ValueError(f"need at least {WINDOW} days of history")
    return fmean([history[-7], history[-14], history[-21], history[-28]])
