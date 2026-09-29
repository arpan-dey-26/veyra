"use client";

import type { BloodGroup, DemandForecast, ForecastSummary, ModelCard } from "@veyra/api-client";
import { useEffect, useState } from "react";

import { StatTile } from "@/components/app/page-header";
import { BarList } from "@/components/charts/charts";
import { ForecastChart } from "@/components/charts/forecast-chart";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardLabel } from "@/components/ui/card";
import { SelectInput } from "@/components/ui/field";
import { SimulatedBadge } from "@/components/ui/simulated-badge";
import { EmptyState, ErrorState, Skeleton } from "@/components/ui/states";
import { api } from "@/lib/api";
import {
  attentionRows,
  FORECAST_BADGE,
  FORECAST_COMPONENTS,
  forecastByGroup,
  forecastTimeline,
  PRESSURE,
  SIGNAL,
  signalCounts,
  type ForecastComponent,
} from "@/lib/forecast";
import { BLOOD_GROUPS, displayGroup } from "@/lib/network";
import { toFailure } from "@/lib/problem";
import { useReload } from "@/lib/use-reload";

const HORIZONS = [7, 14] as const;

/** Prototype banner: every forecast view carries it. */
export function ForecastDisclaimer({ text }: { text?: string }) {
  return (
    <div role="note" className="flex flex-wrap items-center gap-3 rounded-md bg-simulated-soft px-4 py-3 text-sm text-simulated" data-testid="forecast-disclaimer">
      <SimulatedBadge label="Synthetic data" subject="Demand forecast" />
      <span className="font-medium">{FORECAST_BADGE}</span>
      <span className="text-xs">
        {text ?? "Trained and run on synthetic demand data. Not clinical guidance and not a certified medical prediction system."}
      </span>
    </div>
  );
}

function ModelLabel({ model }: { model: DemandForecast["model"] }) {
  return (
    <p className="text-xs text-ink-subtle" data-testid="model-label">
      Model {model.name} v{model.version} · trained on {model.trained_on} data · validation MAE {model.one_step_mae} vs baseline{" "}
      {model.baseline_one_step_mae}
    </p>
  );
}

function Controls({
  group,
  component,
  horizon,
  onGroup,
  onComponent,
  onHorizon,
}: {
  group: BloodGroup;
  component: ForecastComponent;
  horizon: number;
  onGroup: (g: BloodGroup) => void;
  onComponent: (c: ForecastComponent) => void;
  onHorizon: (h: number) => void;
}) {
  return (
    <div className="flex flex-wrap gap-2">
      <SelectInput aria-label="Blood group" className="h-9 w-24" value={group} onChange={(e) => onGroup(e.target.value as BloodGroup)}>
        {BLOOD_GROUPS.map((g) => (
          <option key={g} value={g}>
            {displayGroup(g)}
          </option>
        ))}
      </SelectInput>
      <SelectInput aria-label="Component" className="h-9 w-48" value={component} onChange={(e) => onComponent(e.target.value as ForecastComponent)}>
        {FORECAST_COMPONENTS.map((c) => (
          <option key={c.code} value={c.code}>
            {c.label}
          </option>
        ))}
      </SelectInput>
      <SelectInput aria-label="Forecast horizon" className="h-9 w-32" value={horizon} onChange={(e) => onHorizon(Number(e.target.value))}>
        {HORIZONS.map((h) => (
          <option key={h} value={h}>
            {h} days
          </option>
        ))}
      </SelectInput>
    </div>
  );
}

function Retry({ title, message, onRetry }: { title: string; message: string; onRetry: () => void }) {
  return (
    <ErrorState
      title={title}
      description={message}
      action={
        <Button size="sm" variant="secondary" onClick={onRetry}>
          Try again
        </Button>
      }
    />
  );
}

/** Hospital / blood bank forecast tab. Scoped server-side to the caller's facility. */
export function ForecastPanel({ kind }: { kind: "HOSPITAL" | "BLOOD_BANK" }) {
  const [group, setGroup] = useState<BloodGroup>("O+");
  const [component, setComponent] = useState<ForecastComponent>("PRBC");
  const [horizon, setHorizon] = useState(7);
  const [demand, setDemand] = useState<DemandForecast | null>(null);
  const [summary, setSummary] = useState<ForecastSummary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [version, reload] = useReload();

  useEffect(() => {
    let active = true;
    void api
      .GET("/api/v1/forecast/demand", { params: { query: { blood_group: group, component, horizon } } })
      .then(({ data, error: e, response }) => {
        if (!active) return;
        if (data) {
          setDemand(data);
          setError(null);
        } else setError(toFailure(e, response).message);
      });
    return () => {
      active = false;
    };
  }, [group, component, horizon, version]);

  useEffect(() => {
    let active = true;
    void api.GET("/api/v1/forecast/summary", { params: { query: { horizon } } }).then(({ data }) => {
      if (active) setSummary(data ?? null);
    });
    return () => {
      active = false;
    };
  }, [horizon, version]);

  const bank = kind === "BLOOD_BANK";
  return (
    <div className="flex flex-col gap-6" data-testid="forecast-panel">
      <ForecastDisclaimer />
      <Card>
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <CardLabel>{bank ? "Demand on your blood bank" : "Your demand"}</CardLabel>
            <p className="mt-1 text-xs text-ink-subtle">28 days of synthetic history, then the forecast.</p>
          </div>
          <Controls group={group} component={component} horizon={horizon} onGroup={setGroup} onComponent={setComponent} onHorizon={setHorizon} />
        </div>
        <div className="mt-5">
          {error ? (
            <Retry title="Forecast unavailable" message={error} onRetry={reload} />
          ) : !demand ? (
            <Skeleton className="h-56 w-full" />
          ) : (
            <div className="flex flex-col gap-4">
              <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
                <StatTile label={`Forecast, next ${demand.horizon} days`} value={Math.round(demand.forecast_total)} note="units (synthetic)" />
                <StatTile label="Forecast per day" value={demand.forecast_daily_mean.toFixed(1)} note={`vs ${demand.history_daily_mean.toFixed(1)}/day last 28 days`} />
                <StatTile
                  label="Demand signal"
                  value={<Badge tone={SIGNAL[demand.signal.status]?.tone ?? "neutral"} dot>{SIGNAL[demand.signal.status]?.label}</Badge>}
                  note="Prototype indicator, not a medical alert"
                />
                <StatTile label="Scope" value={demand.facility_name ? "Your facility" : "Network"} note={demand.facility_name ?? ""} />
              </div>
              <ForecastChart
                title={`${displayGroup(demand.blood_group)} ${FORECAST_COMPONENTS.find((c) => c.code === demand.component)?.label ?? demand.component}`}
                subtitle="Units per day"
                points={forecastTimeline(demand)}
              />
              <ModelLabel model={demand.model} />
            </div>
          )}
        </div>
      </Card>

      {summary === null ? (
        <Skeleton className="h-64 w-full" />
      ) : (
        <div className="grid gap-6 lg:grid-cols-2">
          <Card>
            <BarList
              title={`Upcoming demand by blood group, next ${summary.horizon} days`}
              subtitle={`${FORECAST_COMPONENTS.find((c) => c.code === component)?.label} · synthetic forecast`}
              data={forecastByGroup(summary.rows, component)}
              unit="units"
              emptyText="No demand forecast for this component."
            />
          </Card>
          {bank ? <SupplyVsForecast summary={summary} /> : <SignalList summary={summary} />}
        </div>
      )}
    </div>
  );
}

function SignalList({ summary }: { summary: ForecastSummary }) {
  const flagged = attentionRows(summary).filter((r) => r.signal.status !== "normal");
  return (
    <Card>
      <CardLabel>Demand signals</CardLabel>
      <p className="mt-1 text-xs text-ink-subtle">Prototype indicators from the synthetic forecast; not medical emergencies.</p>
      {flagged.length === 0 ? (
        <p className="mt-4 text-sm text-ink-muted">All blood groups and components are within their usual range.</p>
      ) : (
        <ul className="mt-3 flex flex-col divide-y divide-line">
          {flagged.map((r) => (
            <li key={`${r.blood_group}-${r.component}`} className="flex items-center justify-between gap-3 py-2 text-sm">
              <span>
                {displayGroup(r.blood_group)} · {FORECAST_COMPONENTS.find((c) => c.code === r.component)?.label}
              </span>
              <Badge tone={SIGNAL[r.signal.status]?.tone ?? "neutral"} dot>
                {SIGNAL[r.signal.status]?.label} · ×{r.signal.ratio}
              </Badge>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

/** Blood bank: REAL usable stock vs the SYNTHETIC forecast, as coverage in days. */
function SupplyVsForecast({ summary }: { summary: ForecastSummary }) {
  const rows = attentionRows(summary).slice(0, 10);
  return (
    <Card className="overflow-x-auto">
      <CardLabel>Supply vs forecast</CardLabel>
      <p className="mt-1 text-xs text-ink-subtle">Real usable stock against the synthetic forecast. Coverage = stock ÷ forecast per day.</p>
      <table className="mt-3 w-full min-w-[420px] text-sm" data-testid="supply-table">
        <thead>
          <tr className="border-b border-line text-left text-ink-subtle">
            <th scope="col" className="py-2 font-medium">Group · component</th>
            <th scope="col" className="py-2 text-right font-medium">Stock</th>
            <th scope="col" className="py-2 text-right font-medium">Forecast/day</th>
            <th scope="col" className="py-2 text-right font-medium">Coverage</th>
            <th scope="col" className="py-2 text-right font-medium">Band</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => {
            const band = PRESSURE[r.pressure ?? "ok"] ?? { label: "Covered", tone: "verified" as const };
            return (
              <tr key={`${r.blood_group}-${r.component}`} className="border-b border-line last:border-0">
                <th scope="row" className="py-1.5 text-left font-normal">
                  {displayGroup(r.blood_group)} · {r.component}
                </th>
                <td className="py-1.5 text-right tabular-nums">{r.stock_available ?? 0}</td>
                <td className="py-1.5 text-right tabular-nums">{r.forecast_daily_mean.toFixed(1)}</td>
                <td className="py-1.5 text-right tabular-nums">{r.coverage_days === null || r.coverage_days === undefined ? "—" : `${r.coverage_days} d`}</td>
                <td className="py-1.5 text-right">
                  <Badge tone={band.tone} dot>
                    {band.label}
                  </Badge>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      <p className="mt-2 text-2xs text-ink-subtle">Bands: pressure &lt; 3 days, watch &lt; 7 days (prototype thresholds).</p>
    </Card>
  );
}

/** Overview card: counts of elevated/high signals, links to the Forecast tab. */
export function ForecastOutlook({ onOpen }: { onOpen: () => void }) {
  const [summary, setSummary] = useState<ForecastSummary | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    let active = true;
    void api.GET("/api/v1/forecast/summary", { params: { query: { horizon: 7 } } }).then(({ data }) => {
      if (!active) return;
      if (data) setSummary(data);
      else setFailed(true);
    });
    return () => {
      active = false;
    };
  }, []);
  if (failed) return null;
  if (!summary) return <Skeleton className="h-24 w-full" />;
  const { elevated, high } = signalCounts(summary);
  const pressure = summary.rows.filter((r) => r.pressure === "pressure").length;
  return (
    <Card className="flex flex-wrap items-center justify-between gap-4 p-4" data-testid="forecast-outlook">
      <div>
        <CardLabel>7-day demand outlook</CardLabel>
        <p className="mt-1 text-sm">
          {high + elevated === 0 ? "Forecast demand is within the usual range." : `${high} high and ${elevated} elevated demand signals.`}
          {summary.scope === "facility" && pressure > 0 ? ` ${pressure} stock lines under pressure.` : ""}
        </p>
        <p className="mt-1 text-2xs text-ink-subtle">{FORECAST_BADGE}</p>
      </div>
      <Button size="sm" variant="secondary" onClick={onOpen}>
        Open forecast
      </Button>
    </Card>
  );
}

/** Admin: network forecast + model evaluation. */
export function AdminForecast() {
  const [summary, setSummary] = useState<ForecastSummary | null>(null);
  const [card, setCard] = useState<ModelCard | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [component, setComponent] = useState<ForecastComponent>("PRBC");
  const [version, reload] = useReload();

  useEffect(() => {
    let active = true;
    void Promise.all([
      api.GET("/api/v1/forecast/summary", { params: { query: { horizon: 7 } } }),
      api.GET("/api/v1/forecast/model"),
    ]).then(([s, m]) => {
      if (!active) return;
      if (s.data && m.data) {
        setSummary(s.data);
        setCard(m.data);
        setError(null);
      } else {
        const failed = s.data ? m : s;
        setError(toFailure(failed.error, failed.response).message);
      }
    });
    return () => {
      active = false;
    };
  }, [version]);

  if (error) return <Retry title="Network forecast unavailable" message={error} onRetry={reload} />;
  if (!summary || !card) return <Skeleton className="h-64 w-full" />;
  const { elevated, high } = signalCounts(summary);
  const evals = [
    { name: "Next day", e: card.one_step },
    { name: "7-day recursive", e: card.horizon_7 },
  ];
  return (
    <section aria-labelledby="admin-forecast" className="flex flex-col gap-4" data-testid="admin-forecast">
      <h2 id="admin-forecast" className="text-lg font-medium">
        Network demand forecast
      </h2>
      <ForecastDisclaimer text={card.disclaimer} />
      {summary.facilities_included === 0 ? (
        <EmptyState title="No hospitals yet" description="The network forecast sums hospital demand. Onboard a hospital to see it." />
      ) : (
        <div className="grid gap-6 lg:grid-cols-2">
          <Card>
            <div className="mb-3 flex items-center justify-between gap-3">
              <p className="text-xs text-ink-subtle">
                {summary.facilities_included} hospitals · {high} high · {elevated} elevated
              </p>
              <SelectInput aria-label="Component" className="h-9 w-48" value={component} onChange={(e) => setComponent(e.target.value as ForecastComponent)}>
                {FORECAST_COMPONENTS.map((c) => (
                  <option key={c.code} value={c.code}>
                    {c.label}
                  </option>
                ))}
              </SelectInput>
            </div>
            <BarList title="Network demand, next 7 days" subtitle="Sum of hospital forecasts" data={forecastByGroup(summary.rows, component)} unit="units" />
          </Card>
          <Card className="overflow-x-auto">
            <CardLabel>Model evaluation (synthetic validation period)</CardLabel>
            <p className="mt-1 text-xs text-ink-subtle">
              {card.name} v{card.version} · fingerprint <span className="font-mono">{card.fingerprint}</span> · seed {card.seed} · chronological split
            </p>
            <table className="mt-3 w-full min-w-[380px] text-sm" data-testid="model-eval">
              <thead>
                <tr className="border-b border-line text-left text-ink-subtle">
                  <th scope="col" className="py-2 font-medium">Horizon</th>
                  <th scope="col" className="py-2 font-medium">Model</th>
                  <th scope="col" className="py-2 text-right font-medium">MAE</th>
                  <th scope="col" className="py-2 text-right font-medium">RMSE</th>
                  <th scope="col" className="py-2 text-right font-medium">WAPE</th>
                </tr>
              </thead>
              <tbody>
                {evals.flatMap(({ name, e }) =>
                  (["baseline", "gbm"] as const).map((k) => (
                    <tr key={`${name}-${k}`} className="border-b border-line last:border-0">
                      <th scope="row" className="py-1.5 text-left font-normal">{k === "baseline" ? name : ""}</th>
                      <td className="py-1.5">{k === "gbm" ? "Gradient-boosted trees" : "Seasonal baseline"}</td>
                      <td className="py-1.5 text-right tabular-nums">{e[k].mae}</td>
                      <td className="py-1.5 text-right tabular-nums">{e[k].rmse}</td>
                      <td className="py-1.5 text-right tabular-nums">{(e[k].wape * 100).toFixed(1)}%</td>
                    </tr>
                  )),
                )}
              </tbody>
            </table>
            <p className="mt-2 text-2xs text-ink-subtle">Lower is better. MAPE is not reported: zero-demand days make it undefined.</p>
          </Card>
        </div>
      )}
    </section>
  );
}
