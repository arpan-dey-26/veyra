import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type {
  ColdChainReport,
  ColdChainThresholds,
  MonitoredList,
  NetworkEvent,
  TelemetryDevice,
  TelemetryReading,
  TelemetrySeries,
  TelemetrySummary,
} from "@veyra/api-client";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  formatDuration,
  formatTemp,
  readingCounts,
  TELEMETRY_BADGE,
  TELEMETRY_DISCLAIMER,
  temperatureDomain,
} from "@/lib/telemetry";

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

// Capture SSE subscriptions so tests can push simulated live events.
type Listener = (event: NetworkEvent) => void;
const listeners: { topics: string[] | "*"; listener: Listener }[] = [];
vi.mock("@/lib/live", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/live")>()),
  useLive: () => ({
    status: "live",
    lastEventAt: null,
    subscribe: (topics: string[] | "*", listener: Listener) => {
      const entry = { topics, listener };
      listeners.push(entry);
      return () => {
        const i = listeners.indexOf(entry);
        if (i >= 0) listeners.splice(i, 1);
      };
    },
  }),
}));

function emit(topic: string, aggregateId: string) {
  const event: NetworkEvent = {
    event_id: `${topic}-${Math.random()}`,
    topic,
    aggregate_type: "bag",
    aggregate_id: aggregateId,
    created_at: "2026-09-29T10:00:00Z",
  };
  for (const { topics, listener } of [...listeners]) {
    if (topics === "*" || topics.includes(topic)) listener(event);
  }
}

const { TelemetryChart } = await import("@/components/charts/telemetry-chart");
const { BagTelemetryPanel, SmartBagMonitor, AdminColdChain, TelemetryDisclaimer } = await import("./cold-chain");
const { SessionProvider } = await import("@/lib/session");
const { BagTraceView } = await import("@/components/network/bag-trace");

const res = (status: number) => new Response(null, { status });
const ok = (data: unknown) => ({ data, response: res(200) });
const fail = (status: number, code: string, detail: string) => ({
  data: undefined,
  error: { status, code, detail },
  response: res(status),
});

const SOURCE = { provider: "simulator", kind: "simulated" as const, fetched_at: null, note: "Simulated IoT telemetry", simulated: true };
const PUBLIC_ID = "VYR-7F3K-2QXM";

const THRESHOLDS: ColdChainThresholds = {
  label: "2–6 °C",
  nominal_c: 4,
  normal_low: 2,
  normal_high: 6,
  critical_low: 1,
  critical_high: 8,
  note: "Prototype thresholds, not clinical guidance.",
};

function reading(seq: number, temperature_c: number, status: TelemetryReading["status"]): TelemetryReading {
  return { seq, recorded_at: `2026-09-29T10:0${seq}:00Z`, temperature_c, battery_pct: 98 - seq * 0.2, status };
}

const READINGS = [reading(1, 4.1, "normal"), reading(2, 6.9, "warning"), reading(3, 9.2, "critical"), reading(4, 4.3, "normal")];

const DEVICE: TelemetryDevice = {
  public_id: PUBLIC_ID,
  device_id: "SIM-AB12-CD34",
  rfid: "E280-1160-6000-0209-AB12",
  simulated: true,
  battery_pct: 97.2,
  device_status: "online",
  last_seen_at: "2026-09-29T10:04:00Z",
  readings_count: 4,
  sim_running: false,
  sim_mode: "normal",
  attached_at: "2026-09-29T10:00:00Z",
  source: SOURCE,
};

function summary(over: Partial<TelemetrySummary> = {}): TelemetrySummary {
  return {
    public_id: PUBLIC_ID,
    component: "PRBC",
    device_id: DEVICE.device_id,
    cold_chain_status: "normal",
    device_status: "online",
    current_c: 4.3,
    min_c: 4.1,
    max_c: 9.2,
    last_reading_at: "2026-09-29T10:04:00Z",
    battery_pct: 97.2,
    readings_count: 4,
    excursion_active: false,
    excursion_started_at: null,
    excursion_duration_seconds: null,
    excursion_severity: null,
    thresholds: THRESHOLDS,
    source: SOURCE,
    disclaimer: TELEMETRY_DISCLAIMER,
    ...over,
  };
}

const SERIES: TelemetrySeries = { public_id: PUBLIC_ID, component: "PRBC", thresholds: THRESHOLDS, readings: READINGS, source: SOURCE, disclaimer: TELEMETRY_DISCLAIMER };

const REPORT: ColdChainReport = {
  public_id: PUBLIC_ID,
  component: "PRBC",
  cold_chain_status: "normal",
  thresholds: THRESHOLDS,
  excursions: [
    { started_at: "2026-09-29T10:02:00Z", ended_at: "2026-09-29T10:04:00Z", duration_seconds: 120, severity: "critical", peak_c: 9.2, readings: 2 },
  ],
  trace_events: [
    { seq: 2, event_type: "DEVICE_ATTACHED", occurred_at: "2026-09-29T10:00:00Z", meta: {}, row_hash: "a".repeat(64) },
    { seq: 3, event_type: "TEMP_EXCURSION", occurred_at: "2026-09-29T10:02:00Z", meta: {}, row_hash: "b".repeat(64) },
    { seq: 4, event_type: "TEMP_RECOVERED", occurred_at: "2026-09-29T10:04:00Z", meta: {}, row_hash: "c".repeat(64) },
  ],
  chain_valid: true,
  source: SOURCE,
  disclaimer: TELEMETRY_DISCLAIMER,
};

function panelRoutes(over: Record<string, unknown> = {}) {
  GET.mockImplementation(async (path: string) => {
    if (path in over) return over[path];
    if (path === "/api/v1/bags/{public_id}/device") return ok(DEVICE);
    if (path === "/api/v1/bags/{public_id}/telemetry/summary") return ok(summary());
    if (path === "/api/v1/bags/{public_id}/telemetry") return ok(SERIES);
    if (path === "/api/v1/bags/{public_id}/cold-chain") return ok(REPORT);
    return fail(404, "not_found", "not found");
  });
}

const MONITORED: MonitoredList = {
  scope: "facility",
  counts: { normal: 1, warning: 1, critical: 1, offline: 1, paused: 0, awaiting: 0 },
  bags: [
    { public_id: "VYR-AAAA-0001", blood_group: "O_POS", component: "PRBC", bag_status: "available", device_id: "SIM-0001-0001", device_status: "online", cold_chain_status: "normal", current_c: 4.2, last_reading_at: "2026-09-29T10:00:00Z", battery_pct: 99, excursion_duration_seconds: null, sim_running: true },
    { public_id: "VYR-AAAA-0002", blood_group: "A_POS", component: "PRBC", bag_status: "available", device_id: "SIM-0001-0002", device_status: "online", cold_chain_status: "warning", current_c: 6.8, last_reading_at: "2026-09-29T10:00:00Z", battery_pct: 95, excursion_duration_seconds: 60, sim_running: true },
    { public_id: "VYR-AAAA-0003", blood_group: "B_NEG", component: "PLATELETS", bag_status: "available", device_id: "SIM-0001-0003", device_status: "online", cold_chain_status: "critical", current_c: 27.5, last_reading_at: "2026-09-29T10:00:00Z", battery_pct: 90, excursion_duration_seconds: 200, sim_running: true },
    { public_id: "VYR-AAAA-0004", blood_group: "AB_POS", component: "FFP", bag_status: "available", device_id: "SIM-0001-0004", device_status: "offline", cold_chain_status: "normal", current_c: -25, last_reading_at: "2026-09-29T09:00:00Z", battery_pct: 80, excursion_duration_seconds: null, sim_running: false },
  ],
  simulator_enabled: true,
  source: SOURCE,
  disclaimer: TELEMETRY_DISCLAIMER,
};

beforeEach(() => {
  GET.mockReset();
  POST.mockReset();
  listeners.length = 0;
});

describe("telemetry helpers", () => {
  it("formats temperatures and durations", () => {
    expect(formatTemp(4.26)).toBe("4.3 °C");
    expect(formatTemp(-25)).toBe("-25.0 °C");
    expect(formatTemp(null)).toBe("—");
    expect(formatDuration(45)).toBe("45 s");
    expect(formatDuration(120)).toBe("2 min");
    expect(formatDuration(200)).toBe("3 min 20 s");
    expect(formatDuration(7500)).toBe("2 h 5 min");
    expect(formatDuration(null)).toBe("—");
  });

  it("keeps critical limits and every reading inside the chart domain", () => {
    expect(temperatureDomain([], THRESHOLDS)).toEqual([0, 9]);
    expect(temperatureDomain([{ temperature_c: 12.4 }], THRESHOLDS)).toEqual([0, 14]);
  });

  it("counts readings by status", () => {
    expect(readingCounts(READINGS)).toEqual({ normal: 2, warning: 1, critical: 1 });
  });

  it("carries the verbatim prototype disclaimer", () => {
    render(<TelemetryDisclaimer />);
    const note = screen.getByTestId("telemetry-disclaimer");
    expect(note).toHaveTextContent(TELEMETRY_BADGE);
    expect(note).toHaveTextContent(
      "This is simulated IoT telemetry for a student engineering prototype and is not a certified medical monitoring system.",
    );
  });
});

describe("TelemetryChart", () => {
  it("renders an accessible chart with warning and critical markers", () => {
    render(<TelemetryChart readings={READINGS} thresholds={THRESHOLDS} />);
    expect(screen.getByLabelText(/Temperature: 4 simulated readings, latest 4.3 °C/)).toBeInTheDocument();
    expect(screen.getByLabelText("Legend")).toHaveTextContent("Critical limits");
  });

  it("offers a table view with each reading's status", () => {
    render(<TelemetryChart readings={READINGS} thresholds={THRESHOLDS} />);
    fireEvent.click(screen.getByRole("button", { name: "Table" }));
    const table = screen.getByTestId("telemetry-table");
    expect(within(table).getAllByRole("row")).toHaveLength(READINGS.length + 1);
    expect(table).toHaveTextContent("9.2 °C");
    expect(table).toHaveTextContent("Critical");
    expect(table).toHaveTextContent("Warning");
  });

  it("shows an empty state without readings", () => {
    render(<TelemetryChart readings={[]} thresholds={THRESHOLDS} />);
    expect(screen.getByText("No readings yet. Take a reading or start the simulator.")).toBeInTheDocument();
  });
});

describe("BagTelemetryPanel", () => {
  it("shows the device, current state, chart, excursions and trace link-up", async () => {
    panelRoutes();
    render(<BagTelemetryPanel publicId={PUBLIC_ID} canSimulate />);
    expect(await screen.findByTestId("device-id")).toHaveTextContent("SIM-AB12-CD34");
    const panel = screen.getByTestId("bag-telemetry");
    expect(within(panel).getByTestId("telemetry-disclaimer")).toBeInTheDocument();
    expect(panel).toHaveTextContent("4.3 °C");
    expect(panel).toHaveTextContent("97%");
    expect(within(screen.getByTestId("excursions")).getByText(/recovered after 2 min/)).toBeInTheDocument();
    expect(panel).toHaveTextContent("3 cold-chain entries in the hash-chained trace · chain verified");
    expect(screen.getByRole("button", { name: "Inject excursion" })).toBeInTheDocument();
  });

  it("shows warning and critical states with the excursion duration", async () => {
    panelRoutes({
      "/api/v1/bags/{public_id}/telemetry/summary": ok(
        summary({ cold_chain_status: "critical", excursion_active: true, excursion_started_at: "2026-09-29T10:02:00Z", excursion_duration_seconds: 200, excursion_severity: "critical", current_c: 9.2 }),
      ),
    });
    render(<BagTelemetryPanel publicId={PUBLIC_ID} canSimulate={false} />);
    await screen.findByTestId("device-id");
    const badge = document.querySelector('[data-cold-status="critical"]');
    expect(badge).toHaveTextContent("Critical");
    expect(screen.getByTestId("bag-telemetry")).toHaveTextContent("3 min 20 s");
  });

  it("hides simulator controls from viewers who do not hold the bag", async () => {
    panelRoutes();
    render(<BagTelemetryPanel publicId={PUBLIC_ID} canSimulate={false} />);
    await screen.findByTestId("device-id");
    expect(screen.queryByRole("button", { name: "Inject excursion" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Take reading" })).not.toBeInTheDocument();
  });

  it("offers to attach a simulated device when the bag is not monitored", async () => {
    panelRoutes({ "/api/v1/bags/{public_id}/device": fail(404, "no_device", "No simulated device is attached to this bag") });
    POST.mockResolvedValue(ok({ device: DEVICE, summary: summary(), generated: 0, transitions: ["DEVICE_ATTACHED"] }));
    render(<BagTelemetryPanel publicId={PUBLIC_ID} canSimulate />);
    expect(await screen.findByText("Not monitored")).toBeInTheDocument();
    panelRoutes();
    fireEvent.click(screen.getByRole("button", { name: "Attach simulated device" }));
    await waitFor(() => expect(POST).toHaveBeenCalledWith("/api/v1/simulator/bags/{public_id}/attach", expect.anything()));
    expect(await screen.findByText(/Simulated device attached/)).toBeInTheDocument();
    expect(await screen.findByTestId("device-id")).toBeInTheDocument();
  });

  it("injects an excursion and reports the raised transitions", async () => {
    panelRoutes();
    POST.mockResolvedValue(ok({ device: DEVICE, summary: summary(), generated: 1, transitions: ["temperature.critical"] }));
    render(<BagTelemetryPanel publicId={PUBLIC_ID} canSimulate />);
    await screen.findByTestId("device-id");
    fireEvent.click(screen.getByRole("button", { name: "Take reading" }));
    await waitFor(() =>
      expect(POST).toHaveBeenCalledWith("/api/v1/simulator/bags/{public_id}/tick", expect.objectContaining({ body: { count: 1 } })),
    );
    expect(await screen.findByText("Critical: temperature passed the critical limit.")).toBeInTheDocument();
  });

  it("shows an error with retry", async () => {
    panelRoutes({ "/api/v1/bags/{public_id}/device": fail(500, "internal", "Boom") });
    render(<BagTelemetryPanel publicId={PUBLIC_ID} canSimulate />);
    expect(await screen.findByText("Telemetry unavailable")).toBeInTheDocument();
    panelRoutes();
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByTestId("device-id")).toBeInTheDocument();
  });

  it("refetches on live telemetry events for this bag only", async () => {
    panelRoutes();
    render(<BagTelemetryPanel publicId={PUBLIC_ID} canSimulate />);
    await screen.findByTestId("device-id");
    const deviceCalls = () => GET.mock.calls.filter((call: unknown[]) => call[0] === "/api/v1/bags/{public_id}/device").length;
    const before = deviceCalls();
    act(() => emit("temperature.warning", "VYR-OTHER-0000"));
    expect(deviceCalls()).toBe(before);
    act(() => emit("temperature.warning", PUBLIC_ID));
    await waitFor(() => expect(deviceCalls()).toBe(before + 1));
  });
});

describe("SmartBagMonitor", () => {
  it("lists monitored bags with status counts and offers to attach", async () => {
    GET.mockImplementation(async (path: string) => {
      if (path === "/api/v1/telemetry/monitored") return ok(MONITORED);
      if (path === "/api/v1/inventory/bags")
        return ok({ data: [{ id: "b9", public_id: "VYR-BBBB-0009", blood_group: "O_NEG", component: "PRBC" }], next_cursor: null });
      return fail(404, "not_found", "x");
    });
    render(<SmartBagMonitor />);
    const monitor = await screen.findByTestId("smart-bag-monitor");
    expect(within(monitor).getByTestId("telemetry-disclaimer")).toBeInTheDocument();
    const rows = within(screen.getByTestId("monitored-table")).getAllByRole("row");
    expect(rows).toHaveLength(5);
    expect(monitor).toHaveTextContent("27.5 °C");
    expect(monitor).toHaveTextContent("Offline / stale");
    expect(monitor).toHaveTextContent("3 min 20 s");
    expect(screen.getByRole("button", { name: "Attach simulated device" })).toBeInTheDocument();
  });

  it("shows the empty state and an error with retry", async () => {
    GET.mockResolvedValue(fail(500, "internal", "Boom"));
    render(<SmartBagMonitor />);
    expect(await screen.findByText("Cold-chain view unavailable")).toBeInTheDocument();
    GET.mockImplementation(async (path: string) =>
      path === "/api/v1/telemetry/monitored"
        ? ok({ ...MONITORED, bags: [], counts: {} })
        : ok({ data: [], next_cursor: null }),
    );
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByText("No monitored bags yet")).toBeInTheDocument();
  });

  it("refreshes on any live telemetry event", async () => {
    GET.mockImplementation(async (path: string) =>
      path === "/api/v1/telemetry/monitored" ? ok(MONITORED) : ok({ data: [], next_cursor: null }),
    );
    render(<SmartBagMonitor />);
    await screen.findByTestId("smart-bag-monitor");
    const calls = () => GET.mock.calls.filter((call: unknown[]) => call[0] === "/api/v1/telemetry/monitored").length;
    const before = calls();
    act(() => emit("temperature.critical", "VYR-AAAA-0003"));
    await waitFor(() => expect(calls()).toBe(before + 1));
  });
});

describe("AdminColdChain", () => {
  it("shows network-level counts only", async () => {
    GET.mockResolvedValue(ok({ ...MONITORED, scope: "network" }));
    render(<AdminColdChain />);
    const card = await screen.findByTestId("admin-cold-chain");
    expect(card).toHaveTextContent("4 monitored bags · 1 normal · 1 warning · 1 critical · 1 offline or paused");
    expect(card).toHaveTextContent(TELEMETRY_BADGE);
  });
});

describe("bag page integration", () => {
  const TRACE = {
    bag: {
      id: "b1",
      public_id: PUBLIC_ID,
      qr_payload: `veyra:bag:${PUBLIC_ID}`,
      blood_group: "O_POS",
      component: "PRBC",
      volume_ml: 350,
      collected_at: "2026-09-27T09:00:00Z",
      expires_at: "2026-11-08T09:00:00Z",
      status: "available",
      is_expired: false,
      current_facility_id: "f1",
      current_facility_name: "Central Blood Bank",
    },
    events: [
      { seq: 1, event_type: "COLLECTED", occurred_at: "2026-09-27T09:00:00Z", from_facility: null, to_facility: "Central Blood Bank", meta: {}, prev_hash: "0".repeat(64), row_hash: "a".repeat(64) },
    ],
    chain: { valid: true, length: 1, head_hash: "a".repeat(64), note: "Not anchored on a blockchain (possible future work)." },
  };
  const me = (facilityId: string) => ({
    user: { id: "u1", email: "bank@demo.veyra", full_name: "Demo Bank", mobile: "+910000000000", role: "BLOOD_BANK", status: "active", is_demo: true, created_at: "2026-09-01T00:00:00Z", verified_at: null },
    facility: { id: facilityId, name: "Central Blood Bank", type: "BLOOD_BANK", city: "Kolkata", state: "West Bengal", is_simulated: false },
    donor: null,
    permissions: [],
  });

  async function renderPage(facilityId: string) {
    panelRoutes({ "/api/v1/auth/me": ok(me(facilityId)), "/api/v1/bags/{public_id}": ok(TRACE) });
    render(
      <SessionProvider>
        <BagTraceView publicId={PUBLIC_ID} />
      </SessionProvider>,
    );
    await screen.findByTestId("device-id");
  }

  it("shows the cold-chain panel with simulator controls for the holding facility", async () => {
    await renderPage("f1");
    expect(screen.getByRole("heading", { name: "Cold chain" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Restore normal temperature" })).toBeInTheDocument();
  });

  it("is read-only for a signed-in user at another facility", async () => {
    await renderPage("f2");
    expect(screen.queryByRole("button", { name: "Restore normal temperature" })).not.toBeInTheDocument();
  });
});
