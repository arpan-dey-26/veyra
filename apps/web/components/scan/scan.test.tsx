import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { QR_DISCLAIMER } from "@/lib/phase8";

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn(), replace: vi.fn() }), usePathname: () => "/scan" }));
const GET = vi.fn();
vi.mock("@/lib/api", () => ({
  api: { GET: (...a: unknown[]) => GET(...a), POST: vi.fn() },
  SESSION_EXPIRED_EVENT: "veyra:session-expired",
}));

const { BagScanner, cameraSupport } = await import("./bag-scanner");
const { BagQrCard, QrSvg } = await import("./bag-qr");

const BAG = {
  id: "b1",
  public_id: "VYR-7F3K-2QXM",
  qr_payload: "veyra:bag:VYR-7F3K-2QXM",
  blood_group: "O+",
  component: "PRBC",
  volume_ml: 250,
  collected_at: "2026-09-28T09:00:00Z",
  expires_at: "2026-11-09T09:00:00Z",
  status: "in_transit",
  is_expired: false,
  current_facility_id: "f1",
  current_facility_name: "Central Blood Bank",
};
const RESULT = {
  public_id: BAG.public_id,
  qr_payload: BAG.qr_payload,
  bag: BAG,
  lifecycle_status: "in_transit",
  usable: false,
  location: "Central Blood Bank",
  cold_chain: { monitored: true, status: "warning", excursion_active: true, current_c: 7.4, last_reading_at: "2026-09-28T10:00:00Z", simulated: true },
  shipment: {
    id: "s1",
    reference: "SHP-ABCD1234",
    status: "in_transit",
    source_name: "Central Blood Bank",
    destination_name: "City Hospital",
    eta_at: "2026-09-28T11:00:00Z",
    delay_active: false,
    simulated: true,
  },
  chain: { valid: true, length: 6, head_hash: "a".repeat(64), note: "n" },
  events: 6,
  last_event_type: "TEMP_EXCURSION",
  last_event_at: "2026-09-28T10:00:00Z",
  trace_path: "/bags/VYR-7F3K-2QXM",
  disclaimer: QR_DISCLAIMER,
};
const res = (status: number) => new Response(null, { status });

beforeEach(() => GET.mockReset());

describe("bag scanner", () => {
  it("falls back to manual entry when the camera can't be used (jsdom)", () => {
    render(<BagScanner />);
    expect(cameraSupport()).not.toBe("ok");
    expect(screen.getByText("Camera scanning isn't available here")).toBeInTheDocument();
    expect(screen.getByTestId("qr-disclaimer")).toHaveTextContent(QR_DISCLAIMER);
    expect(screen.getByText("Nothing scanned yet")).toBeInTheDocument();
  });

  it("looks up a typed id and shows status, cold chain, shipment and trace", async () => {
    GET.mockResolvedValue({ data: RESULT, response: res(200) });
    render(<BagScanner />);
    fireEvent.change(screen.getByLabelText("Bag ID or QR text"), { target: { value: "vyr-7f3k-2qxm" } });
    fireEvent.click(screen.getByRole("button", { name: "Look up" }));
    expect(await screen.findByTestId("scan-result")).toBeInTheDocument();
    expect(GET).toHaveBeenCalledWith("/api/v1/bags/scan", { params: { query: { payload: "vyr-7f3k-2qxm" } } });
    expect(screen.getByTestId("scan-chain")).toHaveTextContent("Chain verified · 6 events");
    expect(screen.getByText("SHP-ABCD1234")).toHaveAttribute("href", "/shipments/s1");
    expect(screen.getByText("Excursion active")).toBeInTheDocument();
    expect(screen.getByText("Open the complete bag trace")).toHaveAttribute("href", "/bags/VYR-7F3K-2QXM");
  });

  it("rejects malformed input locally without calling the API", () => {
    render(<BagScanner />);
    fireEvent.change(screen.getByLabelText("Bag ID or QR text"), { target: { value: "hello" } });
    fireEvent.click(screen.getByRole("button", { name: "Look up" }));
    expect(screen.getByText("Not a VEYRA bag label")).toBeInTheDocument();
    expect(GET).not.toHaveBeenCalled();
    fireEvent.change(screen.getByLabelText("Bag ID or QR text"), { target: { value: "  " } });
    fireEvent.click(screen.getByRole("button", { name: "Look up" }));
    expect(screen.getByRole("alert")).toHaveTextContent("Enter a bag ID");
  });

  it("shows not-found for bags outside the caller's scope and retries other failures", async () => {
    GET.mockResolvedValueOnce({ error: { title: "Not found", detail: "Blood bag not found" }, response: res(404) });
    render(<BagScanner />);
    fireEvent.change(screen.getByLabelText("Bag ID or QR text"), { target: { value: "veyra:bag:VYR-7F3K-2QXM" } });
    fireEvent.click(screen.getByRole("button", { name: "Look up" }));
    expect(await screen.findByText("No bag found")).toBeInTheDocument();
    GET.mockResolvedValueOnce({ error: { title: "Down", detail: "Service unavailable" }, response: res(503) });
    fireEvent.click(screen.getByRole("button", { name: "Look up" }));
    expect(await screen.findByText("Lookup failed")).toBeInTheDocument();
    GET.mockResolvedValueOnce({ data: RESULT, response: res(200) });
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByTestId("scan-result")).toBeInTheDocument();
  });
});

describe("bag QR", () => {
  it("renders an accessible SVG with a quiet zone", () => {
    render(<QrSvg modules={["101", "010", "101"]} label="QR label for bag X" />);
    const svg = screen.getByRole("img", { name: "QR label for bag X" });
    expect(svg).toHaveAttribute("viewBox", "0 0 11 11");
  });

  it("loads the QR only on demand and shows the disclaimer", async () => {
    GET.mockResolvedValue({
      data: { public_id: BAG.public_id, payload: BAG.qr_payload, size: 3, modules: ["111", "101", "111"], error_correction: "M", disclaimer: QR_DISCLAIMER },
      response: res(200),
    });
    render(<BagQrCard publicId={BAG.public_id} payload={BAG.qr_payload} />);
    expect(GET).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Show QR" }));
    expect(await screen.findByTestId("bag-qr-svg")).toBeInTheDocument();
    expect(screen.getByText(QR_DISCLAIMER)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Print label" })).toBeInTheDocument();
  });
});
