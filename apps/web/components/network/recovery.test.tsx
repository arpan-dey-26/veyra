import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

// Phase 8 hardening: a failed load must never leave a page stuck (endless skeleton) or
// permanently in error after a later refresh succeeds; every error offers "Try again".

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/hospital",
}));

const GET = vi.fn();
const POST = vi.fn();
vi.mock("@/lib/api", () => ({
  api: { GET: (...a: unknown[]) => GET(...a), POST: (...a: unknown[]) => POST(...a) },
  SESSION_EXPIRED_EVENT: "veyra:session-expired",
}));

const live = new Map<string, () => void>();
vi.mock("@/lib/live", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/live")>()),
  useLiveRefresh: (topics: string[], cb: () => void) => {
    for (const t of topics) live.set(t, cb);
  },
}));

const { MyRequests } = await import("./my-requests");
const { DonationDesk } = await import("./donation-desk");
const { DonorDonations } = await import("../donor/donor-donations");

const fail = () => ({
  error: { title: "Service unavailable", detail: "Temporarily unavailable" },
  response: new Response(null, { status: 503 }),
});

beforeEach(() => {
  GET.mockReset();
  POST.mockReset();
  live.clear();
});

describe("load failures recover", () => {
  it("my requests: error offers retry and a successful retry clears it", async () => {
    GET.mockResolvedValueOnce(fail()).mockResolvedValue({ data: { data: [], meta: { total: 0 } } });
    render(<MyRequests />);
    expect(await screen.findByRole("alert")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByText("No requests yet")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("my requests: a live refresh after a failure also recovers", async () => {
    GET.mockResolvedValueOnce(fail()).mockResolvedValue({ data: { data: [], meta: { total: 0 } } });
    render(<MyRequests />);
    await screen.findByRole("alert");
    live.get("request.dispatched")?.();
    await waitFor(() => expect(screen.queryByRole("alert")).toBeNull());
  });

  it("donation desk: recent donations show an error instead of an endless skeleton", async () => {
    GET.mockResolvedValueOnce(fail()).mockResolvedValue({ data: { data: [], meta: { total: 0 } } });
    render(<DonationDesk />);
    expect(await screen.findByText("Recent donations unavailable")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByText("No donations yet")).toBeInTheDocument();
  });

  it("donor history: failure is announced and retryable", async () => {
    GET.mockResolvedValueOnce(fail()).mockResolvedValue({
      data: { donations: [], eligible_now: true, eligible_from: null, interval_days: 90 },
    });
    render(<DonorDonations />);
    expect(await screen.findByRole("alert")).toHaveTextContent("couldn't be loaded");
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByText("No donations yet")).toBeInTheDocument();
  });
});
