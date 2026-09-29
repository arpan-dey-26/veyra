"use client";

import type { ActivityItem } from "@veyra/api-client";
import { useEffect, useState } from "react";

import { Card, CardLabel } from "@/components/ui/card";
import { activityText } from "@/lib/charts";
import { useLive } from "@/lib/live";
import { formatDateTime } from "@/lib/network";

const LIMIT = 10;

/** Recent network events: seeded from the dashboard API, then prepended live over SSE. */
export function ActivityFeed({ initial, title = "Recent network activity" }: { initial: ActivityItem[]; title?: string }) {
  const [live, setLive] = useState<ActivityItem[]>([]);
  const { subscribe } = useLive();

  useEffect(
    () =>
      subscribe("*", (e) => {
        const item: ActivityItem = {
          event_id: e.event_id,
          topic: e.topic,
          created_at: e.created_at,
          reference: typeof e.reference === "string" ? e.reference : null,
          status: typeof e.status === "string" ? e.status : null,
          blood_group: typeof e.blood_group === "string" ? e.blood_group : null,
          component: typeof e.component === "string" ? e.component : null,
          units: typeof e.units === "number" ? e.units : null,
          urgency: typeof e.urgency === "string" ? e.urgency : null,
          reason: typeof e.reason === "string" ? e.reason : null,
        };
        setLive((cur) => [item, ...cur.filter((x) => x.event_id !== item.event_id)].slice(0, LIMIT));
      }),
    [subscribe],
  );

  const seen = new Set<string>();
  const items = [...live, ...initial].filter((i) => (seen.has(i.event_id) ? false : (seen.add(i.event_id), true))).slice(0, LIMIT);

  return (
    <Card className="p-5">
      <CardLabel>{title}</CardLabel>
      {items.length === 0 ? (
        <p className="mt-3 text-sm text-ink-muted">No activity yet. Donations, requests and dispatches appear here as they happen.</p>
      ) : (
        <ol className="mt-3 flex flex-col divide-y divide-line" aria-live="polite" data-testid="activity-feed">
          {items.map((i) => {
            const t = activityText(i);
            return (
              <li key={i.event_id} className="flex items-start justify-between gap-3 py-2.5 text-sm">
                <div className="min-w-0">
                  <p className="font-medium">
                    {t.title}
                    {i.urgency === "emergency" && <span className="ml-2 text-xs font-semibold text-critical">Emergency</span>}
                  </p>
                  {t.detail && <p className="truncate text-xs text-ink-muted">{t.detail}</p>}
                </div>
                <time dateTime={i.created_at} className="shrink-0 text-2xs text-ink-subtle">
                  {formatDateTime(i.created_at)}
                </time>
              </li>
            );
          })}
        </ol>
      )}
    </Card>
  );
}
