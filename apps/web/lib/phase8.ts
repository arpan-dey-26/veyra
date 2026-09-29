/** Phase 8 disclosures (verbatim; the API returns the same text). */
export const COMPATIBILITY_DISCLAIMER =
  "Informational prototype reference only; final transfusion decisions require authorized clinical confirmation.";
export const CAMP_DISCLAIMER =
  "Prototype camp-management workflow; donor eligibility and medical screening remain governed by authorized staff.";
export const QR_DISCLAIMER =
  "QR is a traceability identifier, not an authentication credential or medical authorization.";

export const CAMP_STATUS: Record<string, { label: string; tone: "neutral" | "vital" | "verified" | "warn" | "critical"; icon: string }> = {
  planned: { label: "Planned", tone: "neutral", icon: "○" },
  published: { label: "Published", tone: "neutral", icon: "◔" },
  registration_open: { label: "Registration open", tone: "verified", icon: "◑" },
  ongoing: { label: "Ongoing", tone: "vital", icon: "●" },
  completed: { label: "Completed", tone: "verified", icon: "✓" },
  cancelled: { label: "Cancelled", tone: "critical", icon: "✕" },
};

export const REGISTRATION_STATUS: Record<string, { label: string; tone: "neutral" | "vital" | "verified" | "warn" | "critical" }> = {
  registered: { label: "Registered", tone: "vital" },
  attended: { label: "Attended", tone: "verified" },
  cancelled: { label: "Cancelled", tone: "neutral" },
  no_show: { label: "Did not attend", tone: "warn" },
};

export const CAMP_ACTION_LABEL: Record<string, string> = {
  publish: "Publish",
  "open-registration": "Open registration",
  start: "Start camp",
  complete: "Complete camp",
  cancel: "Cancel camp",
};

export const CAMP_TOPICS = ["camp.updated"] as const;

/** Local datetime input value ("YYYY-MM-DDTHH:mm") → ISO string with the browser offset. */
export function localToIso(value: string): string {
  return new Date(value).toISOString();
}

/** ISO → value for <input type="datetime-local"> in the browser's zone. */
export function isoToLocal(iso: string): string {
  const d = new Date(iso);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}
