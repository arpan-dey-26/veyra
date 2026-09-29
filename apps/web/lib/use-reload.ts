import { useCallback, useState } from "react";

/**
 * A counter to put in an effect's dependency list: calling `reload()` (from an event
 * handler, a live-event callback or after a mutation) re-runs that effect exactly once.
 * Fetching stays inside the effect with an `active` guard, which the React hooks rules
 * (`set-state-in-effect`) accept and which drops responses from superseded fetches.
 */
export function useReload(): [number, () => void] {
  const [version, setVersion] = useState(0);
  const reload = useCallback(() => setVersion((v) => v + 1), []);
  return [version, reload];
}
