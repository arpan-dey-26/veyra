import type { BadgeTone } from "@/components/ui/badge";

/** Shown on every Phase 6 view (verbatim with the API). */
export const OPS_LABEL = "Operational recommendation — prototype";
export const OPS_DISCLAIMER =
  "This is an operational engineering prototype. Recommendations are not clinical decisions or medical advice.";
export const FORECAST_INPUT_LABEL = "Synthetic forecast input — prototype";
export const ROUTING_LABEL = "Simulated routing — prototype";

export const OPS_TOPICS = [
  "request.created",
  "request.dispatched",
  "request.fulfilled",
  "request.rejected",
  "request.cancelled",
  "request.priority_changed",
  "request.operational_alert",
  "allocation.recommendation_updated",
  "routing.updated",
  "forecast.pressure_changed",
  "cold_chain.operational_alert",
  "temperature.warning",
  "temperature.critical",
  "temperature.recovered",
];

type Status = { label: string; tone: BadgeTone; icon: string };

/** Every status is text + a glyph + colour, never colour alone. */
export const PRIORITY_BAND: Record<string, Status> = {
  immediate: { label: "Immediate", tone: "critical", icon: "▲" },
  high: { label: "High", tone: "warn", icon: "◆" },
  standard: { label: "Standard", tone: "neutral", icon: "●" },
};

export const PRESSURE_LEVEL: Record<string, Status> = {
  elevated: { label: "Elevated", tone: "critical", icon: "▲" },
  watch: { label: "Watch", tone: "warn", icon: "◆" },
  normal: { label: "Normal", tone: "verified", icon: "✓" },
};

export const COLD_STATE: Record<string, Status> = {
  critical: { label: "Cold-chain critical", tone: "critical", icon: "▲" },
  warning: { label: "Cold-chain warning", tone: "warn", icon: "◆" },
  stale: { label: "Device offline / stale", tone: "warn", icon: "◌" },
  normal: { label: "Cold chain normal", tone: "verified", icon: "✓" },
  unmonitored: { label: "Not monitored", tone: "neutral", icon: "–" },
};

export const REASON_TONE: Record<string, Status> = {
  warning: { label: "Warning", tone: "critical", icon: "▲" },
  attention: { label: "Attention", tone: "warn", icon: "◆" },
  positive: { label: "OK", tone: "verified", icon: "✓" },
  info: { label: "Info", tone: "neutral", icon: "•" },
};

export const ROUTE_STATUS: Record<string, Status> = {
  clear: { label: "Clear (simulated)", tone: "verified", icon: "✓" },
  slow: { label: "Slow (simulated)", tone: "warn", icon: "◆" },
  delayed: { label: "Delayed (simulated)", tone: "critical", icon: "▲" },
};

export const CHANGE_REASONS = [
  { value: "escalated_by_requesting_team", label: "Escalated by the requesting team" },
  { value: "situation_resolved", label: "Need has eased" },
  { value: "entered_in_error", label: "Entered in error" },
  { value: "other", label: "Other operational reason" },
] as const;

/** 45 min · 3 h 5 min · 2 d 4 h */
export function formatMinutes(minutes: number): string {
  const m = Math.max(0, Math.round(minutes));
  if (m < 60) return `${m} min`;
  if (m < 60 * 24) return `${Math.floor(m / 60)} h${m % 60 ? ` ${m % 60} min` : ""}`;
  const d = Math.floor(m / 1440);
  const h = Math.floor((m % 1440) / 60);
  return `${d} d${h ? ` ${h} h` : ""}`;
}

export function formatCoverage(days: number | null | undefined): string {
  if (days === null || days === undefined) return "—";
  return `${days.toFixed(1)} d`;
}
