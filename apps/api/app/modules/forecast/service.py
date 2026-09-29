"""Demand forecasts (Phase 4): SYNTHETIC history + a versioned GBM, scoped like dashboards.

Scope:
- hospital / blood bank → its own facility only (another facility id → 404)
- admin → the network (sum over active hospitals) or any single facility
- donor → no access (permission check)

Payloads contain facility names and synthetic unit counts only: no donor, patient or user
data. Real inventory appears only in the caller's own facility summary (supply vs forecast).
"""

from __future__ import annotations

import math
from datetime import date, timedelta, timezone
from uuid import UUID

from app.core.clock import Clock
from app.core.errors import NotFoundError, PermissionDeniedError
from app.core.provenance import SourceKind, SourceMeta
from app.core.rbac import AuthContext, Permission, Role
from app.modules.facilities.models import Facility
from app.modules.forecast.features import WINDOW, fmean
from app.modules.forecast.model import ForecastPoint, LoadedModel, recursive_forecast
from app.modules.forecast.schemas import (
    FORECAST_DISCLAIMER,
    DemandForecast,
    DemandSignal,
    ForecastPointOut,
    ForecastSummary,
    HistoryPoint,
    ModelCard,
    ModelInfo,
    PressureBand,
    SummaryRow,
)
from app.modules.forecast.synthetic import SeriesKey, generate
from app.persistence.repositories import UnitOfWork

FORECAST_GROUPS: tuple[str, ...] = ("A+", "A-", "B+", "B-", "AB+", "AB-", "O+", "O-")
FORECAST_COMPONENTS: tuple[str, ...] = ("PRBC", "PLATELETS", "FFP")  # what the model was trained on

HIGH_RATIO, ELEVATED_RATIO = 1.5, 1.2
MIN_UNITS_FOR_SIGNAL = 0.5  # tiny series (rare groups) never raise a signal on noise alone


def demand_signal(history_mean: float, forecast_mean: float) -> DemandSignal:
    ratio = round(forecast_mean / max(history_mean, 0.25), 2)
    if ratio >= HIGH_RATIO and forecast_mean >= 2 * MIN_UNITS_FOR_SIGNAL:
        return DemandSignal(
            status="high", ratio=ratio, reason="Forecast ≥ 1.5 x the last 28 days' average"
        )
    if ratio >= ELEVATED_RATIO and forecast_mean >= MIN_UNITS_FOR_SIGNAL:
        return DemandSignal(
            status="elevated", ratio=ratio, reason="Forecast ≥ 1.2 x the last 28 days' average"
        )
    return DemandSignal(status="normal", ratio=ratio, reason="Within the usual range")


def pressure_band(stock: int, forecast_mean: float) -> tuple[float | None, PressureBand]:
    if forecast_mean < 0.1:
        return None, "ok"
    days = round(stock / forecast_mean, 1)
    return days, "pressure" if days < 3 else "watch" if days < 7 else "ok"


def model_info(model: LoadedModel) -> ModelInfo:
    metrics = model.card["metrics"]
    return ModelInfo(
        name=model.name,
        version=model.version,
        fingerprint=model.fingerprint,
        generator=model.generator,
        one_step_mae=metrics["gbm"]["mae"],
        baseline_one_step_mae=metrics["baseline"]["mae"],
    )


class ForecastService:
    def __init__(
        self, uow: UnitOfWork, clock: Clock, model: LoadedModel, *, utc_offset_minutes: int
    ) -> None:
        self._uow = uow
        self._clock = clock
        self._model = model
        self._tz = timezone(timedelta(minutes=utc_offset_minutes))

    # ------------------------------------------------------------------ scope

    async def _scope(
        self, ctx: AuthContext, facility_id: UUID | None
    ) -> tuple[Facility | None, list[Facility]]:
        """Returns (single facility or None for network, facilities to aggregate)."""
        is_admin = ctx.role is Role.ADMIN and ctx.has(Permission.NETWORK_READ)
        if is_admin:
            if facility_id is None:
                hospitals = [
                    f for f in await self._uow.stats.active_facilities() if f.type == "HOSPITAL"
                ]
                return None, hospitals
            facility = await self._uow.facilities.get(facility_id)
            if facility is None or facility.status != "active":
                raise NotFoundError("Facility not found")
            return facility, [facility]
        if not ctx.has(Permission.FORECAST_READ_OWN) or ctx.facility_id is None:
            raise PermissionDeniedError()
        if facility_id is not None and facility_id != ctx.facility_id:
            raise NotFoundError("Facility not found")  # never confirm other facilities exist
        facility = await self._uow.facilities.get(ctx.facility_id)
        if facility is None:
            raise NotFoundError("Facility not found")
        return facility, [facility]

    # ------------------------------------------------------------------ core

    def _today(self) -> date:
        return self._clock.now().astimezone(self._tz).date()

    def _series(
        self, facilities: list[Facility], group: str, component: str, horizon: int
    ) -> tuple[list[int], list[ForecastPoint]]:
        today = self._today()
        start = today - timedelta(days=WINDOW)
        history = [0] * WINDOW
        combined: list[ForecastPoint] | None = None
        for f in facilities:
            key = SeriesKey(str(f.id), f.type, group, component)
            hist = generate(key, start, WINDOW, self._model.seed)
            points = recursive_forecast(
                self._model.gbm,
                [float(v) for v in hist],
                today,
                component,
                horizon,
                self._model.q10,
                self._model.q90,
            )
            history = [a + b for a, b in zip(history, hist, strict=True)]
            if combined is None:
                combined = points
            else:  # network: sum facility forecasts (intervals summed: conservative)
                combined = [
                    ForecastPoint(
                        day=a.day,
                        predicted=a.predicted + b.predicted,
                        lower=a.lower + b.lower,
                        upper=a.upper + b.upper,
                        baseline=a.baseline + b.baseline,
                    )
                    for a, b in zip(combined, points, strict=True)
                ]
        if combined is None:  # a network with no hospitals yet
            combined = [
                ForecastPoint(
                    day=today + timedelta(days=i), predicted=0, lower=0, upper=0, baseline=0
                )
                for i in range(horizon)
            ]
        return history, combined

    def _source(self) -> SourceMeta:
        return SourceMeta(
            provider=f"{self._model.name}@{self._model.version}",
            kind=SourceKind.SYNTHETIC,
            fetched_at=self._clock.now(),
            note=FORECAST_DISCLAIMER,
        )

    # ------------------------------------------------------------------ endpoints

    async def demand(
        self,
        ctx: AuthContext,
        *,
        blood_group: str,
        component: str,
        horizon: int,
        facility_id: UUID | None,
    ) -> DemandForecast:
        facility, facilities = await self._scope(ctx, facility_id)
        history, points = self._series(facilities, blood_group, component, horizon)
        start = self._today() - timedelta(days=WINDOW)
        hist_mean = fmean([float(v) for v in history]) if history else 0.0
        fc_mean = fmean([p.predicted for p in points])
        return DemandForecast(
            scope="facility" if facility else "network",
            facility_id=facility.id if facility else None,
            facility_name=facility.name if facility else None,
            facilities_included=len(facilities),
            blood_group=blood_group,
            component=component,
            horizon=horizon,
            generated_at=self._clock.now(),
            history=[
                HistoryPoint(day=start + timedelta(days=i), demand=v) for i, v in enumerate(history)
            ],
            forecast=[
                ForecastPointOut(
                    day=p.day,
                    predicted=round(p.predicted, 2),
                    lower=round(p.lower, 2),
                    upper=round(p.upper, 2),
                    baseline=round(p.baseline, 2),
                )
                for p in points
            ],
            history_daily_mean=round(hist_mean, 2),
            forecast_daily_mean=round(fc_mean, 2),
            forecast_total=round(math.fsum(p.predicted for p in points), 1),
            signal=demand_signal(hist_mean, fc_mean),
            model=model_info(self._model),
            source=self._source(),
        )

    async def summary(
        self, ctx: AuthContext, *, horizon: int, facility_id: UUID | None
    ) -> ForecastSummary:
        facility, facilities = await self._scope(ctx, facility_id)
        stock: dict[tuple[str, str], int] = {}
        if facility is not None:
            now = self._clock.now()
            for c in await self._uow.bags.inventory_counts(facility.id, now=now, soon=now):
                stock[(c.blood_group, c.component)] = c.available
        rows: list[SummaryRow] = []
        for component in FORECAST_COMPONENTS:
            for group in FORECAST_GROUPS:
                history, points = self._series(facilities, group, component, horizon)
                hist_mean = fmean([float(v) for v in history])
                fc_mean = fmean([p.predicted for p in points])
                row = SummaryRow(
                    blood_group=group,
                    component=component,
                    history_daily_mean=round(hist_mean, 2),
                    forecast_daily_mean=round(fc_mean, 2),
                    forecast_total=round(math.fsum(p.predicted for p in points), 1),
                    signal=demand_signal(hist_mean, fc_mean),
                )
                if facility is not None:
                    units = stock.get((group, component), 0)
                    coverage, band = pressure_band(units, fc_mean)
                    row.stock_available = units
                    row.coverage_days = coverage
                    row.pressure = band
                rows.append(row)
        counts = {"normal": 0, "elevated": 0, "high": 0}
        for r in rows:
            counts[r.signal.status] += 1
        return ForecastSummary(
            scope="facility" if facility else "network",
            facility_id=facility.id if facility else None,
            facility_name=facility.name if facility else None,
            facilities_included=len(facilities),
            horizon=horizon,
            generated_at=self._clock.now(),
            rows=rows,
            signal_counts=counts,
            model=model_info(self._model),
            source=self._source(),
        )


def model_card(model: LoadedModel) -> ModelCard:
    card = model.card
    m = card["metrics"]
    return ModelCard(
        name=model.name,
        version=model.version,
        fingerprint=model.fingerprint,
        generator=model.generator,
        seed=model.seed,
        purpose="Prototype short-term (1-14 day) blood-demand forecasting to demonstrate "
        "how a network could anticipate demand by blood group and component.",
        intended_use="Engineering demonstration and UI prototyping inside VEYRA.",
        not_intended_for=[
            "Clinical decisions, transfusion planning or patient care",
            "Real inventory ordering or staffing without validated real-world data",
            "Predicting medical emergencies or crises",
        ],
        features=list(model.gbm.feature_names),
        model_type="Gradient-boosted regression trees (pure Python, squared error, depth "
        f"{model.gbm.params.max_depth}, {model.gbm.params.n_estimators} trees, learning rate "
        f"{model.gbm.params.learning_rate}) predicting demand / trailing 28-day level; "
        "recursive multi-day forecasting.",
        training_data=card["training_data"],
        split=card["split"],
        one_step={"horizon": m["horizon"], "baseline": m["baseline"], "gbm": m["gbm"]},
        horizon_7=m["horizon_7"],
        uncertainty=card["uncertainty"],
        limitations=[
            "Trained only on synthetic data from hand-chosen assumptions; real demand differs.",
            "Every facility's history is itself synthetic (seeded by the facility id).",
            "Intervals are empirical and approximate (~80%); they are not calibrated guarantees.",
            "Spikes are random in the synthetic data, so no model can foresee them.",
            f"Components limited to {', '.join(FORECAST_COMPONENTS)}.",
        ],
    )


def facility_daily_mean(
    model: LoadedModel,
    facility: Facility,
    group: str,
    component: str,
    today: date,
    horizon: int = 7,
) -> float | None:
    """Mean synthetic daily demand over ``horizon`` days for one facility series.

    ``None`` when the model does not cover that group/component (Phase 6 then falls back to
    real stock vs open requests only).
    """
    if component not in FORECAST_COMPONENTS or group not in FORECAST_GROUPS:
        return None
    start = today - timedelta(days=WINDOW)
    hist = generate(
        SeriesKey(str(facility.id), facility.type, group, component), start, WINDOW, model.seed
    )
    points = recursive_forecast(
        model.gbm, [float(v) for v in hist], today, component, horizon, model.q10, model.q90
    )
    return fmean([p.predicted for p in points])
