import createClient, { type ClientOptions } from "openapi-fetch";

import type { components, paths } from "./schema";
import { readCookie, sessionMiddleware, CSRF_COOKIE } from "./session";

export type { components, paths };
export { readCookie, sessionMiddleware, CSRF_COOKIE, CSRF_HEADER } from "./session";

type Schemas = components["schemas"];
export type MetaResponse = Schemas["MetaResponse"];
export type ReadinessResponse = Schemas["ReadinessResponse"];
export type MeResponse = Schemas["MeResponse"];
export type UserOut = Schemas["UserOut"];
export type RegisterDonorRequest = Schemas["RegisterDonorRequest"];
export type RegisterResponse = Schemas["RegisterResponse"];
export type VerificationOut = Schemas["VerificationOut"];
export type DonorProfile = Schemas["DonorProfile"];
export type UpdateDonorProfileRequest = Schemas["UpdateDonorProfileRequest"];
export type RegistrationReference = Schemas["RegistrationReference"];
export type FacilityOut = Schemas["FacilityOut"];
export type CreateFacilityRequest = Schemas["CreateFacilityRequest"];
export type CreatedInvite = Schemas["CreatedInvite"];
export type InviteOut = Schemas["InviteOut"];
export type InvitePreview = Schemas["InvitePreview"];

export type Role = "DONOR" | "HOSPITAL" | "BLOOD_BANK" | "ADMIN";

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

/** Field name → first error message, from a 422 problem (loc: ["body", "<field>"]). */
export function fieldErrors(problem: ProblemDetails | null | undefined): Record<string, string> {
  const out: Record<string, string> = {};
  for (const err of problem?.errors ?? []) {
    const field = err.loc[err.loc.length - 1];
    if (typeof field === "string" && !(field in out)) {
      out[field] = err.msg.replace(/^Value error, /, "");
    }
  }
  return out;
}

/**
 * Create a typed client. In the browser, use the same-origin base ("/"): Next.js proxies
 * /api/* to the API so auth cookies stay first-party. On the server, pass the internal URL.
 */
export function createVeyraClient(baseUrl = "/", options: Omit<ClientOptions, "baseUrl"> = {}) {
  return createClient<paths>({ baseUrl, credentials: "include", ...options });
}

export type VeyraClient = ReturnType<typeof createVeyraClient>;

/** Browser client: CSRF header + silent refresh-and-retry on 401. */
export function createBrowserClient(onSessionExpired?: () => void): VeyraClient {
  const client = createVeyraClient(typeof window === "undefined" ? "http://localhost" : "/");
  client.use(
    sessionMiddleware({
      getCsrfToken: () =>
        typeof document === "undefined" ? null : readCookie(document.cookie, CSRF_COOKIE),
      onSessionExpired,
    }),
  );
  return client;
}
