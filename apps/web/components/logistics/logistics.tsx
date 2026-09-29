"use client";

import type {
  LogisticsResult,
  ShipmentCheckpoint,
  ShipmentDetail,
  ShipmentList,
  ShipmentTelemetry,
  ShipmentTimeline,
} from "@veyra/api-client";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";

import { StatTile } from "@/components/app/page-header";
import { Badge, type BadgeTone } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardLabel } from "@/components/ui/card";
import { Field, InlineAlert, SelectInput, Spinner } from "@/components/ui/field";
import { SimulatedBadge } from "@/components/ui/simulated-badge";
import { EmptyState, ErrorState, Skeleton } from "@/components/ui/states";
import { api } from "@/lib/api";
import { useLiveRefresh } from "@/lib/live";
import {
  CHECKPOINT_GLYPH,
  COLD_ALERT,
  DELAY_REASONS,
  ETA_LABEL,
  ETA_STATUS,
  formatEta,
  LOGISTICS_DISCLAIMER,
  LOGISTICS_LABEL,
  ROUTE_MAP_LABEL,
  SHIPMENT_STATUS,
  SHIPMENT_TOPICS,
  TIMELINE_LABEL,
} from "@/lib/logistics";
import { componentLabel, displayGroup, formatDateTime } from "@/lib/network";
import { toFailure } from "@/lib/problem";
import { useOptionalSession } from "@/lib/session";
import { formatTemp } from "@/lib/telemetry";
import { useReload } from "@/lib/use-reload";

type Loaded<T> = { data?: T; error?: unknown; response: Response };
type SimAction = "advance" | "delay" | "resume" | "arrive";
type DelayReason = (typeof DELAY_REASONS)[number]["value"];

/** Fetch inside the effect (active guard); `version` from useReload() drives refetches. */
function useLoad<T>(load: () => Promise<Loaded<T>>, version: number) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const loader = useRef(load);
  useEffect(() => {
    loader.current = load;
  });
  useEffect(() => {
    let active = true;
    void loader.current().then(({ data: d, error: e, response }) => {
      if (!active) return;
      if (d) {
        setData(d);
        setError(null);
      } else setError(toFailure(e, response).message);
    });
    return () => {
      active = false;
    };
  }, [version]);
  return { data, error };
}

function Pill({ status, map }: { status: string; map: Record<string, { label: string; tone: BadgeTone; icon: string }> }) {
  const s = map[status] ?? { label: status, tone: "neutral" as const, icon: "•" };
  return (
    <Badge tone={s.tone} data-status={status}>
      <span aria-hidden>{s.icon}</span> {s.label}
    </Badge>
  );
}

export function LogisticsDisclaimer() {
  return (
    <div role="note" className="flex flex-wrap items-center gap-3 rounded-md bg-simulated-soft px-4 py-3 text-sm text-simulated" data-testid="logistics-disclaimer">
      <SimulatedBadge subject="Logistics" />
      <span className="font-medium">{LOGISTICS_LABEL}</span>
      <span className="text-xs">{LOGISTICS_DISCLAIMER}</span>
    </div>
  );
}

function Retry({ title, error, onRetry }: { title: string; error: string; onRetry: () => void }) {
  return (
    <ErrorState
      title={title}
      description={error}
      action={
        <Button size="sm" variant="secondary" onClick={onRetry}>
          Try again
        </Button>
      }
    />
  );
}

// ---------------------------------------------------------------- list (bank / hospital)

/** Shipments in scope: bank → dispatched by it; hospital → incoming. */
export function ShipmentsPanel({ kind }: { kind: "HOSPITAL" | "BLOOD_BANK" }) {
  const [version, reload] = useReload();
  useLiveRefresh(SHIPMENT_TOPICS, reload);
  const { data, error } = useLoad<ShipmentList>(() => api.GET("/api/v1/shipments"), version);
  if (error) return <Retry title="Shipments unavailable" error={error} onRetry={reload} />;
  if (!data) return <Skeleton className="h-48 w-full" />;
  const c = data.counts;
  return (
    <section aria-labelledby="shipments-heading" className="flex flex-col gap-4" data-testid="shipments">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 id="shipments-heading" className="text-lg font-medium">
          {kind === "BLOOD_BANK" ? "Logistics — outgoing shipments" : "Incoming shipments"}
        </h2>
        <SimulatedBadge subject="Logistics" />
      </div>
      <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
        <StatTile label="Awaiting pickup" value={c.awaiting_pickup ?? 0} />
        <StatTile label="In transit" value={c.in_transit ?? 0} />
        <StatTile label="Delayed" value={c.delayed ?? 0} note="simulated" />
        <StatTile label={kind === "BLOOD_BANK" ? "Completed today" : "Received today"} value={c.completed_today ?? 0} />
        <StatTile label="Cold-chain alerts" value={c.cold_chain_alerts ?? 0} note="simulated telemetry" />
      </div>
      {data.shipments.length === 0 ? (
        <EmptyState
          title="No shipments yet"
          description="A shipment starts when a blood bank confirms dispatch of recommended bags."
        />
      ) : (
        <Card className="overflow-x-auto p-0">
          <table className="w-full min-w-[760px] text-sm" data-testid="shipments-table">
            <caption className="sr-only">Shipments with simulated ETA</caption>
            <thead>
              <tr className="border-b border-line text-left text-ink-subtle">
                <th scope="col" className="px-4 py-2 font-medium">Shipment</th>
                <th scope="col" className="px-3 py-2 font-medium">Status</th>
                <th scope="col" className="px-3 py-2 font-medium">{kind === "BLOOD_BANK" ? "To" : "From"}</th>
                <th scope="col" className="px-3 py-2 font-medium">ETA (simulated)</th>
                <th scope="col" className="px-3 py-2 font-medium">Checkpoint</th>
                <th scope="col" className="px-3 py-2 font-medium">Cold chain</th>
              </tr>
            </thead>
            <tbody>
              {data.shipments.map((s) => (
                <tr key={s.id} className="border-b border-line last:border-0" data-shipment={s.id}>
                  <th scope="row" className="px-4 py-2 text-left font-normal">
                    <Link href={`/shipments/${s.id}`} className="font-mono underline-offset-4 hover:underline">
                      {s.reference}
                    </Link>
                    <span className="block text-xs text-ink-subtle">
                      {s.bag_count} × {displayGroup(s.blood_group)} {componentLabel(s.component)} · {s.request_reference}
                    </span>
                  </th>
                  <td className="px-3 py-2">
                    <Pill status={s.status} map={SHIPMENT_STATUS} />
                  </td>
                  <td className="px-3 py-2 text-ink-muted">{kind === "BLOOD_BANK" ? s.destination_name : s.source_name}</td>
                  <td className="px-3 py-2">
                    <Pill status={s.eta.status} map={ETA_STATUS} />
                    {s.eta.status !== "delivered" && s.eta.status !== "arrived" && (
                      <span className="block text-xs text-ink-subtle tabular-nums">
                        {formatEta(s.eta.remaining_minutes)} · {formatDateTime(s.eta.eta_at)}
                        {s.eta.delay_minutes > 0 && ` · +${s.eta.delay_minutes} min delay`}
                      </span>
                    )}
                  </td>
                  <td className="px-3 py-2 text-ink-muted">{s.current_checkpoint_name ?? "Not picked up yet"}</td>
                  <td className="px-3 py-2">
                    <Pill status={s.cold_chain_alert} map={COLD_ALERT} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}
      <p className="text-2xs text-ink-subtle">{LOGISTICS_DISCLAIMER}</p>
    </section>
  );
}

// ---------------------------------------------------------------- route (schematic)

export function RouteVisual({ checkpoints, current }: { checkpoints: ShipmentCheckpoint[]; current: number }) {
  return (
    <figure className="flex flex-col gap-3" aria-labelledby="route-caption" data-testid="route-visual">
      <figcaption id="route-caption" className="flex flex-wrap items-center gap-2 text-sm font-medium">
        {ROUTE_MAP_LABEL}
      </figcaption>
      <ol className="flex flex-col gap-0 md:flex-row md:items-start" aria-label="Route checkpoints">
        {checkpoints.map((c, i) => {
          const g = CHECKPOINT_GLYPH[c.status] ?? { icon: "○", label: c.status };
          const reached = c.status !== "pending";
          return (
            <li
              key={c.seq}
              className="relative flex gap-3 pb-4 md:flex-1 md:flex-col md:items-center md:pb-0 md:text-center"
              aria-current={c.seq === current ? "step" : undefined}
              data-checkpoint={c.seq}
              data-reached={reached}
            >
              {i < checkpoints.length - 1 && (
                <span
                  aria-hidden
                  className={`absolute top-6 left-2.5 h-[calc(100%-1rem)] w-0.5 md:top-2.5 md:left-1/2 md:h-0.5 md:w-full ${reached ? "bg-vital" : "bg-line-strong"}`}
                />
              )}
              <span
                aria-hidden
                className={`relative z-10 flex size-5 shrink-0 items-center justify-center rounded-full bg-surface-raised text-sm ${c.seq === current ? "text-vital motion-safe:animate-pulse" : reached ? "text-vital" : "text-ink-subtle"}`}
              >
                {c.seq === current ? "◉" : g.icon}
              </span>
              <span className="flex flex-col text-xs md:mt-2">
                <span className="font-medium text-ink">{c.name}</span>
                <span className="text-ink-subtle">
                  {g.label}
                  {c.seq === current && " · current"} · {c.distance_km} km
                </span>
                <span className="text-ink-subtle tabular-nums">
                  {c.actual_at ? `at ${formatDateTime(c.actual_at)}` : `expected ${formatDateTime(c.expected_at)}`}
                </span>
              </span>
            </li>
          );
        })}
      </ol>
      <p className="text-2xs text-ink-subtle">Schematic checkpoints and simulated distances — no GPS, maps or traffic data.</p>
    </figure>
  );
}

function CheckpointTable({ checkpoints }: { checkpoints: ShipmentCheckpoint[] }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[560px] text-sm" data-testid="checkpoint-table">
        <caption className="sr-only">Route checkpoints (simulated)</caption>
        <thead>
          <tr className="border-b border-line text-left text-ink-subtle">
            <th scope="col" className="py-2 pr-3 font-medium">#</th>
            <th scope="col" className="py-2 pr-3 font-medium">Checkpoint</th>
            <th scope="col" className="py-2 pr-3 text-right font-medium">Distance</th>
            <th scope="col" className="py-2 pr-3 font-medium">Expected</th>
            <th scope="col" className="py-2 pr-3 font-medium">Actual</th>
            <th scope="col" className="py-2 font-medium">Status</th>
          </tr>
        </thead>
        <tbody>
          {checkpoints.map((c) => (
            <tr key={c.seq} className="border-b border-line last:border-0">
              <th scope="row" className="py-1.5 pr-3 text-left font-normal tabular-nums">{c.seq}</th>
              <td className="py-1.5 pr-3">{c.name}</td>
              <td className="py-1.5 pr-3 text-right tabular-nums">{c.distance_km} km</td>
              <td className="py-1.5 pr-3 text-ink-muted">{formatDateTime(c.expected_at)}</td>
              <td className="py-1.5 pr-3 text-ink-muted">{c.actual_at ? formatDateTime(c.actual_at) : "—"}</td>
              <td className="py-1.5">{CHECKPOINT_GLYPH[c.status]?.label ?? c.status}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ---------------------------------------------------------------- timeline + cold chain

export function ShipmentTimelineList({ timeline }: { timeline: ShipmentTimeline }) {
  return (
    <ol className="flex flex-col gap-3 border-l border-line pl-5" aria-label="Shipment timeline" data-testid="shipment-timeline">
      {timeline.events.map((e) => {
        const warn = e.event_type.startsWith("COLD_CHAIN_") && e.event_type !== "COLD_CHAIN_RECOVERED";
        const delay = e.event_type === "SHIPMENT_DELAYED";
        return (
          <li key={e.seq} className="relative text-sm" data-event={e.event_type}>
            <span aria-hidden className={`absolute top-1 -left-[26px] size-2.5 rounded-full ${warn ? "bg-critical" : delay ? "bg-warn" : "bg-vital"}`} />
            <p className="font-medium">
              {warn && <span aria-hidden>▲ </span>}
              {delay && <span aria-hidden>◆ </span>}
              {TIMELINE_LABEL[e.event_type] ?? e.event_type}
              {delay && typeof e.meta.minutes === "number" && ` +${e.meta.minutes} min`}
              {e.event_type === "CHECKPOINT_REACHED" && typeof e.meta.checkpoint_name === "string" && `: ${e.meta.checkpoint_name}`}
              {e.meta.confirmed_at_receipt === true && " (confirmed at receipt)"}
            </p>
            <p className="text-xs text-ink-subtle">
              <time dateTime={e.occurred_at}>{formatDateTime(e.occurred_at)}</time> · status {SHIPMENT_STATUS[e.status]?.label ?? e.status}
            </p>
          </li>
        );
      })}
    </ol>
  );
}

export function ShipmentColdChain({ telemetry }: { telemetry: ShipmentTelemetry }) {
  return (
    <div className="flex flex-col gap-3" data-testid="shipment-cold-chain">
      <div className="flex flex-wrap items-center gap-2">
        <Pill status={telemetry.cold_chain_alert} map={COLD_ALERT} />
        {telemetry.cold_chain_alert !== "none" && (
          <span className="text-xs text-ink-muted">Flagged for human review — nothing is discarded or received automatically.</span>
        )}
      </div>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[560px] text-sm">
          <caption className="sr-only">Cold-chain state of the bags in this shipment</caption>
          <thead>
            <tr className="border-b border-line text-left text-ink-subtle">
              <th scope="col" className="py-2 pr-3 font-medium">Bag</th>
              <th scope="col" className="py-2 pr-3 font-medium">Cold chain</th>
              <th scope="col" className="py-2 pr-3 text-right font-medium">Latest</th>
              <th scope="col" className="py-2 pr-3 font-medium">Device</th>
              <th scope="col" className="py-2 font-medium">Last telemetry</th>
            </tr>
          </thead>
          <tbody>
            {telemetry.bags.map((b) => (
              <tr key={b.public_id} className="border-b border-line last:border-0">
                <th scope="row" className="py-1.5 pr-3 text-left font-mono font-normal">{b.public_id}</th>
                <td className="py-1.5 pr-3">
                  {b.monitored ? b.cold_chain_status : "Not monitored"}
                  {b.excursion_active && <Badge tone="critical" className="ml-2"><span aria-hidden>▲</span> Active excursion</Badge>}
                </td>
                <td className="py-1.5 pr-3 text-right tabular-nums">{formatTemp(b.latest_temperature_c)}</td>
                <td className="py-1.5 pr-3 text-ink-muted">{b.device_id ? `${b.device_id} · ${b.device_status ?? ""}` : "—"}</td>
                <td className="py-1.5 text-ink-muted">{b.last_telemetry_at ? formatDateTime(b.last_telemetry_at) : "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="text-2xs text-ink-subtle">{telemetry.note}</p>
    </div>
  );
}

// ---------------------------------------------------------------- detail page

async function simulate(id: string, action: SimAction, delay?: { minutes: number; reason: DelayReason }) {
  const params = { params: { path: { shipment_id: id } } };
  switch (action) {
    case "advance":
      return api.POST("/api/v1/simulator/shipments/{shipment_id}/advance", params);
    case "delay":
      return api.POST("/api/v1/simulator/shipments/{shipment_id}/delay", { ...params, body: delay ?? { minutes: 18, reason: "traffic_simulated" } });
    case "resume":
      return api.POST("/api/v1/simulator/shipments/{shipment_id}/resume", params);
    case "arrive":
      return api.POST("/api/v1/simulator/shipments/{shipment_id}/arrive", params);
    default: {
      const unreachable: never = action;
      throw new Error(`unknown action ${String(unreachable)}`);
    }
  }
}

export function ShipmentDetailView({ shipmentId }: { shipmentId: string }) {
  const me = useOptionalSession()?.me ?? null;
  const [version, reload] = useReload();
  useLiveRefresh(SHIPMENT_TOPICS, reload);
  const detail = useLoad<ShipmentDetail>(
    () => api.GET("/api/v1/shipments/{shipment_id}", { params: { path: { shipment_id: shipmentId } } }),
    version,
  );
  const timeline = useLoad<ShipmentTimeline>(
    () => api.GET("/api/v1/shipments/{shipment_id}/timeline", { params: { path: { shipment_id: shipmentId } } }),
    version,
  );
  const [busy, setBusy] = useState<string | null>(null);
  const [notice, setNotice] = useState<{ tone: "error" | "success" | "info"; text: string } | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [delayMinutes, setDelayMinutes] = useState(18);
  const [delayReason, setDelayReason] = useState<DelayReason>("traffic_simulated");
  const [view, setView] = useState<"route" | "table">("route");

  if (detail.error) {
    const notFound = /not found/i.test(detail.error);
    return notFound ? (
      <EmptyState title="Shipment not found" description="You can only see shipments your facility sent or is receiving." />
    ) : (
      <Retry title="Shipment unavailable" error={detail.error} onRetry={reload} />
    );
  }
  const s = detail.data;
  if (!s) return <Skeleton className="h-96 w-full" />;
  const isSource = me?.facility?.id === s.source_facility_id && me.user.role === "BLOOD_BANK";
  const isDestination = me?.facility?.id === s.destination_facility_id && me.user.role === "HOSPITAL";

  async function act(action: SimAction) {
    setBusy(action);
    setNotice(null);
    const { data, error: e, response } = await simulate(shipmentId, action, action === "delay" ? { minutes: delayMinutes, reason: delayReason } : undefined);
    setBusy(null);
    setNotice(data ? { tone: "info", text: `${(data as LogisticsResult).action}: now ${SHIPMENT_STATUS[(data as LogisticsResult).shipment.status]?.label ?? ""}` } : { tone: "error", text: toFailure(e, response).message });
    reload();
  }

  async function receive() {
    setBusy("receive");
    const { data, error: e, response } = await api.POST("/api/v1/shipments/{shipment_id}/receive", {
      params: { path: { shipment_id: shipmentId } },
    });
    setBusy(null);
    setConfirming(false);
    setNotice(data ? { tone: "success", text: "Receipt confirmed. The request is fulfilled and the bags are recorded as received." } : { tone: "error", text: toFailure(e, response).message });
    reload();
  }

  return (
    <div className="flex flex-col gap-6" data-testid="shipment-detail">
      <LogisticsDisclaimer />
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <p className="text-2xs font-semibold tracking-(--tracking-label) text-ink-subtle uppercase">Shipment</p>
          <h1 className="font-mono text-2xl">{s.reference}</h1>
          <p className="text-sm text-ink-muted">
            {s.source_name} → {s.destination_name} · request <span className="font-mono">{s.request_reference}</span> ({s.request_status})
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Pill status={s.status} map={SHIPMENT_STATUS} />
          <Pill status={s.cold_chain_alert} map={COLD_ALERT} />
          <Badge tone={s.trace_valid ? "verified" : "critical"}>
            <span aria-hidden>{s.trace_valid ? "✓" : "▲"}</span> {s.trace_valid ? "Trace chain verified" : "Trace chain broken"}
          </Badge>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <StatTile
          label="ETA (simulated)"
          value={s.eta.status === "delivered" || s.eta.status === "arrived" ? ETA_STATUS[s.eta.status]?.label ?? "" : formatEta(s.eta.remaining_minutes)}
          note={`${ETA_STATUS[s.eta.status]?.label ?? s.eta.status} · ${formatDateTime(s.eta.eta_at)}`}
        />
        <StatTile label="Delay" value={s.eta.delay_minutes ? `+${s.eta.delay_minutes} min` : "None"} note={s.eta.delay_active ? "Active (simulated)" : undefined} />
        <StatTile label="Courier (simulated)" value={<span className="text-lg">{s.courier.name}</span>} note={`${s.courier.courier_id} · ${s.courier.vehicle_type}`} />
        <StatTile label="Route" value={`${s.distance_km} km`} note={`planned ${formatEta(s.planned_minutes)} · ${s.current_checkpoint_name ?? "awaiting pickup"}`} />
      </div>
      {s.eta.status === "delayed" && (
        <InlineAlert tone="info">
          <span aria-hidden>◆ </span>Delayed +{s.eta.delay_minutes} min (simulated). The ETA holds until the shipment resumes.
        </InlineAlert>
      )}
      <p className="text-2xs text-ink-subtle">{ETA_LABEL}. {s.eta.reasons.join(" · ")}</p>
      {notice && <InlineAlert tone={notice.tone}>{notice.text}</InlineAlert>}

      {isSource && s.simulator_enabled && s.status !== "received" && (
        <Card className="flex flex-col gap-3 p-4" data-testid="logistics-controls">
          <CardLabel>Demo logistics controls (simulated)</CardLabel>
          <div className="flex flex-wrap items-end gap-2">
            <Button size="sm" variant="secondary" disabled={busy !== null} onClick={() => void act("advance")}>
              {busy === "advance" && <Spinner />}Advance shipment
            </Button>
            <Field label="Delay minutes" className="w-32">
              {(p) => (
                <SelectInput {...p} value={String(delayMinutes)} onChange={(e) => setDelayMinutes(Number(e.target.value))}>
                  {[10, 18, 30, 60].map((m) => (
                    <option key={m} value={m}>
                      +{m} min
                    </option>
                  ))}
                </SelectInput>
              )}
            </Field>
            <Field label="Delay reason" className="w-56">
              {(p) => (
                <SelectInput {...p} value={delayReason} onChange={(e) => setDelayReason(e.target.value as DelayReason)}>
                  {DELAY_REASONS.map((r) => (
                    <option key={r.value} value={r.value}>
                      {r.label}
                    </option>
                  ))}
                </SelectInput>
              )}
            </Field>
            <Button size="sm" variant="secondary" disabled={busy !== null} onClick={() => void act("delay")}>
              Inject delay
            </Button>
            <Button size="sm" variant="secondary" disabled={busy !== null} onClick={() => void act("resume")}>
              Resume
            </Button>
            <Button size="sm" variant="secondary" disabled={busy !== null} onClick={() => void act("arrive")}>
              Arrive
            </Button>
          </div>
          <p className="text-2xs text-ink-subtle">Deterministic simulation. The hospital confirms receipt; nothing is received automatically.</p>
        </Card>
      )}

      {isDestination && s.status === "arrived" && (
        <Card className="flex flex-col gap-3 p-4" data-testid="receive">
          <CardLabel>Confirm receipt</CardLabel>
          {!confirming ? (
            <div>
              <Button variant="vital" size="sm" onClick={() => setConfirming(true)}>
                Receive shipment…
              </Button>
            </div>
          ) : (
            <div role="group" aria-label="Confirm receipt" className="flex flex-wrap items-center gap-2">
              <span className="text-sm">Confirm {s.bag_count} bag(s) physically received?</span>
              <Button variant="vital" size="sm" disabled={busy !== null} onClick={() => void receive()}>
                {busy === "receive" && <Spinner />}Confirm receipt
              </Button>
              <Button variant="ghost" size="sm" disabled={busy !== null} onClick={() => setConfirming(false)}>
                Cancel
              </Button>
            </div>
          )}
        </Card>
      )}

      <Card className="flex flex-col gap-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <CardLabel>Route</CardLabel>
          <div className="flex gap-1" role="group" aria-label="Route view">
            <Button size="sm" variant={view === "route" ? "primary" : "ghost"} aria-pressed={view === "route"} onClick={() => setView("route")}>
              Schematic
            </Button>
            <Button size="sm" variant={view === "table" ? "primary" : "ghost"} aria-pressed={view === "table"} onClick={() => setView("table")}>
              Table
            </Button>
          </div>
        </div>
        {view === "route" ? <RouteVisual checkpoints={s.checkpoints} current={s.current_checkpoint} /> : <CheckpointTable checkpoints={s.checkpoints} />}
      </Card>

      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardLabel>Timeline</CardLabel>
          <div className="mt-3">
            {timeline.error ? (
              <Retry title="Timeline unavailable" error={timeline.error} onRetry={reload} />
            ) : timeline.data ? (
              <ShipmentTimelineList timeline={timeline.data} />
            ) : (
              <Skeleton className="h-40 w-full" />
            )}
          </div>
        </Card>
        <Card>
          <CardLabel>Cold chain in transit</CardLabel>
          <div className="mt-3">
            <ShipmentColdChain telemetry={s.telemetry} />
          </div>
        </Card>
      </div>

      <Card>
        <CardLabel>Bags</CardLabel>
        <ul className="mt-2 flex flex-col divide-y divide-line">
          {s.bags.map((b) => (
            <li key={b.public_id} className="flex flex-wrap items-center justify-between gap-3 py-2 text-sm">
              <Link href={`/bags/${b.public_id}`} className="font-mono underline-offset-4 hover:underline">
                {b.public_id}
              </Link>
              <span className="text-ink-muted">
                {displayGroup(b.blood_group)} · {componentLabel(b.component)} · {b.status} · expires {formatDateTime(b.expires_at)}
              </span>
              <Badge tone={b.chain_valid ? "verified" : "critical"}>
                <span aria-hidden>{b.chain_valid ? "✓" : "▲"}</span> {b.chain_valid ? `Chain verified · ${b.chain_length} events` : "Chain broken"}
              </Badge>
            </li>
          ))}
        </ul>
      </Card>
    </div>
  );
}

// ---------------------------------------------------------------- admin

export function AdminLogistics() {
  const [version, reload] = useReload();
  useLiveRefresh(SHIPMENT_TOPICS, reload);
  const { data, error } = useLoad<ShipmentList>(() => api.GET("/api/v1/shipments"), version);
  if (error) return <Retry title="Logistics overview unavailable" error={error} onRetry={reload} />;
  if (!data) return <Skeleton className="h-32 w-full" />;
  const c = data.counts;
  return (
    <section aria-labelledby="admin-logistics-heading" className="flex flex-col gap-4" data-testid="admin-logistics">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 id="admin-logistics-heading" className="text-lg font-medium">
          Network shipments
        </h2>
        <SimulatedBadge subject="Logistics" />
      </div>
      <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
        <StatTile label="Shipments" value={data.shipments.length} />
        <StatTile label="In transit" value={(c.in_transit ?? 0) + (c.awaiting_pickup ?? 0)} note={`${c.awaiting_pickup ?? 0} awaiting pickup`} />
        <StatTile label="Delayed" value={c.delayed ?? 0} />
        <StatTile label="Avg delivery (simulated)" value={data.average_delivery_minutes === null ? "—" : formatEta(data.average_delivery_minutes)} />
        <StatTile label="Cold-chain alerts" value={c.cold_chain_alerts ?? 0} />
      </div>
      <p className="text-sm text-ink-muted" data-testid="route-status-summary">
        Route status: {c.on_schedule ?? 0} on schedule · {c.delayed ?? 0} delayed · {c.late ?? 0} past ETA · {c.arrived ?? 0} arrived
      </p>
      <p className="text-2xs text-ink-subtle">{LOGISTICS_DISCLAIMER}</p>
    </section>
  );
}
