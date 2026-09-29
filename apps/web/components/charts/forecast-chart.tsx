"use client";

import { useState } from "react";

import { ChartFrame } from "@/components/charts/charts";
import { niceMax } from "@/lib/charts";
import { cn } from "@/lib/cn";
import type { TimelinePoint } from "@/lib/forecast";

const W = 100;
const H = 140;

function fmt(v: number | null): string {
  return v === null ? "—" : Number.isInteger(v) ? String(v) : v.toFixed(1);
}

/**
 * History (muted line) → today → forecast (vital line) with a ~80% interval band (vital wash).
 * One axis, shared units. Hover shows the day; the Table view lists every value.
 */
export function ForecastChart({
  title,
  subtitle,
  points,
}: {
  title: string;
  subtitle?: string;
  points: TimelinePoint[];
}) {
  const [hover, setHover] = useState<number | null>(null);
  const n = points.length;
  const values = points.flatMap((p) => [p.history, p.upper, p.predicted].filter((v): v is number => v !== null));
  const max = niceMax(Math.max(0, ...values));
  const x = (i: number) => (n <= 1 ? W / 2 : (i / (n - 1)) * W);
  const y = (v: number) => H - (v / max) * H;
  const firstFuture = points.findIndex((p) => p.predicted !== null);
  const path = (sel: (p: TimelinePoint) => number | null, from = 0, to = n) => {
    const segs: string[] = [];
    for (let i = from; i < to; i++) {
      const point = points[i];
      const v = point ? sel(point) : null;
      if (v === null) continue;
      segs.push(`${segs.length ? "L" : "M"}${x(i).toFixed(2)} ${y(v).toFixed(2)}`);
    }
    return segs.join(" ");
  };
  // Connect the last history point to the first forecast so the line reads continuously.
  const bridge = firstFuture > 0 ? firstFuture - 1 : firstFuture;
  const historyPath = path((p) => p.history, 0, firstFuture < 0 ? n : firstFuture);
  const forecastPath = path((p) => p.predicted ?? p.history, Math.max(0, bridge), n);
  const band =
    firstFuture < 0
      ? ""
      : [
          ...points.slice(firstFuture).map((p, k) => `${k ? "L" : "M"}${x(firstFuture + k).toFixed(2)} ${y(p.upper ?? 0).toFixed(2)}`),
          ...points
            .slice(firstFuture)
            .map((p, k) => ({ p, i: firstFuture + k }))
            .reverse()
            .map(({ p, i }) => `L${x(i).toFixed(2)} ${y(p.lower ?? 0).toFixed(2)}`),
          "Z",
        ].join(" ");
  const hovered = hover === null ? null : points[hover];
  const total = values.reduce((a, b) => a + b, 0);

  return (
    <ChartFrame
      title={title}
      subtitle={subtitle}
      empty={n === 0 || total === 0 ? "No demand to show for this selection." : null}
      legend={
        <ul className="flex flex-wrap gap-4 text-xs text-ink-muted" aria-label="Legend">
          <li className="flex items-center gap-1.5">
            <span aria-hidden className="inline-block h-0.5 w-4 bg-ink-subtle" /> History (synthetic)
          </li>
          <li className="flex items-center gap-1.5">
            <span aria-hidden className="inline-block h-0.5 w-4 bg-vital" /> Forecast
          </li>
          <li className="flex items-center gap-1.5">
            <span aria-hidden className="inline-block h-2.5 w-4 rounded-sm bg-vital/15" /> ~80% interval
          </li>
        </ul>
      }
      table={
        <table className="w-full text-sm" data-testid="forecast-table">
          <thead>
            <tr className="border-b border-line text-left text-ink-subtle">
              <th scope="col" className="py-2 font-medium">Day</th>
              <th scope="col" className="py-2 text-right font-medium">History</th>
              <th scope="col" className="py-2 text-right font-medium">Forecast</th>
              <th scope="col" className="py-2 text-right font-medium">Interval</th>
              <th scope="col" className="py-2 text-right font-medium">Baseline</th>
            </tr>
          </thead>
          <tbody>
            {points.map((p) => (
              <tr key={p.key} className="border-b border-line last:border-0">
                <th scope="row" className="py-1.5 text-left font-normal">{p.label}</th>
                <td className="py-1.5 text-right tabular-nums">{fmt(p.history)}</td>
                <td className="py-1.5 text-right tabular-nums">{fmt(p.predicted)}</td>
                <td className="py-1.5 text-right tabular-nums">{p.lower === null ? "—" : `${fmt(p.lower)}–${fmt(p.upper)}`}</td>
                <td className="py-1.5 text-right tabular-nums">{fmt(p.baseline)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      }
    >
      <div className="flex" data-chart="forecast">
        <div className="flex w-7 flex-col justify-between pr-1 text-right text-2xs text-ink-subtle tabular-nums" style={{ height: H }}>
          <span>{max}</span>
          <span>{max / 2}</span>
          <span>0</span>
        </div>
        <div className="relative min-w-0 flex-1">
          <svg
            viewBox={`0 0 ${W} ${H}`}
            preserveAspectRatio="none"
            className="h-[140px] w-full overflow-visible"
            role="img"
            aria-label={`${title}. ${points.filter((p) => p.history !== null).length} days of synthetic history and a ${points.filter((p) => p.predicted !== null).length}-day forecast.`}
            onMouseLeave={() => setHover(null)}
            onMouseMove={(e) => {
              const r = e.currentTarget.getBoundingClientRect();
              const i = Math.round(((e.clientX - r.left) / Math.max(1, r.width)) * (n - 1));
              setHover(Math.min(n - 1, Math.max(0, i)));
            }}
          >
            {[0, 0.5, 1].map((f) => (
              <line key={f} x1="0" x2={W} y1={H * f} y2={H * f} className="stroke-line" strokeWidth="1" vectorEffect="non-scaling-stroke" />
            ))}
            {band && <path d={band} className="fill-vital/15" data-series="interval" />}
            {firstFuture > 0 && (
              <line x1={x(firstFuture)} x2={x(firstFuture)} y1="0" y2={H} className="stroke-line-strong" strokeWidth="1" vectorEffect="non-scaling-stroke" />
            )}
            <path d={historyPath} fill="none" className="stroke-ink-subtle" strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" vectorEffect="non-scaling-stroke" data-series="history" />
            <path d={forecastPath} fill="none" className="stroke-vital" strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" vectorEffect="non-scaling-stroke" data-series="forecast" />
            {hover !== null && (
              <line x1={x(hover)} x2={x(hover)} y1="0" y2={H} className="stroke-ink-muted" strokeWidth="1" vectorEffect="non-scaling-stroke" />
            )}
          </svg>
          {firstFuture > 0 && (
            <span className="absolute -top-4 text-2xs text-ink-subtle" style={{ left: `${x(firstFuture)}%` }}>
              Today
            </span>
          )}
          {hovered && hover !== null && (
            <div
              role="tooltip"
              className={cn(
                "pointer-events-none absolute top-2 z-10 w-max rounded-md bg-ink px-3 py-2 text-xs text-surface shadow-2",
                x(hover) > 60 ? "-translate-x-full" : "translate-x-2",
              )}
              style={{ left: `${x(hover)}%` }}
            >
              <p className="font-medium">{hovered.label}</p>
              {hovered.history !== null ? (
                <p>Demand (synthetic): {fmt(hovered.history)}</p>
              ) : (
                <>
                  <p>Forecast: {fmt(hovered.predicted)}</p>
                  <p>Interval: {fmt(hovered.lower)}–{fmt(hovered.upper)}</p>
                  <p>Baseline: {fmt(hovered.baseline)}</p>
                </>
              )}
            </div>
          )}
        </div>
      </div>
      <div className="mt-1 ml-7 flex justify-between text-2xs text-ink-subtle">
        <span>{points[0]?.label}</span>
        <span>{points[n - 1]?.label}</span>
      </div>
    </ChartFrame>
  );
}
