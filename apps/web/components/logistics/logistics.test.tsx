import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { ShipmentCheckpoint, ShipmentDetail, ShipmentList, ShipmentTimeline } from "@veyra/api-client";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { formatEta, LOGISTICS_DISCLAIMER } from "@/lib/logistics";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/shipments/s1",
}));

const GET = vi.fn();
const POST = vi.fn();
vi.mock("@/lib/api", () => ({
  api: { GET: (...a: unknown[]) => GET(...a), POST: (...a: unknown[]) => POST(...a) },
  SESSION_EXPIRED_EVENT: "veyra:session-expired",
}));

let me: { user: { role: string }; facility: { id: string } | null } | null = null;
vi.mock("@/lib/session", () => ({ useOptionalSession: () => ({ me }) }));

const live = new Map<string, () => void>();
vi.mock("@/lib/live", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/live")>()),
  useLiveRefresh: (topics: string[], cb: () => void) => {
    for (const t of topics) live.set(`${t}#${live.size}`, cb);
  },
}));
function emit(topic: string) {
  for (const [key, cb] of [...live]) if (key.startsWith(`${topic}#`)) cb();
}

const { ShipmentsPanel, RouteVisual, ShipmentDetailView, AdminLogistics, LogisticsDisclaimer } = await import("./logistics");

const res = (status: number) => new Response(null, { status });
const ok = (data: unknown) => ({ data, response: res(200) });
const fail = (status: number, detail: string) => ({ data: undefined, error: { status, code: "x", detail }, response: res(status) });
const SIM = { provider: "veyra-logistics-sim", kind: "simulated" as const, fetched_at: null, note: null, simulated: true };

function checkpoints(reached: number): ShipmentCheckpoint[] {
  const names = ["Central Blood Bank", "Collection point (simulated)", "Transit checkpoint (simulated)", "Kolkata destination area (simulated)", "City Hospital"];
  const kinds = ["source", "collection", "transit", "destination_area", "destination"] as const;
  return names.map((name, seq) => ({
    seq,
    name,
    kind: kinds[seq]!,
    distance_km: seq * 2,
    expected_at: `2026-09-28T09:${10 + seq * 3}:00Z`,
    actual_at: seq <= reached ? `2026-09-28T09:${10 + seq * 3}:00Z` : null,
    status: seq <= reached ? "reached" : "pending",
    current: seq === reached,
  }));
}

const ETA = {
  eta_at: "2026-09-28T09:30:00Z",
  remaining_minutes: 22,
  status: "on_schedule" as const,
  delay_minutes: 0,
  delay_active: false,
  delay_reason: null,
  reasons: ["Schematic legs at simulated speeds"],
  label: "Simulated ETA — prototype",
};

function summary(over: Partial<ShipmentDetail> = {}) {
  return {
    id: "s1",
    reference: "SH-ABCD1234",
    request_id: "r1",
    request_reference: "RQ-EMRG0001",
    source_facility_id: "b1",
    source_name: "Central Blood Bank",
    destination_facility_id: "h1",
    destination_name: "City Hospital",
    status: "in_transit" as const,
    urgency: "emergency",
    bag_count: 1,
    blood_group: "O+",
    component: "PRBC",
    courier: { courier_id: "SIM-CR-0042", name: "Demo Courier Delta", vehicle_type: "Insulated motorbike box (simulated)", simulated: true },
    eta: ETA,
    current_checkpoint: 1,
    current_checkpoint_name: "Collection point (simulated)",
    cold_chain_alert: "none" as const,
    created_at: "2026-09-28T09:00:00Z",
    picked_up_at: "2026-09-28T09:10:00Z",
    arrived_at: null,
    received_at: null,
    last_update_at: "2026-09-28T09:13:00Z",
    ...over,
  };
}

function detail(over: Partial<ShipmentDetail> = {}): ShipmentDetail {
  const base = summary(over);
  return {
    ...base,
    request_status: "dispatched",
    bags: [{ public_id: "VYR-NEWR-0002", blood_group: "O+", component: "PRBC", status: "in_transit", expires_at: "2026-11-09T09:00:00Z", chain_valid: true, chain_length: 5 }],
    checkpoints: checkpoints(base.current_checkpoint),
    distance_km: 8,
    planned_minutes: 30,
    trace_valid: true,
    telemetry: {
      shipment_id: "s1",
      reference: "SH-ABCD1234",
      status: base.status,
      in_transit: true,
      cold_chain_alert: base.cold_chain_alert,
      bags: [{ public_id: "VYR-NEWR-0002", monitored: true, device_id: "SIM-AAAA-BBBB", cold_chain_status: "critical", excursion_active: true, latest_temperature_c: 9.1, device_status: "paused", last_telemetry_at: "2026-09-28T09:12:00Z" }],
      source: SIM,
      note: "Simulated IoT telemetry — prototype. Critical bags stay flagged for human review.",
    },
    simulator_enabled: true,
    source: SIM,
    label: "Simulated logistics — prototype",
    disclaimer: LOGISTICS_DISCLAIMER,
    ...over,
  } as ShipmentDetail;
}

const TIMELINE: ShipmentTimeline = {
  shipment_id: "s1",
  reference: "SH-ABCD1234",
  label: "Simulated logistics — prototype",
  events: [
    { seq: 1, event_type: "SHIPMENT_CREATED", status: "created", occurred_at: "2026-09-28T09:00:00Z", meta: {} },
    { seq: 2, event_type: "COURIER_ASSIGNED", status: "pickup_pending", occurred_at: "2026-09-28T09:00:00Z", meta: {} },
    { seq: 3, event_type: "SHIPMENT_DELAYED", status: "delayed", occurred_at: "2026-09-28T09:14:00Z", meta: { minutes: 18 } },
    { seq: 4, event_type: "COLD_CHAIN_CRITICAL", status: "delayed", occurred_at: "2026-09-28T09:15:00Z", meta: {} },
    { seq: 5, event_type: "CHECKPOINT_REACHED", status: "in_transit", occurred_at: "2026-09-28T09:20:00Z", meta: { checkpoint_name: "Transit checkpoint (simulated)" } },
  ],
};

function list(shipments: ReturnType<typeof summary>[]): ShipmentList {
  return {
    scope: "source",
    shipments,
    counts: { awaiting_pickup: 1, in_transit: 2, delayed: 1, arrived: 0, completed_today: 3, cold_chain_alerts: 1, on_schedule: 2, late: 0 },
    average_delivery_minutes: 42,
    generated_at: "2026-09-28T09:00:00Z",
    label: "Simulated logistics — prototype",
    disclaimer: LOGISTICS_DISCLAIMER,
  };
}

function routes(over: Record<string, unknown> = {}) {
  GET.mockImplementation(async (path: string) => {
    if (path in over) return over[path];
    if (path === "/api/v1/shipments") {
      return ok(list([summary(), summary({ id: "s2", reference: "SH-DLAY0002", status: "delayed", cold_chain_alert: "critical", eta: { ...ETA, status: "delayed", delay_minutes: 18, delay_active: true } })]));
    }
    if (path === "/api/v1/shipments/{shipment_id}") return ok(detail());
    if (path === "/api/v1/shipments/{shipment_id}/timeline") return ok(TIMELINE);
    return fail(404, "not found");
  });
}

beforeEach(() => {
  GET.mockReset();
  POST.mockReset();
  live.clear();
  me = null;
});

describe("logistics helpers", () => {
  it("formats ETAs and carries the verbatim disclaimer", () => {
    expect(formatEta(7)).toBe("7 min");
    expect(formatEta(65)).toBe("1 h 5 min");
    render(<LogisticsDisclaimer />);
    expect(screen.getByTestId("logistics-disclaimer")).toHaveTextContent(
      "This is a simulated logistics prototype. Routes, courier status and ETAs are not real-world navigation or delivery guarantees.",
    );
  });
});

describe("ShipmentsPanel", () => {
  it("shows a skeleton, then counts and a scrollable table with text statuses", async () => {
    routes();
    const { container } = render(<ShipmentsPanel kind="BLOOD_BANK" />);
    expect(container.querySelector(".veyra-skeleton")).not.toBeNull();
    const table = await screen.findByTestId("shipments-table");
    expect(table.closest(".overflow-x-auto")).not.toBeNull();
    const rows = within(table).getAllByRole("row");
    expect(rows).toHaveLength(3);
    const delayed = within(table).getByText("SH-DLAY0002").closest("tr")!;
    expect(delayed).toHaveTextContent("Delayed");
    expect(delayed).toHaveTextContent("+18 min delay");
    expect(delayed).toHaveTextContent("Cold-chain critical");
    expect(within(table).getByRole("link", { name: "SH-ABCD1234" })).toHaveAttribute("href", "/shipments/s1");
    expect(screen.getByTestId("shipments")).toHaveTextContent("Completed today");
  });

  it("shows empty and error states with retry, and refreshes on shipment events", async () => {
    GET.mockResolvedValue(fail(500, "Boom"));
    render(<ShipmentsPanel kind="HOSPITAL" />);
    expect(await screen.findByText("Shipments unavailable")).toBeInTheDocument();
    GET.mockResolvedValue(ok(list([])));
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByText("No shipments yet")).toBeInTheDocument();
    const before = GET.mock.calls.length;
    act(() => emit("shipment.delayed"));
    await waitFor(() => expect(GET.mock.calls.length).toBe(before + 1));
  });
});

describe("RouteVisual", () => {
  it("is labelled as schematic, marks the current step, and never relies on colour alone", () => {
    render(<RouteVisual checkpoints={checkpoints(2)} current={2} />);
    const fig = screen.getByTestId("route-visual");
    expect(fig).toHaveTextContent("Prototype logistics route — not a geographic map");
    const steps = within(screen.getByRole("list", { name: "Route checkpoints" })).getAllByRole("listitem");
    expect(steps).toHaveLength(5);
    expect(steps[2]).toHaveAttribute("aria-current", "step");
    expect(steps[2]).toHaveTextContent("Reached · current");
    expect(steps[4]).toHaveTextContent("Not yet reached");
    expect(fig.querySelector(".motion-safe\\:animate-pulse")).not.toBeNull(); // no motion under reduced motion
  });
});

describe("ShipmentDetailView", () => {
  it("shows status, ETA, courier, route, timeline and cold chain", async () => {
    routes();
    render(<ShipmentDetailView shipmentId="s1" />);
    const page = await screen.findByTestId("shipment-detail");
    expect(page).toHaveTextContent("SH-ABCD1234");
    expect(page).toHaveTextContent("In transit");
    expect(page).toHaveTextContent("22 min");
    expect(page).toHaveTextContent("Demo Courier Delta");
    expect(page).toHaveTextContent("Trace chain verified");
    expect(screen.getByTestId("route-visual")).toBeInTheDocument();
    const timeline = await screen.findByRole("list", { name: "Shipment timeline" });
    expect(timeline).toHaveTextContent("Delay (simulated) +18 min");
    expect(timeline).toHaveTextContent("Cold-chain critical in transit");
    expect(timeline).toHaveTextContent("Checkpoint reached: Transit checkpoint (simulated)");
    const cold = screen.getByTestId("shipment-cold-chain");
    expect(cold).toHaveTextContent("Active excursion");
    expect(cold).toHaveTextContent("9.1 °C");
    fireEvent.click(screen.getByRole("button", { name: "Table" }));
    expect(screen.getByTestId("checkpoint-table")).toBeInTheDocument();
    expect(screen.queryByTestId("logistics-controls")).not.toBeInTheDocument(); // not the source bank
  });

  it("gives the dispatching bank the demo controls (delay with minutes and reason)", async () => {
    me = { user: { role: "BLOOD_BANK" }, facility: { id: "b1" } };
    routes();
    POST.mockResolvedValue(ok({ action: "delay", events: ["shipment.delayed"], shipment: detail({ status: "delayed" }) }));
    render(<ShipmentDetailView shipmentId="s1" />);
    const controls = await screen.findByTestId("logistics-controls");
    fireEvent.change(within(controls).getByLabelText("Delay minutes"), { target: { value: "30" } });
    fireEvent.click(within(controls).getByRole("button", { name: "Inject delay" }));
    await waitFor(() =>
      expect(POST).toHaveBeenCalledWith("/api/v1/simulator/shipments/{shipment_id}/delay", {
        params: { path: { shipment_id: "s1" } },
        body: { minutes: 30, reason: "traffic_simulated" },
      }),
    );
    await screen.findByText(/delay: now Delayed/);
    fireEvent.click(within(controls).getByRole("button", { name: "Advance shipment" }));
    await waitFor(() => expect(POST).toHaveBeenCalledWith("/api/v1/simulator/shipments/{shipment_id}/advance", { params: { path: { shipment_id: "s1" } } }));
  });

  it("shows a visible delay notice", async () => {
    routes({ "/api/v1/shipments/{shipment_id}": ok(detail({ status: "delayed", eta: { ...ETA, status: "delayed", delay_minutes: 18, delay_active: true } })) });
    render(<ShipmentDetailView shipmentId="s1" />);
    expect(await screen.findByText(/Delayed \+18 min \(simulated\)/)).toBeInTheDocument();
  });

  it("lets the destination hospital receive an arrived shipment after explicit confirmation", async () => {
    me = { user: { role: "HOSPITAL" }, facility: { id: "h1" } };
    routes({ "/api/v1/shipments/{shipment_id}": ok(detail({ status: "arrived", current_checkpoint: 4, eta: { ...ETA, status: "arrived", remaining_minutes: 0 } })) });
    POST.mockResolvedValue(ok(detail({ status: "received" })));
    render(<ShipmentDetailView shipmentId="s1" />);
    const card = await screen.findByTestId("receive");
    fireEvent.click(within(card).getByRole("button", { name: "Receive shipment…" }));
    expect(POST).not.toHaveBeenCalled();
    fireEvent.click(within(screen.getByRole("group", { name: "Confirm receipt" })).getByRole("button", { name: "Confirm receipt" }));
    await waitFor(() => expect(POST).toHaveBeenCalledWith("/api/v1/shipments/{shipment_id}/receive", { params: { path: { shipment_id: "s1" } } }));
    expect(await screen.findByText(/Receipt confirmed/)).toBeInTheDocument();
  });

  it("does not offer receipt before arrival, and explains not-found and errors", async () => {
    me = { user: { role: "HOSPITAL" }, facility: { id: "h1" } };
    routes();
    render(<ShipmentDetailView shipmentId="s1" />);
    await screen.findByTestId("shipment-detail");
    expect(screen.queryByTestId("receive")).not.toBeInTheDocument();
  });

  it("explains a hidden shipment and offers retry on errors", async () => {
    GET.mockResolvedValue(fail(404, "Shipment not found"));
    const { unmount } = render(<ShipmentDetailView shipmentId="s1" />);
    expect(await screen.findByText("Shipment not found")).toBeInTheDocument();
    unmount();
    GET.mockResolvedValue(fail(500, "Boom"));
    render(<ShipmentDetailView shipmentId="s1" />);
    expect(await screen.findByText("Shipment unavailable")).toBeInTheDocument();
    routes();
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByTestId("shipment-detail")).toBeInTheDocument();
  });
});

describe("AdminLogistics", () => {
  it("shows network counts, the simulated average and the route status summary", async () => {
    routes();
    render(<AdminLogistics />);
    const section = await screen.findByTestId("admin-logistics");
    expect(section).toHaveTextContent("42 min");
    expect(screen.getByTestId("route-status-summary")).toHaveTextContent("2 on schedule · 1 delayed · 0 past ETA");
    expect(section).toHaveTextContent(LOGISTICS_DISCLAIMER);
  });
});
