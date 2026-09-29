"use client";

import type { BagTrace } from "@veyra/api-client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState, type FormEvent } from "react";

import { PageHeader } from "@/components/app/page-header";
import { BagTelemetryPanel } from "@/components/telemetry/cold-chain";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardLabel } from "@/components/ui/card";
import { InlineAlert, TextInput } from "@/components/ui/field";
import { ErrorState, Skeleton } from "@/components/ui/states";
import { api } from "@/lib/api";
import { cn } from "@/lib/cn";
import { useLiveRefresh } from "@/lib/live";
import {
  BAG_STATUS,
  componentLabel,
  displayGroup,
  EVENT_LABEL,
  formatDate,
  formatDateTime,
  parseBagId,
  relativeExpiry,
} from "@/lib/network";
import { toFailure } from "@/lib/problem";
import { useOptionalSession } from "@/lib/session";

/** Type a bag id or paste a scanned QR payload. */
export function TraceSearch() {
  const router = useRouter();
  const [value, setValue] = useState("");
  const [error, setError] = useState<string | null>(null);
  function onSubmit(e: FormEvent) {
    e.preventDefault();
    const id = parseBagId(value);
    if (!id) {
      setError("Enter a bag ID like VYR-7F3K-2QXM, or paste the QR payload.");
      return;
    }
    router.push(`/bags/${id}`);
  }
  return (
    <form onSubmit={onSubmit} className="flex flex-col gap-2" noValidate>
      <label htmlFor="trace-search" className="text-sm font-medium">
        Trace a bag
      </label>
      <div className="flex gap-2">
        <TextInput
          id="trace-search"
          className="font-mono uppercase"
          placeholder="VYR-XXXX-XXXX"
          value={value}
          onChange={(e) => {
            setValue(e.target.value);
            setError(null);
          }}
          aria-invalid={Boolean(error)}
        />
        <Button type="submit" variant="secondary">
          Trace
        </Button>
      </div>
      {error && (
        <p role="alert" className="text-xs font-medium text-critical">
          {error}
        </p>
      )}
    </form>
  );
}

export function BagTraceView({ publicId }: { publicId: string }) {
  const me = useOptionalSession()?.me ?? null;
  const [trace, setTrace] = useState<BagTrace | null>(null);
  const [error, setError] = useState<{ message: string; notFound: boolean } | null>(null);
  const [tick, setTick] = useState(0);

  useEffect(() => {
    let active = true;
    void api
      .GET("/api/v1/bags/{public_id}", { params: { path: { public_id: publicId } } })
      .then(({ data, error: e, response }) => {
        if (!active) return;
        if (data) {
          setTrace(data);
          setError(null);
        } else {
          setError({ message: toFailure(e, response).message, notFound: response.status === 404 });
        }
      });
    return () => {
      active = false;
    };
  }, [publicId, tick]);
  useLiveRefresh(["request.dispatched", "request.fulfilled", "bag.discarded"], () => setTick((t) => t + 1));

  if (error) {
    return (
      <ErrorState
        title={error.notFound ? "Bag not found" : "Couldn't load this bag"}
        description={
          error.notFound
            ? "No bag with this ID is visible to your facility. You can trace bags your facility holds or has held."
            : error.message
        }
        action={
          <Link href="/dashboard" className="text-sm underline underline-offset-4">
            Back to dashboard
          </Link>
        }
      />
    );
  }
  if (!trace) return <Skeleton className="h-96 w-full" />;

  const { bag, events, chain } = trace;
  const status = BAG_STATUS[bag.status] ?? { label: bag.status, tone: "neutral" as const };

  return (
    <>
      <PageHeader
        eyebrow="Bag trace"
        title={bag.public_id}
        description={`${componentLabel(bag.component)} · ${bag.volume_ml} ml · held by ${bag.current_facility_name}`}
        actions={
          <span className="font-display text-display-sm text-vital" aria-label={`Blood group ${bag.blood_group}`}>
            {displayGroup(bag.blood_group)}
          </span>
        }
      />
      <div className="grid gap-6 lg:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
        <Card>
          <CardLabel>Custody trail</CardLabel>
          <ol className="relative mt-5 flex flex-col gap-6 border-l border-line pl-6">
            {events.map((e) => (
              <li key={e.seq} className="relative">
                <span
                  aria-hidden
                  className={cn(
                    "absolute top-1.5 -left-[1.95rem] size-3 rounded-full border-2 border-surface-raised",
                    e.event_type === "DISCARDED" ? "bg-ink-subtle" : "bg-vital",
                  )}
                />
                <p className="font-medium">
                  {EVENT_LABEL[e.event_type] ?? e.event_type}
                  <span className="ml-2 text-xs font-normal text-ink-subtle">#{e.seq}</span>
                </p>
                <p className="text-sm text-ink-muted">
                  {formatDateTime(e.occurred_at)}
                  {e.from_facility && ` · from ${e.from_facility}`}
                  {e.to_facility && ` · to ${e.to_facility}`}
                </p>
                {Object.keys(e.meta).length > 0 && (
                  <p className="mt-1 text-xs text-ink-subtle">
                    {Object.entries(e.meta)
                      .map(([k, v]) => `${k}: ${String(v)}`)
                      .join(" · ")}
                  </p>
                )}
                <p className="mt-1 truncate font-mono text-2xs text-ink-subtle" title={e.row_hash}>
                  sha256 {e.row_hash.slice(0, 16)}… ← {e.prev_hash.slice(0, 8)}…
                </p>
              </li>
            ))}
          </ol>
        </Card>
        <div className="flex flex-col gap-4">
          <Card>
            <CardLabel>Status</CardLabel>
            <div className="mt-3 flex flex-wrap gap-2">
              <Badge tone={status.tone} dot>
                {status.label}
              </Badge>
              {bag.is_expired && <Badge tone="critical">Expired</Badge>}
            </div>
            <dl className="mt-4 grid grid-cols-2 gap-3 text-sm">
              <dt className="text-ink-subtle">Collected</dt>
              <dd>{formatDate(bag.collected_at)}</dd>
              <dt className="text-ink-subtle">Expires</dt>
              <dd>
                {formatDate(bag.expires_at)}
                <span className="block text-xs text-ink-subtle">{relativeExpiry(bag.expires_at)}</span>
              </dd>
            </dl>
          </Card>
          <Card>
            <CardLabel>Integrity</CardLabel>
            <div className="mt-3">
              {chain.valid ? (
                <InlineAlert tone="success" title={`Chain verified · ${chain.length} events`}>
                  Every event&apos;s hash matches its content and the event before it.
                </InlineAlert>
              ) : (
                <InlineAlert title="Chain broken">
                  This trail doesn&apos;t match its hashes. Treat the history as unreliable and report it.
                </InlineAlert>
              )}
            </div>
            <p className="mt-3 text-xs text-ink-subtle">{chain.note}</p>
          </Card>
          <Card>
            <CardLabel>QR label</CardLabel>
            <p className="mt-2 font-mono text-sm break-all">{bag.qr_payload}</p>
            <p className="mt-1 text-xs text-ink-subtle">Printed on the bag; scanning it opens this trace.</p>
          </Card>
        </div>
      </div>
      {me && (
        <BagTelemetryPanel
          publicId={bag.public_id}
          canSimulate={
            !!me.facility &&
            me.facility.id === bag.current_facility_id &&
            (me.user.role === "BLOOD_BANK" || me.user.role === "HOSPITAL")
          }
        />
      )}
    </>
  );
}
