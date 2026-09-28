import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { BloodRequestOut } from "@veyra/api-client";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { displayGroup, parseBagId, relativeExpiry } from "@/lib/network";

const push = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push, replace: vi.fn() }),
  usePathname: () => "/hospital",
}));

const GET = vi.fn();
const POST = vi.fn();
vi.mock("@/lib/api", () => ({
  api: { GET: (...a: unknown[]) => GET(...a), POST: (...a: unknown[]) => POST(...a) },
  SESSION_EXPIRED_EVENT: "veyra:session-expired",
}));

const { RequestCard } = await import("./request-card");
const { TraceSearch, BagTraceView } = await import("./bag-trace");
const { LiveIndicator } = await import("./live-indicator");
const { NewRequest } = await import("./new-request");

const res = (status: number) => new Response(null, { status });

const REQUEST: BloodRequestOut = {
  id: "r1",
  reference: "RQ-ABCD1234",
  hospital_id: "h1",
  hospital_name: "City Hospital",
  provider: "mock",
  target_facility_id: null,
  target_name: "Howrah Regional Blood Centre",
  blood_group: "O-",
  component: "PRBC",
  units: 2,
  urgency: "emergency",
  needed_by: "2026-09-29T09:00:00Z",
  status: "acknowledged",
  notes: null,
  response_note: "Simulated partner blood bank: no real blood bank was contacted.",
  created_at: "2026-09-28T09:00:00Z",
  updated_at: "2026-09-28T09:00:00Z",
  bags: [],
  source: { provider: "mock", kind: "simulated", fetched_at: null, note: null, simulated: true },
};

beforeEach(() => {
  push.mockReset();
  GET.mockReset();
  POST.mockReset();
});

describe("network helpers", () => {
  it("parses typed ids and scanned QR payloads, rejecting look-alikes", () => {
    expect(parseBagId(" vyr-7f3k-2qxm ")).toBe("VYR-7F3K-2QXM");
    expect(parseBagId("veyra:bag:VYR-7F3K-2QXM")).toBe("VYR-7F3K-2QXM");
    expect(parseBagId("VYR-7F3K-2QXO")).toBeNull(); // O is not Crockford
    expect(parseBagId("VYR-7F3K")).toBeNull();
    expect(parseBagId("https://evil.example/VYR-7F3K-2QXM")).toBeNull();
  });

  it("formats expiry and groups", () => {
    const now = new Date("2026-09-28T09:00:00Z");
    expect(relativeExpiry("2026-09-28T14:00:00Z", now)).toBe("in 5 h");
    expect(relativeExpiry("2026-10-03T09:00:00Z", now)).toBe("in 5 days");
    expect(relativeExpiry("2026-09-26T09:00:00Z", now)).toBe("expired 2 days ago");
    expect(displayGroup("AB-")).toBe("AB−");
  });
});

describe("RequestCard", () => {
  it("labels a simulated partner bank and the urgency", () => {
    render(<RequestCard request={REQUEST} perspective="hospital" />);
    expect(screen.getByText("Simulated")).toBeInTheDocument();
    expect(screen.getByText("Emergency")).toBeInTheDocument();
    expect(screen.getByText(/to Howrah Regional Blood Centre/)).toBeInTheDocument();
    expect(screen.getByText("Acknowledged (simulated)")).toBeInTheDocument();
  });
});

describe("TraceSearch", () => {
  it("navigates only for valid bag ids", () => {
    render(<TraceSearch />);
    const input = screen.getByLabelText("Trace a bag");
    fireEvent.change(input, { target: { value: "not a bag" } });
    fireEvent.click(screen.getByRole("button", { name: "Trace" }));
    expect(screen.getByRole("alert")).toHaveTextContent("VYR-7F3K-2QXM");
    expect(push).not.toHaveBeenCalled();
    fireEvent.change(input, { target: { value: "veyra:bag:VYR-7F3K-2QXM" } });
    fireEvent.click(screen.getByRole("button", { name: "Trace" }));
    expect(push).toHaveBeenCalledWith("/bags/VYR-7F3K-2QXM");
  });
});

describe("BagTraceView", () => {
  const trace = (valid: boolean) => ({
    bag: {
      id: "b1",
      public_id: "VYR-7F3K-2QXM",
      qr_payload: "veyra:bag:VYR-7F3K-2QXM",
      blood_group: "O+",
      component: "PRBC",
      volume_ml: 250,
      collected_at: "2026-09-27T09:00:00Z",
      expires_at: "2026-11-08T09:00:00Z",
      status: "in_transit",
      is_expired: false,
      current_facility_id: "f1",
      current_facility_name: "Central Blood Bank",
    },
    events: [
      { seq: 1, event_type: "COLLECTED", occurred_at: "2026-09-27T09:00:00Z", from_facility: null, to_facility: "Central Blood Bank", meta: {}, prev_hash: "0".repeat(64), row_hash: "a".repeat(64) },
      { seq: 2, event_type: "DISPATCHED", occurred_at: "2026-09-28T09:00:00Z", from_facility: "Central Blood Bank", to_facility: "City Hospital", meta: { request: "RQ-1" }, prev_hash: "a".repeat(64), row_hash: "b".repeat(64) },
    ],
    chain: { valid, length: 2, head_hash: valid ? "b".repeat(64) : null, note: "Not anchored on a blockchain yet (planned for Phase 8)." },
  });

  it("renders the custody trail and a verified chain", async () => {
    GET.mockResolvedValue({ data: trace(true), response: res(200) });
    render(<BagTraceView publicId="VYR-7F3K-2QXM" />);
    expect(await screen.findByText("Chain verified · 2 events")).toBeInTheDocument();
    expect(screen.getByText("Dispatched")).toBeInTheDocument();
    expect(screen.getByText(/to City Hospital/)).toBeInTheDocument();
    expect(screen.getByText(/Not anchored on a blockchain/)).toBeInTheDocument();
  });

  it("warns loudly when the chain is broken", async () => {
    GET.mockResolvedValue({ data: trace(false), response: res(200) });
    render(<BagTraceView publicId="VYR-7F3K-2QXM" />);
    expect(await screen.findByText("Chain broken")).toBeInTheDocument();
  });

  it("explains scoped visibility on 404", async () => {
    GET.mockResolvedValue({ data: undefined, error: { status: 404, code: "not_found", detail: "Blood bag not found" }, response: res(404) });
    render(<BagTraceView publicId="VYR-7F3K-2QXM" />);
    expect(await screen.findByText("Bag not found")).toBeInTheDocument();
  });
});

describe("LiveIndicator", () => {
  it("is offline outside a live provider", () => {
    render(<LiveIndicator />);
    expect(screen.getByText(/Offline/)).toBeInTheDocument();
  });
});

describe("NewRequest", () => {
  it("shows banded availability, labels simulated banks and sends an idempotent request", async () => {
    GET.mockResolvedValue({
      data: {
        blood_group: "O+",
        component: "PRBC",
        units: 2,
        results: [
          { provider: "internal", target_ref: "bank-1", name: "Central Blood Bank", city: "Kolkata", state: "West Bengal", band: "sufficient", source: { provider: "internal", kind: "internal", fetched_at: null, note: null, simulated: false } },
          { provider: "mock", target_ref: "MOCK-HWH", name: "Howrah Regional Blood Centre", city: "Howrah", state: "West Bengal", band: "none", source: { provider: "mock", kind: "simulated", fetched_at: null, note: "Simulated partner blood bank", simulated: true } },
        ],
      },
      response: res(200),
    });
    POST.mockResolvedValue({ data: { ...REQUEST, id: "r2", provider: "internal", status: "pending" }, response: res(201) });
    const onCreated = vi.fn();
    render(<NewRequest onCreated={onCreated} />);
    fireEvent.click(screen.getByRole("button", { name: "Find blood banks" }));
    expect(await screen.findByText("Can cover this request")).toBeInTheDocument();
    expect(screen.getByText("Simulated")).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: /Howrah/ })).toBeDisabled(); // no stock
    fireEvent.click(screen.getByRole("radio", { name: /Central Blood Bank/ }));
    fireEvent.click(screen.getByRole("button", { name: "Send request" }));
    await waitFor(() => expect(onCreated).toHaveBeenCalled());
    const [path, init] = POST.mock.calls[0] as [string, { params: { header: Record<string, string> }; body: Record<string, unknown> }];
    expect(path).toBe("/api/v1/requests");
    expect(init.params.header["Idempotency-Key"]).toMatch(/.{8,}/);
    expect(init.body).toMatchObject({ provider: "internal", target_ref: "bank-1", units: 2 });
  });
});
