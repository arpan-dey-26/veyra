"use client";

import type { BloodGroup, CompatibilityCheck, CompatibilityMatrix } from "@veyra/api-client";
import { useEffect, useRef, useState } from "react";

import { PageHeader } from "@/components/app/page-header";
import { Badge } from "@/components/ui/badge";
import { Card, CardLabel } from "@/components/ui/card";
import { Field, SelectInput, TextInput } from "@/components/ui/field";
import { Retry } from "@/components/ui/retry";
import { EmptyState, Skeleton } from "@/components/ui/states";
import { api } from "@/lib/api";
import { displayGroup } from "@/lib/network";
import { COMPATIBILITY_DISCLAIMER } from "@/lib/phase8";
import { toFailure } from "@/lib/problem";
import { useLoad } from "@/lib/use-load";
import { useReload } from "@/lib/use-reload";

type Code = CompatibilityCheck["component"];

export function CompatibilityDisclaimer() {
  return (
    <div role="note" data-testid="compatibility-disclaimer" className="rounded-md bg-warn-soft px-4 py-3 text-sm text-warn">
      <p className="font-medium">{COMPATIBILITY_DISCLAIMER}</p>
      <p className="mt-1 text-xs">
        Simplified ABO/Rh reference for a student prototype. It never approves, allocates or dispatches blood; the
        existing human-confirmed workflow stays mandatory.
      </p>
    </div>
  );
}

function Verdict({ ok }: { ok: boolean }) {
  return ok ? (
    <Badge tone="verified" data-result="compatible">
      <span aria-hidden>✓</span> Compatible
    </Badge>
  ) : (
    <Badge tone="critical" data-result="not_compatible">
      <span aria-hidden>✕</span> Not compatible
    </Badge>
  );
}

/** One donor/recipient/component answer, always from the API (rules live in the backend). */
function Checker({ groups, components }: { groups: string[]; components: { code: Code; label: string }[] }) {
  const [donor, setDonor] = useState("O-");
  const [recipient, setRecipient] = useState("A+");
  const [component, setComponent] = useState<Code>("PRBC");
  const [result, setResult] = useState<CompatibilityCheck | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [version, reload] = useReload();
  const query = useRef({ donor, recipient, component });
  useEffect(() => {
    query.current = { donor, recipient, component };
  });
  useEffect(() => {
    let active = true;
    const q = query.current;
    void api
      .GET("/api/v1/compatibility/check", {
        params: {
          query: {
            donor_group: q.donor as BloodGroup,
            recipient_group: q.recipient as BloodGroup,
            component: q.component,
          },
        },
      })
      .then(({ data, error: e, response }) => {
        if (!active) return;
        if (data) {
          setResult(data);
          setError(null);
        } else setError(toFailure(e, response).message);
      });
    return () => {
      active = false;
    };
  }, [donor, recipient, component, version]);

  return (
    <Card>
      <CardLabel>Check a pair</CardLabel>
      <div className="mt-4 grid gap-4 sm:grid-cols-3">
        <Field label="Donor blood group">
          {(p) => (
            <SelectInput {...p} value={donor} onChange={(e) => setDonor(e.target.value)}>
              {groups.map((g) => (
                <option key={g} value={g}>
                  {displayGroup(g)}
                </option>
              ))}
            </SelectInput>
          )}
        </Field>
        <Field label="Recipient blood group">
          {(p) => (
            <SelectInput {...p} value={recipient} onChange={(e) => setRecipient(e.target.value)}>
              {groups.map((g) => (
                <option key={g} value={g}>
                  {displayGroup(g)}
                </option>
              ))}
            </SelectInput>
          )}
        </Field>
        <Field label="Component">
          {(p) => (
            <SelectInput {...p} value={component} onChange={(e) => setComponent(e.target.value as Code)}>
              {components.map((c) => (
                <option key={c.code} value={c.code}>
                  {c.label}
                </option>
              ))}
            </SelectInput>
          )}
        </Field>
      </div>
      <div className="mt-5" aria-live="polite" data-testid="compatibility-result">
        {error ? (
          <Retry title="Check unavailable" error={error} onRetry={reload} />
        ) : !result ? (
          <Skeleton className="h-16 w-full" />
        ) : (
          <div className="flex flex-col gap-2">
            <div className="flex flex-wrap items-center gap-3">
              <span className="font-display text-xl">
                {displayGroup(result.donor_group)} → {displayGroup(result.recipient_group)}
              </span>
              <span className="text-sm text-ink-muted">{result.component_label}</span>
              <Verdict ok={result.compatible} />
            </div>
            <p className="text-sm text-ink-muted">{result.reason}</p>
            <p className="text-xs text-ink-subtle">{result.rule}</p>
            <p className="text-xs text-ink-subtle">Requires authorized clinical confirmation.</p>
          </div>
        )}
      </div>
    </Card>
  );
}

export function CompatibilityPage() {
  const [version, reload] = useReload();
  const { data, error } = useLoad<CompatibilityMatrix>(() => api.GET("/api/v1/compatibility/matrix"), version);
  const [component, setComponent] = useState<string>("PRBC");
  const [filter, setFilter] = useState("");
  const [onlyCompatible, setOnlyCompatible] = useState(false);

  const header = (
    <PageHeader
      eyebrow="Reference"
      title="Blood compatibility"
      description="ABO/Rh donor → recipient reference for the supported blood components."
    />
  );
  if (error && !data) {
    return (
      <>
        {header}
        <Retry title="Compatibility reference unavailable" error={error} onRetry={reload} />
      </>
    );
  }
  if (!data) {
    return (
      <>
        {header}
        <Skeleton className="h-96 w-full" />
      </>
    );
  }
  const comps = data.components.map((c) => ({ code: c.component, label: c.label }));
  const matrix = data.components.find((c) => c.component === component) ?? data.components[0];
  const needle = filter.trim().toUpperCase().replace("−", "-");
  const rows = (matrix?.rows ?? []).filter((r) => !needle || r.recipient_group.includes(needle));

  return (
    <div className="flex flex-col gap-6">
      {header}
      <CompatibilityDisclaimer />
      <Checker groups={data.blood_groups} components={comps} />
      <Card>
        <div className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <CardLabel>Matrix</CardLabel>
            {matrix && <p className="mt-1 max-w-prose text-sm text-ink-muted">{matrix.rule}</p>}
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="Component">
              {(p) => (
                <SelectInput {...p} value={component} onChange={(e) => setComponent(e.target.value)}>
                  {comps.map((c) => (
                    <option key={c.code} value={c.code}>
                      {c.label}
                    </option>
                  ))}
                </SelectInput>
              )}
            </Field>
            <Field label="Filter recipient group" hint="e.g. AB or O-">
              {(p) => <TextInput {...p} value={filter} onChange={(e) => setFilter(e.target.value)} placeholder="All groups" />}
            </Field>
          </div>
        </div>
        <label className="mt-4 inline-flex items-center gap-2 text-sm">
          <input type="checkbox" checked={onlyCompatible} onChange={(e) => setOnlyCompatible(e.target.checked)} />
          Show compatible donors only
        </label>
        {rows.length === 0 ? (
          <div className="mt-5">
            <EmptyState title="No matching groups" description="Clear the filter to see all eight ABO/Rh groups." />
          </div>
        ) : onlyCompatible ? (
          <ul className="mt-5 flex flex-col divide-y divide-line" data-testid="compatibility-list">
            {rows.map((r) => (
              <li key={r.recipient_group} className="flex flex-wrap items-center gap-3 py-2">
                <span className="w-24 font-medium">Recipient {displayGroup(r.recipient_group)}</span>
                <span className="text-sm text-ink-muted">
                  {r.compatible_donors.length ? r.compatible_donors.map(displayGroup).join(", ") : "None"}
                </span>
              </li>
            ))}
          </ul>
        ) : (
          <div className="mt-5 overflow-x-auto">
            <table className="w-full min-w-[36rem] border-collapse text-sm" data-testid="compatibility-matrix">
              <caption className="sr-only">
                {matrix?.label} compatibility: rows are recipient groups, columns donor groups
              </caption>
              <thead>
                <tr>
                  <th scope="col" className="p-2 text-left text-xs text-ink-subtle">
                    Recipient ↓ / Donor →
                  </th>
                  {data.blood_groups.map((g) => (
                    <th key={g} scope="col" className="p-2 text-center font-medium">
                      {displayGroup(g)}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.recipient_group} className="border-t border-line">
                    <th scope="row" className="p-2 text-left font-medium">
                      {displayGroup(r.recipient_group)}
                    </th>
                    {data.blood_groups.map((d) => {
                      const ok = r.compatible_donors.includes(d);
                      return (
                        <td
                          key={d}
                          className={ok ? "bg-verified-soft p-2 text-center text-verified" : "p-2 text-center text-ink-subtle"}
                          aria-label={`Donor ${d} to recipient ${r.recipient_group}: ${ok ? "compatible" : "not compatible"}`}
                        >
                          <span aria-hidden>{ok ? "✓" : "·"}</span>
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <p className="mt-4 text-xs text-ink-subtle">{data.label}</p>
      </Card>
    </div>
  );
}
