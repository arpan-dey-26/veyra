"use client";

import type { BloodRequestOut } from "@veyra/api-client";
import { useEffect, useState } from "react";

import { RequestCard } from "@/components/network/request-card";
import { Button } from "@/components/ui/button";
import { InlineAlert } from "@/components/ui/field";
import { EmptyState, ErrorState, Skeleton } from "@/components/ui/states";
import { api } from "@/lib/api";
import { useLiveRefresh } from "@/lib/live";
import { toFailure } from "@/lib/problem";
import { useReload } from "@/lib/use-reload";

/** Hospital: outgoing requests. Status changes arrive live; receiving closes the loop. */
export function MyRequests({ highlight }: { highlight?: string | null }) {
  const [items, setItems] = useState<BloodRequestOut[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  const [version, reload] = useReload();

  useEffect(() => {
    let active = true;
    void api
      .GET("/api/v1/requests", { params: { query: { limit: 50 } } })
      .then(({ data, error: e, response }) => {
        if (!active) return;
        if (data) {
          setItems(data.data);
          setError(null); // a later refresh recovers from an earlier failure
        } else setError(toFailure(e, response).message);
      });
    return () => {
      active = false;
    };
  }, [version, highlight]);
  useLiveRefresh(["request.dispatched", "request.rejected", "request.created"], reload);

  async function act(r: BloodRequestOut, action: "cancel" | "receive") {
    setActionError(null);
    const path =
      action === "cancel" ? "/api/v1/requests/{request_id}/cancel" : "/api/v1/requests/{request_id}/receive";
    const { error: e, response } = await api.POST(path, { params: { path: { request_id: r.id } } });
    if (e) setActionError(toFailure(e, response).message);
    reload();
  }

  if (error) {
    return (
      <ErrorState
        description={error}
        action={
          <Button size="sm" variant="secondary" onClick={reload}>
            Try again
          </Button>
        }
      />
    );
  }
  if (items === null) return <Skeleton className="h-40" />;
  if (items.length === 0) {
    return <EmptyState title="No requests yet" description="Requests you send to blood banks are tracked here." />;
  }
  return (
    <div className="flex flex-col gap-3">
      {actionError && <InlineAlert>{actionError}</InlineAlert>}
      <ul className="flex flex-col gap-3">
        {items.map((r) => (
          <li key={r.id} className={r.id === highlight ? "veyra-rise" : undefined}>
            <RequestCard
              request={r}
              perspective="hospital"
              actions={
                <>
                  {r.status === "dispatched" && (
                    <Button variant="vital" size="sm" onClick={() => void act(r, "receive")}>
                      Confirm {r.bags.length} bag{r.bags.length === 1 ? "" : "s"} received
                    </Button>
                  )}
                  {(r.status === "pending" || r.status === "acknowledged") && (
                    <Button variant="ghost" size="sm" onClick={() => void act(r, "cancel")}>
                      Cancel request
                    </Button>
                  )}
                </>
              }
            />
          </li>
        ))}
      </ul>
    </div>
  );
}
