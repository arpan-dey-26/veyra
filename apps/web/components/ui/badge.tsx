import type { HTMLAttributes } from "react";

import { cn } from "@/lib/cn";

export type BadgeTone = "neutral" | "vital" | "verified" | "warn" | "critical" | "simulated";

const tones: Record<BadgeTone, string> = {
  neutral: "bg-surface-sunken text-ink-muted",
  vital: "bg-vital-soft text-vital",
  verified: "bg-verified-soft text-verified",
  warn: "bg-warn-soft text-warn",
  critical: "bg-critical-soft text-critical",
  simulated: "bg-simulated-soft text-simulated",
};

export interface BadgeProps extends HTMLAttributes<HTMLSpanElement> {
  tone?: BadgeTone;
  dot?: boolean;
}

export function Badge({ tone = "neutral", dot = false, className, children, ...props }: BadgeProps) {
  return (
    <span
      data-tone={tone}
      className={cn(
        "inline-flex items-center gap-1.5 rounded-pill px-2.5 py-0.5 text-xs font-medium",
        tones[tone],
        className,
      )}
      {...props}
    >
      {dot && <span aria-hidden className="size-1.5 rounded-full bg-current" />}
      {children}
    </span>
  );
}
