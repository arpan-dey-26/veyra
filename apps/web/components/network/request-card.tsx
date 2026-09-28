import type { BloodRequestOut } from "@veyra/api-client";
import Link from "next/link";
import type { ReactNode } from "react";

import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { SimulatedBadge } from "@/components/ui/simulated-badge";
import { cn } from "@/lib/cn";
import {
  componentLabel,
  displayGroup,
  formatDateTime,
  REQUEST_STATUS,
  URGENCY_LABEL,
} from "@/lib/network";

export function RequestCard({
  request,
  perspective,
  actions,
}: {
  request: BloodRequestOut;
  perspective: "hospital" | "blood_bank";
  actions?: ReactNode;
}) {
  const status = REQUEST_STATUS[request.status];
  const counterpart = perspective === "hospital" ? request.target_name : request.hospital_name;
  return (
    <Card
      className={cn("p-5", request.urgency === "emergency" && request.status === "pending" && "border-critical")}
      data-request-id={request.id}
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex items-baseline gap-4">
          <span className="font-display text-3xl leading-none text-vital">{displayGroup(request.blood_group)}</span>
          <div>
            <p className="font-medium">
              {request.units} × {componentLabel(request.component)}
            </p>
            <p className="text-xs text-ink-subtle">
              <span className="font-mono">{request.reference}</span> ·{" "}
              {perspective === "hospital" ? "to" : "from"} {counterpart}
            </p>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {request.source.simulated && <SimulatedBadge subject="Blood bank" />}
          {request.urgency !== "routine" && (
            <Badge tone={request.urgency === "emergency" ? "critical" : "warn"}>
              {URGENCY_LABEL[request.urgency]}
            </Badge>
          )}
          <Badge tone={status.tone} dot>
            {status.label}
          </Badge>
        </div>
      </div>
      <dl className="mt-3 flex flex-wrap gap-x-6 gap-y-1 text-xs text-ink-muted">
        <div>
          <dt className="inline">Needed by </dt>
          <dd className="inline font-medium text-ink">{formatDateTime(request.needed_by)}</dd>
        </div>
        <div>
          <dt className="inline">Raised </dt>
          <dd className="inline">{formatDateTime(request.created_at)}</dd>
        </div>
      </dl>
      {request.notes && <p className="mt-2 text-sm text-ink-muted">“{request.notes}”</p>}
      {request.response_note && (
        <p className="mt-2 text-sm">
          <span className="text-ink-subtle">Response: </span>
          {request.response_note}
        </p>
      )}
      {request.bags.length > 0 && (
        <ul className="mt-3 flex flex-wrap gap-2" aria-label="Allocated bags">
          {request.bags.map((b) => (
            <li key={b.public_id}>
              <Link
                href={`/bags/${b.public_id}`}
                className="rounded-pill bg-surface-sunken px-3 py-1 font-mono text-xs hover:text-ink"
              >
                {b.public_id}
              </Link>
            </li>
          ))}
        </ul>
      )}
      {actions && <div className="mt-4 flex flex-wrap items-center gap-2">{actions}</div>}
    </Card>
  );
}
