import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type {
  OpsAlerts,
  OpsFacilityPressure,
  OpsPriority,
  OpsRecommendation,
  OpsRequest,
  OpsRequestList,
  OpsRoute,
  OpsRoutingOverview,
} from "@veyra/api-client";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { formatCoverage, formatMinutes, OPS_DISCLAIMER } from "@/lib/operations";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/blood-bank",
}));

const GET = vi.fn();
const POST = vi.fn();
vi.mock("@/lib/api", () => ({
  api: { GET: (...a: unknown[]) => GET(...a), POST: (...a: unknown[]) => POST(...a) },
  SESSION_EXPIRED_EVENT: "veyra:session-expired",
}));

// Capture live-refresh callbacks so tests can simulate SSE events.
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

const { EmergencyQueue, AllocationPanel, PressurePanel, AlertsPanel, AdminOperations, OpsDisclaimer, OperationsWorkspace } =
  await import("./operations");

const res = (status: number) => new Response(null, { status });
const ok = (data: unknown) => ({ data, response: res(200) });
const fail = (status: number, detail: string) => ({ data: undefined, error: { status, code: "x", detail }, response: res(status) });

const SIM = { provider: "veyra-routing-sim", kind: "simulated" as const, fetched_at: null, note: null, simulated: true };

const ROUTE: OpsRoute = {
  source_facility_id: "b1",
  source_name: "Central Blood Bank",
  destination_facility_id: "h1",
  destination_name: "City Hospital",
  urgency: "emergency",
  distance_km: 7.4,
  travel_minutes: 10,
  handover_minutes: 10,
  eta_minutes: 20,
  status: "slow",
  reasons: [{ code: "scope", text: "Same city (Kolkata): simulated distance 7.4 km", points: 0, tone: "info" }],
  source: SIM,
  label: "Simulated routing — prototype",
};

function priority(over: Partial<OpsPriority> = {}): OpsPriority {
  return {
    request_id: "r1",
    reference: "RQ-EMRG0001",
    score: 70,
    band: "immediate",
    recommendation: "Review the recommended bags, then confirm dispatch",
    action_code: "review_and_dispatch",
    reasons: [
      { code: "urgency_emergency", text: "Emergency request", points: 50, tone: "warning" },
      { code: "needed_2h", text: "Needed within 2 hours", points: 10, tone: "attention" },
      { code: "stock_ok", text: "Available compatible stock (1 units without cold-chain concern)", points: 0, tone: "positive" },
      { code: "cold_chain_flagged", text: "Cold-chain concern on 1 compatible bags", points: 3, tone: "attention" },
    ],
    computed_at: "2026-09-28T09:00:00Z",
    label: "Operational recommendation — prototype",
    disclaimer: OPS_DISCLAIMER,
    ...over,
  };
}

function request(over: Partial<OpsRequest> = {}): OpsRequest {
  return {
    id: "r1",
    reference: "RQ-EMRG0001",
    hospital_id: "h1",
    hospital_name: "City Hospital",
    target_facility_id: "b1",
    target_name: "Central Blood Bank",
    provider: "internal",
    blood_group: "O+",
    component: "PRBC",
    units: 1,
    urgency: "emergency",
    status: "pending",
    requested_at: "2026-09-28T08:15:00Z",
    needed_by: "2026-09-28T10:00:00Z",
    age_minutes: 45,
    priority: priority(),
    route: null,
    ...over,
  };
}

function list(requests: OpsRequest[]): OpsRequestList {
  return {
    scope: "facility",
    requests,
    counts: { open: 2, emergency_open: 1, dispatched: 0, expected_units: 3, received_units_7d: 4 },
    generated_at: "2026-09-28T09:00:00Z",
    label: "Operational recommendation — prototype",
    disclaimer: OPS_DISCLAIMER,
  };
}

const RECOMMENDATION: OpsRecommendation = {
  request_id: "r1",
  reference: "RQ-EMRG0001",
  status: "pending",
  units: 1,
  blood_group: "O+",
  component: "PRBC",
  recommendation: "Dispatch VYR-NEWR-0002 (FEFO, skipping bags with cold-chain concerns) — after your review.",
  recommended_bag_ids: ["VYR-NEWR-0002"],
  fefo_default_bag_ids: ["VYR-OLDR-0001"],
  candidates: [
    {
      rank: 1, public_id: "VYR-NEWR-0002", blood_group: "O+", component: "PRBC", expires_at: "2026-11-09T09:00:00Z",
      expires_in_hours: 1008, fefo_position: 2, cold_chain_state: "unmonitored", device_id: null, latest_temperature_c: null,
      current_facility_id: "b1", current_facility_name: "Central Blood Bank", recommended: true, deprioritized: false,
      reasons: [{ code: "recommended", text: "Recommended for this request", points: 0, tone: "positive" }],
    },
    {
      rank: 2, public_id: "VYR-OLDR-0001", blood_group: "O+", component: "PRBC", expires_at: "2026-11-07T09:00:00Z",
      expires_in_hours: 960, fefo_position: 1, cold_chain_state: "critical", device_id: "SIM-AAAA-BBBB", latest_temperature_c: 9.3,
      current_facility_id: "b1", current_facility_name: "Central Blood Bank", recommended: false, deprioritized: true,
      reasons: [{ code: "cold_chain_critical", text: "Cold-chain critical — deprioritised; review before any dispatch", points: 0, tone: "warning" }],
    },
  ],
  compatibility_rule: "Existing VEYRA rule: same blood group and component.",
  priority: priority(),
  pressure: {
    blood_group: "O+", component: "PRBC", level: "elevated", stock: 2, open_units: 1, free_stock: 1,
    forecast_daily_mean: 1.4, coverage_days: 0.7, reasons: [],
  },
  route: ROUTE,
  human_confirmation: "Nothing is dispatched automatically. Confirm dispatch yourself.",
  generated_at: "2026-09-28T09:00:00Z",
  label: "Operational recommendation — prototype",
  disclaimer: OPS_DISCLAIMER,
};

const PRESSURE: OpsFacilityPressure = {
  facility_id: "b1",
  facility_name: "Central Blood Bank",
  facility_type: "BLOOD_BANK",
  horizon_days: 7,
  rows: [
    { blood_group: "O+", component: "PRBC", level: "elevated", stock: 2, open_units: 1, free_stock: 1, forecast_daily_mean: 1.4, coverage_days: 0.7, reasons: [] },
    { blood_group: "A+", component: "PRBC", level: "watch", stock: 6, open_units: 0, free_stock: 6, forecast_daily_mean: 1.2, coverage_days: 5, reasons: [] },
    { blood_group: "B+", component: "FFP", level: "normal", stock: 30, open_units: 0, free_stock: 30, forecast_daily_mean: 1, coverage_days: 30, reasons: [] },
  ],
  counts: { elevated: 1, watch: 1, normal: 1 },
  generated_at: "2026-09-28T09:00:00Z",
  source: { provider: "demand-gbm@1", kind: "synthetic", fetched_at: null, note: null, simulated: true },
  forecast_label: "Synthetic forecast input — prototype",
  disclaimer: OPS_DISCLAIMER,
};

const ALERTS: OpsAlerts = {
  scope: "facility",
  alerts: [
    { kind: "emergency_request", severity: "warning", title: "Emergency request RQ-EMRG0001", detail: "1 x O+ PRBC", ref: "r1", facility_name: "City Hospital", at: null },
    { kind: "cold_chain", severity: "warning", title: "Cold-chain critical: VYR-OLDR-0001", detail: "Cold-chain critical — deprioritised", ref: "VYR-OLDR-0001", facility_name: null, at: null },
    { kind: "expiring", severity: "attention", title: "Expires soon: VYR-PLT0-0003", detail: "PLATELETS expires within 72 h", ref: "VYR-PLT0-0003", facility_name: null, at: null },
  ],
  counts: { emergency_request: 1, cold_chain: 1, expiring: 1, pressure: 1 },
  generated_at: "2026-09-28T09:00:00Z",
  label: "Operational recommendation — prototype",
  disclaimer: OPS_DISCLAIMER,
};

const ROUTING: OpsRoutingOverview = {
  scope: "facility",
  routes: [{ request_id: "r9", reference: "RQ-INTR0009", dispatched_at: "2026-09-28T08:00:00Z", expected_at: "2026-09-28T08:20:00Z", route: ROUTE }],
  generated_at: "2026-09-28T09:00:00Z",
  label: "Simulated routing — prototype",
};

function routes(over: Record<string, unknown> = {}) {
  GET.mockImplementation(async (path: string) => {
    if (path in over) return over[path];
    switch (path) {
      case "/api/v1/operations/requests":
        return ok(list([request(), request({ id: "r2", reference: "RQ-RTNE0002", urgency: "routine", priority: priority({ request_id: "r2", score: 10, band: "standard", reasons: [{ code: "urgency_routine", text: "Routine request", points: 10, tone: "info" }] }) })]));
      case "/api/v1/operations/requests/{request_id}/recommendations":
        return ok(RECOMMENDATION);
      case "/api/v1/operations/facilities/{facility_id}/pressure":
        return ok(PRESSURE);
      case "/api/v1/operations/alerts":
        return ok(ALERTS);
      case "/api/v1/operations/routing":
        return ok(ROUTING);
      default:
        return fail(404, "not found");
    }
  });
}

beforeEach(() => {
  GET.mockReset();
  POST.mockReset();
  live.clear();
});

describe("operations helpers", () => {
  it("formats minutes and coverage", () => {
    expect(formatMinutes(45)).toBe("45 min");
    expect(formatMinutes(185)).toBe("3 h 5 min");
    expect(formatMinutes(60 * 24 * 2 + 240)).toBe("2 d 4 h");
    expect(formatCoverage(0.72)).toBe("0.7 d");
    expect(formatCoverage(null)).toBe("—");
  });

  it("carries the verbatim prototype disclaimer", () => {
    render(<OpsDisclaimer />);
    const note = screen.getByTestId("ops-disclaimer");
    expect(note).toHaveTextContent("Operational recommendation — prototype");
    expect(note).toHaveTextContent("This is an operational engineering prototype. Recommendations are not clinical decisions or medical advice.");
  });
});

describe("EmergencyQueue", () => {
  it("shows a loading skeleton, then requests ordered with band, score, age and status", async () => {
    routes();
    const { container } = render(<EmergencyQueue kind="BLOOD_BANK" />);
    expect(container.querySelector(".veyra-skeleton")).not.toBeNull();
    const queue = await screen.findByTestId("emergency-queue");
    const rows = within(queue).getAllByRole("listitem");
    expect(rows).toHaveLength(2);
    const first = rows[0]!;
    expect(first).toHaveTextContent("RQ-EMRG0001");
    expect(within(first).getByText("Immediate")).toBeInTheDocument(); // text, not colour alone
    expect(within(first).getByLabelText("Operational priority score 70 of 100")).toBeInTheDocument();
    expect(first).toHaveTextContent("45 min");
    expect(first).toHaveTextContent("Emergency");
    expect(rows[1]).toHaveTextContent("Standard");
    expect(queue).toHaveTextContent("Emergency open");
  });

  it("explains the priority with structured reasons (keyboard-toggled)", async () => {
    routes();
    render(<EmergencyQueue kind="HOSPITAL" />);
    await screen.findByTestId("emergency-queue");
    const toggle = screen.getAllByRole("button", { name: "Why this priority?" })[0]!;
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    const reasons = screen.getByRole("list", { name: "Priority reasons for RQ-EMRG0001" });
    expect(within(reasons).getByText("Emergency request")).toBeInTheDocument();
    expect(reasons).toHaveTextContent("Warning: Emergency request");
    expect(reasons).toHaveTextContent("(+50)");
    expect(screen.getByText(/not a clinical score/)).toBeInTheDocument();
  });

  it("shows empty and error states with retry", async () => {
    GET.mockResolvedValue(fail(500, "Boom"));
    render(<EmergencyQueue kind="BLOOD_BANK" />);
    expect(await screen.findByText("Operational queue unavailable")).toBeInTheDocument();
    GET.mockResolvedValue(ok(list([])));
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByText("No open requests")).toBeInTheDocument();
  });

  it("refetches on live operational events", async () => {
    routes();
    render(<EmergencyQueue kind="BLOOD_BANK" />);
    await screen.findByTestId("emergency-queue");
    const calls = () => GET.mock.calls.filter((c: unknown[]) => c[0] === "/api/v1/operations/requests").length;
    const before = calls();
    act(() => emit("request.operational_alert"));
    await waitFor(() => expect(calls()).toBe(before + 1));
  });

  it("lets a hospital change priority with a reason code only", async () => {
    routes();
    POST.mockResolvedValue(ok(priority()));
    render(<EmergencyQueue kind="HOSPITAL" />);
    await screen.findByTestId("emergency-queue");
    fireEvent.click(screen.getAllByRole("button", { name: "Why this priority?" })[1]!);
    const form = screen.getByRole("form", { name: "Change priority" });
    fireEvent.change(within(form).getByLabelText("New priority"), { target: { value: "emergency" } });
    fireEvent.click(within(form).getByRole("button", { name: "Update priority" }));
    await waitFor(() =>
      expect(POST).toHaveBeenCalledWith("/api/v1/operations/requests/{request_id}/priority", {
        params: { path: { request_id: "r2" } },
        body: { urgency: "emergency", reason: "escalated_by_requesting_team" },
      }),
    );
    expect(await screen.findByText("Priority is now Emergency.")).toBeInTheDocument();
  });

  it("shows the simulated ETA for dispatched requests", async () => {
    routes({ "/api/v1/operations/requests": ok(list([request({ status: "dispatched", route: ROUTE })])) });
    render(<EmergencyQueue kind="HOSPITAL" />);
    const route = await screen.findByTestId("route");
    expect(route).toHaveTextContent("ETA 20 min");
    expect(route).toHaveTextContent("Slow (simulated)");
    expect(route).toHaveTextContent("Simulated routing — prototype");
  });
});

describe("AllocationPanel", () => {
  it("ranks candidates, explains deprioritised cold-chain bags and needs explicit confirmation", async () => {
    routes();
    POST.mockResolvedValue(ok({ bags: [{ public_id: "VYR-NEWR-0002" }] }));
    const onDispatched = vi.fn();
    render(<AllocationPanel requestId="r1" onDispatched={onDispatched} />);
    expect(await screen.findByTestId("recommendation")).toHaveTextContent("skipping bags with cold-chain concerns");
    const table = screen.getByTestId("candidates");
    expect(table.parentElement).toHaveClass("overflow-x-auto"); // mobile: scrolls, never overflows
    const old = within(table).getByText("VYR-OLDR-0001").closest("tr")!;
    expect(old).toHaveAttribute("data-recommended", "false");
    expect(old).toHaveTextContent("Deprioritised");
    expect(old).toHaveTextContent("Cold-chain critical");
    expect(old).toHaveTextContent("9.3 °C (simulated)");
    expect(within(old).getByRole("list", { name: "Ranking reasons for VYR-OLDR-0001" })).toHaveTextContent("review before any dispatch");
    const recommended = within(table).getByText("VYR-NEWR-0002").closest("tr")!;
    expect(recommended).toHaveTextContent("Recommended");
    expect(screen.getByText(/Synthetic forecast input — prototype/)).toBeInTheDocument();
    expect(screen.getByTestId("allocation")).toHaveTextContent("Elevated");
    expect(screen.getByTestId("route")).toHaveTextContent("ETA 20 min");

    fireEvent.click(screen.getByRole("button", { name: "Dispatch recommended bags…" }));
    expect(POST).not.toHaveBeenCalled(); // nothing is dispatched without confirmation
    const confirm = screen.getByRole("group", { name: "Confirm dispatch" });
    fireEvent.click(within(confirm).getByRole("button", { name: "Confirm dispatch" }));
    await waitFor(() =>
      expect(POST).toHaveBeenCalledWith("/api/v1/requests/{request_id}/fulfil", {
        params: { path: { request_id: "r1" } },
        body: { bag_public_ids: ["VYR-NEWR-0002"] },
      }),
    );
    expect(await screen.findByText("Dispatched VYR-NEWR-0002")).toBeInTheDocument();
    expect(onDispatched).toHaveBeenCalled();
  });

  it("can cancel the confirmation and offers no dispatch when only flagged bags exist", async () => {
    routes({
      "/api/v1/operations/requests/{request_id}/recommendations": ok({
        ...RECOMMENDATION,
        recommended_bag_ids: [],
        recommendation: "Only bags with cold-chain concerns can cover this request — review them before any dispatch",
      }),
    });
    render(<AllocationPanel requestId="r1" onDispatched={vi.fn()} />);
    expect(await screen.findByTestId("recommendation")).toHaveTextContent("Only bags with cold-chain concerns");
    expect(screen.queryByRole("button", { name: "Dispatch recommended bags…" })).not.toBeInTheDocument();
  });

  it("shows an error with retry", async () => {
    GET.mockResolvedValue(fail(404, "Blood request not found"));
    render(<AllocationPanel requestId="r1" onDispatched={vi.fn()} />);
    expect(await screen.findByText("Recommendation unavailable")).toBeInTheDocument();
    routes();
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByTestId("candidates")).toBeInTheDocument();
  });
});

describe("PressurePanel, alerts and routing", () => {
  it("shows pressure bands with text and the synthetic-input label", async () => {
    routes();
    render(<PressurePanel facilityId="b1" />);
    const panel = await screen.findByTestId("pressure");
    expect(panel).toHaveTextContent("Synthetic forecast input — prototype");
    expect(panel).toHaveTextContent("Not a medical emergency prediction");
    const table = within(panel).getByTestId("pressure-table");
    expect(within(table).getAllByRole("row")).toHaveLength(3); // header + elevated + watch
    expect(table).toHaveTextContent("Elevated");
    expect(table).toHaveTextContent("0.7 d");
    fireEvent.click(within(panel).getByRole("button", { name: "Show all rows" }));
    expect(within(table).getAllByRole("row")).toHaveLength(4);
  });

  it("lists alerts with severity in text and an empty state", async () => {
    routes();
    render(<AlertsPanel />);
    const list = await screen.findByRole("list", { name: "Operational alerts" });
    expect(within(list).getAllByRole("listitem")).toHaveLength(3);
    expect(list).toHaveTextContent("Warning: Emergency request RQ-EMRG0001");
    expect(list).toHaveTextContent("Attention: Expires soon");
  });

  it("renders the operations workspace for a blood bank", async () => {
    routes();
    render(<OperationsWorkspace kind="BLOOD_BANK" facilityId="b1" />);
    expect(await screen.findByTestId("emergency-queue")).toBeInTheDocument();
    expect(await screen.findByTestId("ops-alerts")).toBeInTheDocument();
    expect(await screen.findByTestId("routing")).toHaveTextContent("RQ-INTR0009");
    expect(await screen.findByTestId("pressure")).toBeInTheDocument();
    expect(screen.getByTestId("ops-disclaimer")).toBeInTheDocument();
  });

  it("gives hospitals banded network availability", async () => {
    routes({
      "/api/v1/network/availability": ok({
        blood_group: "O+", component: "PRBC", units: 1,
        results: [{ provider: "internal", target_ref: "b1", name: "Central Blood Bank", city: "Kolkata", state: "WB", band: "limited", source: { provider: "internal", kind: "internal", fetched_at: null, note: null, simulated: false } }],
      }),
    });
    render(<OperationsWorkspace kind="HOSPITAL" facilityId="h1" />);
    const card = await screen.findByTestId("availability-bands");
    fireEvent.click(within(card).getByRole("button", { name: "Check bands" }));
    expect(await within(card).findByText("◆ Limited")).toBeInTheDocument();
    expect(card).toHaveTextContent("exact stock of other facilities is never shown");
  });
});

describe("AdminOperations", () => {
  it("shows network counts, open emergencies and simulated routing", async () => {
    routes();
    render(<AdminOperations />);
    const section = await screen.findByTestId("admin-operations");
    expect(section).toHaveTextContent("Open emergencies");
    expect(within(section).getByRole("list", { name: "Open emergency requests" })).toHaveTextContent("RQ-EMRG0001");
    expect(section).toHaveTextContent("Cold-chain warnings");
    expect(await within(section).findByTestId("routing")).toHaveTextContent("Simulated routing overview");
  });

  it("shows an error with retry", async () => {
    GET.mockResolvedValue(fail(403, "Permission denied"));
    render(<AdminOperations />);
    expect(await screen.findByText("Operations overview unavailable")).toBeInTheDocument();
  });
});
