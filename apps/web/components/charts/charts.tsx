"use client";

import { useId, useState, type ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/cn";
import { niceMax, type BarDatum, type SeriesPoint } from "@/lib/charts";

const TONE_BG: Record<NonNullable<BarDatum["tone"]>, string> = {
  vital: "bg-vital",
  warn: "bg-warn",
  critical: "bg-critical",
  verified: "bg-verified",
  neutral: "bg-ink-subtle",
};
/**
 * Chart frame: title, optional legend, the plot, and a "Table" toggle so every value is
 * available without hover or color (accessibility + print).
 */
export function ChartFrame({
  title,
  subtitle,
  legend,
  table,
  children,
  empty,
}: {
  title: string;
  subtitle?: string;
  legend?: ReactNode;
  table: ReactNode;
  children: ReactNode;
  empty?: string | null;
}) {
  const [showTable, setShowTable] = useState(false);
  const id = useId();
  return (
    <figure className="flex min-w-0 flex-col gap-3" aria-labelledby={`${id}-t`}>
      <div className="flex items-start justify-between gap-3">
        <figcaption>
          <p id={`${id}-t`} className="text-sm font-medium text-ink">
            {title}
          </p>
          {subtitle && <p className="text-xs text-ink-subtle">{subtitle}</p>}
        </figcaption>
        {!empty && (
          <Button
            size="sm"
            variant="ghost"
            aria-pressed={showTable}
            onClick={() => setShowTable((v) => !v)}
          >
            {showTable ? "Chart" : "Table"}
          </Button>
        )}
      </div>
      {legend}
      {empty ? (
        <p className="rounded-md bg-surface-sunken px-4 py-6 text-center text-sm text-ink-muted">
          {empty}
        </p>
      ) : showTable ? (
        <div className="overflow-x-auto">{table}</div>
      ) : (
        children
      )}
    </figure>
  );
}

function Tooltip({ children }: { children: ReactNode }) {
  return (
    <div
      role="tooltip"
      className="pointer-events-none absolute z-10 w-max max-w-56 -translate-x-1/2 rounded-md bg-ink px-3 py-2 text-xs text-surface shadow-2"
    >
      {children}
    </div>
  );
}

function DataTable({ head, rows }: { head: string[]; rows: (string | number)[][] }) {
  return (
    <table className="w-full text-sm">
      <thead>
        <tr className="border-b border-line text-left text-ink-subtle">
          {head.map((h, i) => (
            <th key={h} scope="col" className={cn("py-2 font-medium", i > 0 && "text-right")}>
              {h}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.map((r) => (
          <tr key={String(r[0])} className="border-b border-line last:border-0">
            {r.map((c, i) =>
              i === 0 ? (
                <th key={i} scope="row" className="py-1.5 text-left font-normal">
                  {c}
                </th>
              ) : (
                <td key={i} className="py-1.5 text-right tabular-nums">
                  {c}
                </td>
              ),
            )}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

/** Horizontal bars for categories (blood groups, statuses, expiry windows). */
export function BarList({
  title,
  subtitle,
  data,
  unit = "units",
  emptyText = "Nothing to show yet.",
}: {
  title: string;
  subtitle?: string;
  data: BarDatum[];
  unit?: string;
  emptyText?: string;
}) {
  const [hover, setHover] = useState<string | null>(null);
  const max = niceMax(Math.max(0, ...data.map((d) => d.value)));
  const total = data.reduce((n, d) => n + d.value, 0);
  return (
    <ChartFrame
      title={title}
      subtitle={subtitle}
      empty={total === 0 ? emptyText : null}
      table={<DataTable head={["", unit]} rows={data.map((d) => [d.label, d.value])} />}
    >
      <ul className="flex flex-col gap-1.5" data-chart="bar-list">
        {data.map((d) => (
          <li key={d.key} className="relative">
            <div
              tabIndex={0}
              aria-label={`${d.label}: ${d.value} ${unit}${d.detail ? `. ${d.detail}` : ""}`}
              onMouseEnter={() => setHover(d.key)}
              onMouseLeave={() => setHover(null)}
              onFocus={() => setHover(d.key)}
              onBlur={() => setHover(null)}
              className="grid grid-cols-[7.5rem_1fr_2.5rem] items-center gap-3 rounded-sm py-1 text-sm outline-none focus-visible:ring-2 focus-visible:ring-focus"
            >
              <span className="truncate text-ink-muted">{d.label}</span>
              <span className="relative h-3 rounded-r-sm bg-surface-sunken">
                {d.value > 0 && (
                  <span
                    data-value={d.value}
                    className={cn("absolute inset-y-0 left-0 rounded-r-[4px]", TONE_BG[d.tone ?? "vital"])}
                    style={{ width: `${Math.max(2, (d.value / max) * 100)}%` }}
                  />
                )}
              </span>
              <span className="text-right font-medium tabular-nums text-ink">{d.value}</span>
            </div>
            {hover === d.key && (
              <div className="absolute top-full left-1/2">
                <Tooltip>
                  <p className="font-medium">
                    {d.label}: {d.value} {unit}
                  </p>
                  {d.detail && <p className="mt-0.5 opacity-80">{d.detail}</p>}
                </Tooltip>
              </div>
            )}
          </li>
        ))}
      </ul>
    </ChartFrame>
  );
}

const PLOT_H = 120;

/**
 * Columns over time. One series → VEYRA vital, no legend. Two series → validated viz-1/viz-2,
 * side by side (never stacked on different scales), with a legend.
 */
export function ColumnChart({
  title,
  subtitle,
  points,
  series,
  emptyText = "No activity in this period.",
}: {
  title: string;
  subtitle?: string;
  points: SeriesPoint[];
  series: { key: string; label: string }[];
  emptyText?: string;
}) {
  const [hover, setHover] = useState<number | null>(null);
  const total = points.reduce((n, p) => n + series.reduce((m, s) => m + (p.values[s.key] ?? 0), 0), 0);
  const max = niceMax(Math.max(0, ...points.flatMap((p) => series.map((s) => p.values[s.key] ?? 0))));
  const multi = series.length > 1;
  const fills = multi ? ["fill-viz-1", "fill-viz-2"] : ["fill-vital"];
  const n = points.length;
  const slot = 100 / Math.max(1, n);
  const every = Math.ceil(n / 7);
  const hovered = hover === null ? null : points[hover];

  const legend = multi ? (
    <ul className="flex flex-wrap gap-4 text-xs text-ink-muted" aria-label="Legend">
      {series.map((s, i) => (
        <li key={s.key} className="flex items-center gap-1.5">
          <svg aria-hidden viewBox="0 0 10 10" className="size-2.5">
            <rect width="10" height="10" rx="2" className={fills[i]} />
          </svg>
          {s.label}
        </li>
      ))}
    </ul>
  ) : undefined;

  return (
    <ChartFrame
      title={title}
      subtitle={subtitle}
      legend={total > 0 ? legend : undefined}
      empty={total === 0 ? emptyText : null}
      table={
        <DataTable
          head={["Day", ...series.map((s) => s.label)]}
          rows={points.map((p) => [p.label, ...series.map((s) => p.values[s.key] ?? 0)])}
        />
      }
    >
      <div className="relative" data-chart="columns">
        <div className="flex">
          <div className="flex w-6 flex-col justify-between pr-1 text-right text-2xs text-ink-subtle tabular-nums" style={{ height: PLOT_H }}>
            <span>{max}</span>
            <span>{max / 2}</span>
            <span>0</span>
          </div>
          <div className="relative min-w-0 flex-1">
          <svg
            viewBox={`0 0 100 ${PLOT_H}`}
            preserveAspectRatio="none"
            className="h-[120px] w-full overflow-visible"
            role="img"
            aria-label={`${title}: ${total} in total over ${n} days`}
            onMouseLeave={() => setHover(null)}
          >
            {[0, 0.5, 1].map((f) => (
              <line
                key={f}
                x1="0"
                x2="100"
                y1={PLOT_H * f}
                y2={PLOT_H * f}
                className="stroke-line"
                strokeWidth="1"
                vectorEffect="non-scaling-stroke"
              />
            ))}
            {points.map((p, i) => {
              const inner = slot * 0.7;
              const barW = Math.min(inner / series.length, 3.2);
              const groupW = barW * series.length + (series.length - 1) * 0.4;
              const x0 = i * slot + (slot - groupW) / 2;
              return (
                <g key={p.key} onMouseEnter={() => setHover(i)} data-day={p.key}>
                  <rect x={i * slot} y="0" width={slot} height={PLOT_H} fill="transparent" />
                  {series.map((s, j) => {
                    const v = p.values[s.key] ?? 0;
                    if (v === 0) return null;
                    const h = Math.max(2, (v / max) * PLOT_H);
                    return (
                      <rect
                        key={s.key}
                        x={x0 + j * (barW + 0.4)}
                        y={PLOT_H - h}
                        width={barW}
                        height={h}
                        rx="0.8"
                        className={cn(fills[j], hover !== null && hover !== i && "opacity-40")}
                      />
                    );
                  })}
                </g>
              );
            })}
          </svg>
          {hovered && hover !== null && (
            <div className="absolute top-0" style={{ left: `${(hover + 0.5) * slot}%` }}>
              <Tooltip>
                <p className="font-medium">{hovered.label}</p>
                {series.map((s) => (
                  <p key={s.key}>
                    {s.label}: {hovered.values[s.key] ?? 0}
                  </p>
                ))}
              </Tooltip>
            </div>
          )}
          </div>
        </div>
        <div className="mt-1 ml-6 flex text-2xs text-ink-subtle">
          {points.map((p, i) => (
            <span key={p.key} className="text-center" style={{ width: `${slot}%` }}>
              {i % every === every - 1 || i === n - 1 ? p.label : ""}
            </span>
          ))}
        </div>
      </div>
    </ChartFrame>
  );
}
