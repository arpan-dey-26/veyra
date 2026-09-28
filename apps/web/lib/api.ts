import { createBrowserClient } from "@veyra/api-client";

export const SESSION_EXPIRED_EVENT = "veyra:session-expired";

/**
 * Browser client: same-origin (proxied to the API by Next.js rewrites), adds the CSRF header,
 * and silently refreshes an expired access token once before giving up.
 */
export const api = createBrowserClient(() => {
  if (typeof window !== "undefined") window.dispatchEvent(new Event(SESSION_EXPIRED_EVENT));
});
