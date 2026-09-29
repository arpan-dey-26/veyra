"""Loading the versioned artifact and producing multi-day forecasts."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.modules.forecast.features import feature_row, level_of, seasonal_baseline
from app.modules.forecast.gbm import GradientBoostedTrees

ARTIFACT_PATH = Path(__file__).with_name("demand_model_v1.json")
MAX_HORIZON = 14


@dataclass(frozen=True)
class ForecastPoint:
    day: date
    predicted: float
    lower: float
    upper: float
    baseline: float


def recursive_forecast(
    model: GradientBoostedTrees,
    history: list[float],
    start: date,
    component: str,
    horizon: int,
    q10: float = 0.0,
    q90: float = 0.0,
) -> list[ForecastPoint]:
    """Forecast ``horizon`` days from ``start`` (the day after the last history value).

    Each step feeds its own prediction back as history (recursive strategy). The interval
    is the validation residual band (relative to level) widened by sqrt(step).
    """
    if not 1 <= horizon <= MAX_HORIZON:
        raise ValueError(f"horizon must be between 1 and {MAX_HORIZON}")
    work = list(history)
    out: list[ForecastPoint] = []
    for step in range(1, horizon + 1):
        day = start + timedelta(days=step - 1)
        level = level_of(work)
        pred = max(0.0, model.predict_one(feature_row(work, day, component)) * level)
        widen = math.sqrt(step)
        out.append(
            ForecastPoint(
                day=day,
                predicted=pred,
                lower=max(0.0, pred + q10 * level * widen),
                upper=max(0.0, pred + q90 * level * widen),
                baseline=seasonal_baseline(work),
            )
        )
        work.append(pred)
    return out


@dataclass(frozen=True)
class LoadedModel:
    name: str
    version: str
    fingerprint: str
    generator: str
    seed: int
    q10: float
    q90: float
    gbm: GradientBoostedTrees
    card: dict[str, Any]


def load_artifact(path: Path = ARTIFACT_PATH) -> LoadedModel:
    data = json.loads(path.read_text(encoding="utf-8"))
    return LoadedModel(
        name=data["model_name"],
        version=data["model_version"],
        fingerprint=data["fingerprint"],
        generator=data["generator"],
        seed=int(data["seed"]),
        q10=float(data["uncertainty"]["q10"]),
        q90=float(data["uncertainty"]["q90"]),
        gbm=GradientBoostedTrees.from_dict(data["model"]),
        card={k: v for k, v in data.items() if k != "model"},
    )


@lru_cache(maxsize=1)
def default_model() -> LoadedModel:
    """Loaded once per process (the artifact is immutable and versioned)."""
    return load_artifact()
