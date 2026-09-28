import type { ReactNode } from "react";

import { cn } from "@/lib/cn";

/** Loading placeholder. Shimmer is disabled under reduced motion. */
export function Skeleton({ className }: { className?: string }) {
  return <div aria-hidden className={cn("veyra-skeleton rounded-md", className)} />;
}

export function EmptyState({
  title,
  description,
  action,
}: {
  title: string;
  description: string;
  action?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-start gap-3 rounded-lg border border-dashed border-line-strong p-8">
      <p className="text-base font-medium text-ink">{title}</p>
      <p className="max-w-prose text-sm text-ink-muted">{description}</p>
      {action}
    </div>
  );
}

export function ErrorState({
  title = "Something went wrong",
  description,
  requestId,
  action,
}: {
  title?: string;
  description: string;
  requestId?: string | null;
  action?: ReactNode;
}) {
  return (
    <div role="alert" className="flex flex-col items-start gap-3 rounded-lg bg-critical-soft p-6">
      <p className="text-base font-medium text-critical">{title}</p>
      <p className="text-sm text-ink-muted">{description}</p>
      {requestId && <p className="font-mono text-xs text-ink-subtle">Request ID: {requestId}</p>}
      {action}
    </div>
  );
}

/** Live-status beacon. `critical` uses the emergency pulse; reserved for true criticals. */
export function StatusBeacon({
  tone = "verified",
  label,
}: {
  tone?: "verified" | "warn" | "critical" | "idle";
  label: string;
}) {
  const color = {
    verified: "bg-verified",
    warn: "bg-warn",
    critical: "bg-critical",
    idle: "bg-ink-subtle",
  }[tone];
  return (
    <span className="inline-flex items-center gap-2 text-sm text-ink-muted">
      <span className="relative inline-flex size-2.5">
        {tone !== "idle" && (
          <span aria-hidden className={cn("veyra-beacon absolute inset-0 rounded-full", color)} />
        )}
        <span aria-hidden className={cn("relative inline-flex size-2.5 rounded-full", color)} />
      </span>
      {label}
    </span>
  );
}
