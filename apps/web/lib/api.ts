import { createVeyraClient } from "@veyra/api-client";

/** Browser client: same-origin, proxied to the API by Next.js rewrites. */
export const api = createVeyraClient("/");
