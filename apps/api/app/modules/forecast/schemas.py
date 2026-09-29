from __future__ import annotations

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.core.provenance import SourceMeta

FORECAST_DISCLAIMER = (
    "Synthetic ML forecast — prototype. Trained and run on synthetic demand data; not "
    "clinical guidance and not a certified medical prediction system."
)
SignalStatus = Literal["normal", "elevated", "high"]
PressureBand = Literal["ok", "watch", "pressure"]


class ModelInfo(BaseModel):
    name: str
    version: str
    fingerprint: str
    generator: str
    trained_on: Literal["synthetic"] = "synthetic"
    one_step_mae: float
    baseline_one_step_mae: float


class DemandSignal(BaseModel):
    """Operational prototype indicator only; never a medical or crisis prediction."""

    status: SignalStatus
    ratio: float = Field(description="Forecast daily mean / trailing 28-day daily mean")
    reason: str


class HistoryPoint(BaseModel):
    day: date
    demand: int = Field(description="Synthetic historical demand (units/day)")


class ForecastPointOut(BaseModel):
    day: date
    predicted: float
    lower: float = Field(description="Lower bound of the ~80% prototype interval")
    upper: float = Field(description="Upper bound of the ~80% prototype interval")
    baseline: float = Field(description="Seasonal-naive baseline for the same day")


class DemandForecast(BaseModel):
    scope: Literal["facility", "network"]
    facility_id: UUID | None
    facility_name: str | None
    facilities_included: int
    blood_group: str
    component: str
    horizon: int
    generated_at: datetime
    history: list[HistoryPoint]
    forecast: list[ForecastPointOut]
    history_daily_mean: float
    forecast_daily_mean: float
    forecast_total: float
    signal: DemandSignal
    model: ModelInfo
    source: SourceMeta
    disclaimer: str = FORECAST_DISCLAIMER


class SummaryRow(BaseModel):
    blood_group: str
    component: str
    history_daily_mean: float
    forecast_daily_mean: float
    forecast_total: float
    signal: DemandSignal
    stock_available: int | None = Field(
        default=None, description="Real usable units on hand (facility scope only)"
    )
    coverage_days: float | None = Field(
        default=None, description="Real stock / synthetic forecast daily mean"
    )
    pressure: PressureBand | None = None


class ForecastSummary(BaseModel):
    scope: Literal["facility", "network"]
    facility_id: UUID | None
    facility_name: str | None
    facilities_included: int
    horizon: int
    generated_at: datetime
    rows: list[SummaryRow]
    signal_counts: dict[str, int]
    model: ModelInfo
    source: SourceMeta
    disclaimer: str = FORECAST_DISCLAIMER


class MetricSet(BaseModel):
    mae: float
    rmse: float
    wape: float


class Evaluation(BaseModel):
    horizon: str
    baseline: MetricSet
    gbm: MetricSet


class ModelCard(BaseModel):
    name: str
    version: str
    fingerprint: str
    generator: str
    seed: int
    purpose: str
    intended_use: str
    not_intended_for: list[str]
    features: list[str]
    model_type: str
    training_data: dict[str, object]
    split: dict[str, object]
    one_step: Evaluation
    horizon_7: Evaluation
    uncertainty: dict[str, object]
    limitations: list[str]
    disclaimer: str = FORECAST_DISCLAIMER
