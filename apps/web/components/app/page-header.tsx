import type { ReactNode } from "react";

export function PageHeader({
  eyebrow,
  title,
  description,
  actions,
}: {
  eyebrow?: string;
  title: string;
  description?: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <div className="mb-8 flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
      <div>
        {eyebrow && (
          <p className="text-2xs font-semibold tracking-(--tracking-label) text-ink-subtle uppercase">
            {eyebrow}
          </p>
        )}
        <h1 className="mt-1 font-display text-display-sm leading-(--leading-tight) tracking-(--tracking-display)">
          {title}
        </h1>
        {description && <p className="mt-2 max-w-prose text-ink-muted">{description}</p>}
      </div>
      {actions}
    </div>
  );
}

export function StatTile({ label, value, note }: { label: string; value: ReactNode; note?: string }) {
  return (
    <div className="rounded-lg border border-line bg-surface-raised p-5 shadow-1">
      <p className="text-2xs font-semibold tracking-(--tracking-label) text-ink-subtle uppercase">
        {label}
      </p>
      <p className="mt-2 font-display text-3xl leading-none">{value}</p>
      {note && <p className="mt-2 text-xs text-ink-subtle">{note}</p>}
    </div>
  );
}

/** Honest placeholder for a module that arrives in a later phase. */
export function ComingInPhase({
  phase,
  title,
  description,
}: {
  phase: number;
  title: string;
  description: string;
}) {
  return (
    <div className="flex flex-col gap-2 rounded-lg border border-dashed border-line-strong p-6">
      <p className="text-2xs font-semibold tracking-(--tracking-label) text-ink-subtle uppercase">
        Arrives in Phase {phase}
      </p>
      <p className="font-medium">{title}</p>
      <p className="text-sm text-ink-muted">{description}</p>
    </div>
  );
}
