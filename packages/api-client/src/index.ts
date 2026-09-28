import createClient, { type ClientOptions } from "openapi-fetch";

import type { components, paths } from "./schema";

export type { components, paths };
export type MetaResponse = components["schemas"]["MetaResponse"];
export type ReadinessResponse = components["schemas"]["ReadinessResponse"];

/** RFC 9457 problem body returned by every VEYRA API error. */
export interface ProblemDetails {
  type: string;
  title: string;
  status: number;
  code: string;
  detail: string;
  request_id: string | null;
  errors?: { loc: (string | number)[]; msg: string; type: string }[];
}

export function isProblem(value: unknown): value is ProblemDetails {
  return (
    typeof value === "object" &&
    value !== null &&
    "code" in value &&
    "status" in value &&
    typeof (value as { status: unknown }).status === "number"
  );
}

/**
 * Create a typed client. In the browser, use the same-origin base ("/"): Next.js proxies
 * /api/* to the API so auth cookies stay first-party. On the server, pass the internal URL.
 */
export function createVeyraClient(baseUrl = "/", options: Omit<ClientOptions, "baseUrl"> = {}) {
  return createClient<paths>({ baseUrl, credentials: "include", ...options });
}

export type VeyraClient = ReturnType<typeof createVeyraClient>;
