"use client";

import type {
  BagOut,
  ColdChainReport,
  MonitoredList,
  SimulatorResult,
  TelemetryDevice,
  TelemetrySeries,
  TelemetrySummary,
} from "@veyra/api-client";
import Link from "next/link";
import { useEffect, useState } from "react";

import { StatTile } from "@/components/app/page-header";
import { TelemetryChart } from "@/components/charts/telemetry-chart";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardLabel } from "@/components/ui/card";
import { InlineAlert, Spinner } from "@/components/ui/field";
import { SimulatedBadge } from "@/components/ui/simulated-badge";
import { EmptyState, ErrorState, Skeleton } from "@/components/ui/states";
import { api } from "@/lib/api";
import { useLive } from "@/lib/live";
import { componentLabel, displayGroup, formatDateTime } from "@/lib/network";
import { toFailure } from "@/lib/problem";
import {
  COLD_STATUS,
  DEVICE_STATUS,
  formatDuration,
  formatTemp,
  TELEMETRY_BADGE,
  TELEMETRY_DISCLAIMER,
  TELEMETRY_TOPICS,
} from "@/lib/telemetry";
import { useReload } from "@/lib/use-reload";

type SimAction = "attach" | "start" | "pause" | "tick" | "excursion" | "recover";

const TRANSITION_TEXT: Record<string, string> = {
  "temperature.warning": "Warning: temperature left the normal range.",
  "temperature.critical": "Critical: temperature passed the critical limit.",
  "temperature.recovered": "Recovered: temperature is back in the normal range.",
  DEVICE_ATTACHED: "Simulated device attached. Monitoring is recorded in the bag's trace.",
};

export function TelemetryDisclaimer() {
  return (
    <div role="note" className="flex flex-wrap items-center gap-3 rounded-md bg-simulated-soft px-4 py-3 text-sm text-simulated" data-testid="telemetry-disclaimer">
      <SimulatedBadge subject="IoT telemetry" />
      <span className="font-medium">{TELEMETRY_BADGE}</span>
      <span className="text-xs">{TELEMETRY_DISCLAIMER}</span>
    </div>
  );
}

function StatusBadge({ status }: { status: string }) {
  const s = COLD_STATUS[status] ?? { label: status, tone: "neutral" as const };
  return (
    <Badge tone={s.tone} dot data-cold-status={status}>
      {s.label}
    </Badge>
  );
}

function DeviceBadge({ status }: { status: string }) {
  const s = DEVICE_STATUS[status] ?? { label: status, tone: "neutral" as const };
  return <Badge tone={s.tone}>{s.label}</Badge>;
}

/** Re-run `reload` when a telemetry event arrives (optionally only for one bag). */
function useTelemetryRefresh(reload: () => void, publicId?: string) {
  const { subscribe } = useLive();
  useEffect(
    () =>
      subscribe(TELEMETRY_TOPICS, (event) => {
        if (!publicId || event.aggregate_id === publicId) reload();
      }),
    [subscribe, reload, publicId],
  );
}

async function simulate(publicId: string, action: SimAction, count = 1) {
  const params = { params: { path: { public_id: publicId } } };
  // Separate typed calls keep openapi-fetch's path typing intact.
  switch (action) {
    case "attach":
      return api.POST("/api/v1/simulator/bags/{public_id}/attach", params);
    case "start":
      return api.POST("/api/v1/simulator/bags/{public_id}/start", params);
    case "pause":
      return api.POST("/api/v1/simulator/bags/{public_id}/pause", params);
    case "excursion":
      return api.POST("/api/v1/simulator/bags/{public_id}/excursion", params);
    case "recover":
      return api.POST("/api/v1/simulator/bags/{public_id}/recover", params);
    case "tick":
      return api.POST("/api/v1/simulator/bags/{public_id}/tick", { ...params, body: { count } });
    default: {
      const unreachable: never = action;
      throw new Error(`unknown simulator action ${String(unreachable)}`);
    }
  }
}

// ---------------------------------------------------------------- blood-bank monitor

/** Blood bank "Cold chain" tab: every monitored bag at this facility (simulated). */
export function SmartBagMonitor() {
  const [data, setData] = useState<MonitoredList | null>(null);
  const [unmonitored, setUnmonitored] = useState<BagOut[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [version, reload] = useReload();
  useTelemetryRefresh(reload);

  useEffect(() => {
    let active = true;
    void Promise.all([
      api.GET("/api/v1/telemetry/monitored"),
      api.GET("/api/v1/inventory/bags", { params: { query: { status: "available", limit: 50 } } }),
    ]).then(([m, b]) => {
      if (!active) return;
      if (m.data) {
        setData(m.data);
        setError(null);
        const monitored = new Set(m.data.bags.map((x) => x.public_id));
        setUnmonitored((b.data?.data ?? []).filter((x) => !monitored.has(x.public_id)).slice(0, 8));
      } else setError(toFailure(m.error, m.response).message);
    });
    return () => {
      active = false;
    };
  }, [version]);

  async function attach(publicId: string) {
    setBusy(publicId);
    const { error: e, response } = await simulate(publicId, "attach");
    setBusy(null);
    setNotice(e ? toFailure(e, response).message : `Simulated device attached to ${publicId}.`);
    reload();
  }

  if (error) {
    return (
      <ErrorState
        title="Cold-chain view unavailable"
        description={error}
        action={
          <Button size="sm" variant="secondary" onClick={reload}>
            Try again
          </Button>
        }
      />
    );
  }
  if (!data) return <Skeleton className="h-64 w-full" />;

  const c = data.counts;
  const stale = (c.offline ?? 0) + (c.paused ?? 0);
  return (
    <div className="flex flex-col gap-6" data-testid="smart-bag-monitor">
      <TelemetryDisclaimer />
      <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
        <StatTile label="Monitored bags" value={data.bags.length} />
        <StatTile label="Normal" value={c.normal ?? 0} />
        <StatTile label="Warning" value={c.warning ?? 0} note={(c.warning ?? 0) > 0 ? "Outside normal range" : undefined} />
        <StatTile label="Critical" value={c.critical ?? 0} note={(c.critical ?? 0) > 0 ? "Past critical limit" : undefined} />
        <StatTile label="Offline / paused" value={stale} note={`${c.awaiting ?? 0} awaiting first reading`} />
      </div>
      {notice && <InlineAlert tone="info">{notice}</InlineAlert>}

      {data.bags.length === 0 ? (
        <EmptyState
          title="No monitored bags yet"
          description="Attach a simulated smart-bag device to a bag below to start cold-chain monitoring. No hardware is involved."
        />
      ) : (
        <Card className="overflow-x-auto p-0">
          <table className="w-full min-w-[760px] text-sm" data-testid="monitored-table">
            <thead>
              <tr className="border-b border-line text-left text-ink-subtle">
                <th scope="col" className="px-5 py-3 font-medium">Bag</th>
                <th scope="col" className="px-3 py-3 font-medium">Cold chain</th>
                <th scope="col" className="px-3 py-3 text-right font-medium">Latest</th>
                <th scope="col" className="px-3 py-3 font-medium">Last reading</th>
                <th scope="col" className="px-3 py-3 text-right font-medium">Battery</th>
                <th scope="col" className="px-3 py-3 font-medium">Device</th>
                <th scope="col" className="px-3 py-3 text-right font-medium">Excursion</th>
              </tr>
            </thead>
            <tbody>
              {data.bags.map((b) => (
                <tr key={b.public_id} className="border-b border-line last:border-0" data-bag={b.public_id}>
                  <td className="px-5 py-2.5">
                    <Link href={`/bags/${b.public_id}`} className="font-mono underline-offset-4 hover:underline">
                      {b.public_id}
                    </Link>
                    <span className="ml-2 text-xs text-ink-subtle">
                      {displayGroup(b.blood_group)} · {componentLabel(b.component)}
                    </span>
                  </td>
                  <td className="px-3 py-2.5">
                    <StatusBadge status={b.cold_chain_status} />
                  </td>
                  <td className="px-3 py-2.5 text-right tabular-nums">{formatTemp(b.current_c)}</td>
                  <td className="px-3 py-2.5 text-ink-muted">{b.last_reading_at ? formatDateTime(b.last_reading_at) : "—"}</td>
                  <td className="px-3 py-2.5 text-right tabular-nums">{b.battery_pct.toFixed(0)}%</td>
                  <td className="px-3 py-2.5">
                    <DeviceBadge status={b.device_status} />
                  </td>
                  <td className="px-3 py-2.5 text-right">{formatDuration(b.excursion_duration_seconds)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}

      {data.simulator_enabled && unmonitored.length > 0 && (
        <Card>
          <CardLabel>Start monitoring</CardLabel>
          <p className="mt-1 text-xs text-ink-subtle">Bags in storage without a simulated device.</p>
          <ul className="mt-3 flex flex-col divide-y divide-line">
            {unmonitored.map((b) => (
              <li key={b.id} className="flex flex-wrap items-center justify-between gap-3 py-2 text-sm">
                <span>
                  <span className="font-mono">{b.public_id}</span>{" "}
                  <span className="text-xs text-ink-subtle">
                    {displayGroup(b.blood_group)} · {componentLabel(b.component)}
                  </span>
                </span>
                <Button size="sm" variant="secondary" disabled={busy !== null} onClick={() => void attach(b.public_id)}>
                  {busy === b.public_id && <Spinner />}Attach simulated device
                </Button>
              </li>
            ))}
          </ul>
        </Card>
      )}
    </div>
  );
}

// ---------------------------------------------------------------- bag detail

interface BagTelemetry {
  device: TelemetryDevice;
  summary: TelemetrySummary;
  series: TelemetrySeries;
  report: ColdChainReport;
}

/** Bag page: device, current state, chart/table, excursions, and demo simulator controls. */
export function BagTelemetryPanel({ publicId, canSimulate }: { publicId: string; canSimulate: boolean }) {
  const [data, setData] = useState<BagTelemetry | null>(null);
  const [state, setState] = useState<"loading" | "ready" | "none" | "error">("loading");
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<{ tone: "info" | "error" | "success"; text: string } | null>(null);
  const [busy, setBusy] = useState<SimAction | null>(null);
  const [version, reload] = useReload();
  useTelemetryRefresh(reload, publicId);

  useEffect(() => {
    let active = true;
    const path = { params: { path: { public_id: publicId } } };
    void api.GET("/api/v1/bags/{public_id}/device", path).then(async ({ data: device, error: e, response }) => {
      if (!active) return;
      if (!device) {
        if (response.status === 404 && (e as { code?: string } | undefined)?.code === "no_device") {
          setState("none");
        } else {
          setError(toFailure(e, response).message);
          setState("error");
        }
        return;
      }
      const [summary, series, report] = await Promise.all([
        api.GET("/api/v1/bags/{public_id}/telemetry/summary", path),
        api.GET("/api/v1/bags/{public_id}/telemetry", { params: { path: { public_id: publicId }, query: { limit: 120 } } }),
        api.GET("/api/v1/bags/{public_id}/cold-chain", path),
      ]);
      if (!active) return;
      if (summary.data && series.data && report.data) {
        setData({ device, summary: summary.data, series: series.data, report: report.data });
        setState("ready");
      } else {
        const failed = !summary.data ? summary : !series.data ? series : report;
        setError(toFailure(failed.error, failed.response).message);
        setState("error");
      }
    });
    return () => {
      active = false;
    };
  }, [publicId, version]);

  async function act(action: SimAction, count = 1) {
    setBusy(action);
    setNotice(null);
    const { data: res, error: e, response } = await simulate(publicId, action, count);
    setBusy(null);
    if (!res) {
      setNotice({ tone: "error", text: toFailure(e, response).message });
    } else {
      const t = (res as SimulatorResult).transitions;
      if (t.length) setNotice({ tone: t.includes("temperature.recovered") ? "success" : "info", text: t.map((x) => TRANSITION_TEXT[x] ?? x).join(" ") });
    }
    reload();
  }

  return (
    <section aria-labelledby="telemetry-heading" className="mt-6 flex flex-col gap-4" data-testid="bag-telemetry">
      <h2 id="telemetry-heading" className="text-lg font-medium">
        Cold chain
      </h2>
      <TelemetryDisclaimer />
      {state === "loading" && <Skeleton className="h-64 w-full" />}
      {state === "error" && (
        <ErrorState
          title="Telemetry unavailable"
          description={error ?? "Please try again."}
          action={
            <Button size="sm" variant="secondary" onClick={reload}>
              Try again
            </Button>
          }
        />
      )}
      {state === "none" && (
        <EmptyState
          title="Not monitored"
          description="This bag has no simulated smart-bag device yet."
          action={
            canSimulate ? (
              <Button size="sm" onClick={() => void act("attach")} disabled={busy !== null}>
                {busy === "attach" && <Spinner />}Attach simulated device
              </Button>
            ) : undefined
          }
        />
      )}
      {notice && <InlineAlert tone={notice.tone}>{notice.text}</InlineAlert>}
      {state === "ready" && data && (
        <>
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            <StatTile label="Cold chain" value={<StatusBadge status={data.summary.cold_chain_status} />} note={data.summary.thresholds.label} />
            <StatTile label="Current temperature" value={formatTemp(data.summary.current_c)} note={`min ${formatTemp(data.summary.min_c)} · max ${formatTemp(data.summary.max_c)}`} />
            <StatTile label="Battery" value={`${data.device.battery_pct.toFixed(0)}%`} note={DEVICE_STATUS[data.device.device_status]?.label} />
            <StatTile
              label="Excursion"
              value={data.summary.excursion_active ? formatDuration(data.summary.excursion_duration_seconds) : "None"}
              note={data.summary.excursion_active ? `since ${data.summary.excursion_started_at ? formatDateTime(data.summary.excursion_started_at) : ""}` : `${data.report.excursions.length} past excursions`}
            />
          </div>
          <Card className="flex flex-wrap items-center gap-x-6 gap-y-2 p-4 text-sm">
            <span>
              <span className="text-ink-subtle">Device </span>
              <span className="font-mono" data-testid="device-id">{data.device.device_id}</span>
            </span>
            <span>
              <span className="text-ink-subtle">RFID (simulated) </span>
              <span className="font-mono">{data.device.rfid}</span>
            </span>
            <span className="text-ink-subtle">
              Last reading {data.summary.last_reading_at ? formatDateTime(data.summary.last_reading_at) : "—"} · {data.device.readings_count} readings
            </span>
            <DeviceBadge status={data.device.device_status} />
          </Card>
          {canSimulate && (
            <Card className="p-4">
              <CardLabel>Demo simulator</CardLabel>
              <p className="mt-1 text-xs text-ink-subtle">Deterministic simulated readings. No hardware is contacted.</p>
              <div className="mt-3 flex flex-wrap gap-2">
                <Button size="sm" variant="secondary" disabled={busy !== null} onClick={() => void act("tick", 1)}>
                  {busy === "tick" && <Spinner />}Take reading
                </Button>
                {data.device.sim_running ? (
                  <Button size="sm" variant="secondary" disabled={busy !== null} onClick={() => void act("pause")}>
                    Pause live readings
                  </Button>
                ) : (
                  <Button size="sm" variant="secondary" disabled={busy !== null} onClick={() => void act("start")}>
                    Start live readings
                  </Button>
                )}
                <Button size="sm" variant="vital" disabled={busy !== null} onClick={() => void act("excursion")}>
                  Inject excursion
                </Button>
                <Button size="sm" variant="ghost" disabled={busy !== null} onClick={() => void act("recover")}>
                  Restore normal temperature
                </Button>
              </div>
              <p className="mt-2 text-2xs text-ink-subtle">
                Mode: {data.device.sim_mode}. After injecting, take readings to see warning, then critical.
              </p>
            </Card>
          )}
          <Card>
            <TelemetryChart readings={data.series.readings} thresholds={data.series.thresholds} />
          </Card>
          <Card>
            <CardLabel>Excursions</CardLabel>
            {data.report.excursions.length === 0 ? (
              <p className="mt-2 text-sm text-ink-muted">No temperature excursions recorded.</p>
            ) : (
              <ul className="mt-2 flex flex-col divide-y divide-line" data-testid="excursions">
                {data.report.excursions.map((x) => (
                  <li key={x.started_at} className="flex flex-wrap items-center justify-between gap-3 py-2 text-sm">
                    <span>
                      {formatDateTime(x.started_at)} · {x.ended_at ? `recovered after ${formatDuration(x.duration_seconds)}` : "ongoing"}
                    </span>
                    <span className="flex items-center gap-2">
                      <span className="tabular-nums text-ink-muted">peak {formatTemp(x.peak_c)}</span>
                      <StatusBadge status={x.severity} />
                    </span>
                  </li>
                ))}
              </ul>
            )}
            <p className="mt-3 text-xs text-ink-subtle">
              {data.report.trace_events.length} cold-chain entries in the hash-chained trace ·{" "}
              {data.report.chain_valid ? "chain verified" : "chain broken"}
            </p>
          </Card>
        </>
      )}
    </section>
  );
}

// ---------------------------------------------------------------- admin

/** Admin: network-level counts only (simulated). */
export function AdminColdChain() {
  const [data, setData] = useState<MonitoredList | null>(null);
  const [failed, setFailed] = useState(false);
  const [version, reload] = useReload();
  useTelemetryRefresh(reload);
  useEffect(() => {
    let active = true;
    void api.GET("/api/v1/telemetry/monitored").then(({ data: d }) => {
      if (!active) return;
      if (d) setData(d);
      else setFailed(true);
    });
    return () => {
      active = false;
    };
  }, [version]);
  if (failed) return null;
  if (!data) return <Skeleton className="h-24 w-full" />;
  const c = data.counts;
  return (
    <Card className="flex flex-col gap-3" data-testid="admin-cold-chain">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <CardLabel>Cold chain across the network</CardLabel>
        <SimulatedBadge subject="IoT telemetry" />
      </div>
      <p className="text-sm">
        {data.bags.length} monitored bags · {c.normal ?? 0} normal · {c.warning ?? 0} warning · {c.critical ?? 0} critical ·{" "}
        {(c.offline ?? 0) + (c.paused ?? 0)} offline or paused
      </p>
      <p className="text-2xs text-ink-subtle">{TELEMETRY_BADGE}</p>
    </Card>
  );
}
