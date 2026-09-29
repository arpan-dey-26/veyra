import type { DemandForecast, ForecastSummary, ForecastSummaryRow } from "@veyra/api-client";

import type { BarDatum } from "@/lib/charts";
import { dayLabel } from "@/lib/charts";
import { displayGroup } from "@/lib/network";

/** Shown next to every forecast (verbatim). */
export const FORECAST_BADGE = "Synthetic ML forecast — prototype";

export const FORECAST_COMPONENTS = [
  { code: "PRBC", label: "Packed red cells" },
  { code: "PLATELETS", label: "Platelets" },
  { code: "FFP", label: "Fresh frozen plasma" },
] as const;
export type ForecastComponent = (typeof FORECAST_COMPONENTS)[number]["code"];

export const SIGNAL: Record<string, { label: string; tone: "verified" | "warn" | "critical" }> = {
  normal: { label: "Normal", tone: "verified" },
  elevated: { label: "Elevated demand", tone: "warn" },
  high: { label: "High demand", tone: "critical" },
};

export const PRESSURE: Record<string, { label: string; tone: "verified" | "warn" | "critical" }> = {
  ok: { label: "Covered", tone: "verified" },
  watch: { label: "Watch", tone: "warn" },
  pressure: { label: "Pressure", tone: "critical" },
};

/** One point on the combined history + forecast timeline. */
export interface TimelinePoint {
  key: string;
  label: string;
  history: number | null;
  predicted: number | null;
  lower: number | null;
  upper: number | null;
  baseline: number | null;
}

export function forecastTimeline(f: Pick<DemandForecast, "history" | "forecast">): TimelinePoint[] {
  const past: TimelinePoint[] = f.history.map((h) => ({
    key: h.day,
    label: dayLabel(h.day),
    history: h.demand,
    predicted: null,
    lower: null,
    upper: null,
    baseline: null,
  }));
  const future: TimelinePoint[] = f.forecast.map((p) => ({
    key: p.day,
    label: dayLabel(p.day),
    history: null,
    predicted: p.predicted,
    lower: p.lower,
    upper: p.upper,
    baseline: p.baseline,
  }));
  return [...past, ...future];
}

/** Forecast total per blood group for one component, in fixed blood-group order. */
export function forecastByGroup(rows: ForecastSummaryRow[], component: string): BarDatum[] {
  return rows
    .filter((r) => r.component === component)
    .map((r) => ({
      key: r.blood_group,
      label: displayGroup(r.blood_group),
      value: Math.round(r.forecast_total),
      detail: `${r.forecast_daily_mean.toFixed(1)}/day forecast vs ${r.history_daily_mean.toFixed(1)}/day last 28 days · ${SIGNAL[r.signal.status]?.label ?? r.signal.status}`,
      tone: r.signal.status === "high" ? "critical" : r.signal.status === "elevated" ? "warn" : "vital",
    }));
}

/** Rows that deserve attention first: pressure, then signal, then forecast size. */
export function attentionRows(s: Pick<ForecastSummary, "rows">): ForecastSummaryRow[] {
  const rank = (r: ForecastSummaryRow) =>
    (r.pressure === "pressure" ? 0 : r.pressure === "watch" ? 1 : 2) * 10 +
    (r.signal.status === "high" ? 0 : r.signal.status === "elevated" ? 1 : 2);
  return [...s.rows].sort((a, b) => rank(a) - rank(b) || b.forecast_total - a.forecast_total);
}

export function signalCounts(s: Pick<ForecastSummary, "signal_counts">): { elevated: number; high: number } {
  return { elevated: s.signal_counts.elevated ?? 0, high: s.signal_counts.high ?? 0 };
}
