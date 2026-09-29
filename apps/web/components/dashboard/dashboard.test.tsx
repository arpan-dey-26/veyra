import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type {
  AdminDashboard,
  FacilityDashboard,
  InventorySummary,
  NetworkGraph,
} from "@veyra/api-client";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  activityText,
  expiryBars,
  inventoryByGroup,
  niceMax,
  requestStatusBars,
  usersByRole,
} from "@/lib/charts";
import { LANDING_DISCLAIMER } from "@/lib/landing";
import {
  applyEvent,
  initialState,
  layout,
  reduce,
  referencesUnknownNode,
} from "@/lib/network-graph";
import { DEMO_VERIFICATION_DISCLAIMER } from "@/lib/validation";
import { summaryFixture } from "@/test/forecast-fixtures";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/blood-bank",
}));

const GET = vi.fn();
vi.mock("@/lib/api", () => ({
  api: { GET: (...a: unknown[]) => GET(...a), POST: vi.fn() },
  SESSION_EXPIRED_EVENT: "veyra:session-expired",
}));

const { BarList, ColumnChart } = await import("@/components/charts/charts");
const { FacilityOverview } = await import("./facility-overview");
const { AdminOverview } = await import("./admin-overview");
const { LiveNetwork } = await import("@/components/network/live-network");
const { DonorDonations } = await import("@/components/donor/donor-donations");
const { LiveEventsProvider } = await import("@/lib/live");
const HomePage = (await import("@/app/(marketing)/page")).default;

const res = (status: number) => new Response(null, { status });
const ok = (data: unknown) => ({ data, response: res(200) });

const STOCK: InventorySummary = {
  facility_id: "bank-1",
  facility_name: "Central Blood Bank",
  generated_at: "2026-09-28T09:00:00Z",
  total_available: 3,
  rows: [
    { blood_group: "O+", component: "PRBC", available: 2, expired: 0, expiring_soon: 1, next_expiry: null },
    { blood_group: "O+", component: "FFP", available: 1, expired: 1, expiring_soon: 0, next_expiry: null },
  ],
  components: [],
  reference_note: "Prototype defaults",
};

const days = (n: number, f: (i: number) => object) =>
  Array.from({ length: n }, (_, i) => ({ day: `2026-09-${String(15 + i).padStart(2, "0")}`, ...f(i) }));

const STATUSES = ["pending", "acknowledged", "dispatched", "fulfilled", "rejected", "cancelled"];

const BANK_DASH: FacilityDashboard = {
  facility_id: "bank-1",
  facility_name: "Central Blood Bank",
  kind: "BLOOD_BANK",
  generated_at: "2026-09-28T09:00:00Z",
  window_days: 14,
  utc_offset_minutes: 330,
  requests: {
    direction: "incoming",
    total: 3,
    open: 2,
    emergency_open: 1,
    by_status: STATUSES.map((s) => ({ status: s, count: s === "pending" ? 2 : s === "fulfilled" ? 1 : 0 })),
  },
  donations: { applicable: true, today: 2, window_total: 5, by_day: days(14, (i) => ({ count: i === 13 ? 2 : i % 4 === 0 ? 1 : 0 })) as FacilityDashboard["donations"]["by_day"] },
  movements: days(14, (i) => ({ dispatched: i === 13 ? 1 : 0, received: 0 })) as FacilityDashboard["movements"],
  on_hand: 3,
  expiry: [
    { bucket: "expired", label: "Expired", count: 1 },
    { bucket: "lt_1d", label: "< 24 h", count: 0 },
    { bucket: "d1_3", label: "1-3 days", count: 1 },
    { bucket: "d3_7", label: "3-7 days", count: 0 },
    { bucket: "d7_30", label: "7-30 days", count: 0 },
    { bucket: "gt_30d", label: "> 30 days", count: 2 },
  ],
  activity: [
    { event_id: "e1", topic: "request.created", created_at: "2026-09-28T08:00:00Z", reference: "RQ-AAAA1111", units: 2, component: "PRBC", blood_group: "O-", urgency: "emergency" },
  ],
};

const GRAPH: NetworkGraph = {
  generated_at: "2026-09-28T09:00:00Z",
  window_days: 30,
  nodes: [
    { id: "h1", name: "City Hospital", kind: "HOSPITAL", city: "Kolkata", simulated: false, is_self: true },
    { id: "b1", name: "Central Blood Bank", kind: "BLOOD_BANK", city: "Kolkata", simulated: false, is_self: false },
    { id: "mock:MOCK-HWH", name: "Howrah Regional", kind: "BLOOD_BANK", city: "Howrah", simulated: true, is_self: false },
  ],
  edges: [{ source: "h1", target: "b1", requests: 1, open: 1, units: 2, last_status: "pending", last_at: "2026-09-28T08:00:00Z" }],
  note: "Prototype network visualization — not a geographic map.",
};

const event = (over: Record<string, unknown>) => ({
  event_id: "ev-1",
  topic: "request.created",
  aggregate_type: "blood_request",
  aggregate_id: "r1",
  created_at: "2026-09-28T09:05:00Z",
  hospital_id: "h1",
  target_facility_id: "b1",
  reference: "RQ-BBBB2222",
  units: 3,
  status: "pending",
  ...over,
});

/** Minimal EventSource double: tests push events by topic. */
class FakeEventSource {
  static last: FakeEventSource | null = null;
  static readonly CLOSED = 2;
  readyState = 1;
  onopen: (() => void) | null = null;
  onerror: (() => void) | null = null;
  private handlers = new Map<string, ((m: MessageEvent<string>) => void)[]>();
  constructor(public url: string) {
    FakeEventSource.last = this;
  }
  addEventListener(topic: string, h: (m: MessageEvent<string>) => void) {
    this.handlers.set(topic, [...(this.handlers.get(topic) ?? []), h]);
  }
  close() {}
  emit(data: Record<string, unknown>) {
    for (const h of this.handlers.get(String(data.topic)) ?? []) h({ data: JSON.stringify(data) } as MessageEvent<string>);
  }
}

beforeEach(() => {
  GET.mockReset();
  FakeEventSource.last = null;
  vi.stubGlobal("EventSource", FakeEventSource);
});

// ---------------------------------------------------------------- chart data mapping

describe("chart data mapping", () => {
  it("maps inventory to all 8 groups in fixed order with component detail", () => {
    const bars = inventoryByGroup(STOCK);
    expect(bars.map((b) => b.key)).toEqual(["A+", "A-", "B+", "B-", "AB+", "AB-", "O+", "O-"]);
    const o = bars.find((b) => b.key === "O+");
    expect(o?.value).toBe(3);
    expect(o?.detail).toContain("2 Packed red cells");
    expect(o?.detail).toContain("1 expiring within 72 h");
    expect(bars.find((b) => b.key === "AB-")?.value).toBe(0);
  });

  it("keeps request statuses in API order with human labels and status tones", () => {
    const bars = requestStatusBars(BANK_DASH.requests.by_status);
    expect(bars.map((b) => b.key)).toEqual(STATUSES);
    expect(bars[0]).toMatchObject({ label: "Awaiting blood bank", value: 2, tone: "warn" });
    expect(bars[3]).toMatchObject({ label: "Received", tone: "verified" });
  });

  it("marks expired and near-expiry buckets as critical/warn", () => {
    const bars = expiryBars(BANK_DASH.expiry);
    expect(bars[0]).toMatchObject({ key: "expired", tone: "critical", value: 1 });
    expect(bars[2]?.tone).toBe("warn");
  });

  it("rounds axis maxima to clean numbers", () => {
    expect(niceMax(0)).toBe(4);
    expect(niceMax(7)).toBe(10);
    expect(niceMax(13)).toBe(20);
    expect(niceMax(230)).toBe(250);
  });

  it("describes events without personal data", () => {
    expect(activityText({ topic: "request.created", reference: "RQ-1", units: 2, component: "PRBC", blood_group: "O-" })).toEqual({
      title: "Request raised",
      detail: "RQ-1 · 2 × Packed red cells O−",
    });
    expect(activityText({ topic: "bag.discarded", reason: "failed_screening" }).detail).toBe("failed screening");
  });

  it("maps accounts per role with a status split", () => {
    const bars = usersByRole({ users: [{ role: "DONOR", active: 3, pending_verification: 1, disabled: 0, total: 4 }] });
    expect(bars[0]).toMatchObject({ label: "Donor", value: 4, detail: "3 active · 1 pending · 0 disabled" });
  });
});

describe("chart components", () => {
  it("BarList shows an empty state when every value is zero", () => {
    render(<BarList title="Stock" data={[{ key: "a", label: "A", value: 0 }]} emptyText="No stock yet." />);
    expect(screen.getByText("No stock yet.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Table" })).not.toBeInTheDocument();
  });

  it("BarList offers a table view with every value", () => {
    render(<BarList title="Stock" data={[{ key: "a", label: "A+", value: 3 }, { key: "b", label: "B+", value: 1 }]} />);
    fireEvent.click(screen.getByRole("button", { name: "Table" }));
    const table = screen.getByRole("table");
    expect(within(table).getByText("A+")).toBeInTheDocument();
    expect(within(table).getByText("3")).toBeInTheDocument();
  });

  it("BarList shows a tooltip on keyboard focus", () => {
    render(<BarList title="Stock" data={[{ key: "a", label: "A+", value: 3, detail: "2 PRBC" }]} />);
    fireEvent.focus(screen.getByLabelText(/A\+: 3 units/));
    expect(screen.getByRole("tooltip")).toHaveTextContent("2 PRBC");
  });

  it("ColumnChart shows a legend only for two series", () => {
    const points = [{ key: "d1", label: "1 Sep", values: { a: 1, b: 2 } }];
    const { rerender } = render(<ColumnChart title="Moves" points={points} series={[{ key: "a", label: "Dispatched" }, { key: "b", label: "Received" }]} />);
    expect(screen.getByRole("list", { name: "Legend" })).toHaveTextContent("Dispatched");
    rerender(<ColumnChart title="Moves" points={points} series={[{ key: "a", label: "Dispatched" }]} />);
    expect(screen.queryByRole("list", { name: "Legend" })).not.toBeInTheDocument();
  });
});

// ---------------------------------------------------------------- live network state

describe("live network state", () => {
  it("lays out hospitals left and banks right, self first, simulated last", () => {
    const { nodes } = layout(GRAPH.nodes);
    const h = nodes.find((n) => n.id === "h1");
    const banks = nodes.filter((n) => n.kind === "BLOOD_BANK");
    expect(h?.x).toBeLessThan(banks[0]!.x);
    expect(banks.map((b) => b.id)).toEqual(["b1", "mock:MOCK-HWH"]);
  });

  it("applies request lifecycle events to edges and emits pulses in the right direction", () => {
    let s = reduce(initialState(null), { type: "graph", graph: GRAPH });
    s = applyEvent(s, event({}) as never);
    expect(s.edges[0]).toMatchObject({ requests: 2, open: 2, units: 5 });
    expect(s.pulses.at(-1)).toMatchObject({ kind: "request", from: "h1", to: "b1" });
    s = applyEvent(s, event({ event_id: "ev-2", topic: "request.dispatched", status: "dispatched" }) as never);
    expect(s.pulses.at(-1)).toMatchObject({ kind: "dispatch", from: "b1", to: "h1" });
    s = applyEvent(s, event({ event_id: "ev-3", topic: "request.fulfilled", status: "fulfilled" }) as never);
    expect(s.edges[0]).toMatchObject({ open: 1, last_status: "fulfilled" });
    expect(s.log.map((l) => l.id)).toEqual(["ev-3", "ev-2", "ev-1"]);
  });

  it("ignores duplicate deliveries (at-least-once)", () => {
    let s = reduce(initialState(null), { type: "graph", graph: GRAPH });
    s = applyEvent(s, event({}) as never);
    const again = applyEvent(s, event({}) as never);
    expect(again).toBe(s);
  });

  it("flags unknown facilities for a refetch instead of inventing nodes", () => {
    const s = reduce(initialState(null), { type: "graph", graph: GRAPH });
    const e = event({ hospital_id: "h-new" });
    expect(referencesUnknownNode(new Set(GRAPH.nodes.map((n) => n.id)), e as never)).toBe(true);
    const next = applyEvent(s, e as never);
    expect(next.stale).toBe(true);
    expect(next.nodes).toHaveLength(3);
  });

  it("rings a node on inventory updates and expires pulses", () => {
    let s = reduce(initialState(null), { type: "graph", graph: GRAPH });
    s = applyEvent(s, { event_id: "inv", topic: "inventory.updated", aggregate_type: "facility", aggregate_id: "b1", created_at: "x" });
    expect(s.pulses).toEqual([{ id: "inv", kind: "inventory", from: "b1", to: null }]);
    expect(reduce(s, { type: "expire", id: "inv" }).pulses).toEqual([]);
  });
});

describe("LiveNetwork", () => {
  it("labels itself as a non-geographic prototype and updates on live events", async () => {
    GET.mockResolvedValue(ok(GRAPH));
    render(
      <LiveEventsProvider>
        <LiveNetwork />
      </LiveEventsProvider>,
    );
    expect(await screen.findByTestId("network-disclaimer")).toHaveTextContent(
      "Prototype network visualization — not a geographic map.",
    );
    const svg = screen.getByTestId("live-network");
    expect(svg.querySelectorAll("[data-node]")).toHaveLength(3);
    expect(svg.querySelector('[data-edge="h1>b1"]')).toHaveAttribute("data-open", "1");
    act(() => FakeEventSource.last?.emit(event({})));
    await waitFor(() => expect(svg.querySelector('[data-edge="h1>b1"]')).toHaveAttribute("data-open", "2"));
    expect(screen.getByText("Request raised")).toBeInTheDocument();
    expect(GET).toHaveBeenCalledTimes(1);
    // An unknown hospital triggers exactly one graph refetch.
    act(() => FakeEventSource.last?.emit(event({ event_id: "ev-9", hospital_id: "h-new" })));
    await waitFor(() => expect(GET).toHaveBeenCalledTimes(2));
  });

  it("shows an error state when the graph can't load", async () => {
    GET.mockResolvedValue({ data: undefined, error: { status: 403, code: "forbidden", detail: "Permission denied" }, response: res(403) });
    render(<LiveNetwork />);
    expect(await screen.findByText("Network view unavailable")).toBeInTheDocument();
  });
});

// ---------------------------------------------------------------- role dashboards

describe("FacilityOverview", () => {
  it("renders blood-bank tiles, charts and the emergency call-out", async () => {
    GET.mockImplementation(async (path: string) =>
      path === "/api/v1/dashboard/facility"
        ? ok(BANK_DASH)
        : path === "/api/v1/inventory/summary"
          ? ok(STOCK)
          : path === "/api/v1/forecast/summary"
            ? ok(summaryFixture())
            : ok(GRAPH),
    );
    const onNavigate = vi.fn();
    render(<FacilityOverview kind="BLOOD_BANK" onNavigate={onNavigate} />);
    expect(screen.getByLabelText("Loading overview")).toBeInTheDocument();
    const root = await screen.findByTestId("overview-blood_bank");
    expect(within(root).getByText("Donations today")).toBeInTheDocument();
    expect(within(root).getByText("Usable units by blood group")).toBeInTheDocument();
    expect(within(root).getByText(/1 emergency request is open/)).toBeInTheDocument();
    fireEvent.click(within(root).getByRole("button", { name: "Review incoming" }));
    expect(onNavigate).toHaveBeenCalledWith("incoming");
    expect(within(root).getByTestId("activity-feed")).toHaveTextContent("RQ-AAAA1111");
  });

  it("shows hospital availability as bands, never counts per bank", async () => {
    const hospitalDash = { ...BANK_DASH, kind: "HOSPITAL", donations: { applicable: false, today: 0, window_total: 0, by_day: [] }, requests: { ...BANK_DASH.requests, emergency_open: 0, direction: "outgoing" } };
    GET.mockImplementation(async (path: string) => {
      if (path === "/api/v1/dashboard/facility") return ok(hospitalDash);
      if (path === "/api/v1/inventory/summary") return ok(STOCK);
      if (path === "/api/v1/forecast/summary") return ok(summaryFixture());
      if (path === "/api/v1/network/availability") {
        return ok({ blood_group: "O+", component: "PRBC", units: 2, results: [
          { provider: "internal", target_ref: "b1", name: "Central", city: "Kolkata", state: "WB", band: "sufficient", source: { provider: "internal", kind: "internal", simulated: false } },
          { provider: "mock", target_ref: "MOCK-HWH", name: "Howrah", city: "Howrah", state: "WB", band: "limited", source: { provider: "mock", kind: "simulated", simulated: true } },
        ] });
      }
      return ok(GRAPH);
    });
    render(<FacilityOverview kind="HOSPITAL" onNavigate={vi.fn()} />);
    const avail = await screen.findByTestId("availability-overview");
    expect(avail).toHaveTextContent("Can cover: 1");
    expect(avail).toHaveTextContent("Limited: 1");
    expect(avail).toHaveTextContent("includes 1 simulated partner banks");
    expect(screen.queryByText("Donations today")).not.toBeInTheDocument();
  });

  it("offers a retry on error", async () => {
    GET.mockResolvedValue({ data: undefined, error: { status: 500, code: "internal", detail: "Boom" }, response: res(500) });
    render(<FacilityOverview kind="BLOOD_BANK" onNavigate={vi.fn()} />);
    expect(await screen.findByText("Couldn't load the overview")).toBeInTheDocument();
    GET.mockClear();
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    await waitFor(() => expect(GET).toHaveBeenCalled());
  });
});

describe("AdminOverview", () => {
  const ADMIN: AdminDashboard = {
    generated_at: "2026-09-28T09:00:00Z",
    window_days: 14,
    utc_offset_minutes: 330,
    users: [{ role: "DONOR", active: 2, pending_verification: 0, disabled: 0, total: 2 }],
    users_total: 2,
    facilities: { blood_banks: 1, hospitals: 1, simulated: 0 },
    requests_by_status: STATUSES.map((s) => ({ status: s, count: s === "pending" ? 1 : 0 })),
    bags_by_status: [{ status: "available", count: 3 }],
    donations_by_day: days(14, () => ({ count: 0 })) as AdminDashboard["donations_by_day"],
    movements: days(14, () => ({ dispatched: 0, received: 0 })) as AdminDashboard["movements"],
    audit: { last_24h: 4, top_actions: [{ status: "auth.login", count: 3 }], recent: [{ action: "auth.login", resource: "user", actor_type: "user", created_at: "2026-09-28T08:00:00Z" }] },
    activity: [],
  };

  it("renders network counts and an audit summary without IPs", async () => {
    GET.mockImplementation(async (path: string) => (path === "/api/v1/meta" ? ok({ name: "VEYRA", version: "1", environment: "dev", phase: "3" }) : ok(ADMIN)));
    render(<AdminOverview />);
    const root = await screen.findByTestId("admin-overview");
    expect(within(root).getByText("Open requests")).toBeInTheDocument();
    const audit = within(root).getByTestId("audit-table");
    expect(audit).toHaveTextContent("auth.login");
    expect(audit.querySelectorAll("th")).toHaveLength(3);
    // Both time-series charts are empty here: each shows its empty state, not a flat chart.
    expect(within(root).getAllByText("No activity in this period.")).toHaveLength(2);
  });
});

describe("DonorDonations", () => {
  it("shows impact tiles and verification status", async () => {
    GET.mockResolvedValue(ok({
      donations: [{ id: "d1", collected_at: "2026-09-01T09:00:00Z", facility_name: "Central", facility_city: "Kolkata", volume_ml: 450, components: ["Packed red cells", "Fresh frozen plasma"], bags_total: 2, bags_in_stock: 1, bags_sent_to_hospitals: 1, bags_discarded: 0 }],
      last_donation_at: "2026-09-01T09:00:00Z",
      eligible_from: "2026-11-30T09:00:00Z",
      eligible_now: false,
      interval_days: 90,
    }));
    render(<DonorDonations verifiedAt="2026-08-01T00:00:00Z" bloodGroupStatus="confirmed" />);
    const tiles = await screen.findByTestId("donor-impact");
    expect(tiles).toHaveTextContent("Verified");
    expect(tiles).toHaveTextContent("Blood group confirmed by a blood bank");
    expect(tiles).toHaveTextContent("Sent to hospitals1");
    expect(screen.queryByText(/City Hospital/)).not.toBeInTheDocument();
  });
});

// ---------------------------------------------------------------- landing page

describe("landing page", () => {
  it("states purpose, roles, disclosures and the prototype disclaimer", () => {
    render(<HomePage />);
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Every unit of blood");
    for (const heading of ["One chain of custody.", "One network, four roles.", "Built to share only what is needed.", "What is real, and what is simulated."]) {
      expect(screen.getByRole("heading", { name: heading })).toBeInTheDocument();
    }
    const disclosures = screen.getByTestId("landing-disclosures");
    expect(disclosures).toHaveTextContent(DEMO_VERIFICATION_DISCLAIMER);
    expect(disclosures).toHaveTextContent("no real blood bank is contacted");
    expect(screen.getByTestId("landing-disclaimer")).toHaveTextContent(LANDING_DISCLAIMER);
    expect(screen.getAllByRole("link", { name: /become a donor|register as a donor/i })[0]).toHaveAttribute("href", "/register");
    expect(screen.getAllByRole("link", { name: /sign in/i }).length).toBeGreaterThan(0);
  });

  it("makes no clinical claims", () => {
    const { container } = render(<HomePage />);
    const text = container.textContent ?? "";
    expect(text).not.toMatch(/\b(saves lives|clinically (proven|validated)|diagnos\w*|cures?)\b/i);
    expect(text).toContain("not a certified medical device");
  });
});
