import type {
  ActivityItem,
  AdminDashboard,
  ExpiryBucket,
  InventorySummary,
  MovementDay,
  StatusCount,
} from "@veyra/api-client";

import { BLOOD_GROUPS, componentLabel, displayGroup, REQUEST_STATUS } from "@/lib/network";
import { isRole, ROLE_LABEL } from "@/lib/roles";

/** One mark in a bar/column chart. `tone` picks a token color, never a data-driven hue. */
export interface BarDatum {
  key: string;
  label: string;
  value: number;
  /** Optional secondary text for the tooltip, e.g. "2 expiring within 72 h". */
  detail?: string;
  tone?: "vital" | "warn" | "critical" | "verified" | "neutral";
}

export interface SeriesPoint {
  key: string;
  label: string;
  values: Record<string, number>;
}

/**
 * A clean axis maximum. Values above `floor` round up to 1, 2, 2.5 or 5 × 10^n; empty or
 * tiny data uses `floor` itself (small whole numbers, integer mid-tick), never a re-rounded
 * floor.
 */
export function niceMax(value: number, floor = 4): number {
  if (value <= floor) return floor;
  const exp = 10 ** Math.floor(Math.log10(value));
  for (const m of [1, 2, 2.5, 5, 10]) if (value <= m * exp) return m * exp;
  return 10 * exp;
}

/** Usable units per blood group (all components), with expiring-soon as detail. */
export function inventoryByGroup(summary: InventorySummary): BarDatum[] {
  return BLOOD_GROUPS.map((g) => {
    const rows = summary.rows.filter((r) => r.blood_group === g);
    const available = rows.reduce((n, r) => n + r.available, 0);
    const soon = rows.reduce((n, r) => n + r.expiring_soon, 0);
    const parts = rows
      .filter((r) => r.available > 0)
      .map((r) => `${r.available} ${componentLabel(r.component)}`);
    return {
      key: g,
      label: displayGroup(g),
      value: available,
      detail: [parts.join(", "), soon > 0 ? `${soon} expiring within 72 h` : ""]
        .filter(Boolean)
        .join(" · "),
      tone: "vital",
    };
  });
}

const STATUS_TONE: Record<string, BarDatum["tone"]> = {
  pending: "warn",
  acknowledged: "neutral",
  dispatched: "vital",
  fulfilled: "verified",
  rejected: "critical",
  cancelled: "neutral",
};

/** Request status distribution; keeps the API's fixed order so bars never re-sort. */
export function requestStatusBars(items: StatusCount[]): BarDatum[] {
  return items.map((s) => ({
    key: s.status,
    label: REQUEST_STATUS[s.status as keyof typeof REQUEST_STATUS]?.label ?? s.status,
    value: s.count,
    tone: STATUS_TONE[s.status] ?? "neutral",
  }));
}

const EXPIRY_TONE: Record<ExpiryBucket["bucket"], BarDatum["tone"]> = {
  expired: "critical",
  lt_1d: "critical",
  d1_3: "warn",
  d3_7: "warn",
  d7_30: "vital",
  gt_30d: "vital",
};

export function expiryBars(buckets: ExpiryBucket[]): BarDatum[] {
  return buckets.map((b) => ({ key: b.bucket, label: b.label, value: b.count, tone: EXPIRY_TONE[b.bucket] }));
}

const dayFmt = new Intl.DateTimeFormat("en-IN", { day: "numeric", month: "short", timeZone: "UTC" });

/** "2026-09-28" → "28 Sept" (the API already bucketed the day in the network's offset). */
export function dayLabel(isoDay: string): string {
  return dayFmt.format(new Date(`${isoDay}T00:00:00Z`));
}

export function dayColumns(days: { day: string; count: number }[]): BarDatum[] {
  return days.map((d) => ({ key: d.day, label: dayLabel(d.day), value: d.count, tone: "vital" }));
}

export function movementSeries(days: MovementDay[]): SeriesPoint[] {
  return days.map((d) => ({
    key: d.day,
    label: dayLabel(d.day),
    values: { dispatched: d.dispatched, received: d.received },
  }));
}

export function sumValues(data: { value: number }[]): number {
  return data.reduce((n, d) => n + d.value, 0);
}

const TOPIC_VERB: Record<string, string> = {
  "request.created": "Request raised",
  "request.dispatched": "Units dispatched",
  "request.fulfilled": "Receipt confirmed",
  "request.rejected": "Request declined",
  "request.cancelled": "Request cancelled",
  "inventory.updated": "Inventory updated",
  "bag.discarded": "Bag discarded",
};

/** Human text for one network event. Uses only the event's non-personal fields. */
export function activityText(item: Pick<ActivityItem, "topic" | "reference" | "units" | "component" | "blood_group" | "reason">): {
  title: string;
  detail: string;
} {
  const title = TOPIC_VERB[item.topic] ?? item.topic;
  const parts: string[] = [];
  if (item.reference) parts.push(item.reference);
  if (item.units && item.component) {
    parts.push(`${item.units} × ${componentLabel(item.component)}${item.blood_group ? ` ${displayGroup(item.blood_group)}` : ""}`);
  }
  if (item.reason) parts.push(item.reason.replaceAll("_", " "));
  return { title, detail: parts.join(" · ") };
}

/** Accounts per role with the status split as tooltip detail. */
export function usersByRole(d: Pick<AdminDashboard, "users">): BarDatum[] {
  return d.users.map((u) => ({
    key: u.role,
    label: isRole(u.role) ? ROLE_LABEL[u.role] : u.role,
    value: u.total,
    detail: `${u.active} active · ${u.pending_verification} pending · ${u.disabled} disabled`,
    tone: "vital",
  }));
}
