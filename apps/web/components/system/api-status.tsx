"use client";

import type { MetaResponse, VeyraClient } from "@veyra/api-client";
import { useCallback, useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { Skeleton, StatusBeacon } from "@/components/ui/states";
import { api as defaultApi } from "@/lib/api";

type State =
  | { kind: "loading" }
  | { kind: "ok"; meta: MetaResponse }
  | { kind: "error"; requestId: string | null };

/** Fetch product metadata. Never throws: failures become an error state. */
async function fetchMeta(client: VeyraClient): Promise<State> {
  try {
    const { data, response } = await client.GET("/api/v1/meta");
    if (data) return { kind: "ok", meta: data };
    return { kind: "error", requestId: response.headers.get("x-request-id") };
  } catch {
    return { kind: "error", requestId: null };
  }
}

/** Foundation wiring check: web → Next proxy → API /api/v1/meta, using the generated client. */
export function ApiStatus({ client = defaultApi }: { client?: VeyraClient }) {
  const [state, setState] = useState<State>({ kind: "loading" });

  useEffect(() => {
    let active = true;
    void fetchMeta(client).then((next) => {
      if (active) setState(next);
    });
    return () => {
      active = false;
    };
  }, [client]);

  const retry = useCallback(async () => {
    setState({ kind: "loading" });
    setState(await fetchMeta(client));
  }, [client]);

  if (state.kind === "loading") {
    return (
      <div aria-busy="true" aria-label="Checking API status" className="flex items-center gap-3">
        <Skeleton className="h-4 w-40" />
        <Skeleton className="h-4 w-24" />
      </div>
    );
  }

  if (state.kind === "error") {
    return (
      <div role="status" className="flex flex-wrap items-center gap-3">
        <StatusBeacon tone="warn" label="API unreachable" />
        {state.requestId && (
          <span className="font-mono text-xs text-ink-subtle">req {state.requestId}</span>
        )}
        <Button size="sm" variant="secondary" onClick={() => void retry()}>
          Retry
        </Button>
      </div>
    );
  }

  const { meta } = state;
  return (
    <div role="status" className="flex flex-wrap items-center gap-x-4 gap-y-2">
      <StatusBeacon tone="verified" label={`${meta.name} API connected`} />
      <span className="font-mono text-xs text-ink-subtle">
        v{meta.version} · {meta.environment} · phase {meta.phase}
      </span>
    </div>
  );
}
