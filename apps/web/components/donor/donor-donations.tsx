"use client";

import type { MyDonations } from "@veyra/api-client";
import { useEffect, useState } from "react";

import { StatTile } from "@/components/app/page-header";
import { Badge } from "@/components/ui/badge";
import { Card, CardLabel } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { EmptyState, Skeleton } from "@/components/ui/states";
import { api } from "@/lib/api";
import { formatDate } from "@/lib/network";
import { useReload } from "@/lib/use-reload";

/** The donor's own history: impact without ever naming the receiving hospital or patient. */
/** Impact tiles from the donor's own history (counts only). */
export function donorImpact(data: MyDonations): { donations: number; sent: number; inStock: number; components: number } {
  return {
    donations: data.donations.length,
    sent: data.donations.reduce((n, d) => n + d.bags_sent_to_hospitals, 0),
    inStock: data.donations.reduce((n, d) => n + d.bags_in_stock, 0),
    components: data.donations.reduce((n, d) => n + d.bags_total, 0),
  };
}

export function DonorDonations({
  verifiedAt,
  bloodGroupStatus,
}: {
  verifiedAt?: string | null;
  bloodGroupStatus?: string;
} = {}) {
  const [data, setData] = useState<MyDonations | null>(null);
  const [failed, setFailed] = useState(false);
  const [version, reload] = useReload();

  useEffect(() => {
    let active = true;
    void api.GET("/api/v1/donors/me/donations").then(({ data: d }) => {
      if (!active) return;
      if (d) {
        setData(d);
        setFailed(false);
      } else setFailed(true);
    });
    return () => {
      active = false;
    };
  }, [version]);

  if (failed) {
    return (
      <Card>
        <CardLabel>Donations</CardLabel>
        <p role="alert" className="mt-2 text-sm text-ink-muted">
          Your donation history couldn&apos;t be loaded.
        </p>
        <Button size="sm" variant="secondary" className="mt-3" onClick={reload}>
          Try again
        </Button>
      </Card>
    );
  }
  if (!data) return <Skeleton className="h-40 w-full" />;
  const impact = donorImpact(data);

  return (
    <div className="flex flex-col gap-4 md:col-span-2">
    <div className="grid grid-cols-2 gap-3 lg:grid-cols-4" data-testid="donor-impact">
      <StatTile label="Donations" value={impact.donations} note={impact.components > 0 ? `${impact.components} bags produced` : "None recorded yet"} />
      <StatTile label="Sent to hospitals" value={impact.sent} note="Bags dispatched from your donations" />
      <StatTile
        label="Next eligible"
        value={data.eligible_now ? "Now" : data.eligible_from ? formatDate(data.eligible_from) : "—"}
        note={`Minimum ${data.interval_days}-day interval (prototype default)`}
      />
      <StatTile
        label="Verification"
        value={verifiedAt ? "Verified" : "Pending"}
        note={bloodGroupStatus === "confirmed" ? "Blood group confirmed by a blood bank" : "Blood group self-declared"}
      />
    </div>
    <Card>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <CardLabel>Donations</CardLabel>
          <p className="mt-1 text-sm text-ink-muted">
            {data.donations.length === 0
              ? "Your donations will appear here after a blood bank records them."
              : `${data.donations.length} donation${data.donations.length === 1 ? "" : "s"} recorded`}
          </p>
        </div>
        {data.eligible_now ? (
          <Badge tone="verified" dot>
            Eligible to donate
          </Badge>
        ) : (
          <Badge tone="warn" dot>
            Next eligible {data.eligible_from ? formatDate(data.eligible_from) : "soon"}
          </Badge>
        )}
      </div>
      {data.donations.length === 0 ? (
        <div className="mt-5">
          <EmptyState
            title="No donations yet"
            description={`After each donation, VEYRA shows what it became and whether it reached a hospital. Donors can give again after ${data.interval_days} days.`}
          />
        </div>
      ) : (
        <ol className="mt-5 flex flex-col divide-y divide-line">
          {data.donations.map((d) => (
            <li key={d.id} className="flex flex-wrap items-center justify-between gap-3 py-3">
              <div>
                <p className="font-medium">{formatDate(d.collected_at)}</p>
                <p className="text-xs text-ink-subtle">
                  {d.facility_name}, {d.facility_city} · {d.volume_ml} ml · {d.components.join(", ")}
                </p>
              </div>
              <div className="flex flex-wrap gap-2">
                {d.bags_sent_to_hospitals > 0 && (
                  <Badge tone="vital">
                    {d.bags_sent_to_hospitals} sent to {d.bags_sent_to_hospitals === 1 ? "a hospital" : "hospitals"}
                  </Badge>
                )}
                {d.bags_in_stock > 0 && <Badge tone="verified">{d.bags_in_stock} in storage</Badge>}
                {d.bags_discarded > 0 && <Badge>{d.bags_discarded} not used</Badge>}
              </div>
            </li>
          ))}
        </ol>
      )}
    </Card>
    </div>
  );
}
