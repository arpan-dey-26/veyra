import { useEffect, useRef, useState } from "react";

import { toFailure } from "@/lib/problem";

export type Loaded<T> = { data?: T; error?: unknown; response: Response };

/**
 * Fetch inside the effect (active guard); `version` from useReload() drives refetches.
 * A later successful load clears an earlier error, so a page never stays stuck.
 */
export function useLoad<T>(load: () => Promise<Loaded<T>>, version: number, enabled = true) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [status, setStatus] = useState<number | null>(null);
  const loader = useRef(load);
  useEffect(() => {
    loader.current = load;
  });
  useEffect(() => {
    if (!enabled) return;
    let active = true;
    void loader.current().then(({ data: d, error: e, response }) => {
      if (!active) return;
      setStatus(response?.status ?? null);
      if (d) {
        setData(d);
        setError(null);
      } else setError(toFailure(e, response).message);
    });
    return () => {
      active = false;
    };
  }, [version, enabled]);
  return { data, error, status };
}
