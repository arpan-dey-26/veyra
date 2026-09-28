import type { Middleware } from "openapi-fetch";

/**
 * Session middleware for cookie-authenticated browser clients.
 *
 * 1. Adds the double-submit CSRF header (`X-CSRF-Token` = `veyra_csrf` cookie) to unsafe requests.
 * 2. On a 401 from a protected route, performs ONE shared refresh (`POST /api/v1/auth/refresh`)
 *    and retries the original request once. Auth endpoints themselves are never retried.
 */

const SAFE_METHODS = new Set(["GET", "HEAD", "OPTIONS"]);
const NO_RETRY_PATHS = [
  "/api/v1/auth/login",
  "/api/v1/auth/register",
  "/api/v1/auth/verify",
  "/api/v1/auth/refresh",
  "/api/v1/auth/logout",
  "/api/v1/auth/invites",
];

export const CSRF_COOKIE = "veyra_csrf";
export const CSRF_HEADER = "x-csrf-token";

export interface SessionMiddlewareOptions {
  getCsrfToken: () => string | null;
  refreshPath?: string;
  fetchImpl?: typeof fetch;
  onSessionExpired?: () => void;
}

export function readCookie(cookieString: string, name: string): string | null {
  for (const part of cookieString.split(";")) {
    const [key, ...rest] = part.trim().split("=");
    if (key === name) return decodeURIComponent(rest.join("="));
  }
  return null;
}

function withCsrf(request: Request, token: string | null): Request {
  if (SAFE_METHODS.has(request.method.toUpperCase()) || !token) return request;
  const headers = new Headers(request.headers);
  headers.set(CSRF_HEADER, token);
  return new Request(request, { headers });
}

export function sessionMiddleware(options: SessionMiddlewareOptions): Middleware {
  const refreshPath = options.refreshPath ?? "/api/v1/auth/refresh";
  const doFetch = options.fetchImpl ?? ((input: RequestInfo | URL, init?: RequestInit) => fetch(input, init));
  const replayable = new WeakMap<Request, Request>();
  let inflight: Promise<boolean> | null = null;

  const refreshOnce = (origin: string): Promise<boolean> => {
    inflight ??= (async () => {
      try {
        const token = options.getCsrfToken();
        const res = await doFetch(new URL(refreshPath, origin), {
          method: "POST",
          credentials: "include",
          headers: token ? { [CSRF_HEADER]: token } : {},
        });
        return res.ok;
      } catch {
        return false;
      } finally {
        queueMicrotask(() => {
          inflight = null;
        });
      }
    })();
    return inflight;
  };

  return {
    onRequest({ request }) {
      const prepared = withCsrf(request, options.getCsrfToken());
      replayable.set(prepared, prepared.clone());
      return prepared;
    },
    async onResponse({ request, response }) {
      if (response.status !== 401) return response;
      const path = new URL(request.url).pathname;
      if (NO_RETRY_PATHS.some((p) => path.startsWith(p))) return response;
      const refreshed = await refreshOnce(request.url);
      if (!refreshed) {
        options.onSessionExpired?.();
        return response;
      }
      const original = replayable.get(request) ?? request;
      // The refresh rotated the CSRF cookie too, so re-apply the current token.
      return doFetch(withCsrf(original.clone(), options.getCsrfToken()));
    },
  };
}
