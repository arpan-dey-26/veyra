"use client";

import type {
  AvailabilityItem,
  AvailabilityResponse,
  BloodComponent,
  BloodGroup,
  BloodRequestOut,
} from "@veyra/api-client";
import { useRef, useState, type FormEvent } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardLabel } from "@/components/ui/card";
import { Field, InlineAlert, SelectInput, Spinner, TextInput } from "@/components/ui/field";
import { SimulatedBadge } from "@/components/ui/simulated-badge";
import { EmptyState } from "@/components/ui/states";
import { api } from "@/lib/api";
import { cn } from "@/lib/cn";
import { BLOOD_GROUPS, COMPONENTS, displayGroup, newIdempotencyKey } from "@/lib/network";
import { toFailure } from "@/lib/problem";

type Urgency = "routine" | "urgent" | "emergency";

const BAND = {
  sufficient: { label: "Can cover this request", tone: "verified" },
  limited: { label: "Limited stock", tone: "warn" },
  none: { label: "No stock", tone: "neutral" },
} as const;

function defaultNeededBy(): string {
  const d = new Date(Date.now() + 6 * 3_600_000);
  d.setMinutes(0, 0, 0);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

/** Hospital: search the network (banded availability), then send a request to one bank. */
export function NewRequest({ onCreated }: { onCreated: (r: BloodRequestOut) => void }) {
  const [group, setGroup] = useState<BloodGroup>("O+");
  const [component, setComponent] = useState<BloodComponent>("PRBC");
  const [units, setUnits] = useState(2);
  const [urgency, setUrgency] = useState<Urgency>("urgent");
  const [neededBy, setNeededBy] = useState(defaultNeededBy);
  const [notes, setNotes] = useState("");
  const [results, setResults] = useState<AvailabilityResponse | null>(null);
  const [target, setTarget] = useState<AvailabilityItem | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<"search" | "send" | null>(null);
  const attemptKey = useRef<string | null>(null);

  async function search(e: FormEvent) {
    e.preventDefault();
    setBusy("search");
    setError(null);
    setTarget(null);
    attemptKey.current = null;
    const { data, error: apiError, response } = await api.GET("/api/v1/network/availability", {
      params: { query: { blood_group: group, component, units } },
    });
    setBusy(null);
    if (data) setResults(data);
    else setError(toFailure(apiError, response).message);
  }

  async function send() {
    if (!target) return;
    setBusy("send");
    setError(null);
    // Same key for retries of this attempt: a double click or a flaky network never
    // creates two requests.
    attemptKey.current ??= newIdempotencyKey();
    const { data, error: apiError, response } = await api.POST("/api/v1/requests", {
      params: { header: { "Idempotency-Key": attemptKey.current } },
      body: {
        provider: target.provider === "mock" ? "mock" : "internal",
        target_ref: target.target_ref,
        blood_group: group,
        component,
        units,
        urgency,
        needed_by: new Date(neededBy).toISOString(),
        notes: notes.trim() || null,
      },
    });
    setBusy(null);
    if (data) {
      attemptKey.current = null;
      setResults(null);
      setTarget(null);
      setNotes("");
      onCreated(data);
    } else {
      setError(toFailure(apiError, response).message);
    }
  }

  return (
    <div className="flex flex-col gap-6">
      <Card>
        <form onSubmit={search} className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4" noValidate>
          <Field label="Blood group">
            {(p) => (
              <SelectInput {...p} value={group} onChange={(e) => setGroup(e.target.value as BloodGroup)}>
                {BLOOD_GROUPS.map((g) => (
                  <option key={g} value={g}>
                    {displayGroup(g)}
                  </option>
                ))}
              </SelectInput>
            )}
          </Field>
          <Field label="Component">
            {(p) => (
              <SelectInput {...p} value={component} onChange={(e) => setComponent(e.target.value as BloodComponent)}>
                {COMPONENTS.map((c) => (
                  <option key={c.code} value={c.code}>
                    {c.label}
                  </option>
                ))}
              </SelectInput>
            )}
          </Field>
          <Field label="Units" hint="1–20">
            {(p) => (
              <TextInput
                {...p}
                type="number"
                min={1}
                max={20}
                value={units}
                onChange={(e) => setUnits(Math.max(1, Math.min(20, Number(e.target.value) || 1)))}
              />
            )}
          </Field>
          <Field label="Urgency">
            {(p) => (
              <SelectInput {...p} value={urgency} onChange={(e) => setUrgency(e.target.value as Urgency)}>
                <option value="routine">Routine</option>
                <option value="urgent">Urgent</option>
                <option value="emergency">Emergency</option>
              </SelectInput>
            )}
          </Field>
          <div className="flex items-end sm:col-span-2 lg:col-span-4">
            <Button type="submit" disabled={busy !== null}>
              {busy === "search" && <Spinner />}Find blood banks
            </Button>
          </div>
        </form>
      </Card>

      {error && <InlineAlert>{error}</InlineAlert>}

      {results && (
        <section aria-labelledby="availability-heading" className="flex flex-col gap-3">
          <div>
            <h2 id="availability-heading" className="text-lg font-medium">
              Availability for {results.units} × {displayGroup(results.blood_group)}
            </h2>
            <p className="text-xs text-ink-subtle">
              Shown as bands: VEYRA never discloses another facility&apos;s exact stock.
            </p>
          </div>
          {results.results.length === 0 ? (
            <EmptyState title="No blood banks found" description="No onboarded blood bank matches yet." />
          ) : (
            <ul className="grid gap-3 md:grid-cols-2" role="radiogroup" aria-label="Choose a blood bank">
              {results.results.map((r) => {
                const band = BAND[r.band];
                const selected = target?.target_ref === r.target_ref && target.provider === r.provider;
                return (
                  <li key={`${r.provider}:${r.target_ref}`}>
                    <button
                      type="button"
                      role="radio"
                      aria-checked={selected}
                      disabled={r.band === "none"}
                      onClick={() => setTarget(r)}
                      className={cn(
                        "flex w-full flex-col gap-2 rounded-lg border bg-surface-raised p-4 text-left shadow-1",
                        "disabled:cursor-not-allowed disabled:opacity-55",
                        selected ? "border-ink ring-2 ring-ink/10" : "border-line hover:border-line-strong",
                      )}
                    >
                      <span className="flex flex-wrap items-center justify-between gap-2">
                        <span className="font-medium">{r.name}</span>
                        {r.source.simulated && <SimulatedBadge subject="Blood bank" />}
                      </span>
                      <span className="text-xs text-ink-subtle">
                        {r.city}, {r.state}
                      </span>
                      <Badge tone={band.tone} dot className="self-start">
                        {band.label}
                      </Badge>
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
        </section>
      )}

      {target && (
        <Card>
          <CardLabel>Send request to {target.name}</CardLabel>
          {target.source.simulated && (
            <div className="mt-3">
              <InlineAlert tone="demo" title="Simulated partner blood bank">
                {target.source.note ?? "No real blood bank is contacted."} The request is acknowledged
                automatically and no blood is dispatched.
              </InlineAlert>
            </div>
          )}
          <div className="mt-4 grid gap-4 sm:grid-cols-2">
            <Field label="Needed by">
              {(p) => (
                <TextInput {...p} type="datetime-local" value={neededBy} onChange={(e) => setNeededBy(e.target.value)} />
              )}
            </Field>
            <Field label="Note for the blood bank (optional)" hint="No patient identifiers">
              {(p) => <TextInput {...p} maxLength={500} value={notes} onChange={(e) => setNotes(e.target.value)} />}
            </Field>
          </div>
          <div className="mt-5">
            <Button variant="vital" onClick={() => void send()} disabled={busy !== null}>
              {busy === "send" && <Spinner />}Send request
            </Button>
          </div>
        </Card>
      )}
    </div>
  );
}
