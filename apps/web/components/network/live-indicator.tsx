"use client";

import { StatusBeacon } from "@/components/ui/states";
import { useLive } from "@/lib/live";

const LABEL = {
  connecting: "Connecting…",
  live: "Live",
  reconnecting: "Reconnecting…",
  offline: "Offline: refresh to retry",
} as const;

/** Shows whether this screen is receiving live network events (SSE from the outbox). */
export function LiveIndicator() {
  const { status, lastEventAt } = useLive();
  const tone = status === "live" ? "verified" : status === "offline" ? "idle" : "warn";
  return (
    <span
      className="inline-flex items-center gap-3"
      title={lastEventAt ? `Last update ${lastEventAt.toLocaleTimeString("en-IN")}` : undefined}
      data-live-status={status}
    >
      <StatusBeacon tone={tone} label={LABEL[status]} />
      {status === "live" && lastEventAt && (
        <span className="text-xs text-ink-subtle">
          updated {lastEventAt.toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit" })}
        </span>
      )}
    </span>
  );
}
