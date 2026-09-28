import { describe, expect, it, vi } from "vitest";

import { createVeyraClient, fieldErrors } from "./index";
import { readCookie, sessionMiddleware } from "./session";

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });

function setup(responses: Array<(req: Request) => Response>) {
  let csrf = "csrf-1";
  const seen: Request[] = [];
  const fetchImpl = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const req = input instanceof Request ? input : new Request(input, init);
    seen.push(req);
    const next = responses.shift();
    if (!next) throw new Error("unexpected request " + req.url);
    const res = next(req);
    if (new URL(req.url).pathname === "/api/v1/auth/refresh" && res.ok) csrf = "csrf-2";
    return res;
  });
  const onSessionExpired = vi.fn();
  const client = createVeyraClient("http://api.test", { fetch: fetchImpl });
  client.use(sessionMiddleware({ getCsrfToken: () => csrf, fetchImpl, onSessionExpired }));
  return { client, seen, fetchImpl, onSessionExpired };
}

const ME = { user: { email: "a@b.in" }, permissions: [] };

describe("sessionMiddleware", () => {
  it("adds the CSRF header to unsafe requests only", async () => {
    const { client, seen } = setup([() => json(ME), () => json({}, 204)]);
    await client.GET("/api/v1/auth/me");
    await client.POST("/api/v1/auth/logout");
    expect(seen[0]?.headers.get("x-csrf-token")).toBeNull();
    expect(seen[1]?.headers.get("x-csrf-token")).toBe("csrf-1");
  });

  it("refreshes once on 401 and retries with the rotated CSRF token", async () => {
    const { client, seen } = setup([
      () => json({ code: "unauthenticated", status: 401 }, 401),
      () => json(ME),
      () => json({ city: "Durgapur" }),
    ]);
    const { data } = await client.PATCH("/api/v1/donors/me", { body: { city: "Durgapur" } });
    expect(data).toEqual({ city: "Durgapur" });
    expect(seen.map((r) => new URL(r.url).pathname)).toEqual([
      "/api/v1/donors/me",
      "/api/v1/auth/refresh",
      "/api/v1/donors/me",
    ]);
    expect(seen[2]?.headers.get("x-csrf-token")).toBe("csrf-2");
    expect(await seen[2]?.text()).toBe(JSON.stringify({ city: "Durgapur" }));
  });

  it("does not retry auth endpoints", async () => {
    const { client, seen } = setup([() => json({ code: "invalid_credentials", status: 401 }, 401)]);
    const { error } = await client.POST("/api/v1/auth/login", {
      body: { email: "a@b.in", password: "x" },
    });
    expect(error).toBeDefined();
    expect(seen).toHaveLength(1);
  });

  it("reports an expired session when refresh fails", async () => {
    const { client, onSessionExpired } = setup([
      () => json({ status: 401, code: "unauthenticated" }, 401),
      () => json({ status: 401, code: "session_invalid" }, 401),
    ]);
    const { response } = await client.GET("/api/v1/auth/me");
    expect(response.status).toBe(401);
    expect(onSessionExpired).toHaveBeenCalledOnce();
  });

  it("shares a single refresh between concurrent 401s", async () => {
    const { client, seen } = setup([
      () => json({ status: 401, code: "unauthenticated" }, 401),
      () => json({ status: 401, code: "unauthenticated" }, 401),
      () => json(ME),
      () => json(ME),
      () => json(ME),
    ]);
    await Promise.all([client.GET("/api/v1/auth/me"), client.GET("/api/v1/auth/me")]);
    const refreshes = seen.filter((r) => r.url.endsWith("/api/v1/auth/refresh"));
    expect(refreshes).toHaveLength(1);
  });
});

describe("helpers", () => {
  it("reads cookies", () => {
    expect(readCookie("a=1; veyra_csrf=abc%3D; b=2", "veyra_csrf")).toBe("abc=");
    expect(readCookie("a=1", "veyra_csrf")).toBeNull();
  });

  it("maps 422 problems to field errors", () => {
    const errors = fieldErrors({
      type: "t",
      title: "Validation failed",
      status: 422,
      code: "validation_error",
      detail: "Request is invalid",
      request_id: null,
      errors: [
        { loc: ["body", "pin_code"], msg: "Value error, Enter a valid 6-digit PIN code", type: "value_error" },
        { loc: ["body", "pin_code"], msg: "second", type: "value_error" },
      ],
    });
    expect(errors).toEqual({ pin_code: "Enter a valid 6-digit PIN code" });
  });
});
