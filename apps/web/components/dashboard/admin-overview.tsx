"use client";

import type { AdminDashboard } from "@veyra/api-client";
import Link from "next/link";
import { useEffect, useState } from "react";

import { StatTile } from "@/components/app/page-header";
import { BarList, ColumnChart } from "@/components/charts/charts";
import { ActivityFeed } from "@/components/dashboard/activity-feed";
import { LiveIndicator } from "@/components/network/live-indicator";
import { ApiStatus } from "@/components/system/api-status";
import { Button } from "@/components/ui/button";
import { Card, CardLabel } from "@/components/ui/card";
import { ErrorState, Skeleton } from "@/components/ui/states";
import { api } from "@/lib/api";
import { dayColumns, movementSeries, requestStatusBars, usersByRole } from "@/lib/charts";
import { useLiveRefresh } from "@/lib/live";
import { BAG_STATUS, formatDateTime } from "@/lib/network";
import { toFailure } from "@/lib/problem";
import { useReload } from "@/lib/use-reload";

const TOPICS = ["request.created", "request.dispatched", "request.fulfilled", "request.rejected", "request.cancelled", "inventory.updated", "bag.discarded"];

/** Network-wide counts for administrators. Counts only: no donor data, no audit details. */
export function AdminOverview() {
  const [data, setData] = useState<AdminDashboard | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [version, reload] = useReload();
  useLiveRefresh(TOPICS, reload);

  useEffect(() => {
    let active = true;
    void api.GET("/api/v1/dashboard/admin").then(({ data: d, error: e, response }) => {
      if (!active) return;
      if (d) {
        setData(d);
        setError(null);
      } else setError(toFailure(e, response).message);
    });
    return () => {
      active = false;
    };
  }, [version]);

  if (error) {
    return (
      <ErrorState
        title="Couldn't load network overview"
        description={error}
        action={
          <Button size="sm" variant="secondary" onClick={reload}>
            Try again
          </Button>
        }
      />
    );
  }
  if (!data) {
    return (
      <div aria-busy="true" aria-label="Loading network overview" className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        {[0, 1, 2, 3].map((i) => (
          <Skeleton key={i} className="h-24" />
        ))}
      </div>
    );
  }

  const open = data.requests_by_status
    .filter((s) => ["pending", "acknowledged", "dispatched"].includes(s.status))
    .reduce((n, s) => n + s.count, 0);
  const bagsInUse = data.bags_by_status.filter((s) => s.status !== "discarded").reduce((n, s) => n + s.count, 0);

  return (
    <div className="flex flex-col gap-6" data-testid="admin-overview">
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <StatTile label="Accounts" value={data.users_total} />
        <StatTile
          label="Facilities"
          value={data.facilities.blood_banks + data.facilities.hospitals}
          note={`${data.facilities.blood_banks} blood banks · ${data.facilities.hospitals} hospitals`}
        />
        <StatTile label="Open requests" value={open} note="Network-wide" />
        <StatTile label="Bags tracked" value={bagsInUse} note="Excludes discarded" />
      </div>

      <Card className="flex flex-wrap items-center justify-between gap-4 p-4">
        <div className="flex flex-col gap-2">
          <CardLabel>System health</CardLabel>
          <ApiStatus />
        </div>
        <div className="flex items-center gap-4">
          <LiveIndicator />
          <Link href="/network" className="text-sm font-medium underline underline-offset-4">
            Open live network
          </Link>
        </div>
      </Card>

      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <BarList title="Accounts by role" data={usersByRole(data)} unit="accounts" />
        </Card>
        <Card>
          <BarList title="Requests by status" subtitle="Network-wide, all time" data={requestStatusBars(data.requests_by_status)} unit="requests" emptyText="No requests yet." />
        </Card>
        <Card>
          <ColumnChart
            title="Donations"
            subtitle={`Network-wide, last ${data.window_days} days`}
            points={dayColumns(data.donations_by_day).map((d) => ({ key: d.key, label: d.label, values: { donations: d.value } }))}
            series={[{ key: "donations", label: "Donations" }]}
          />
        </Card>
        <Card>
          <ColumnChart
            title="Dispatch and receipt"
            subtitle={`Bags per day, last ${data.window_days} days`}
            points={movementSeries(data.movements)}
            series={[
              { key: "dispatched", label: "Dispatched" },
              { key: "received", label: "Received" },
            ]}
          />
        </Card>
        <Card>
          <BarList
            title="Bags by status"
            data={data.bags_by_status.map((s) => ({ key: s.status, label: BAG_STATUS[s.status]?.label ?? s.status, value: s.count, tone: "vital" }))}
            unit="bags"
            emptyText="No bags recorded yet."
          />
        </Card>
        <Card>
          <BarList
            title="Audit activity"
            subtitle={`${data.audit.last_24h} entries in the last 24 h, top actions`}
            data={data.audit.top_actions.map((a) => ({ key: a.status, label: a.status, value: a.count, tone: "neutral" }))}
            unit="entries"
            emptyText="No audit entries in the last 24 h."
          />
        </Card>
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        <ActivityFeed initial={data.activity} />
        <Card className="p-5">
          <CardLabel>Recent audit entries</CardLabel>
          <p className="mt-1 text-xs text-ink-subtle">Summary only. IP addresses and details stay in the append-only audit log.</p>
          {data.audit.recent.length === 0 ? (
            <p className="mt-3 text-sm text-ink-muted">No audit entries yet.</p>
          ) : (
            <table className="mt-3 w-full text-sm" data-testid="audit-table">
              <thead>
                <tr className="border-b border-line text-left text-ink-subtle">
                  <th scope="col" className="py-2 font-medium">Action</th>
                  <th scope="col" className="py-2 font-medium">Actor</th>
                  <th scope="col" className="py-2 text-right font-medium">When</th>
                </tr>
              </thead>
              <tbody>
                {data.audit.recent.map((a, i) => (
                  <tr key={`${a.created_at}-${i}`} className="border-b border-line last:border-0">
                    <td className="py-1.5 font-mono text-xs">{a.action}</td>
                    <td className="py-1.5 text-ink-muted">{a.actor_type}</td>
                    <td className="py-1.5 text-right text-xs text-ink-subtle">{formatDateTime(a.created_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Card>
      </div>
    </div>
  );
}
