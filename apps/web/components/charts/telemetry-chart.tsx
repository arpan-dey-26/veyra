"use client";

import type { ColdChainThresholds, TelemetryReading } from "@veyra/api-client";
import { useState } from "react";

import { ChartFrame } from "@/components/charts/charts";
import { cn } from "@/lib/cn";
import { formatDateTime } from "@/lib/network";
import { COLD_STATUS, formatTemp, temperatureDomain } from "@/lib/telemetry";

const W = 100;
const H = 150;
const MARK: Record<string, string> = { warning: "bg-warn", critical: "bg-critical" };

/**
 * Temperature over readings. The normal band is a light wash; the critical limits are hairlines.
 * Out-of-range readings get a marker (colour + the status in the tooltip/table, never colour alone).
 */
export function TelemetryChart({
  readings,
  thresholds,
  title = "Temperature",
}: {
  readings: TelemetryReading[];
  thresholds: ColdChainThresholds;
  title?: string;
}) {
  const [hover, setHover] = useState<number | null>(null);
  const [lo, hi] = temperatureDomain(readings, thresholds);
  const n = readings.length;
  const x = (i: number) => (n <= 1 ? W / 2 : (i / (n - 1)) * W);
  const y = (t: number) => H - ((t - lo) / Math.max(1e-9, hi - lo)) * H;
  const line = readings.map((r, i) => `${i ? "L" : "M"}${x(i).toFixed(2)} ${y(r.temperature_c).toFixed(2)}`).join(" ");
  const hovered = hover === null ? null : readings[hover];

  return (
    <ChartFrame
      title={title}
      subtitle={`°C per reading · normal ${thresholds.label} (prototype thresholds)`}
      empty={n === 0 ? "No readings yet. Take a reading or start the simulator." : null}
      legend={
        <ul className="flex flex-wrap gap-4 text-xs text-ink-muted" aria-label="Legend">
          <li className="flex items-center gap-1.5">
            <span aria-hidden className="inline-block h-0.5 w-4 bg-ink" /> Temperature (simulated)
          </li>
          <li className="flex items-center gap-1.5">
            <span aria-hidden className="inline-block h-2.5 w-4 rounded-sm bg-verified/15" /> Normal range
          </li>
          <li className="flex items-center gap-1.5">
            <span aria-hidden className="inline-block h-0.5 w-4 bg-critical" /> Critical limits
          </li>
          <li className="flex items-center gap-1.5">
            <span aria-hidden className="inline-block size-2.5 rounded-full bg-warn" /> Warning reading
          </li>
          <li className="flex items-center gap-1.5">
            <span aria-hidden className="inline-block size-2.5 rounded-full bg-critical" /> Critical reading
          </li>
        </ul>
      }
      table={
        <table className="w-full text-sm" data-testid="telemetry-table">
          <thead>
            <tr className="border-b border-line text-left text-ink-subtle">
              <th scope="col" className="py-2 font-medium">#</th>
              <th scope="col" className="py-2 font-medium">Time</th>
              <th scope="col" className="py-2 text-right font-medium">Temperature</th>
              <th scope="col" className="py-2 text-right font-medium">Status</th>
              <th scope="col" className="py-2 text-right font-medium">Battery</th>
            </tr>
          </thead>
          <tbody>
            {readings.map((r) => (
              <tr key={r.seq} className="border-b border-line last:border-0">
                <th scope="row" className="py-1.5 text-left font-normal tabular-nums">{r.seq}</th>
                <td className="py-1.5 text-ink-muted">{formatDateTime(r.recorded_at)}</td>
                <td className="py-1.5 text-right tabular-nums">{formatTemp(r.temperature_c)}</td>
                <td className="py-1.5 text-right">{COLD_STATUS[r.status]?.label ?? r.status}</td>
                <td className="py-1.5 text-right tabular-nums">{r.battery_pct.toFixed(1)}%</td>
              </tr>
            ))}
          </tbody>
        </table>
      }
    >
      <div className="flex" data-chart="telemetry">
        <div className="flex w-10 flex-col justify-between pr-1 text-right text-2xs text-ink-subtle tabular-nums" style={{ height: H }}>
          <span>{hi}°</span>
          <span>{((hi + lo) / 2).toFixed(0)}°</span>
          <span>{lo}°</span>
        </div>
        <div className="relative min-w-0 flex-1">
          <svg
            viewBox={`0 0 ${W} ${H}`}
            preserveAspectRatio="none"
            className="h-[150px] w-full overflow-visible"
            role="img"
            aria-label={`${title}: ${n} simulated readings, latest ${formatTemp(readings[n - 1]?.temperature_c)}.`}
            onMouseLeave={() => setHover(null)}
            onMouseMove={(e) => {
              const r = e.currentTarget.getBoundingClientRect();
              const i = Math.round(((e.clientX - r.left) / Math.max(1, r.width)) * (n - 1));
              setHover(Math.min(n - 1, Math.max(0, i)));
            }}
          >
            <rect
              x="0"
              width={W}
              y={y(thresholds.normal_high)}
              height={Math.max(0, y(thresholds.normal_low) - y(thresholds.normal_high))}
              className="fill-verified/10"
              data-band="normal"
            />
            {[thresholds.critical_low, thresholds.critical_high].map((t) => (
              <line key={t} x1="0" x2={W} y1={y(t)} y2={y(t)} className="stroke-critical/70" strokeWidth="1" vectorEffect="non-scaling-stroke" data-limit={t} />
            ))}
            <path d={line} fill="none" className="stroke-ink" strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" vectorEffect="non-scaling-stroke" data-series="temperature" />
            {hover !== null && (
              <line x1={x(hover)} x2={x(hover)} y1="0" y2={H} className="stroke-ink-muted" strokeWidth="1" vectorEffect="non-scaling-stroke" />
            )}
          </svg>
          {/* Markers in HTML so they stay round in a stretched SVG. */}
          {readings.map((r, i) =>
            r.status === "normal" ? null : (
              <span
                key={r.seq}
                aria-hidden
                data-marker={r.status}
                className={cn(
                  "absolute size-2.5 -translate-x-1/2 -translate-y-1/2 rounded-full ring-2 ring-surface-raised",
                  MARK[r.status],
                )}
                style={{ left: `${x(i)}%`, top: `${(y(r.temperature_c) / H) * 100}%` }}
              />
            ),
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
              <p className="font-medium">
                #{hovered.seq} · {formatDateTime(hovered.recorded_at)}
              </p>
              <p>
                {formatTemp(hovered.temperature_c)} · {COLD_STATUS[hovered.status]?.label}
              </p>
              <p>Battery {hovered.battery_pct.toFixed(1)}%</p>
            </div>
          )}
        </div>
      </div>
    </ChartFrame>
  );
}
