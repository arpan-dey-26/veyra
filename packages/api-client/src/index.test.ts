import { describe, expect, it, vi } from "vitest";

import { createVeyraClient, isProblem } from "./index";

describe("api-client", () => {
  it("calls the typed /api/v1/meta route", async () => {
    const fetchMock = vi.fn(
      async () =>
        new Response(
          JSON.stringify({
            name: "VEYRA",
            tagline: "Intelligent Blood Network",
            version: "0.0.0",
            environment: "dev",
            api_version: "v1",
            demo_mode: true,
            phase: "0",
            disclosures: [],
          }),
          { status: 200, headers: { "content-type": "application/json" } },
        ),
    );
    const client = createVeyraClient("http://api.test", { fetch: fetchMock });
    const { data, error } = await client.GET("/api/v1/meta");
    expect(error).toBeUndefined();
    expect(data?.name).toBe("VEYRA");
    const req = (fetchMock.mock.calls[0] as unknown as [Request])[0];
    expect(req.url).toBe("http://api.test/api/v1/meta");
  });

  it("recognises RFC 9457 problem bodies", () => {
    expect(isProblem({ code: "not_found", status: 404 })).toBe(true);
    expect(isProblem({ message: "nope" })).toBe(false);
    expect(isProblem(null)).toBe(false);
  });
});
