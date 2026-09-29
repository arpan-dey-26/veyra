import type { BloodComponent, BloodGroup, BloodRequestOut } from "@veyra/api-client";

export const BLOOD_GROUPS: readonly BloodGroup[] = ["A+", "A-", "B+", "B-", "AB+", "AB-", "O+", "O-"];

export const COMPONENTS: readonly { code: BloodComponent; label: string; short: string }[] = [
  { code: "WHOLE_BLOOD", label: "Whole blood", short: "WB" },
  { code: "PRBC", label: "Packed red cells", short: "PRBC" },
  { code: "FFP", label: "Fresh frozen plasma", short: "FFP" },
  { code: "PLATELETS", label: "Platelets", short: "PLT" },
  { code: "CRYO", label: "Cryoprecipitate", short: "CRYO" },
];

export function componentLabel(code: string): string {
  return COMPONENTS.find((c) => c.code === code)?.label ?? code;
}

/** Typographic minus for display ("O−"), the value stays ASCII. */
export function displayGroup(group: string): string {
  return group.replace("-", "−");
}

export const BAG_STATUS: Record<string, { label: string; tone: "verified" | "warn" | "neutral" | "critical" }> = {
  available: { label: "In storage", tone: "verified" },
  in_transit: { label: "In transit", tone: "warn" },
  received: { label: "Received", tone: "verified" },
  discarded: { label: "Discarded", tone: "neutral" },
};

export const REQUEST_STATUS: Record<
  BloodRequestOut["status"],
  { label: string; tone: "verified" | "warn" | "neutral" | "critical" | "vital" }
> = {
  pending: { label: "Awaiting blood bank", tone: "warn" },
  acknowledged: { label: "Acknowledged (simulated)", tone: "neutral" },
  dispatched: { label: "Dispatched", tone: "vital" },
  fulfilled: { label: "Received", tone: "verified" },
  rejected: { label: "Declined", tone: "critical" },
  cancelled: { label: "Cancelled", tone: "neutral" },
};

export const URGENCY_LABEL: Record<string, string> = {
  routine: "Routine",
  urgent: "Urgent",
  emergency: "Emergency",
};

export const EVENT_LABEL: Record<string, string> = {
  COLLECTED: "Collected",
  DISPATCHED: "Dispatched",
  RECEIVED: "Received",
  DISCARDED: "Discarded",
  DEVICE_ATTACHED: "Temperature monitoring started (simulated device)",
  TEMP_EXCURSION: "Temperature excursion (simulated)",
  TEMP_RECOVERED: "Temperature recovered (simulated)",
};

const dateTime = new Intl.DateTimeFormat("en-IN", {
  day: "numeric",
  month: "short",
  year: "numeric",
  hour: "2-digit",
  minute: "2-digit",
});
const dateOnly = new Intl.DateTimeFormat("en-IN", { day: "numeric", month: "short", year: "numeric" });

export function formatDateTime(iso: string): string {
  return dateTime.format(new Date(iso));
}

export function formatDate(iso: string): string {
  return dateOnly.format(new Date(iso));
}

/** "in 3 days", "in 5 h", "expired 2 days ago". */
export function relativeExpiry(iso: string, now: Date = new Date()): string {
  const ms = new Date(iso).getTime() - now.getTime();
  const hours = Math.round(Math.abs(ms) / 3_600_000);
  const text = hours < 48 ? `${hours} h` : `${Math.round(hours / 24)} days`;
  return ms >= 0 ? `in ${text}` : `expired ${text} ago`;
}

/** Bag label ids: VYR-XXXX-XXXX (Crockford base32, no I/L/O/U). */
const BAG_ID = /^VYR-[0-9A-HJKMNP-TV-Z]{4}-[0-9A-HJKMNP-TV-Z]{4}$/;

/** Accepts a typed id or a scanned QR payload ("veyra:bag:VYR-…"); returns the id or null. */
export function parseBagId(input: string): string | null {
  const value = input.trim().toUpperCase().replace(/^VEYRA:BAG:/, "");
  return BAG_ID.test(value) ? value : null;
}

/** A fresh key per submission attempt; retries of the same attempt reuse it. */
export function newIdempotencyKey(): string {
  return typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID()
    : `k-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}
