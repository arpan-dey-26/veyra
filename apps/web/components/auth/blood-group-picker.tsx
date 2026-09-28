"use client";

import { cn } from "@/lib/cn";

const GROUPS = ["A+", "A-", "B+", "B-", "AB+", "AB-", "O+", "O-"] as const;

/** Radio group styled as tiles: fast to scan, keyboard accessible (arrow keys via native radios). */
export function BloodGroupPicker({
  value,
  onChange,
  groups = GROUPS,
  error,
  name = "blood_group",
}: {
  value: string;
  onChange: (value: string) => void;
  groups?: readonly string[];
  error?: string | null;
  name?: string;
}) {
  return (
    <fieldset aria-invalid={Boolean(error)} aria-describedby={error ? `${name}-error` : undefined}>
      <legend className="mb-1.5 text-sm font-medium text-ink">Blood group</legend>
      <div className="grid grid-cols-4 gap-2">
        {groups.map((group) => {
          const selected = value === group;
          return (
            <label
              key={group}
              className={cn(
                "relative flex h-12 cursor-pointer items-center justify-center rounded-md border",
                "font-mono text-[0.95rem] font-semibold transition-[transform,background-color,border-color,color]",
                "duration-(--dur-fast) ease-standard select-none active:scale-[0.97]",
                "has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-offset-2 has-[:focus-visible]:outline-focus",
                selected
                  ? "border-vital bg-vital text-on-vital shadow-1"
                  : "border-line-strong bg-surface-raised text-ink hover:border-vital/60",
              )}
            >
              <input
                type="radio"
                name={name}
                value={group}
                checked={selected}
                onChange={() => onChange(group)}
                className="sr-only"
              />
              {group.replace("-", "−")}
            </label>
          );
        })}
      </div>
      {error ? (
        <p id={`${name}-error`} role="alert" className="mt-1.5 text-xs font-medium text-critical">
          {error}
        </p>
      ) : (
        <p className="mt-1.5 text-xs text-ink-subtle">
          Self-declared for now. A blood bank confirms it at your first donation.
        </p>
      )}
    </fieldset>
  );
}
