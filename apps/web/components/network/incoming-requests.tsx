"use client";

import type { BloodRequestOut } from "@veyra/api-client";
import { useCallback, useEffect, useState } from "react";

import { RequestCard } from "@/components/network/request-card";
import { Button } from "@/components/ui/button";
import { InlineAlert, TextInput } from "@/components/ui/field";
import { EmptyState, ErrorState, Skeleton } from "@/components/ui/states";
import { api } from "@/lib/api";
import { useLiveRefresh } from "@/lib/live";
import { toFailure } from "@/lib/problem";

type View = "pending" | "all";

/** Blood bank: requests addressed to this bank. Fulfilment allocates first-expiry-first-out. */
export function IncomingRequests() {
  const [view, setView] = useState<View>("pending");
  const [items, setItems] = useState<BloodRequestOut[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<{ id: string; tone: "error" | "success"; text: string } | null>(null);

  const load = useCallback(async () => {
    const { data, error: e, response } = await api.GET("/api/v1/requests", {
      params: { query: { limit: 50, ...(view === "pending" ? { status: "pending" } : {}) } },
    });
    if (data) setItems(data.data);
    else setError(toFailure(e, response).message);
  }, [view]);

  useEffect(() => {
    void load();
  }, [load]);
  useLiveRefresh(["request.created", "request.cancelled", "request.fulfilled"], () => void load());

  async function fulfil(r: BloodRequestOut) {
    const { data, error: e, response } = await api.POST("/api/v1/requests/{request_id}/fulfil", {
      params: { path: { request_id: r.id } },
      body: {},
    });
    setNotice(
      data
        ? { id: r.id, tone: "success", text: `Dispatched ${data.bags.map((b) => b.public_id).join(", ")}` }
        : { id: r.id, tone: "error", text: toFailure(e, response).message },
    );
    await load();
  }

  async function reject(r: BloodRequestOut, note: string) {
    const { error: e, response } = await api.POST("/api/v1/requests/{request_id}/reject", {
      params: { path: { request_id: r.id } },
      body: { note },
    });
    setNotice(
      e
        ? { id: r.id, tone: "error", text: toFailure(e, response).message }
        : { id: r.id, tone: "success", text: `Declined ${r.reference}` },
    );
    await load();
  }

  if (error) return <ErrorState description={error} />;

  return (
    <div className="flex flex-col gap-4">
      <div className="flex gap-2" role="tablist" aria-label="Filter requests">
        {(["pending", "all"] as const).map((v) => (
          <Button
            key={v}
            role="tab"
            aria-selected={view === v}
            size="sm"
            variant={view === v ? "primary" : "secondary"}
            onClick={() => setView(v)}
          >
            {v === "pending" ? "Needs action" : "All requests"}
          </Button>
        ))}
      </div>
      {notice && !items?.some((i) => i.id === notice.id && i.status === "pending") && (
        <InlineAlert tone={notice.tone}>{notice.text}</InlineAlert>
      )}
      {items === null ? (
        <Skeleton className="h-40" />
      ) : items.length === 0 ? (
        <EmptyState
          title={view === "pending" ? "Nothing waiting" : "No requests yet"}
          description="Requests from hospitals appear here instantly."
        />
      ) : (
        <ul className="flex flex-col gap-3">
          {items.map((r) => (
            <li key={r.id}>
              <RequestCard
                request={r}
                perspective="blood_bank"
                actions={
                  r.status === "pending" ? (
                    <>
                      {notice?.id === r.id && notice.tone === "error" && (
                        <div className="w-full">
                          <InlineAlert>{notice.text}</InlineAlert>
                        </div>
                      )}
                      <Button variant="vital" size="sm" onClick={() => void fulfil(r)}>
                        Dispatch {r.units} unit{r.units === 1 ? "" : "s"}
                      </Button>
                      <RejectControl onReject={(note) => reject(r, note)} />
                    </>
                  ) : null
                }
              />
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function RejectControl({ onReject }: { onReject: (note: string) => Promise<void> }) {
  const [open, setOpen] = useState(false);
  const [note, setNote] = useState("");
  if (!open) {
    return (
      <Button size="sm" variant="ghost" onClick={() => setOpen(true)}>
        Decline…
      </Button>
    );
  }
  return (
    <span className="flex flex-1 flex-wrap items-center gap-2">
      <TextInput
        aria-label="Reason for declining"
        className="h-8 max-w-xs text-sm"
        placeholder="Reason, e.g. no O− in stock"
        value={note}
        maxLength={500}
        onChange={(e) => setNote(e.target.value)}
      />
      <Button size="sm" variant="secondary" disabled={note.trim().length < 3} onClick={() => void onReject(note.trim())}>
        Decline
      </Button>
      <Button size="sm" variant="ghost" onClick={() => setOpen(false)}>
        Cancel
      </Button>
    </span>
  );
}
