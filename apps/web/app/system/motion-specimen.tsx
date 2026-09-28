"use client";

import { useState } from "react";

import { Button } from "@/components/ui/button";
import { useReducedMotion } from "@/lib/use-reduced-motion";

/** Lets designers feel each duration token with the standard easing. */
export function MotionSpecimen({ durations }: { durations: Record<string, number> }) {
  const [on, setOn] = useState(false);
  const reduced = useReducedMotion();

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-4">
        <Button size="sm" variant="secondary" onClick={() => setOn((v) => !v)}>
          Play
        </Button>
        {reduced && (
          <span className="text-xs text-ink-subtle">Reduced motion is on: durations collapse to 0.</span>
        )}
      </div>
      <ul className="space-y-3">
        {Object.entries(durations).map(([name, ms]) => (
          <li key={name} className="grid grid-cols-[7rem_1fr] items-center gap-4">
            <span className="font-mono text-xs text-ink-muted">
              {name} · {ms}ms
            </span>
            <div className="h-2 rounded-pill bg-surface-sunken">
              <div
                className="h-2 w-6 rounded-pill bg-vital"
                style={{
                  transform: on ? "translateX(calc(min(60vw, 40rem) - 1.5rem))" : "translateX(0)",
                  transition: `transform var(--dur-${name}) var(--ease-standard)`,
                }}
              />
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}
