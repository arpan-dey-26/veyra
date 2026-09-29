import type { BadgeTone } from "@/components/ui/badge";

/** Verbatim with the API. */
export const LOGISTICS_LABEL = "Simulated logistics — prototype";
export const LOGISTICS_DISCLAIMER =
  "This is a simulated logistics prototype. Routes, courier status and ETAs are not real-world navigation or delivery guarantees.";
export const ETA_LABEL = "Simulated ETA — prototype";
export const ROUTE_MAP_LABEL = "Prototype logistics route — not a geographic map";

export const SHIPMENT_TOPICS = [
  "shipment.created",
  "shipment.picked_up",
  "shipment.in_transit",
  "shipment.delayed",
  "shipment.resumed",
  "shipment.checkpoint_reached",
  "shipment.arrived",
  "shipment.received",
  "shipment.cold_chain_alert",
  "temperature.warning",
  "temperature.critical",
  "temperature.recovered",
];

type Status = { label: string; tone: BadgeTone; icon: string };

export const SHIPMENT_STATUS: Record<string, Status> = {
  created: { label: "Created", tone: "neutral", icon: "○" },
  pickup_pending: { label: "Awaiting pickup", tone: "neutral", icon: "◌" },
  picked_up: { label: "Picked up", tone: "vital", icon: "↑" },
  in_transit: { label: "In transit", tone: "vital", icon: "→" },
  delayed: { label: "Delayed", tone: "warn", icon: "◆" },
  arrived: { label: "Arrived — confirm receipt", tone: "verified", icon: "■" },
  received: { label: "Received", tone: "verified", icon: "✓" },
};

export const ETA_STATUS: Record<string, Status> = {
  on_schedule: { label: "On schedule", tone: "verified", icon: "✓" },
  delayed: { label: "Delayed", tone: "warn", icon: "◆" },
  late: { label: "Past ETA", tone: "critical", icon: "▲" },
  arrived: { label: "Arrived", tone: "verified", icon: "■" },
  delivered: { label: "Delivered", tone: "verified", icon: "✓" },
};

export const COLD_ALERT: Record<string, Status> = {
  none: { label: "No cold-chain alert", tone: "neutral", icon: "–" },
  warning: { label: "Cold-chain warning", tone: "warn", icon: "◆" },
  critical: { label: "Cold-chain critical", tone: "critical", icon: "▲" },
};

export const CHECKPOINT_GLYPH: Record<string, { icon: string; label: string }> = {
  reached: { icon: "●", label: "Reached" },
  confirmed_at_receipt: { icon: "●", label: "Confirmed at receipt" },
  pending: { icon: "○", label: "Not yet reached" },
};

export const TIMELINE_LABEL: Record<string, string> = {
  SHIPMENT_CREATED: "Shipment created (dispatch confirmed)",
  COURIER_ASSIGNED: "Simulated courier assigned",
  SHIPMENT_PICKED_UP: "Picked up at the blood bank",
  SHIPMENT_IN_TRANSIT: "In transit",
  CHECKPOINT_REACHED: "Checkpoint reached",
  SHIPMENT_DELAYED: "Delay (simulated)",
  SHIPMENT_RESUMED: "Resumed",
  SHIPMENT_ARRIVED: "Arrived at the hospital",
  SHIPMENT_RECEIVED: "Receipt confirmed",
  COLD_CHAIN_WARNING: "Cold-chain warning in transit",
  COLD_CHAIN_CRITICAL: "Cold-chain critical in transit",
  COLD_CHAIN_RECOVERED: "Cold chain back in range",
};

export const DELAY_REASONS = [
  { value: "traffic_simulated", label: "Traffic (simulated)" },
  { value: "vehicle_check_simulated", label: "Vehicle check (simulated)" },
  { value: "handover_wait_simulated", label: "Handover wait (simulated)" },
  { value: "weather_simulated", label: "Weather (simulated)" },
] as const;

/** 7 min · 1 h 5 min */
export function formatEta(minutes: number): string {
  const m = Math.max(0, Math.round(minutes));
  if (m < 60) return `${m} min`;
  return `${Math.floor(m / 60)} h${m % 60 ? ` ${m % 60} min` : ""}`;
}
