import type { DemandForecast, ForecastSummary, ModelCard } from "@veyra/api-client";

/** Shared, fixed forecast fixtures for web tests (synthetic, deterministic). */
const SOURCE = { provider: "veyra-demand-gbm@1.0.0", kind: "synthetic", fetched_at: null, note: "Synthetic ML forecast — prototype.", simulated: true } as const;
const MODEL = { name: "veyra-demand-gbm", version: "1.0.0", fingerprint: "47213848aae9e96b", generator: "synthetic-demand-v1", trained_on: "synthetic", one_step_mae: 1.07, baseline_one_step_mae: 1.17 } as const;
const GROUPS = ["A+", "A-", "B+", "B-", "AB+", "AB-", "O+", "O-"] as const;

/** ISO day `offset` days after 2026-09-28 (negative = before). */
function isoDay(offset: number): string {
  return new Date(Date.UTC(2026, 8, 28 + offset)).toISOString().slice(0, 10);
}

export function demandFixture(horizon = 7, overrides: Partial<DemandForecast> = {}): DemandForecast {
  return {
    scope: "facility",
    facility_id: "h1",
    facility_name: "City Hospital",
    facilities_included: 1,
    blood_group: "O+",
    component: "PRBC",
    horizon,
    generated_at: "2026-09-28T09:00:00Z",
    history: Array.from({ length: 28 }, (_, i) => ({ day: isoDay(i - 28), demand: 4 + (i % 3) })),
    forecast: Array.from({ length: horizon }, (_, i) => ({ day: isoDay(i), predicted: 5.2, lower: 2.1, upper: 8.4, baseline: 4.8 })),
    history_daily_mean: 4.9,
    forecast_daily_mean: 5.2,
    forecast_total: 36.4,
    signal: { status: "normal", ratio: 1.06, reason: "Within the usual range" },
    model: { ...MODEL },
    source: { ...SOURCE },
    disclaimer: "Synthetic ML forecast — prototype. Trained and run on synthetic demand data; not clinical guidance and not a certified medical prediction system.",
    ...overrides,
  };
}

export function summaryFixture(scope: "facility" | "network" = "facility", overrides: Partial<ForecastSummary> = {}): ForecastSummary {
  const rows = (["PRBC", "PLATELETS", "FFP"] as const).flatMap((component) =>
    GROUPS.map((g) => {
      const high = g === "O-" && component === "PRBC";
      return {
        blood_group: g,
        component,
        history_daily_mean: 2,
        forecast_daily_mean: high ? 3.4 : 2,
        forecast_total: high ? 23.8 : 14,
        signal: { status: high ? ("high" as const) : ("normal" as const), ratio: high ? 1.7 : 1, reason: "" },
        stock_available: scope === "facility" ? (high ? 2 : 30) : null,
        coverage_days: scope === "facility" ? (high ? 0.6 : 15) : null,
        pressure: scope === "facility" ? (high ? ("pressure" as const) : ("ok" as const)) : null,
      };
    }),
  );
  return {
    scope,
    facility_id: scope === "facility" ? "b1" : null,
    facility_name: scope === "facility" ? "Central Blood Bank" : null,
    facilities_included: scope === "facility" ? 1 : 2,
    horizon: 7,
    generated_at: "2026-09-28T09:00:00Z",
    rows,
    signal_counts: { normal: 23, elevated: 0, high: 1 },
    model: { ...MODEL },
    source: { ...SOURCE },
    disclaimer: "Synthetic ML forecast — prototype.",
    ...overrides,
  };
}

export const MODEL_CARD: ModelCard = {
  name: "veyra-demand-gbm",
  version: "1.0.0",
  fingerprint: "47213848aae9e96b",
  generator: "synthetic-demand-v1",
  seed: 2026,
  purpose: "Prototype",
  intended_use: "Demonstration",
  not_intended_for: ["Clinical decisions, transfusion planning or patient care"],
  features: ["lag1"],
  model_type: "Gradient-boosted regression trees",
  training_data: { kind: "synthetic" },
  split: { method: "chronological" },
  one_step: { horizon: "next day", baseline: { mae: 1.17, rmse: 1.78, wape: 0.53 }, gbm: { mae: 1.07, rmse: 1.61, wape: 0.48 } },
  horizon_7: { horizon: "7-day", baseline: { mae: 1.17, rmse: 1.78, wape: 0.53 }, gbm: { mae: 1.08, rmse: 1.62, wape: 0.49 } },
  uncertainty: { coverage: 0.8 },
  limitations: ["Synthetic"],
  disclaimer: "Synthetic ML forecast — prototype. Trained and run on synthetic demand data; not clinical guidance and not a certified medical prediction system.",
};
