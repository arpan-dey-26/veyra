import type { NetworkEdge, NetworkEvent, NetworkGraph, NetworkNode } from "@veyra/api-client";

/**
 * Live Blood Network (2D) state: the scoped graph from `GET /network/graph`, updated by SSE
 * events. Pure functions so the behaviour is testable without a browser.
 *
 * Layout is schematic, NOT geographic: hospitals on the left, blood banks on the right.
 */

export const VIEW_W = 800;
export const COL_X = { HOSPITAL: 190, BLOOD_BANK: 610 } as const;
const ROW_H = 64;
const PAD_Y = 48;

export interface PositionedNode extends NetworkNode {
  x: number;
  y: number;
}

export type PulseKind = "request" | "dispatch" | "receipt" | "declined" | "inventory";

export interface Pulse {
  id: string;
  kind: PulseKind;
  /** Edge pulses travel between two nodes; node pulses (inventory) ring one node. */
  from: string;
  to: string | null;
}

export interface LogEntry {
  id: string;
  topic: string;
  at: string;
  reference?: string;
  units?: number;
  component?: string;
  blood_group?: string;
  reason?: string;
}

export interface LiveGraphState {
  nodes: NetworkNode[];
  edges: NetworkEdge[];
  pulses: Pulse[];
  log: LogEntry[];
  /** An event referenced a facility we can't draw yet: the caller should refetch the graph. */
  stale: boolean;
  seen: string[];
}

export const LOG_LIMIT = 12;

export function initialState(graph: NetworkGraph | null): LiveGraphState {
  return { nodes: graph?.nodes ?? [], edges: graph?.edges ?? [], pulses: [], log: [], stale: false, seen: [] };
}

export function layout(nodes: NetworkNode[]): { nodes: PositionedNode[]; height: number } {
  const place = (kind: NetworkNode["kind"]) => {
    const col = nodes
      .filter((n) => n.kind === kind)
      .sort((a, b) => Number(b.is_self) - Number(a.is_self) || Number(a.simulated) - Number(b.simulated) || a.name.localeCompare(b.name));
    return col.map((n, i) => ({ ...n, x: COL_X[kind], y: PAD_Y + i * ROW_H }));
  };
  const hospitals = place("HOSPITAL");
  const banks = place("BLOOD_BANK");
  const rows = Math.max(hospitals.length, banks.length, 1);
  const height = PAD_Y * 2 + (rows - 1) * ROW_H;
  // Centre the shorter column so edges stay readable.
  const centre = (col: PositionedNode[]) => {
    const offset = ((rows - col.length) * ROW_H) / 2;
    return col.map((n) => ({ ...n, y: n.y + offset }));
  };
  return { nodes: [...centre(hospitals), ...centre(banks)], height };
}

/** Smooth horizontal S-curve between two node positions. */
export function edgePath(a: { x: number; y: number }, b: { x: number; y: number }): string {
  const mid = (a.x + b.x) / 2;
  return `M${a.x} ${a.y} C ${mid} ${a.y}, ${mid} ${b.y}, ${b.x} ${b.y}`;
}

function str(v: unknown): string | undefined {
  return typeof v === "string" && v ? v : undefined;
}

function targetOf(event: NetworkEvent): string | undefined {
  const facility = str(event.target_facility_id);
  if (facility) return facility;
  const ref = str(event.target_ref);
  return ref ? `mock:${ref}` : undefined;
}

const PULSE: Record<string, PulseKind> = {
  "request.created": "request",
  "request.dispatched": "dispatch",
  "request.fulfilled": "receipt",
  "request.rejected": "declined",
  "request.cancelled": "declined",
};

/** True when a request event names a facility the current graph can't draw yet. */
export function referencesUnknownNode(known: ReadonlySet<string>, event: NetworkEvent): boolean {
  if (!PULSE[event.topic]) return false;
  const hospital = str(event.hospital_id);
  const bank = targetOf(event);
  return !!hospital && !!bank && (!known.has(hospital) || !known.has(bank));
}

const CLOSES = new Set(["request.fulfilled", "request.rejected", "request.cancelled"]);

export type Action =
  | { type: "graph"; graph: NetworkGraph }
  | { type: "event"; event: NetworkEvent }
  | { type: "expire"; id: string };

export function reduce(state: LiveGraphState, action: Action): LiveGraphState {
  switch (action.type) {
    case "graph":
      return { ...state, nodes: action.graph.nodes, edges: action.graph.edges, stale: false };
    case "expire":
      return { ...state, pulses: state.pulses.filter((p) => p.id !== action.id) };
    case "event":
      return applyEvent(state, action.event);
  }
}

export function applyEvent(state: LiveGraphState, event: NetworkEvent): LiveGraphState {
  if (state.seen.includes(event.event_id)) return state; // at-least-once delivery
  const seen = [...state.seen.slice(-199), event.event_id];
  const entry: LogEntry = {
    id: event.event_id,
    topic: event.topic,
    at: event.created_at,
    reference: str(event.reference),
    units: typeof event.units === "number" ? event.units : undefined,
    component: str(event.component),
    blood_group: str(event.blood_group),
    reason: str(event.reason),
  };
  const log = [entry, ...state.log].slice(0, LOG_LIMIT);
  const known = new Set(state.nodes.map((n) => n.id));

  if (event.topic === "inventory.updated" || event.topic === "bag.discarded") {
    const facility = event.topic === "inventory.updated" ? str(event.aggregate_id) : undefined;
    const pulses = facility && known.has(facility)
      ? [...state.pulses, { id: event.event_id, kind: "inventory" as const, from: facility, to: null }]
      : state.pulses;
    return { ...state, log, seen, pulses };
  }

  const kind = PULSE[event.topic];
  const hospital = str(event.hospital_id);
  const bank = targetOf(event);
  if (!kind || !hospital || !bank) return { ...state, log, seen };
  if (!known.has(hospital) || !known.has(bank)) return { ...state, log, seen, stale: true };

  const units = typeof event.units === "number" ? event.units : 0;
  let edges = state.edges;
  const existing = edges.find((e) => e.source === hospital && e.target === bank);
  const status = str(event.status) ?? existing?.last_status ?? "pending";
  if (!existing) {
    edges = [
      ...edges,
      { source: hospital, target: bank, requests: 1, open: CLOSES.has(event.topic) ? 0 : 1, units, last_status: status, last_at: event.created_at },
    ];
  } else {
    edges = edges.map((e) =>
      e !== existing
        ? e
        : {
            ...e,
            requests: e.requests + (event.topic === "request.created" ? 1 : 0),
            units: e.units + (event.topic === "request.created" ? units : 0),
            open: Math.max(0, e.open + (event.topic === "request.created" ? 1 : CLOSES.has(event.topic) ? -1 : 0)),
            last_status: status,
            last_at: event.created_at,
          },
    );
  }
  const toBank = kind === "request";
  const pulse: Pulse = { id: event.event_id, kind, from: toBank ? hospital : bank, to: toBank ? bank : hospital };
  return { ...state, edges, log, seen, pulses: [...state.pulses, pulse] };
}
