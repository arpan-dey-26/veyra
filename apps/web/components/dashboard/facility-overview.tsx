"use client";

import type {
  AvailabilityResponse,
  BloodComponent,
  BloodGroup,
  FacilityDashboard,
  InventorySummary,
} from "@veyra/api-client";
import { useEffect, useState } from "react";

import { StatTile } from "@/components/app/page-header";
import { BarList, ColumnChart } from "@/components/charts/charts";
import { ActivityFeed } from "@/components/dashboard/activity-feed";
import { LiveNetwork } from "@/components/network/live-network";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardLabel } from "@/components/ui/card";
import { SelectInput } from "@/components/ui/field";
import { ErrorState, Skeleton } from "@/components/ui/states";
import { api } from "@/lib/api";
import {
  dayColumns,
  expiryBars,
  inventoryByGroup,
  movementSeries,
  requestStatusBars,
} from "@/lib/charts";
import { useLiveRefresh } from "@/lib/live";
import { BLOOD_GROUPS, COMPONENTS, displayGroup } from "@/lib/network";
import { toFailure } from "@/lib/problem";
import { useReload } from "@/lib/use-reload";

const REFRESH_TOPICS = [
  "inventory.updated",
  "bag.discarded",
  "request.created",
  "request.dispatched",
  "request.fulfilled",
  "request.rejected",
  "request.cancelled",
];

interface Data {
  dash: FacilityDashboard;
  stock: InventorySummary;
}

/** Overview tab for hospitals and blood banks. All figures are the caller's own facility. */
export function FacilityOverview({
  kind,
  onNavigate,
}: {
  kind: "HOSPITAL" | "BLOOD_BANK";
  onNavigate: (tab: string) => void;
}) {
  const [data, setData] = useState<Data | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [version, reload] = useReload();
  useLiveRefresh(REFRESH_TOPICS, reload);

  useEffect(() => {
    let active = true;
    void Promise.all([api.GET("/api/v1/dashboard/facility"), api.GET("/api/v1/inventory/summary")]).then(
      ([d, s]) => {
        if (!active) return;
        if (d.data && s.data) {
          setData({ dash: d.data, stock: s.data });
          setError(null);
        } else {
          const failed = d.data ? s : d;
          setError(toFailure(failed.error, failed.response).message);
        }
      },
    );
    return () => {
      active = false;
    };
  }, [version]);

  if (error) {
    return (
      <ErrorState
        title="Couldn't load the overview"
        description={error}
        action={
          <Button size="sm" variant="secondary" onClick={reload}>
            Try again
          </Button>
        }
      />
    );
  }
  if (!data) return <OverviewSkeleton />;

  const { dash, stock } = data;
  const bank = kind === "BLOOD_BANK";
  const soon = stock.rows.reduce((n, r) => n + r.expiring_soon, 0);
  const expired = stock.rows.reduce((n, r) => n + r.expired, 0);
  const received = dash.requests.by_status.find((s) => s.status === "fulfilled")?.count ?? 0;

  return (
    <div className="flex flex-col gap-6" data-testid={`overview-${kind.toLowerCase()}`}>
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <StatTile
          label={bank ? "Usable units" : "Received stock"}
          value={stock.total_available}
          note={expired > 0 ? `${expired} expired awaiting discard` : "Not expired"}
        />
        <StatTile label="Expiring within 72 h" value={soon} note={soon > 0 ? "Use or dispatch first" : "None"} />
        <StatTile
          label={bank ? "Open incoming requests" : "Open requests"}
          value={dash.requests.open}
          note={dash.requests.emergency_open > 0 ? `${dash.requests.emergency_open} emergency` : "No emergencies"}
        />
        {bank ? (
          <StatTile label="Donations today" value={dash.donations.today} note={`${dash.donations.window_total} in ${dash.window_days} days`} />
        ) : (
          <StatTile label="Requests received" value={received} note={`${dash.requests.total} raised in total`} />
        )}
      </div>

      {dash.requests.emergency_open > 0 && (
        <Card className="flex flex-wrap items-center justify-between gap-3 border-critical p-4">
          <p className="text-sm">
            <Badge tone="critical" dot className="mr-2">
              Emergency
            </Badge>
            {dash.requests.emergency_open} emergency request{dash.requests.emergency_open === 1 ? " is" : "s are"} open.
          </p>
          <Button size="sm" variant="vital" onClick={() => onNavigate(bank ? "incoming" : "requests")}>
            {bank ? "Review incoming" : "View requests"}
          </Button>
        </Card>
      )}

      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <BarList
            title={bank ? "Usable units by blood group" : "Received units by blood group"}
            subtitle="All components; hover or use Table for the breakdown"
            data={inventoryByGroup(stock)}
            emptyText={bank ? "No usable stock. Record a donation to add bags." : "No received units yet."}
          />
        </Card>
        <Card>
          <BarList
            title="Time to expiry"
            subtitle="Units on hand, by remaining shelf life"
            data={expiryBars(dash.expiry)}
            emptyText="No units on hand."
          />
        </Card>
        <Card>
          <BarList
            title={bank ? "Incoming requests by status" : "My requests by status"}
            subtitle="All time"
            data={requestStatusBars(dash.requests.by_status)}
            unit="requests"
            emptyText={bank ? "No requests have been sent to you yet." : "You haven't sent a request yet."}
          />
        </Card>
        <Card>
          <ColumnChart
            title="Dispatch and receipt"
            subtitle={`Bags per day, last ${dash.window_days} days`}
            points={movementSeries(dash.movements)}
            series={[
              { key: "dispatched", label: "Dispatched" },
              { key: "received", label: "Received" },
            ]}
            emptyText="No bags have moved in this period."
          />
        </Card>
        {bank && (
          <Card className="lg:col-span-2">
            <ColumnChart
              title="Donations"
              subtitle={`Collections per day, last ${dash.window_days} days`}
              points={dayColumns(dash.donations.by_day).map((d) => ({ key: d.key, label: d.label, values: { donations: d.value } }))}
              series={[{ key: "donations", label: "Donations" }]}
              emptyText="No donations recorded in this period."
            />
          </Card>
        )}
      </div>

      {!bank && <AvailabilityOverview />}

      <div className="grid gap-6 lg:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
        <LiveNetwork compact />
        <ActivityFeed initial={dash.activity} />
      </div>
    </div>
  );
}

function OverviewSkeleton() {
  return (
    <div aria-busy="true" aria-label="Loading overview" className="flex flex-col gap-6">
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        {[0, 1, 2, 3].map((i) => (
          <Skeleton key={i} className="h-24" />
        ))}
      </div>
      <div className="grid gap-6 lg:grid-cols-2">
        {[0, 1, 2, 3].map((i) => (
          <Skeleton key={i} className="h-56" />
        ))}
      </div>
    </div>
  );
}

const BAND_LABEL = { sufficient: "Can cover", limited: "Limited", none: "No stock" } as const;

/** Hospital: network availability at a glance (banded, never exact stock). */
function AvailabilityOverview() {
  const [group, setGroup] = useState<BloodGroup>("O+");
  const [component, setComponent] = useState<BloodComponent>("PRBC");
  const [result, setResult] = useState<AvailabilityResponse | null>(null);

  useEffect(() => {
    let active = true;
    void api
      .GET("/api/v1/network/availability", { params: { query: { blood_group: group, component, units: 2 } } })
      .then(({ data }) => {
        if (active) setResult(data ?? null);
      });
    return () => {
      active = false;
    };
  }, [group, component]);

  const counts = { sufficient: 0, limited: 0, none: 0 };
  let simulated = 0;
  for (const r of result?.results ?? []) {
    counts[r.band] += 1;
    if (r.source.simulated) simulated += 1;
  }

  return (
    <Card>
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <CardLabel>Network availability</CardLabel>
          <p className="mt-1 text-xs text-ink-subtle">Blood banks able to supply 2 units, banded; exact stock is never shown.</p>
        </div>
        <div className="flex gap-2">
          <SelectInput aria-label="Blood group" className="h-9 w-24" value={group} onChange={(e) => setGroup(e.target.value as BloodGroup)}>
            {BLOOD_GROUPS.map((g) => (
              <option key={g} value={g}>
                {displayGroup(g)}
              </option>
            ))}
          </SelectInput>
          <SelectInput aria-label="Component" className="h-9 w-48" value={component} onChange={(e) => setComponent(e.target.value as BloodComponent)}>
            {COMPONENTS.map((c) => (
              <option key={c.code} value={c.code}>
                {c.label}
              </option>
            ))}
          </SelectInput>
        </div>
      </div>
      {result === null ? (
        <Skeleton className="mt-4 h-10" />
      ) : (
        <div className="mt-4 flex flex-wrap items-center gap-3" data-testid="availability-overview">
          {(Object.keys(counts) as (keyof typeof counts)[]).map((band) => (
            <Badge key={band} tone={band === "sufficient" ? "verified" : band === "limited" ? "warn" : "neutral"} dot>
              {BAND_LABEL[band]}: {counts[band]}
            </Badge>
          ))}
          {simulated > 0 && <span className="text-xs text-ink-subtle">includes {simulated} simulated partner banks</span>}
        </div>
      )}
    </Card>
  );
}
