"use client";

import type {
  AvailabilityResponse,
  BloodComponent,
  BloodGroup,
  OpsAlerts,
  OpsFacilityPressure,
  OpsReason,
  OpsRecommendation,
  OpsRequest,
  OpsRequestList,
  OpsRoute,
  OpsRoutingOverview,
} from "@veyra/api-client";
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
import { BLOOD_GROUPS, COMPONENTS, componentLabel, displayGroup, formatDateTime, REQUEST_STATUS, URGENCY_LABEL } from "@/lib/network";
import {
  CHANGE_REASONS,
  COLD_STATE,
  FORECAST_INPUT_LABEL,
  formatCoverage,
  formatMinutes,
  OPS_DISCLAIMER,
  OPS_LABEL,
  OPS_TOPICS,
  PRESSURE_LEVEL,
  PRIORITY_BAND,
  REASON_TONE,
  ROUTE_STATUS,
  ROUTING_LABEL,
} from "@/lib/operations";
import { toFailure } from "@/lib/problem";
import { useReload } from "@/lib/use-reload";

type Kind = "HOSPITAL" | "BLOOD_BANK";
type Urgency = "routine" | "urgent" | "emergency";
type ChangeReason = (typeof CHANGE_REASONS)[number]["value"];

function StatusPill({ status, map }: { status: string; map: Record<string, { label: string; tone: BadgeTone; icon: string }> }) {
  const s = map[status] ?? { label: status, tone: "neutral" as const, icon: "•" };
  return (
    <Badge tone={s.tone} data-status={status}>
      <span aria-hidden>{s.icon}</span> {s.label}
    </Badge>
  );
}

export function OpsDisclaimer({ extra }: { extra?: string }) {
  return (
    <div role="note" className="flex flex-wrap items-center gap-3 rounded-md bg-simulated-soft px-4 py-3 text-sm text-simulated" data-testid="ops-disclaimer">
      <span className="font-medium">{OPS_LABEL}</span>
      <span className="text-xs">{OPS_DISCLAIMER}</span>
      {extra && <span className="text-xs">{extra}</span>}
    </div>
  );
}

/** Structured reasons: glyph + text (+ points), never colour alone. */
export function ReasonList({ reasons, label = "Reasons" }: { reasons: OpsReason[]; label?: string }) {
  return (
    <ul aria-label={label} className="flex flex-col gap-1 text-sm" data-testid="reasons">
      {reasons.map((r) => {
        const t = REASON_TONE[r.tone] ?? { label: "Info", tone: "neutral" as const, icon: "•" };
        return (
          <li key={`${r.code}-${r.text}`} className="flex items-start gap-2" data-reason={r.code}>
            <span aria-hidden className={t.tone === "critical" ? "text-critical" : t.tone === "warn" ? "text-warn" : t.tone === "verified" ? "text-verified" : "text-ink-subtle"}>
              {t.icon}
            </span>
            <span>
              <span className="sr-only">{t.label}: </span>
              {r.text}
              {r.points > 0 && <span className="ml-1 text-xs text-ink-subtle tabular-nums">(+{r.points})</span>}
            </span>
          </li>
        );
      })}
    </ul>
  );
}

function RouteSummary({ route }: { route: OpsRoute }) {
  return (
    <div className="flex flex-col gap-2 text-sm" data-testid="route">
      <div className="flex flex-wrap items-center gap-2">
        <SimulatedBadge subject="Routing" />
        <span className="font-medium">ETA {formatMinutes(route.eta_minutes)}</span>
        <span className="text-ink-muted">
          {route.distance_km} km · {route.source_name} → {route.destination_name}
        </span>
        <StatusPill status={route.status} map={ROUTE_STATUS} />
      </div>
      <p className="text-2xs text-ink-subtle">{ROUTING_LABEL}. No GPS, maps or traffic data.</p>
    </div>
  );
}

// ---------------------------------------------------------------- queue

type Loaded<T> = { data?: T; error?: unknown; response: Response };

/** Fetch inside the effect (active guard); `version` from useReload() drives refetches. */
function useOps<T>(load: () => Promise<Loaded<T>>, version: number) {
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

/** Emergency request queue with explainable operational priority. */
export function EmergencyQueue({ kind }: { kind: Kind }) {
  const [version, reload] = useReload();
  useLiveRefresh(OPS_TOPICS, reload);
  const { data, error } = useOps<OpsRequestList>(() => api.GET("/api/v1/operations/requests"), version);
  const [open, setOpen] = useState<string | null>(null);

  if (error) {
    return (
      <ErrorState
        title="Operational queue unavailable"
        description={error}
        action={
          <Button size="sm" variant="secondary" onClick={reload}>
            Try again
          </Button>
        }
      />
    );
  }
  if (!data) return <Skeleton className="h-48 w-full" />;
  const c = data.counts;
  return (
    <section aria-labelledby="queue-heading" className="flex flex-col gap-4" data-testid="emergency-queue">
      <h2 id="queue-heading" className="text-lg font-medium">
        {kind === "BLOOD_BANK" ? "Emergency & open requests" : "My requests — priority and status"}
      </h2>
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <StatTile label="Emergency open" value={c.emergency_open ?? 0} />
        <StatTile label="Open" value={c.open ?? 0} />
        <StatTile label="Dispatched" value={c.dispatched ?? 0} note={kind === "HOSPITAL" ? `${c.expected_units ?? 0} units expected` : undefined} />
        {kind === "HOSPITAL" ? <StatTile label="Received (7 days)" value={c.received_units_7d ?? 0} note="units" /> : <StatTile label="Scope" value="Facility" />}
      </div>
      {data.requests.length === 0 ? (
        <EmptyState title="No open requests" description="Open and in-transit requests appear here, ordered by operational priority." />
      ) : (
        <ul className="flex flex-col gap-3">
          {data.requests.map((r) => (
            <li key={r.id}>
              <RequestRow
                request={r}
                kind={kind}
                expanded={open === r.id}
                onToggle={() => setOpen(open === r.id ? null : r.id)}
                onChanged={reload}
              />
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function RequestRow({
  request: r,
  kind,
  expanded,
  onToggle,
  onChanged,
}: {
  request: OpsRequest;
  kind: Kind;
  expanded: boolean;
  onToggle: () => void;
  onChanged: () => void;
}) {
  const status = (REQUEST_STATUS as Record<string, { label: string; tone: BadgeTone } | undefined>)[r.status];
  const emergency = r.urgency === "emergency";
  return (
    <Card className={emergency && r.status === "pending" ? "border-critical p-5" : "p-5"} data-ops-request={r.id}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex items-baseline gap-4">
          <span className="font-display text-3xl leading-none text-vital">{displayGroup(r.blood_group)}</span>
          <div>
            <p className="font-medium">
              {r.units} × {componentLabel(r.component)}
            </p>
            <p className="text-xs text-ink-subtle">
              <span className="font-mono">{r.reference}</span> · {kind === "HOSPITAL" ? `to ${r.target_name}` : `from ${r.hospital_name}`}
            </p>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Badge tone={emergency ? "critical" : r.urgency === "urgent" ? "warn" : "neutral"}>
            {emergency && <span aria-hidden>▲ </span>}
            {URGENCY_LABEL[r.urgency] ?? r.urgency}
          </Badge>
          <StatusPill status={r.priority.band} map={PRIORITY_BAND} />
          <span className="text-xs text-ink-muted tabular-nums" aria-label={`Operational priority score ${r.priority.score} of 100`}>
            {r.priority.score}/100
          </span>
          {status && <Badge tone={status.tone}>{status.label}</Badge>}
        </div>
      </div>
      <dl className="mt-3 grid grid-cols-2 gap-x-6 gap-y-1 text-xs text-ink-muted sm:grid-cols-4">
        <div>
          <dt className="text-ink-subtle">Requested</dt>
          <dd>{formatDateTime(r.requested_at)}</dd>
        </div>
        <div>
          <dt className="text-ink-subtle">Age</dt>
          <dd>{formatMinutes(r.age_minutes)}</dd>
        </div>
        <div>
          <dt className="text-ink-subtle">Needed by</dt>
          <dd>{formatDateTime(r.needed_by)}</dd>
        </div>
        <div>
          <dt className="text-ink-subtle">Recommended action</dt>
          <dd className="text-ink">{r.priority.recommendation}</dd>
        </div>
      </dl>
      {r.route && (
        <div className="mt-3">
          <RouteSummary route={r.route} />
        </div>
      )}
      <div className="mt-3 flex flex-wrap gap-2">
        <Button size="sm" variant="secondary" aria-expanded={expanded} aria-controls={`ops-detail-${r.id}`} onClick={onToggle}>
          {expanded ? "Hide details" : kind === "BLOOD_BANK" && r.status === "pending" ? "Review recommendation" : "Why this priority?"}
        </Button>
      </div>
      {expanded && (
        <div id={`ops-detail-${r.id}`} className="mt-4 flex flex-col gap-4 border-t border-line pt-4">
          <div>
            <CardLabel>Why this priority</CardLabel>
            <p className="mt-1 text-2xs text-ink-subtle">{OPS_LABEL} — not a clinical score.</p>
            <div className="mt-2">
              <ReasonList reasons={r.priority.reasons} label={`Priority reasons for ${r.reference}`} />
            </div>
          </div>
          {kind === "BLOOD_BANK" && r.target_facility_id && <AllocationPanel requestId={r.id} onDispatched={onChanged} />}
          {kind === "HOSPITAL" && (r.status === "pending" || r.status === "acknowledged") && (
            <PriorityChange requestId={r.id} current={r.urgency as Urgency} onChanged={onChanged} />
          )}
        </div>
      )}
    </Card>
  );
}

// ---------------------------------------------------------------- allocation (bank)

/** Ranked candidate bags. Nothing is dispatched until the user confirms. */
export function AllocationPanel({ requestId, onDispatched }: { requestId: string; onDispatched: () => void }) {
  const [version, reload] = useReload();
  useLiveRefresh(["allocation.recommendation_updated", "cold_chain.operational_alert", "temperature.critical", "temperature.recovered"], reload);
  const { data, error } = useOps<OpsRecommendation>(
    () => api.GET("/api/v1/operations/requests/{request_id}/recommendations", { params: { path: { request_id: requestId } } }),
    version,
  );
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<{ tone: "error" | "success"; text: string } | null>(null);

  if (error) {
    return (
      <ErrorState
        title="Recommendation unavailable"
        description={error}
        action={
          <Button size="sm" variant="secondary" onClick={reload}>
            Try again
          </Button>
        }
      />
    );
  }
  if (!data) return <Skeleton className="h-40 w-full" />;

  async function dispatch(ids: string[]) {
    setBusy(true);
    const { data: out, error: e, response } = await api.POST("/api/v1/requests/{request_id}/fulfil", {
      params: { path: { request_id: requestId } },
      body: { bag_public_ids: ids },
    });
    setBusy(false);
    setConfirming(false);
    setNotice(out ? { tone: "success", text: `Dispatched ${out.bags.map((b) => b.public_id).join(", ")}` } : { tone: "error", text: toFailure(e, response).message });
    onDispatched();
  }

  const canDispatch = data.status === "pending" && data.recommended_bag_ids.length === data.units;
  return (
    <div className="flex flex-col gap-4" data-testid="allocation">
      <div>
        <CardLabel>Recommended allocation</CardLabel>
        <p className="mt-1 text-sm font-medium" data-testid="recommendation">
          {data.recommendation}
        </p>
        <p className="mt-1 text-2xs text-ink-subtle">{data.compatibility_rule}</p>
      </div>
      {data.candidates.length === 0 ? (
        <EmptyState title="No compatible bags" description="No available, unexpired bag of this group and component is held here." />
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[720px] text-sm" data-testid="candidates">
            <caption className="sr-only">Candidate bags ranked for {data.reference}</caption>
            <thead>
              <tr className="border-b border-line text-left text-ink-subtle">
                <th scope="col" className="py-2 pr-3 font-medium">Rank</th>
                <th scope="col" className="py-2 pr-3 font-medium">Bag</th>
                <th scope="col" className="py-2 pr-3 font-medium">Expires</th>
                <th scope="col" className="py-2 pr-3 font-medium">Cold chain</th>
                <th scope="col" className="py-2 pr-3 font-medium">Facility</th>
                <th scope="col" className="py-2 font-medium">Why</th>
              </tr>
            </thead>
            <tbody>
              {data.candidates.map((c) => (
                <tr key={c.public_id} className="border-b border-line align-top last:border-0" data-candidate={c.public_id} data-recommended={c.recommended}>
                  <th scope="row" className="py-2 pr-3 text-left font-normal tabular-nums">
                    {c.rank}
                    {c.recommended && <Badge tone="verified" className="ml-2"><span aria-hidden>✓</span> Recommended</Badge>}
                    {c.deprioritized && <Badge tone="warn" className="ml-2"><span aria-hidden>↓</span> Deprioritised</Badge>}
                  </th>
                  <td className="py-2 pr-3 font-mono">{c.public_id}</td>
                  <td className="py-2 pr-3">
                    {formatDateTime(c.expires_at)}
                    <span className="block text-xs text-ink-subtle">in {formatMinutes(c.expires_in_hours * 60)}</span>
                  </td>
                  <td className="py-2 pr-3">
                    <StatusPill status={c.cold_chain_state} map={COLD_STATE} />
                    {c.latest_temperature_c !== null && (
                      <span className="block text-xs text-ink-subtle tabular-nums">{c.latest_temperature_c.toFixed(1)} °C (simulated)</span>
                    )}
                  </td>
                  <td className="py-2 pr-3 text-ink-muted">{c.current_facility_name}</td>
                  <td className="py-2">
                    <ReasonList reasons={c.reasons} label={`Ranking reasons for ${c.public_id}`} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <div className="grid gap-4 md:grid-cols-2">
        <Card className="p-4">
          <CardLabel>Forecast pressure</CardLabel>
          <p className="mt-1 flex flex-wrap items-center gap-2 text-sm">
            <StatusPill status={data.pressure.level} map={PRESSURE_LEVEL} />
            {data.pressure.stock} in stock · {data.pressure.open_units} requested · coverage {formatCoverage(data.pressure.coverage_days)}
          </p>
          <p className="mt-1 text-2xs text-ink-subtle">{FORECAST_INPUT_LABEL}</p>
        </Card>
        {data.route && (
          <Card className="p-4">
            <CardLabel>Simulated route</CardLabel>
            <div className="mt-2">
              <RouteSummary route={data.route} />
            </div>
          </Card>
        )}
      </div>
      {notice && <InlineAlert tone={notice.tone}>{notice.text}</InlineAlert>}
      <p className="text-xs text-ink-subtle">{data.human_confirmation}</p>
      {canDispatch && !confirming && (
        <div>
          <Button variant="vital" size="sm" onClick={() => setConfirming(true)}>
            Dispatch recommended bags…
          </Button>
        </div>
      )}
      {canDispatch && confirming && (
        <div role="group" aria-label="Confirm dispatch" className="flex flex-wrap items-center gap-2 rounded-md border border-line-strong p-3">
          <span className="text-sm">
            Dispatch <span className="font-mono">{data.recommended_bag_ids.join(", ")}</span> for {data.reference}?
          </span>
          <Button variant="vital" size="sm" disabled={busy} onClick={() => void dispatch(data.recommended_bag_ids)}>
            {busy && <Spinner />}Confirm dispatch
          </Button>
          <Button variant="ghost" size="sm" disabled={busy} onClick={() => setConfirming(false)}>
            Cancel
          </Button>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------- priority change (hospital)

function PriorityChange({ requestId, current, onChanged }: { requestId: string; current: Urgency; onChanged: () => void }) {
  const [urgency, setUrgency] = useState<Urgency>(current === "emergency" ? "urgent" : "emergency");
  const [reason, setReason] = useState<ChangeReason>("escalated_by_requesting_team");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<{ tone: "error" | "success"; text: string } | null>(null);

  async function submit() {
    setBusy(true);
    const { data, error: e, response } = await api.POST("/api/v1/operations/requests/{request_id}/priority", {
      params: { path: { request_id: requestId } },
      body: { urgency, reason },
    });
    setBusy(false);
    setNotice(data ? { tone: "success", text: `Priority is now ${URGENCY_LABEL[urgency] ?? urgency}.` } : { tone: "error", text: toFailure(e, response).message });
    if (data) onChanged();
  }

  return (
    <form
      className="flex flex-col gap-3"
      aria-label="Change priority"
      onSubmit={(ev) => {
        ev.preventDefault();
        void submit();
      }}
    >
      <CardLabel>Change priority</CardLabel>
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="New priority">
          {(p) => (
            <SelectInput {...p} value={urgency} onChange={(e) => setUrgency(e.target.value as Urgency)}>
              {(["routine", "urgent", "emergency"] as const)
                .filter((u) => u !== current)
                .map((u) => (
                  <option key={u} value={u}>
                    {URGENCY_LABEL[u] ?? u}
                  </option>
                ))}
            </SelectInput>
          )}
        </Field>
        <Field label="Reason" hint="A reason code only — no free text, so no personal details are stored.">
          {(p) => (
            <SelectInput {...p} value={reason} onChange={(e) => setReason(e.target.value as ChangeReason)}>
              {CHANGE_REASONS.map((r) => (
                <option key={r.value} value={r.value}>
                  {r.label}
                </option>
              ))}
            </SelectInput>
          )}
        </Field>
      </div>
      {notice && <InlineAlert tone={notice.tone}>{notice.text}</InlineAlert>}
      <div>
        <Button type="submit" size="sm" variant="secondary" disabled={busy}>
          {busy && <Spinner />}Update priority
        </Button>
      </div>
    </form>
  );
}

// ---------------------------------------------------------------- pressure

export function PressurePanel({ facilityId }: { facilityId: string }) {
  const [version, reload] = useReload();
  useLiveRefresh(["forecast.pressure_changed", "request.created", "request.dispatched", "request.fulfilled"], reload);
  const { data, error } = useOps<OpsFacilityPressure>(
    () => api.GET("/api/v1/operations/facilities/{facility_id}/pressure", { params: { path: { facility_id: facilityId } } }),
    version,
  );
  const [all, setAll] = useState(false);
  if (error) {
    return (
      <ErrorState
        title="Pressure view unavailable"
        description={error}
        action={
          <Button size="sm" variant="secondary" onClick={reload}>
            Try again
          </Button>
        }
      />
    );
  }
  if (!data) return <Skeleton className="h-40 w-full" />;
  const rows = all ? data.rows : data.rows.filter((r) => r.level !== "normal");
  return (
    <section aria-labelledby="pressure-heading" className="flex flex-col gap-3" data-testid="pressure">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 id="pressure-heading" className="text-lg font-medium">
          Operational pressure
        </h2>
        <Badge tone="simulated">{data.forecast_label}</Badge>
      </div>
      <p className="text-xs text-ink-subtle">
        Real stock minus open requests, against {data.horizon_days} days of synthetic forecast demand. Not a medical emergency prediction.
      </p>
      <div className="grid grid-cols-3 gap-3">
        <StatTile label="Elevated" value={data.counts.elevated ?? 0} />
        <StatTile label="Watch" value={data.counts.watch ?? 0} />
        <StatTile label="Normal" value={data.counts.normal ?? 0} />
      </div>
      <div className="flex">
        <Button size="sm" variant="ghost" aria-pressed={all} onClick={() => setAll((v) => !v)}>
          {all ? "Show only elevated / watch" : "Show all rows"}
        </Button>
      </div>
      {rows.length === 0 ? (
        <EmptyState title="No pressure" description="Every group and component has normal coverage." />
      ) : (
        <Card className="overflow-x-auto p-0">
          <table className="w-full min-w-[640px] text-sm" data-testid="pressure-table">
            <thead>
              <tr className="border-b border-line text-left text-ink-subtle">
                <th scope="col" className="px-4 py-2 font-medium">Group · component</th>
                <th scope="col" className="px-3 py-2 font-medium">Level</th>
                <th scope="col" className="px-3 py-2 text-right font-medium">Stock</th>
                <th scope="col" className="px-3 py-2 text-right font-medium">Requested</th>
                <th scope="col" className="px-3 py-2 text-right font-medium">Forecast / day</th>
                <th scope="col" className="px-3 py-2 text-right font-medium">Coverage</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={`${r.blood_group}-${r.component}`} className="border-b border-line last:border-0" data-pressure-row={`${r.blood_group}/${r.component}`}>
                  <th scope="row" className="px-4 py-2 text-left font-normal">
                    {displayGroup(r.blood_group)} · {componentLabel(r.component)}
                  </th>
                  <td className="px-3 py-2">
                    <StatusPill status={r.level} map={PRESSURE_LEVEL} />
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums">{r.stock}</td>
                  <td className="px-3 py-2 text-right tabular-nums">{r.open_units}</td>
                  <td className="px-3 py-2 text-right tabular-nums">{r.forecast_daily_mean === null ? "—" : r.forecast_daily_mean.toFixed(1)}</td>
                  <td className="px-3 py-2 text-right tabular-nums">{formatCoverage(r.coverage_days)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}
    </section>
  );
}

// ---------------------------------------------------------------- alerts + routing

export function AlertsPanel() {
  const [version, reload] = useReload();
  useLiveRefresh(OPS_TOPICS, reload);
  const { data, error } = useOps<OpsAlerts>(() => api.GET("/api/v1/operations/alerts"), version);
  if (error) {
    return (
      <ErrorState
        title="Alerts unavailable"
        description={error}
        action={
          <Button size="sm" variant="secondary" onClick={reload}>
            Try again
          </Button>
        }
      />
    );
  }
  if (!data) return <Skeleton className="h-32 w-full" />;
  return (
    <section aria-labelledby="alerts-heading" className="flex flex-col gap-3" data-testid="ops-alerts">
      <h2 id="alerts-heading" className="text-lg font-medium">
        Needs attention
      </h2>
      {data.alerts.length === 0 ? (
        <EmptyState title="Nothing needs attention" description="Emergency requests, cold-chain concerns, expiring bags and pressure appear here." />
      ) : (
        <ul className="flex flex-col divide-y divide-line rounded-lg border border-line" aria-label="Operational alerts">
          {data.alerts.map((a) => (
            <li key={`${a.kind}-${a.ref}`} className="flex flex-wrap items-start justify-between gap-3 px-4 py-3 text-sm" data-alert={a.kind}>
              <span>
                <span className="font-medium">
                  <span aria-hidden className={a.severity === "warning" ? "text-critical" : "text-warn"}>
                    {a.severity === "warning" ? "▲ " : "◆ "}
                  </span>
                  <span className="sr-only">{a.severity === "warning" ? "Warning: " : "Attention: "}</span>
                  {a.title}
                </span>
                <span className="block text-xs text-ink-muted">{a.detail}</span>
              </span>
              {a.facility_name && <span className="text-xs text-ink-subtle">{a.facility_name}</span>}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

export function RoutingPanel({ title = "Dispatch queue — simulated ETAs" }: { title?: string }) {
  const [version, reload] = useReload();
  useLiveRefresh(["routing.updated", "request.dispatched", "request.fulfilled"], reload);
  const { data, error } = useOps<OpsRoutingOverview>(() => api.GET("/api/v1/operations/routing"), version);
  if (error) {
    return (
      <ErrorState
        title="Routing unavailable"
        description={error}
        action={
          <Button size="sm" variant="secondary" onClick={reload}>
            Try again
          </Button>
        }
      />
    );
  }
  if (!data) return <Skeleton className="h-24 w-full" />;
  return (
    <section aria-labelledby="routing-heading" className="flex flex-col gap-3" data-testid="routing">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 id="routing-heading" className="text-lg font-medium">
          {title}
        </h2>
        <SimulatedBadge subject="Routing" />
      </div>
      {data.routes.length === 0 ? (
        <EmptyState title="Nothing in transit" description="Dispatched requests show a simulated ETA here until they are received." />
      ) : (
        <ul className="flex flex-col gap-2">
          {data.routes.map((r) => (
            <li key={r.request_id} className="rounded-lg border border-line p-3">
              <p className="text-sm">
                <span className="font-mono">{r.reference}</span> · expected {formatDateTime(r.expected_at)}
              </p>
              <RouteSummary route={r.route} />
            </li>
          ))}
        </ul>
      )}
      <p className="text-2xs text-ink-subtle">{data.label}</p>
    </section>
  );
}

function AvailabilityBands() {
  const [group, setGroup] = useState<BloodGroup>("O+");
  const [component, setComponent] = useState<BloodComponent>("PRBC");
  const [data, setData] = useState<AvailabilityResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  async function check() {
    setBusy(true);
    const { data: d, error: e, response } = await api.GET("/api/v1/network/availability", {
      params: { query: { blood_group: group, component, units: 1 } },
    });
    setBusy(false);
    if (d) {
      setData(d);
      setError(null);
    } else setError(toFailure(e, response).message);
  }
  return (
    <Card className="flex flex-col gap-3" data-testid="availability-bands">
      <CardLabel>Network availability (banded)</CardLabel>
      <div className="grid gap-3 sm:grid-cols-3">
        <Field label="Blood group">
          {(p) => (
            <SelectInput {...p} value={group} onChange={(e) => setGroup(e.target.value as BloodGroup)}>
              {BLOOD_GROUPS.map((g) => (
                <option key={g} value={g}>
                  {g}
                </option>
              ))}
            </SelectInput>
          )}
        </Field>
        <Field label="Component">
          {(p) => (
            <SelectInput {...p} value={component} onChange={(e) => setComponent(e.target.value as BloodComponent)}>
              {COMPONENTS.map((c) => (
                <option key={c.code} value={c.code}>
                  {c.label}
                </option>
              ))}
            </SelectInput>
          )}
        </Field>
        <div className="flex items-end">
          <Button size="sm" variant="secondary" disabled={busy} onClick={() => void check()}>
            {busy && <Spinner />}Check bands
          </Button>
        </div>
      </div>
      {error && <InlineAlert>{error}</InlineAlert>}
      {data && (
        <ul className="flex flex-col gap-1 text-sm">
          {data.results.map((r) => (
            <li key={`${r.provider}-${r.target_ref}`} className="flex items-center justify-between gap-3">
              <span>
                {r.name} {r.source.simulated && <SimulatedBadge subject="Blood bank" />}
              </span>
              <Badge tone={r.band === "sufficient" ? "verified" : r.band === "limited" ? "warn" : "neutral"}>
                {r.band === "sufficient" ? "✓ Sufficient" : r.band === "limited" ? "◆ Limited" : "– None"}
              </Badge>
            </li>
          ))}
        </ul>
      )}
      <p className="text-2xs text-ink-subtle">Bands only: exact stock of other facilities is never shown.</p>
    </Card>
  );
}

// ---------------------------------------------------------------- workspaces

/** Blood bank / hospital "Operations" tab. */
export function OperationsWorkspace({ kind, facilityId }: { kind: Kind; facilityId: string }) {
  return (
    <div className="flex flex-col gap-8" data-testid="operations-workspace">
      <OpsDisclaimer />
      {kind === "BLOOD_BANK" ? <AlertsPanel /> : null}
      <EmergencyQueue kind={kind} />
      <RoutingPanel title={kind === "BLOOD_BANK" ? "Dispatch queue — simulated ETAs" : "Expected deliveries — simulated ETAs"} />
      {kind === "HOSPITAL" && <AvailabilityBands />}
      <PressurePanel facilityId={facilityId} />
      {kind === "HOSPITAL" ? <AlertsPanel /> : null}
    </div>
  );
}

/** Admin: network-level operational picture (counts, open emergencies, routing). */
export function AdminOperations() {
  const [version, reload] = useReload();
  useLiveRefresh(OPS_TOPICS, reload);
  const queue = useOps<OpsRequestList>(() => api.GET("/api/v1/operations/requests"), version);
  const alerts = useOps<OpsAlerts>(() => api.GET("/api/v1/operations/alerts"), version);
  if (queue.error || alerts.error) {
    return (
      <ErrorState
        title="Operations overview unavailable"
        description={queue.error ?? alerts.error ?? ""}
        action={
          <Button size="sm" variant="secondary" onClick={reload}>
            Try again
          </Button>
        }
      />
    );
  }
  if (!queue.data || !alerts.data) return <Skeleton className="h-40 w-full" />;
  const emergencies = queue.data.requests.filter((r) => r.urgency === "emergency" && (r.status === "pending" || r.status === "acknowledged"));
  const ac = alerts.data.counts;
  return (
    <section aria-labelledby="admin-ops-heading" className="flex flex-col gap-4" data-testid="admin-operations">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 id="admin-ops-heading" className="text-lg font-medium">
          Network emergency activity
        </h2>
        <Badge tone="simulated">{OPS_LABEL}</Badge>
      </div>
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <StatTile label="Open emergencies" value={queue.data.counts.emergency_open ?? 0} />
        <StatTile label="Open requests" value={queue.data.counts.open ?? 0} />
        <StatTile label="Cold-chain warnings" value={(ac.cold_chain ?? 0) + (ac.device_stale ?? 0)} note="simulated telemetry" />
        <StatTile label="Banks with elevated pressure" value={ac.pressure ?? 0} note="synthetic forecast input" />
      </div>
      {emergencies.length === 0 ? (
        <EmptyState title="No open emergency requests" description="Emergency requests across the network appear here." />
      ) : (
        <ul className="flex flex-col divide-y divide-line rounded-lg border border-line" aria-label="Open emergency requests">
          {emergencies.map((r) => (
            <li key={r.id} className="flex flex-wrap items-center justify-between gap-3 px-4 py-3 text-sm">
              <span>
                <span className="font-mono">{r.reference}</span> · {r.units} × {displayGroup(r.blood_group)} {componentLabel(r.component)} · {r.hospital_name} → {r.target_name}
              </span>
              <span className="flex items-center gap-2">
                <StatusPill status={r.priority.band} map={PRIORITY_BAND} />
                <span className="text-xs text-ink-muted">{formatMinutes(r.age_minutes)} old</span>
              </span>
            </li>
          ))}
        </ul>
      )}
      <RoutingPanel title="Simulated routing overview" />
      <p className="text-2xs text-ink-subtle">{OPS_DISCLAIMER}</p>
    </section>
  );
}
