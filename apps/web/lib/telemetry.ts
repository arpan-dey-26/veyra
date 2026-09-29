import type { ColdChainThresholds, TelemetryReading } from "@veyra/api-client";

/** Shown next to every telemetry view (verbatim). */
export const TELEMETRY_BADGE = "Simulated IoT telemetry — prototype";
export const TELEMETRY_DISCLAIMER =
  "This is simulated IoT telemetry for a student engineering prototype and is not a certified medical monitoring system.";

export const TELEMETRY_TOPICS = [
  "telemetry.updated",
  "temperature.warning",
  "temperature.critical",
  "temperature.recovered",
];

export const COLD_STATUS: Record<string, { label: string; tone: "verified" | "warn" | "critical" | "neutral" }> = {
  unknown: { label: "No readings yet", tone: "neutral" },
  normal: { label: "Normal", tone: "verified" },
  warning: { label: "Warning", tone: "warn" },
  critical: { label: "Critical", tone: "critical" },
};

export const DEVICE_STATUS: Record<string, { label: string; tone: "verified" | "warn" | "critical" | "neutral" }> = {
  awaiting: { label: "Awaiting first reading", tone: "neutral" },
  online: { label: "Online", tone: "verified" },
  low_battery: { label: "Low battery", tone: "warn" },
  paused: { label: "Paused", tone: "neutral" },
  offline: { label: "Offline / stale", tone: "critical" },
};

export function formatTemp(c: number | null | undefined): string {
  if (c === null || c === undefined) return "—";
  return `${c.toFixed(1)} °C`;
}

/** 45 s · 3 min 20 s · 2 h 5 min */
export function formatDuration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) return "—";
  const s = Math.max(0, Math.round(seconds));
  if (s < 60) return `${s} s`;
  if (s < 3600) return `${Math.floor(s / 60)} min${s % 60 ? ` ${s % 60} s` : ""}`;
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  return `${h} h${m ? ` ${m} min` : ""}`;
}

/** Y-axis domain that always shows the critical limits plus every reading, padded by 1 °C. */
export function temperatureDomain(readings: Pick<TelemetryReading, "temperature_c">[], t: ColdChainThresholds): [number, number] {
  const values = [t.critical_low, t.critical_high, ...readings.map((r) => r.temperature_c)];
  return [Math.floor(Math.min(...values) - 1), Math.ceil(Math.max(...values) + 1)];
}

export function readingCounts(readings: Pick<TelemetryReading, "status">[]): Record<"normal" | "warning" | "critical", number> {
  const out = { normal: 0, warning: 0, critical: 0 };
  for (const r of readings) out[r.status] += 1;
  return out;
}
