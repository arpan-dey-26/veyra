"use client";

import type { NetworkGraph } from "@veyra/api-client";
import { useEffect, useMemo, useReducer, useRef, useState } from "react";

import { LiveIndicator } from "@/components/network/live-indicator";
import { Badge } from "@/components/ui/badge";
import { Card, CardLabel } from "@/components/ui/card";
import { EmptyState, ErrorState, Skeleton } from "@/components/ui/states";
import { api } from "@/lib/api";
import { activityText } from "@/lib/charts";
import { cn } from "@/lib/cn";
import { useLive } from "@/lib/live";
import {
  edgePath,
  initialState,
  layout,
  reduce,
  referencesUnknownNode,
  VIEW_W,
  type LogEntry,
  type Pulse,
} from "@/lib/network-graph";
import { formatDateTime, REQUEST_STATUS } from "@/lib/network";
import { toFailure } from "@/lib/problem";
import { useReducedMotion } from "@/lib/use-reduced-motion";
import { useReload } from "@/lib/use-reload";

export const NETWORK_DISCLAIMER = "Prototype network visualization — not a geographic map.";
const PULSE_MS = 2400;

const PULSE_CLASS: Record<Pulse["kind"], string> = {
  request: "fill-vital",
  dispatch: "fill-vital",
  receipt: "fill-verified",
  declined: "fill-ink-subtle",
  inventory: "stroke-vital",
};

export function LiveNetwork({
  compact = false,
  scopeLabel = "Scoped to your facility",
}: {
  compact?: boolean;
  scopeLabel?: string;
}) {
  const [state, dispatch] = useReducer(reduce, null, initialState);
  const [error, setError] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [version, reload] = useReload();
  const { subscribe } = useLive();
  const reduced = useReducedMotion();
  const knownIds = useRef<ReadonlySet<string>>(new Set());

  useEffect(() => {
    let active = true;
    void api.GET("/api/v1/network/graph").then(({ data, error: e, response }) => {
      if (!active) return;
      if (data) {
        const graph = data as NetworkGraph;
        // Known before the first render with this graph: a live event arriving before the
        // effect below has run must not look like an unknown facility (spurious refetch).
        knownIds.current = new Set(graph.nodes.map((n) => n.id));
        dispatch({ type: "graph", graph });
        setLoaded(true);
      } else {
        setError(toFailure(e, response).message);
      }
    });
    return () => {
      active = false;
    };
  }, [version]);

  useEffect(() => {
    knownIds.current = new Set(state.nodes.map((n) => n.id));
  }, [state.nodes]);

  useEffect(
    () =>
      subscribe("*", (event) => {
        // A new counterpart (e.g. a hospital's first request to this bank): refetch the graph.
        if (referencesUnknownNode(knownIds.current, event)) reload();
        dispatch({ type: "event", event });
        window.setTimeout(() => dispatch({ type: "expire", id: event.event_id }), PULSE_MS);
      }),
    [subscribe, reload],
  );

  const { nodes, height } = useMemo(() => layout(state.nodes), [state.nodes]);
  const pos = useMemo(() => new Map(nodes.map((n) => [n.id, n])), [nodes]);

  if (error) return <ErrorState title="Network view unavailable" description={error} />;
  if (!loaded) return <Skeleton className={compact ? "h-64 w-full" : "h-96 w-full"} />;

  return (
    <div className={cn("grid gap-6", !compact && "lg:grid-cols-[minmax(0,3fr)_minmax(0,1fr)]")}>
      <Card className="p-4 sm:p-6">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <CardLabel>Live blood network</CardLabel>
          <LiveIndicator />
        </div>
        <p className="mt-1 text-xs text-ink-subtle" data-testid="network-disclaimer">
          {NETWORK_DISCLAIMER}
        </p>
        {nodes.length <= 1 && state.edges.length === 0 ? (
          <div className="mt-4">
            <EmptyState
              title="No connections yet"
              description="Requests between hospitals and blood banks will appear here as lines, and move live as they happen."
            />
          </div>
        ) : (
          <svg
            viewBox={`0 0 ${VIEW_W} ${height}`}
            className="mt-4 h-auto w-full"
            role="img"
            aria-label={`Network: ${nodes.filter((n) => n.kind === "HOSPITAL").length} hospitals, ${nodes.filter((n) => n.kind === "BLOOD_BANK").length} blood banks, ${state.edges.length} request links`}
            data-testid="live-network"
          >
            <text x="190" y="18" textAnchor="middle" className="fill-ink-subtle text-[11px] uppercase">
              Hospitals
            </text>
            <text x="610" y="18" textAnchor="middle" className="fill-ink-subtle text-[11px] uppercase">
              Blood banks
            </text>
            {state.edges.map((e) => {
              const a = pos.get(e.source);
              const b = pos.get(e.target);
              if (!a || !b) return null;
              return (
                <path
                  key={`${e.source}-${e.target}`}
                  d={edgePath(a, b)}
                  fill="none"
                  strokeWidth={e.open > 0 ? 2.5 : 1.5}
                  className={e.open > 0 ? "stroke-vital" : "stroke-line-strong"}
                  data-edge={`${e.source}>${e.target}`}
                  data-open={e.open}
                >
                  <title>
                    {`${e.requests} request${e.requests === 1 ? "" : "s"}, ${e.units} units, ${e.open} open. Last: ${REQUEST_STATUS[e.last_status as keyof typeof REQUEST_STATUS]?.label ?? e.last_status}`}
                  </title>
                </path>
              );
            })}
            {state.pulses.map((p) => {
              const a = pos.get(p.from);
              if (!a) return null;
              if (p.kind === "inventory" || !p.to) {
                return (
                  <circle key={p.id} cx={a.x} cy={a.y} r="18" fill="none" strokeWidth="2" className={cn(PULSE_CLASS.inventory, !reduced && "veyra-beacon")} data-pulse="inventory" />
                );
              }
              const b = pos.get(p.to);
              if (!b) return null;
              const path = edgePath(a, b);
              return reduced ? (
                <path key={p.id} d={path} fill="none" strokeWidth="4" className="stroke-vital/60" data-pulse={p.kind} />
              ) : (
                <circle key={p.id} r="6" className={PULSE_CLASS[p.kind]} data-pulse={p.kind}>
                  <animateMotion dur={`${PULSE_MS / 1000}s`} fill="freeze" path={path} />
                </circle>
              );
            })}
            {nodes.map((n) => {
              const left = n.kind === "HOSPITAL";
              return (
                <g key={n.id} data-node={n.id} data-kind={n.kind}>
                  {left ? (
                    <rect
                      x={n.x - 9}
                      y={n.y - 9}
                      width="18"
                      height="18"
                      rx="4"
                      className={cn("stroke-surface-raised", n.is_self ? "fill-ink" : "fill-ink-muted")}
                      strokeWidth="2"
                    />
                  ) : (
                    <circle
                      cx={n.x}
                      cy={n.y}
                      r="10"
                      strokeWidth="2"
                      strokeDasharray={n.simulated ? "3 2" : undefined}
                      className={cn(
                        n.simulated ? "fill-simulated-soft stroke-simulated" : n.is_self ? "fill-vital stroke-surface-raised" : "fill-vital/70 stroke-surface-raised",
                      )}
                    />
                  )}
                  {n.is_self && (
                    <circle cx={n.x} cy={n.y} r="16" fill="none" strokeWidth="1.5" className="stroke-ink" />
                  )}
                  <text
                    x={left ? n.x - 24 : n.x + 24}
                    y={n.y + 4}
                    textAnchor={left ? "end" : "start"}
                    className="fill-ink text-[13px]"
                  >
                    {n.name.length > 30 ? `${n.name.slice(0, 29)}…` : n.name}
                  </text>
                  <text
                    x={left ? n.x - 24 : n.x + 24}
                    y={n.y + 19}
                    textAnchor={left ? "end" : "start"}
                    className="fill-ink-subtle text-[11px]"
                  >
                    {[n.city, n.is_self ? "you" : null, n.simulated ? "simulated" : null].filter(Boolean).join(" · ")}
                  </text>
                </g>
              );
            })}
          </svg>
        )}
        <ul className="mt-4 flex flex-wrap gap-x-5 gap-y-2 text-xs text-ink-muted" aria-label="Legend">
          <li className="flex items-center gap-1.5">
            <span aria-hidden className="inline-block size-3 rounded-[3px] bg-ink-muted" /> Hospital
          </li>
          <li className="flex items-center gap-1.5">
            <span aria-hidden className="inline-block size-3 rounded-full bg-vital/70" /> Blood bank
          </li>
          <li className="flex items-center gap-1.5">
            <span aria-hidden className="inline-block size-3 rounded-full border border-dashed border-simulated bg-simulated-soft" /> Simulated partner
          </li>
          <li className="flex items-center gap-1.5">
            <span aria-hidden className="inline-block h-0.5 w-5 bg-vital" /> Open request
          </li>
          <li className="flex items-center gap-1.5">
            <span aria-hidden className="inline-block h-0.5 w-5 bg-line-strong" /> Closed (last 30 days)
          </li>
        </ul>
      </Card>
      {!compact && <NetworkLog entries={state.log} scopeLabel={scopeLabel} />}
    </div>
  );
}

function NetworkLog({ entries, scopeLabel }: { entries: LogEntry[]; scopeLabel: string }) {
  return (
    <Card className="p-5">
      <CardLabel>Live events</CardLabel>
      {entries.length === 0 ? (
        <p className="mt-3 text-sm text-ink-muted">Waiting for network events… they appear here the moment they happen.</p>
      ) : (
        <ol className="mt-3 flex flex-col gap-3" aria-live="polite">
          {entries.map((e) => {
            const t = activityText(e);
            return (
              <li key={e.id} className="text-sm">
                <p className="font-medium">{t.title}</p>
                {t.detail && <p className="text-xs text-ink-muted">{t.detail}</p>}
                <p className="text-2xs text-ink-subtle">{formatDateTime(e.at)}</p>
              </li>
            );
          })}
        </ol>
      )}
      <Badge className="mt-4">{scopeLabel}</Badge>
    </Card>
  );
}
