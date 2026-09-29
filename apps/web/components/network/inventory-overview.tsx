"use client";

import type { BagOut, InventorySummary } from "@veyra/api-client";
import Link from "next/link";
import { useEffect, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardLabel } from "@/components/ui/card";
import { InlineAlert, SelectInput } from "@/components/ui/field";
import { EmptyState, ErrorState, Skeleton } from "@/components/ui/states";
import { api } from "@/lib/api";
import { cn } from "@/lib/cn";
import { useLiveRefresh } from "@/lib/live";
import {
  BAG_STATUS,
  BLOOD_GROUPS,
  COMPONENTS,
  componentLabel,
  displayGroup,
  formatDate,
  relativeExpiry,
} from "@/lib/network";
import { toFailure } from "@/lib/problem";
import { useReload } from "@/lib/use-reload";

type DiscardReason = "expired" | "damaged" | "failed_screening" | "other";

const DISCARD_REASONS: { value: DiscardReason; label: string }[] = [
  { value: "expired", label: "Expired" },
  { value: "damaged", label: "Damaged / leaking" },
  { value: "failed_screening", label: "Failed screening" },
  { value: "other", label: "Other" },
];

function DiscardControl({
  defaultReason,
  onConfirm,
}: {
  defaultReason: DiscardReason;
  onConfirm: (reason: DiscardReason) => Promise<void>;
}) {
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState<DiscardReason>(defaultReason);
  const [busy, setBusy] = useState(false);
  if (!open) {
    return (
      <Button size="sm" variant="ghost" onClick={() => setOpen(true)}>
        Discard
      </Button>
    );
  }
  return (
    <span className="inline-flex items-center gap-2">
      <SelectInput
        aria-label="Discard reason"
        className="h-8 w-40 text-sm"
        value={reason}
        onChange={(e) => setReason(e.target.value as DiscardReason)}
      >
        {DISCARD_REASONS.map((r) => (
          <option key={r.value} value={r.value}>
            {r.label}
          </option>
        ))}
      </SelectInput>
      <Button
        size="sm"
        variant="secondary"
        disabled={busy}
        onClick={async () => {
          setBusy(true);
          await onConfirm(reason);
          setBusy(false);
          setOpen(false);
        }}
      >
        Confirm
      </Button>
      <Button size="sm" variant="ghost" onClick={() => setOpen(false)}>
        Keep
      </Button>
    </span>
  );
}

type StatusFilter = "available" | "in_transit" | "received" | "discarded" | "";

/** Stock by group × component, and the bags behind it. Scoped to the caller's facility. */
export function InventoryOverview({ canDiscard }: { canDiscard: boolean }) {
  const [summary, setSummary] = useState<InventorySummary | null>(null);
  const [bags, setBags] = useState<BagOut[] | null>(null);
  const [total, setTotal] = useState(0);
  const [status, setStatus] = useState<StatusFilter>(canDiscard ? "available" : "received");
  const [error, setError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  const [version, reload] = useReload();

  useEffect(() => {
    let active = true;
    void Promise.all([
      api.GET("/api/v1/inventory/summary"),
      api.GET("/api/v1/inventory/bags", {
        params: { query: { limit: 50, ...(status ? { status } : {}) } },
      }),
    ]).then(([s, b]) => {
      if (!active) return;
      if (s.data) setSummary(s.data);
      else setError(toFailure(s.error, s.response).message);
      if (b.data) {
        setBags(b.data.data);
        setTotal(b.data.meta.total);
      }
    });
    return () => {
      active = false;
    };
  }, [status, version]);
  useLiveRefresh(["inventory.updated", "bag.discarded", "request.fulfilled"], reload);

  async function discard(bag: BagOut, reason: DiscardReason) {
    setActionError(null);
    const { error: e, response } = await api.POST("/api/v1/bags/{public_id}/discard", {
      params: { path: { public_id: bag.public_id } },
      body: { reason },
    });
    if (e) setActionError(toFailure(e, response).message);
    reload();
  }

  if (error) return <ErrorState description={error} />;
  if (!summary) return <Skeleton className="h-72 w-full" />;

  const cell = new Map(summary.rows.map((r) => [`${r.blood_group}|${r.component}`, r]));
  const expiredTotal = summary.rows.reduce((n, r) => n + r.expired, 0);
  const soonTotal = summary.rows.reduce((n, r) => n + r.expiring_soon, 0);

  return (
    <div className="flex flex-col gap-6">
      <div className="grid gap-4 sm:grid-cols-3">
        <Card>
          <CardLabel>Usable units</CardLabel>
          <p className="mt-2 font-display text-display-sm" data-testid="total-available">
            {summary.total_available}
          </p>
        </Card>
        <Card>
          <CardLabel>Expiring within 72 h</CardLabel>
          <p className={cn("mt-2 font-display text-display-sm", soonTotal > 0 && "text-warn")}>
            {soonTotal}
          </p>
        </Card>
        <Card>
          <CardLabel>Expired, awaiting discard</CardLabel>
          <p className={cn("mt-2 font-display text-display-sm", expiredTotal > 0 && "text-critical")}>
            {expiredTotal}
          </p>
        </Card>
      </div>

      <Card className="overflow-x-auto p-0">
        <table className="w-full min-w-[640px] text-sm">
          <caption className="sr-only">Usable units by blood group and component</caption>
          <thead>
            <tr className="border-b border-line text-left">
              <th scope="col" className="px-5 py-3 font-medium text-ink-subtle">
                Group
              </th>
              {COMPONENTS.map((c) => (
                <th key={c.code} scope="col" className="px-3 py-3 text-right font-medium text-ink-subtle">
                  <abbr title={c.label} className="no-underline">
                    {c.short}
                  </abbr>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {BLOOD_GROUPS.map((g) => (
              <tr key={g} className="border-b border-line last:border-0">
                <th scope="row" className="px-5 py-2.5 text-left font-display text-lg text-vital">
                  {displayGroup(g)}
                </th>
                {COMPONENTS.map((c) => {
                  const r = cell.get(`${g}|${c.code}`);
                  const n = r?.available ?? 0;
                  return (
                    <td key={c.code} className="px-3 py-2.5 text-right tabular-nums">
                      <span className={cn(n === 0 ? "text-ink-subtle" : "font-medium text-ink")}>{n}</span>
                      {r && r.expiring_soon > 0 && (
                        <span className="ml-1.5 text-xs text-warn" title="Expiring within 72 h">
                          ({r.expiring_soon} soon)
                        </span>
                      )}
                      {r && r.expired > 0 && (
                        <span className="ml-1.5 text-xs text-critical" title="Expired">
                          ({r.expired} exp.)
                        </span>
                      )}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
      <p className="text-xs text-ink-subtle">{summary.reference_note}</p>

      <section aria-labelledby="bags-heading" className="flex flex-col gap-3">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <h2 id="bags-heading" className="text-lg font-medium">
            Bags <span className="text-ink-subtle">({total})</span>
          </h2>
          <label className="flex items-center gap-2 text-sm text-ink-muted">
            Status
            <SelectInput
              className="h-9 w-44"
              value={status}
              onChange={(e) => setStatus(e.target.value as StatusFilter)}
            >
              <option value="">All</option>
              <option value="available">In storage</option>
              <option value="in_transit">In transit</option>
              <option value="received">Received</option>
              <option value="discarded">Discarded</option>
            </SelectInput>
          </label>
        </div>
        {actionError && <InlineAlert>{actionError}</InlineAlert>}
        {bags === null ? (
          <Skeleton className="h-40 w-full" />
        ) : bags.length === 0 ? (
          <EmptyState title="No bags here" description="Bags appear when donations are recorded or requests are received." />
        ) : (
          <Card className="overflow-x-auto p-0">
            <table className="w-full min-w-[720px] text-sm">
              <thead>
                <tr className="border-b border-line text-left text-ink-subtle">
                  <th scope="col" className="px-5 py-3 font-medium">Bag ID</th>
                  <th scope="col" className="px-3 py-3 font-medium">Group</th>
                  <th scope="col" className="px-3 py-3 font-medium">Component</th>
                  <th scope="col" className="px-3 py-3 font-medium">Collected</th>
                  <th scope="col" className="px-3 py-3 font-medium">Expiry</th>
                  <th scope="col" className="px-3 py-3 font-medium">Status</th>
                  <th scope="col" className="px-3 py-3"><span className="sr-only">Actions</span></th>
                </tr>
              </thead>
              <tbody>
                {bags.map((b) => {
                  const st = BAG_STATUS[b.status] ?? { label: b.status, tone: "neutral" as const };
                  return (
                    <tr key={b.id} className="border-b border-line last:border-0">
                      <td className="px-5 py-2.5">
                        <Link href={`/bags/${b.public_id}`} className="font-mono text-ink underline-offset-4 hover:underline">
                          {b.public_id}
                        </Link>
                      </td>
                      <td className="px-3 py-2.5 font-medium text-vital">{displayGroup(b.blood_group)}</td>
                      <td className="px-3 py-2.5">{componentLabel(b.component)}</td>
                      <td className="px-3 py-2.5 text-ink-muted">{formatDate(b.collected_at)}</td>
                      <td className={cn("px-3 py-2.5", b.is_expired ? "text-critical" : "text-ink-muted")}>
                        {relativeExpiry(b.expires_at)}
                      </td>
                      <td className="px-3 py-2.5">
                        <Badge tone={b.is_expired && b.status === "available" ? "critical" : st.tone}>
                          {b.is_expired && b.status === "available" ? "Expired" : st.label}
                        </Badge>
                      </td>
                      <td className="px-3 py-2.5 text-right">
                        {canDiscard && b.status === "available" && (
                          <DiscardControl
                            defaultReason={b.is_expired ? "expired" : "damaged"}
                            onConfirm={(reason) => discard(b, reason)}
                          />
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </Card>
        )}
      </section>
    </div>
  );
}
