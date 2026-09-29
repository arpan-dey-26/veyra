import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { CAMP_DISCLAIMER } from "@/lib/phase8";

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn(), replace: vi.fn() }), usePathname: () => "/camps" }));
const GET = vi.fn();
const POST = vi.fn();
const PATCH = vi.fn();
vi.mock("@/lib/api", () => ({
  api: { GET: (...a: unknown[]) => GET(...a), POST: (...a: unknown[]) => POST(...a), PATCH: (...a: unknown[]) => PATCH(...a) },
  SESSION_EXPIRED_EVENT: "veyra:session-expired",
}));
vi.mock("@/lib/live", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/live")>()),
  useLiveRefresh: () => undefined,
}));

const { CampManagement, CampDetail, DonorCamps } = await import("./camps");

const stats = { registered: 1, attended: 0, cancelled: 0, no_show: 0, donations_recorded: 0, bags_collected: 0, seats_left: 49 };
const CAMP = {
  id: "c1",
  code: "CMP-ABCD-1234",
  title: "Salt Lake Camp",
  organizer_facility_id: "f1",
  organizer_name: "Central Blood Bank",
  venue: "Community Hall",
  city: "Kolkata",
  state: "West Bengal",
  starts_at: "2026-10-01T04:00:00Z",
  ends_at: "2026-10-01T10:00:00Z",
  capacity: 50,
  registered_count: 1,
  status: "ongoing",
  registration_open: false,
  description: null,
  contact_name: "Camp Desk (demo)",
  contact_phone: null,
  contact_email: null,
  cancel_reason: null,
  created_at: "2026-09-28T09:00:00Z",
  updated_at: "2026-09-28T09:00:00Z",
  allowed_actions: ["complete"],
  editable: false,
  stats,
  disclaimer: CAMP_DISCLAIMER,
};
const DASH = { scope: "facility", upcoming: 0, active: 1, completed: 0, cancelled: 0, total_capacity: 50, total_registered: 1, total_attended: 0, donations_recorded: 0, bags_collected: 0, next_camps: [], disclaimer: CAMP_DISCLAIMER };
const REG = { id: "r1", donor_id: "d1", donor_name: "Demo Donor", mobile_masked: "+91******3210", status: "registered", registered_at: "2026-09-28T09:00:00Z", cancelled_at: null, attended_at: null, donation_id: null };
const PUBLIC = { ...CAMP, id: "c2", status: "registration_open", registration_open: true, seats_left: 49, my_registration_status: null };
const fail = () => ({ error: { title: "Down", detail: "Service unavailable" }, response: new Response(null, { status: 503 }) });
const ok = (data: unknown) => ({ data, response: new Response(null, { status: 200 }) });

beforeEach(() => {
  GET.mockReset();
  POST.mockReset();
  PATCH.mockReset();
});

describe("camp management", () => {
  it("lists camps with the dashboard, filter and disclaimer", async () => {
    GET.mockImplementation((path: string) =>
      Promise.resolve(path.endsWith("/dashboard") ? ok(DASH) : ok({ scope: "facility", camps: [CAMP], disclaimer: CAMP_DISCLAIMER })),
    );
    render(<CampManagement isAdmin={false} />);
    expect(await screen.findByText("Salt Lake Camp")).toBeInTheDocument();
    expect(screen.getByTestId("camp-disclaimer")).toHaveTextContent(CAMP_DISCLAIMER);
    expect(screen.getByTestId("camp-dashboard")).toHaveTextContent("Active");
    fireEvent.click(screen.getByRole("button", { name: "Upcoming" }));
    expect(screen.getByText("No camps match")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "New camp" }));
    expect(screen.getByRole("form", { name: "New camp" })).toBeInTheDocument();
  });

  it("shows an empty state and recovers from errors", async () => {
    let n = 0;
    GET.mockImplementation((path: string) =>
      Promise.resolve(path.endsWith("/dashboard") ? ok(DASH) : n++ === 0 ? fail() : ok({ scope: "facility", camps: [], disclaimer: CAMP_DISCLAIMER })),
    );
    render(<CampManagement isAdmin={false} />);
    expect(await screen.findByText("Camps unavailable")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByText("No camps yet")).toBeInTheDocument();
  });

  it("creates a camp and surfaces field errors", async () => {
    GET.mockImplementation((path: string) =>
      Promise.resolve(path.endsWith("/dashboard") ? ok(DASH) : ok({ scope: "facility", camps: [], disclaimer: CAMP_DISCLAIMER })),
    );
    POST.mockResolvedValueOnce({
      error: { type: "about:blank", title: "Invalid", status: 422, code: "invalid_camp", detail: "The camp must end after it starts.", request_id: null },
      response: new Response(null, { status: 422 }),
    });
    render(<CampManagement isAdmin={false} />);
    fireEvent.click(await screen.findByRole("button", { name: "New camp" }));
    fireEvent.change(screen.getByLabelText("Camp title"), { target: { value: "Demo camp" } });
    fireEvent.click(screen.getByRole("button", { name: "Create camp" }));
    expect(await screen.findByText("The camp must end after it starts.")).toBeInTheDocument();
    expect(POST).toHaveBeenCalledWith("/api/v1/camps", expect.objectContaining({ body: expect.objectContaining({ title: "Demo camp" }) }));
  });

  it("detail: lifecycle action, attendance and not-found", async () => {
    GET.mockImplementation((path: string) =>
      Promise.resolve(path.endsWith("/registrations") ? ok({ camp_id: "c1", code: CAMP.code, registrations: [REG], disclaimer: CAMP_DISCLAIMER }) : ok(CAMP)),
    );
    POST.mockResolvedValue(ok(CAMP));
    render(<CampDetail campId="c1" />);
    expect(await screen.findByText("Demo Donor")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Confirm attendance" }));
    await waitFor(() =>
      expect(POST).toHaveBeenCalledWith("/api/v1/camps/{camp_id}/registrations/{registration_id}/attend", {
        params: { path: { camp_id: "c1", registration_id: "r1" } },
      }),
    );
    fireEvent.click(screen.getByRole("button", { name: "Complete camp" }));
    await waitFor(() =>
      expect(POST).toHaveBeenCalledWith("/api/v1/camps/{camp_id}/actions/{action}", expect.objectContaining({ params: { path: { camp_id: "c1", action: "complete" } } })),
    );
  });

  it("detail: 404 renders not-found", async () => {
    GET.mockResolvedValue({ error: { title: "Not found", detail: "Camp not found" }, response: new Response(null, { status: 404 }) });
    render(<CampDetail campId="nope" />);
    expect(await screen.findByText("Camp not found")).toBeInTheDocument();
  });
});

describe("donor camps", () => {
  it("registers for an open camp and lists my registrations", async () => {
    GET.mockImplementation((path: string) =>
      Promise.resolve(path.endsWith("/me/registrations") ? ok({ registrations: [], disclaimer: CAMP_DISCLAIMER }) : ok({ camps: [PUBLIC], disclaimer: CAMP_DISCLAIMER })),
    );
    POST.mockResolvedValue(ok({}));
    render(<DonorCamps canRegister />);
    fireEvent.click(await screen.findByRole("button", { name: "Register" }));
    await waitFor(() => expect(POST).toHaveBeenCalledWith("/api/v1/camps/{camp_id}/register", { params: { path: { camp_id: "c2" } } }));
    expect(screen.getByText("No registrations yet")).toBeInTheDocument();
  });

  it("searches, shows empty results, and hides actions for read-only viewers", async () => {
    GET.mockResolvedValue(ok({ camps: [PUBLIC], disclaimer: CAMP_DISCLAIMER }));
    render(<DonorCamps canRegister={false} />);
    await screen.findByText("Salt Lake Camp");
    expect(screen.queryByRole("button", { name: "Register" })).toBeNull();
    expect(screen.queryByText("My registrations")).toBeNull();
    GET.mockResolvedValue(ok({ camps: [], disclaimer: CAMP_DISCLAIMER }));
    fireEvent.change(screen.getByLabelText("Search"), { target: { value: "howrah" } });
    fireEvent.click(screen.getByRole("button", { name: "Search" }));
    expect(await screen.findByText("No camps found")).toBeInTheDocument();
    expect(GET).toHaveBeenLastCalledWith("/api/v1/camps/public", { params: { query: { q: "howrah" } } });
  });
});
