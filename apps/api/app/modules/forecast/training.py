"""Training & evaluation: synthetic reference data → chronological split → baseline vs GBM.

Run ``python -m app.scripts.train_forecast`` to (re)build the committed model artifact.
The split is strictly chronological: every validation day is later than every training day,
and features only ever look backwards, so no future observation reaches training.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from app.modules.forecast.features import (
    FEATURES,
    WINDOW,
    feature_row,
    level_of,
    seasonal_baseline,
)
from app.modules.forecast.gbm import GBMParams, GradientBoostedTrees
from app.modules.forecast.model import recursive_forecast
from app.modules.forecast.synthetic import DEFAULT_SEED, GENERATOR_VERSION, SeriesKey, generate

MODEL_NAME = "veyra-demand-gbm"
MODEL_VERSION = "1.0.0"

# Reference universe (fictional facility keys; never real facilities).
TRAIN_PROFILES: tuple[tuple[str, str], ...] = (
    ("synthetic-hospital-a", "HOSPITAL"),
    ("synthetic-hospital-b", "HOSPITAL"),
    ("synthetic-bank-a", "BLOOD_BANK"),
)
TRAIN_GROUPS: tuple[str, ...] = ("O+", "A+", "AB+", "O-")
TRAIN_COMPONENTS: tuple[str, ...] = ("PRBC", "PLATELETS", "FFP")
DATA_START = date(2024, 6, 1)
DATA_DAYS = 548
VALIDATION_DAYS = 91


@dataclass(frozen=True)
class Row:
    features: list[float]
    target_ratio: float  # y / level
    y: float
    level: float
    baseline: float
    day: date
    series: SeriesKey


@dataclass(frozen=True)
class Split:
    train: list[Row]
    validation: list[Row]
    cutoff: date  # first validation day


def series_keys() -> list[SeriesKey]:
    return [
        SeriesKey(fk, kind, g, c)
        for fk, kind in TRAIN_PROFILES
        for g in TRAIN_GROUPS
        for c in TRAIN_COMPONENTS
    ]


def build_rows(key: SeriesKey, seed: int) -> list[Row]:
    values = [float(v) for v in generate(key, DATA_START, DATA_DAYS, seed)]
    rows: list[Row] = []
    for t in range(WINDOW, DATA_DAYS):
        history = values[:t]  # strictly before day t
        day = DATA_START + timedelta(days=t)
        level = level_of(history)
        rows.append(
            Row(
                features=feature_row(history, day, key.component),
                target_ratio=values[t] / level,
                y=values[t],
                level=level,
                baseline=seasonal_baseline(history),
                day=day,
                series=key,
            )
        )
    return rows


def chronological_split(rows: list[Row]) -> Split:
    cutoff = DATA_START + timedelta(days=DATA_DAYS - VALIDATION_DAYS)
    return Split(
        train=[r for r in rows if r.day < cutoff],
        validation=[r for r in rows if r.day >= cutoff],
        cutoff=cutoff,
    )


def metrics(y: list[float], yhat: list[float]) -> dict[str, float]:
    """MAE, RMSE and WAPE. MAPE is omitted: zero-demand days make it undefined."""
    err = [a - b for a, b in zip(y, yhat, strict=True)]
    total = sum(abs(v) for v in y)
    return {
        "mae": round(sum(abs(e) for e in err) / len(err), 4),
        "rmse": round(math.sqrt(sum(e * e for e in err) / len(err)), 4),
        "wape": round(sum(abs(e) for e in err) / total, 4) if total else 0.0,
    }


def _quantile(values: list[float], q: float) -> float:
    s = sorted(values)
    pos = q * (len(s) - 1)
    lo, hi = math.floor(pos), math.ceil(pos)
    return s[lo] + (s[hi] - s[lo]) * (pos - lo)


def train_and_evaluate(seed: int = DEFAULT_SEED, params: GBMParams | None = None) -> dict[str, Any]:
    """Returns the full artifact: model, metrics, split, uncertainty, provenance."""
    params = params or GBMParams()
    rows = [r for key in series_keys() for r in build_rows(key, seed)]
    split = chronological_split(rows)
    model = GradientBoostedTrees(params=params)
    model.fit([r.features for r in split.train], [r.target_ratio for r in split.train], FEATURES)

    val = split.validation
    y = [r.y for r in val]
    gbm_pred = [max(0.0, model.predict_one(r.features)) * r.level for r in val]
    base_pred = [r.baseline for r in val]
    rel_resid = [(r.y - p) / r.level for r, p in zip(val, gbm_pred, strict=True)]

    # Multi-step (7-day, recursive) evaluation from weekly origins inside the validation period.
    h7_y: list[float] = []
    h7_gbm: list[float] = []
    h7_base: list[float] = []
    for key in series_keys():
        values = [float(v) for v in generate(key, DATA_START, DATA_DAYS, seed)]
        first = DATA_DAYS - VALIDATION_DAYS
        for origin in range(first, DATA_DAYS - 7 + 1, 7):
            points = recursive_forecast(
                model, values[:origin], DATA_START + timedelta(days=origin), key.component, 7
            )
            h7_y += values[origin : origin + 7]
            h7_gbm += [p.predicted for p in points]
            h7_base += [p.baseline for p in points]

    artifact: dict[str, Any] = {
        "model_name": MODEL_NAME,
        "model_version": MODEL_VERSION,
        "generator": GENERATOR_VERSION,
        "seed": seed,
        "training_data": {
            "kind": "synthetic",
            "profiles": [fk for fk, _ in TRAIN_PROFILES],
            "blood_groups": list(TRAIN_GROUPS),
            "components": list(TRAIN_COMPONENTS),
            "start": DATA_START.isoformat(),
            "days": DATA_DAYS,
        },
        "split": {
            "method": "chronological",
            "train_rows": len(split.train),
            "validation_rows": len(val),
            "train_end": (split.cutoff - timedelta(days=1)).isoformat(),
            "validation_start": split.cutoff.isoformat(),
            "validation_days": VALIDATION_DAYS,
        },
        "metrics": {
            "horizon": "one-step-ahead (next day), validation period",
            "baseline": metrics(y, base_pred),
            "gbm": metrics(y, gbm_pred),
            "horizon_7": {
                "horizon": "7-day recursive forecasts from weekly origins, validation period",
                "baseline": metrics(h7_y, h7_base),
                "gbm": metrics(h7_y, h7_gbm),
            },
        },
        "uncertainty": {
            "method": "empirical quantiles of validation residuals / level, widened by sqrt(h)",
            "coverage": 0.8,
            "q10": round(_quantile(rel_resid, 0.10), 4),
            "q90": round(_quantile(rel_resid, 0.90), 4),
        },
        "model": model.to_dict(),
    }
    artifact["fingerprint"] = fingerprint(artifact["model"])
    return artifact


def fingerprint(model_dict: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(model_dict, sort_keys=True).encode()).hexdigest()[:16]
