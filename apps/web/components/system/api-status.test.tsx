import { createVeyraClient } from "@veyra/api-client";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ApiStatus } from "./api-status";

const META = {
  name: "VEYRA",
  tagline: "Intelligent Blood Network",
  version: "0.0.0-phase0",
  environment: "dev",
  api_version: "v1",
  demo_mode: true,
  phase: "0 — Architecture & Foundation",
  disclosures: [],
};

const json = (body: unknown, status = 200, headers: Record<string, string> = {}) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json", ...headers },
  });

describe("ApiStatus", () => {
  it("shows skeleton then connected state", async () => {
    const client = createVeyraClient("http://api.test", { fetch: vi.fn(async () => json(META)) });
    render(<ApiStatus client={client} />);
    expect(screen.getByLabelText(/checking api status/i)).toBeInTheDocument();
    expect(await screen.findByText("VEYRA API connected")).toBeInTheDocument();
    expect(screen.getByText(/v0\.0\.0-phase0 · dev/)).toBeInTheDocument();
  });

  it("shows unreachable state with request id and retries", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        json({ code: "internal_error", status: 500 }, 500, { "x-request-id": "req-12345678" }),
      )
      .mockResolvedValueOnce(json(META));
    const client = createVeyraClient("http://api.test", { fetch: fetchMock });
    render(<ApiStatus client={client} />);
    expect(await screen.findByText("API unreachable")).toBeInTheDocument();
    expect(screen.getByText(/req req-12345678/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(await screen.findByText("VEYRA API connected")).toBeInTheDocument();
  });

  it("handles network failure", async () => {
    const client = createVeyraClient("http://api.test", {
      fetch: vi.fn(async () => {
        throw new TypeError("network down");
      }),
    });
    render(<ApiStatus client={client} />);
    expect(await screen.findByText("API unreachable")).toBeInTheDocument();
  });
});
