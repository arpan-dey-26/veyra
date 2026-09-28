import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { DEMO_VERIFICATION_DISCLAIMER } from "@/lib/validation";

const push = vi.fn();
const replace = vi.fn();
let searchParams = new URLSearchParams();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push, replace }),
  useSearchParams: () => searchParams,
  usePathname: () => "/",
}));

const GET = vi.fn();
const POST = vi.fn();
vi.mock("@/lib/api", () => ({
  api: { GET: (...a: unknown[]) => GET(...a), POST: (...a: unknown[]) => POST(...a) },
  SESSION_EXPIRED_EVENT: "veyra:session-expired",
}));

const { DemoVerificationNotice } = await import("./demo-verification-notice");
const { BloodGroupPicker } = await import("./blood-group-picker");
const { RegisterForm } = await import("./register-form");
const { VerifyForm } = await import("./verify-form");
const { SignInForm } = await import("./sign-in-form");
const { SessionProvider } = await import("@/lib/session");

const withSession = (ui: ReactNode) => <SessionProvider>{ui}</SessionProvider>;
const res = (status: number) => new Response(null, { status });

const REFERENCE = {
  blood_groups: ["A+", "A-", "B+", "B-", "AB+", "AB-", "O+", "O-"],
  states: ["West Bengal", "Delhi"],
  verification_mode: "demo",
  verification_disclaimer: DEMO_VERIFICATION_DISCLAIMER,
};

const ME = {
  user: { id: "u1", email: "arpan@example.in", full_name: "Arpan Dey", mobile: "+919876543210", role: "DONOR", status: "active", is_demo: false, verified_at: null, created_at: "" },
  permissions: [],
  donor: { blood_group: "O+", city: "Kolkata", state: "West Bengal" },
};

beforeEach(() => {
  push.mockReset();
  replace.mockReset();
  GET.mockReset();
  POST.mockReset();
  searchParams = new URLSearchParams();
  GET.mockImplementation(async (path: string) =>
    path === "/api/v1/reference/registration"
      ? { data: REFERENCE, response: res(200) }
      : { data: undefined, error: { status: 401, code: "unauthenticated" }, response: res(401) },
  );
});

describe("DemoVerificationNotice", () => {
  it("shows the exact mandatory disclaimer with a Demo label", () => {
    render(<DemoVerificationNotice />);
    const note = screen.getByRole("note", { name: /demo verification notice/i });
    expect(note).toHaveTextContent(DEMO_VERIFICATION_DISCLAIMER);
    expect(note).toHaveTextContent("Demo");
  });
});

describe("BloodGroupPicker", () => {
  it("is a radio group of all 8 groups", () => {
    const onChange = vi.fn();
    render(<BloodGroupPicker value="" onChange={onChange} />);
    const radios = screen.getAllByRole("radio");
    expect(radios).toHaveLength(8);
    fireEvent.click(radios[6]!);
    expect(onChange).toHaveBeenCalledWith("O+");
  });
});

describe("RegisterForm", () => {
  it("shows the demo disclaimer and blocks invalid submissions client-side", async () => {
    render(<RegisterForm />);
    expect(screen.getByRole("note", { name: /demo verification notice/i })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /create donor account/i }));
    expect(await screen.findByText("Please correct the highlighted fields.")).toBeInTheDocument();
    expect(screen.getByText("Enter a valid 10-digit Indian mobile number")).toBeInTheDocument();
    expect(POST).not.toHaveBeenCalled();
  });

  it("submits all nine fields and continues to verification", async () => {
    POST.mockResolvedValue({
      data: { user: ME.user, verification: { challenge_id: "c-123", destination_hint: "+91 98••••••••" } },
      response: res(201),
    });
    render(<RegisterForm />);
    await screen.findByRole("option", { name: "West Bengal" });
    const type = (label: RegExp, value: string) =>
      fireEvent.change(screen.getByLabelText(label), { target: { value } });
    type(/full name/i, "Arpan Dey");
    type(/^email$/i, "arpan@example.in");
    type(/mobile number/i, "98765 43210");
    fireEvent.click(screen.getByRole("radio", { name: "O+" }));
    type(/^address$/i, "12 Park Street");
    type(/^city$/i, "Kolkata");
    type(/state \/ ut/i, "West Bengal");
    type(/pin code/i, "700016");
    type(/^password$/i, "correct horse battery");
    fireEvent.click(screen.getByRole("button", { name: /create donor account/i }));
    await waitFor(() => expect(push).toHaveBeenCalledOnce());
    const [, options] = POST.mock.calls[0] as [string, { body: Record<string, string> }];
    expect(Object.keys(options.body).sort()).toEqual(
      ["address", "blood_group", "city", "email", "full_name", "mobile", "password", "pin_code", "state"],
    );
    expect(push.mock.calls[0]?.[0]).toContain("/verify?challenge=c-123");
  });

  it("shows server field errors (e.g. duplicate email)", async () => {
    POST.mockResolvedValue({
      error: { status: 409, code: "email_taken", detail: "An account with this email already exists", title: "", type: "", request_id: null },
      response: res(409),
    });
    render(<RegisterForm />);
    await screen.findByRole("option", { name: "West Bengal" });
    const type = (label: RegExp, value: string) =>
      fireEvent.change(screen.getByLabelText(label), { target: { value } });
    type(/full name/i, "Arpan Dey");
    type(/^email$/i, "arpan@example.in");
    type(/mobile number/i, "9876543210");
    fireEvent.click(screen.getByRole("radio", { name: "O+" }));
    type(/^address$/i, "12 Park Street");
    type(/^city$/i, "Kolkata");
    type(/state \/ ut/i, "West Bengal");
    type(/pin code/i, "700016");
    type(/^password$/i, "correct horse battery");
    fireEvent.click(screen.getByRole("button", { name: /create donor account/i }));
    expect(await screen.findByText("An account with this email already exists")).toBeInTheDocument();
  });
});

describe("VerifyForm", () => {
  it("always shows the disclaimer and reports remaining attempts", async () => {
    searchParams = new URLSearchParams({ challenge: "c-123", hint: "+91 98••••••••" });
    POST.mockResolvedValue({
      error: { status: 400, code: "invalid_code", detail: "Incorrect code. 4 attempts remaining.", title: "", type: "", request_id: null },
      response: res(400),
    });
    render(withSession(<VerifyForm />));
    expect(screen.getByRole("note", { name: /demo verification notice/i })).toHaveTextContent(
      DEMO_VERIFICATION_DISCLAIMER,
    );
    fireEvent.change(screen.getByLabelText(/verification code/i), { target: { value: "0000" } });
    fireEvent.click(screen.getByRole("button", { name: /verify and continue/i }));
    expect(await screen.findByText("Incorrect code. 4 attempts remaining.")).toBeInTheDocument();
  });

  it("goes to the role home after a correct code", async () => {
    searchParams = new URLSearchParams({ challenge: "c-123" });
    POST.mockResolvedValue({ data: ME, response: res(200) });
    render(withSession(<VerifyForm />));
    fireEvent.change(screen.getByLabelText(/verification code/i), { target: { value: "3210" } });
    fireEvent.click(screen.getByRole("button", { name: /verify and continue/i }));
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/donor"));
    expect(POST).toHaveBeenCalledWith("/api/v1/auth/verify", {
      body: { challenge_id: "c-123", code: "3210" },
    });
  });

  it("explains how to continue when there is no challenge", () => {
    render(withSession(<VerifyForm />));
    expect(screen.getByText(/no verification in progress/i)).toBeInTheDocument();
  });
});

describe("SignInForm", () => {
  it("restarts verification for pending accounts", async () => {
    POST.mockImplementation(async (path: string) =>
      path === "/api/v1/auth/login"
        ? { error: { status: 403, code: "verification_required", detail: "Verify", title: "", type: "", request_id: null }, response: res(403) }
        : { data: { challenge_id: "c-9", destination_hint: "+91 98••••••••" }, response: res(200) },
    );
    render(withSession(<SignInForm />));
    fireEvent.change(screen.getByLabelText(/^email$/i), { target: { value: "arpan@example.in" } });
    fireEvent.change(screen.getByLabelText(/^password$/i), { target: { value: "correct horse" } });
    fireEvent.click(screen.getByRole("button", { name: /^sign in$/i }));
    await waitFor(() => expect(push).toHaveBeenCalledOnce());
    expect(push.mock.calls[0]?.[0]).toContain("challenge=c-9");
  });

  it("honours a safe ?next= after sign-in and ignores unsafe ones", async () => {
    searchParams = new URLSearchParams({ next: "https://evil.example" });
    POST.mockResolvedValue({ data: ME, response: res(200) });
    render(withSession(<SignInForm />));
    fireEvent.change(screen.getByLabelText(/^email$/i), { target: { value: "arpan@example.in" } });
    fireEvent.change(screen.getByLabelText(/^password$/i), { target: { value: "correct horse" } });
    fireEvent.click(screen.getByRole("button", { name: /^sign in$/i }));
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/donor"));
  });
});
