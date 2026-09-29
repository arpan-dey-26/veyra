import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { COMPATIBILITY_DISCLAIMER } from "@/lib/phase8";

const GET = vi.fn();
vi.mock("@/lib/api", () => ({
  api: { GET: (...a: unknown[]) => GET(...a), POST: vi.fn() },
  SESSION_EXPIRED_EVENT: "veyra:session-expired",
}));

const { CompatibilityPage } = await import("./compatibility");

const GROUPS = ["O-", "O+", "A-", "A+", "B-", "B+", "AB-", "AB+"];
const MATRIX = {
  blood_groups: GROUPS,
  label: "Prototype ABO/Rh compatibility reference (simplified, not clinical)",
  disclaimer: COMPATIBILITY_DISCLAIMER,
  informational_only: true,
  components: [
    {
      component: "PRBC",
      label: "Packed Red Blood Cells (PRBC)",
      rule: "Red cells rule",
      rh_considered: true,
      rows: GROUPS.map((g) => ({ recipient_group: g, compatible_donors: g === "AB+" ? GROUPS : ["O-"] })),
    },
    {
      component: "FFP",
      label: "Fresh Frozen Plasma (FFP)",
      rule: "Plasma rule",
      rh_considered: false,
      rows: GROUPS.map((g) => ({ recipient_group: g, compatible_donors: ["AB-", "AB+"] })),
    },
  ],
};
const check = (compatible: boolean) => ({
  donor_group: "O-",
  recipient_group: "A+",
  component: "PRBC",
  component_label: "Packed Red Blood Cells (PRBC)",
  compatible,
  result: compatible ? "compatible" : "not_compatible",
  reason: compatible ? "Compatible: the recipient carries every donor A/B antigen." : "Not compatible: nope.",
  rule: "Red cells rule",
  compatible_donors_for_recipient: ["O-"],
  compatible_recipients_for_donor: GROUPS,
  label: "x",
  disclaimer: COMPATIBILITY_DISCLAIMER,
  informational_only: true,
  requires_clinical_confirmation: true,
});
const fail = () => ({ error: { title: "Unavailable", detail: "Service unavailable" }, response: new Response(null, { status: 503 }) });

function route(matrix: () => unknown, chk: () => unknown) {
  GET.mockImplementation((path: string) => Promise.resolve(path.endsWith("/matrix") ? matrix() : chk()));
}

beforeEach(() => {
  GET.mockReset();
});

describe("compatibility page", () => {
  it("shows the disclaimer, the matrix and an API verdict", async () => {
    route(() => ({ data: MATRIX }), () => ({ data: check(true) }));
    render(<CompatibilityPage />);
    expect(await screen.findByTestId("compatibility-matrix")).toBeInTheDocument();
    expect(screen.getByTestId("compatibility-disclaimer")).toHaveTextContent(COMPATIBILITY_DISCLAIMER);
    const result = await screen.findByTestId("compatibility-result");
    await waitFor(() => expect(within(result).getByText("Compatible")).toBeInTheDocument());
    // 8 recipient rows; AB+ row accepts every donor.
    const rows = within(screen.getByTestId("compatibility-matrix")).getAllByRole("row");
    expect(rows).toHaveLength(9);
    expect(screen.getByLabelText("Donor B+ to recipient AB+: compatible")).toBeInTheDocument();
    expect(screen.getByLabelText("Donor B+ to recipient A+: not compatible")).toBeInTheDocument();
  });

  it("re-asks the API when a selector changes and shows Not compatible", async () => {
    route(() => ({ data: MATRIX }), () => ({ data: check(false) }));
    render(<CompatibilityPage />);
    await screen.findByTestId("compatibility-matrix");
    fireEvent.change(screen.getAllByLabelText("Donor blood group")[0]!, { target: { value: "AB+" } });
    await waitFor(() =>
      expect(GET).toHaveBeenCalledWith(
        "/api/v1/compatibility/check",
        expect.objectContaining({ params: { query: expect.objectContaining({ donor_group: "AB+" }) } }),
      ),
    );
    expect(await screen.findByText("Not compatible")).toBeInTheDocument();
  });

  it("filters recipients, switches component and shows an empty state", async () => {
    route(() => ({ data: MATRIX }), () => ({ data: check(true) }));
    render(<CompatibilityPage />);
    await screen.findByTestId("compatibility-matrix");
    fireEvent.change(screen.getByLabelText("Filter recipient group"), { target: { value: "ab" } });
    expect(within(screen.getByTestId("compatibility-matrix")).getAllByRole("row")).toHaveLength(3);
    fireEvent.change(screen.getByLabelText("Filter recipient group"), { target: { value: "zz" } });
    expect(screen.getByText("No matching groups")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Filter recipient group"), { target: { value: "" } });
    fireEvent.change(screen.getAllByLabelText("Component")[1]!, { target: { value: "FFP" } });
    expect(screen.getByText("Plasma rule")).toBeInTheDocument();
    fireEvent.click(screen.getByLabelText("Show compatible donors only"));
    expect(screen.getByTestId("compatibility-list")).toHaveTextContent("AB−, AB+");
  });

  it("recovers from a failed load with Try again", async () => {
    let calls = 0;
    route(() => (calls++ === 0 ? fail() : { data: MATRIX }), () => ({ data: check(true) }));
    render(<CompatibilityPage />);
    expect(await screen.findByText("Compatibility reference unavailable")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByTestId("compatibility-matrix")).toBeInTheDocument();
  });
});
