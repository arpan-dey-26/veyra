"use client";

import type {
  BloodComponent,
  BloodGroup,
  DonationOut,
  DonorLookupResult,
} from "@veyra/api-client";
import Link from "next/link";
import { useEffect, useState, type FormEvent } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardLabel } from "@/components/ui/card";
import { Field, InlineAlert, SelectInput, Spinner, TextInput } from "@/components/ui/field";
import { EmptyState, Skeleton } from "@/components/ui/states";
import { api } from "@/lib/api";
import { cn } from "@/lib/cn";
import {
  BLOOD_GROUPS,
  COMPONENTS,
  componentLabel,
  displayGroup,
  formatDate,
  formatDateTime,
} from "@/lib/network";
import { toFailure } from "@/lib/problem";
import { useReload } from "@/lib/use-reload";

const SEPARATED: BloodComponent[] = ["PRBC", "FFP", "PLATELETS", "CRYO"];

/** Blood-bank desk: find a verified donor, record the collection, print bag labels. */
export function DonationDesk() {
  const [mobile, setMobile] = useState("");
  const [donor, setDonor] = useState<DonorLookupResult | null>(null);
  const [lookupError, setLookupError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [recent, setRecent] = useState<DonationOut[] | null>(null);
  const [created, setCreated] = useState<DonationOut | null>(null);

  const [version, reloadRecent] = useReload();

  useEffect(() => {
    let active = true;
    void api.GET("/api/v1/donations", { params: { query: { limit: 10 } } }).then(({ data }) => {
      if (active && data) setRecent(data.data);
    });
    return () => {
      active = false;
    };
  }, [version]);

  async function onLookup(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setLookupError(null);
    setDonor(null);
    setCreated(null);
    const { data, error, response } = await api.POST("/api/v1/donors/lookup", { body: { mobile } });
    setBusy(false);
    if (data) setDonor(data);
    else setLookupError(toFailure(error, response).message);
  }

  return (
    <div className="grid gap-6 lg:grid-cols-[minmax(0,5fr)_minmax(0,4fr)]">
      <div className="flex flex-col gap-6">
        <Card>
          <form onSubmit={onLookup} className="flex flex-col gap-4 sm:flex-row sm:items-end" noValidate>
            <Field label="Donor's mobile number" hint="Verified VEYRA donors only" className="flex-1">
              {(p) => (
                <TextInput
                  {...p}
                  inputMode="tel"
                  autoComplete="off"
                  placeholder="98765 43210"
                  value={mobile}
                  onChange={(e) => setMobile(e.target.value)}
                />
              )}
            </Field>
            <Button type="submit" disabled={busy || mobile.trim().length < 10}>
              {busy && <Spinner />}Find donor
            </Button>
          </form>
          {lookupError && (
            <div className="mt-4">
              <InlineAlert>{lookupError}</InlineAlert>
            </div>
          )}
        </Card>
        {donor && !created && (
          <RecordDonationForm
            donor={donor}
            onRecorded={(d) => {
              setCreated(d);
              reloadRecent();
            }}
          />
        )}
        {created && <BagLabels donation={created} onNext={() => { setCreated(null); setDonor(null); setMobile(""); }} />}
      </div>

      <section aria-labelledby="recent-heading" className="flex flex-col gap-3">
        <h2 id="recent-heading" className="text-lg font-medium">
          Recent donations
        </h2>
        {recent === null ? (
          <Skeleton className="h-40" />
        ) : recent.length === 0 ? (
          <EmptyState title="No donations yet" description="Recorded collections and their bags appear here." />
        ) : (
          <ul className="flex flex-col gap-3">
            {recent.map((d) => (
              <li key={d.id}>
                <Card className="p-4">
                  <div className="flex items-baseline justify-between gap-3">
                    <p className="font-medium">{d.donor_name}</p>
                    <span className="font-display text-lg text-vital">{displayGroup(d.blood_group)}</span>
                  </div>
                  <p className="text-xs text-ink-subtle">
                    {formatDateTime(d.collected_at)} · {d.volume_ml} ml
                  </p>
                  <div className="mt-2 flex flex-wrap gap-2">
                    {d.bags.map((b) => (
                      <Link key={b.id} href={`/bags/${b.public_id}`} className="font-mono text-xs underline-offset-4 hover:underline">
                        {b.public_id} · {componentLabel(b.component)}
                      </Link>
                    ))}
                  </div>
                </Card>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}

function RecordDonationForm({
  donor,
  onRecorded,
}: {
  donor: DonorLookupResult;
  onRecorded: (d: DonationOut) => void;
}) {
  const [group, setGroup] = useState<BloodGroup>(donor.blood_group as BloodGroup);
  const [volume, setVolume] = useState<350 | 450>(450);
  const [mode, setMode] = useState<"whole" | "separated">("separated");
  const [components, setComponents] = useState<BloodComponent[]>(["PRBC", "FFP"]);
  const [notes, setNotes] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const chosen: BloodComponent[] = mode === "whole" ? ["WHOLE_BLOOD"] : components;

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    const { data, error: apiError, response } = await api.POST("/api/v1/donations", {
      body: {
        donor_id: donor.donor_id,
        blood_group: group,
        volume_ml: volume,
        components: chosen,
        notes: notes.trim() || null,
      },
    });
    setBusy(false);
    if (data) onRecorded(data);
    else setError(toFailure(apiError, response).message);
  }

  return (
    <Card>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <CardLabel>Donor</CardLabel>
          <p className="mt-1 text-lg font-medium">{donor.full_name}</p>
          <p className="font-mono text-xs text-ink-subtle">{donor.mobile_masked}</p>
        </div>
        <div className="flex flex-col items-end gap-1.5">
          <Badge tone={donor.blood_group_status === "confirmed" ? "verified" : "neutral"}>
            {displayGroup(donor.blood_group)} ·{" "}
            {donor.blood_group_status === "confirmed" ? "confirmed" : "self-declared"}
          </Badge>
          {donor.eligible_now ? (
            <Badge tone="verified" dot>Eligible to donate</Badge>
          ) : (
            <Badge tone="warn" dot>
              Eligible from {donor.eligible_from ? formatDate(donor.eligible_from) : "later"}
            </Badge>
          )}
        </div>
      </div>

      {!donor.eligible_now ? (
        <div className="mt-5">
          <InlineAlert tone="info" title="Not eligible yet">
            The last donation was on {donor.last_donation_at ? formatDate(donor.last_donation_at) : "record"}. VEYRA
            enforces the minimum interval between whole-blood donations.
          </InlineAlert>
        </div>
      ) : (
        <form onSubmit={onSubmit} className="mt-6 flex flex-col gap-5" noValidate>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Blood group (typed at collection)" hint="This confirms or corrects the donor's self-declared group">
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
            <Field label="Volume collected">
              {(p) => (
                <SelectInput {...p} value={volume} onChange={(e) => setVolume(Number(e.target.value) as 350 | 450)}>
                  <option value={450}>450 ml</option>
                  <option value={350}>350 ml</option>
                </SelectInput>
              )}
            </Field>
          </div>

          <fieldset className="flex flex-col gap-3">
            <legend className="mb-2 text-sm font-medium">Processing</legend>
            <div className="flex gap-2" role="radiogroup">
              {(["separated", "whole"] as const).map((m) => (
                <button
                  key={m}
                  type="button"
                  role="radio"
                  aria-checked={mode === m}
                  onClick={() => setMode(m)}
                  className={cn(
                    "rounded-pill border px-4 py-1.5 text-sm",
                    mode === m ? "border-ink bg-ink text-surface" : "border-line-strong text-ink-muted",
                  )}
                >
                  {m === "whole" ? "Whole blood" : "Component separation"}
                </button>
              ))}
            </div>
            {mode === "separated" && (
              <div className="flex flex-wrap gap-2">
                {SEPARATED.map((c) => {
                  const on = components.includes(c);
                  return (
                    <label
                      key={c}
                      className={cn(
                        "flex cursor-pointer items-center gap-2 rounded-md border px-3 py-2 text-sm",
                        on ? "border-vital bg-vital-soft text-vital" : "border-line-strong",
                      )}
                    >
                      <input
                        type="checkbox"
                        className="accent-(--color-vital)"
                        checked={on}
                        onChange={() =>
                          setComponents((cur) => (on ? cur.filter((x) => x !== c) : [...cur, c]))
                        }
                      />
                      {COMPONENTS.find((x) => x.code === c)?.label}
                    </label>
                  );
                })}
              </div>
            )}
          </fieldset>

          <Field label="Notes (optional)" hint="No medical details: they are not needed here">
            {(p) => <TextInput {...p} maxLength={500} value={notes} onChange={(e) => setNotes(e.target.value)} />}
          </Field>

          {error && <InlineAlert>{error}</InlineAlert>}
          <div>
            <Button type="submit" variant="vital" disabled={busy || chosen.length === 0}>
              {busy && <Spinner />}Record donation · {chosen.length} bag{chosen.length === 1 ? "" : "s"}
            </Button>
          </div>
        </form>
      )}
    </Card>
  );
}

function BagLabels({ donation, onNext }: { donation: DonationOut; onNext: () => void }) {
  return (
    <Card>
      <InlineAlert tone="success" title="Donation recorded">
        {donation.bags.length} labelled bag{donation.bags.length === 1 ? " is" : "s are"} now in your inventory.
      </InlineAlert>
      <ul className="mt-5 grid gap-3 sm:grid-cols-2">
        {donation.bags.map((b) => (
          <li key={b.id} className="rounded-md border border-dashed border-line-strong p-4">
            <p className="text-2xs font-semibold tracking-(--tracking-label) text-ink-subtle uppercase">
              {componentLabel(b.component)} · {b.volume_ml} ml
            </p>
            <p className="mt-1 font-mono text-lg tracking-wider">{b.public_id}</p>
            <p className="mt-1 text-xs text-ink-muted">
              {displayGroup(b.blood_group)} · expires {formatDate(b.expires_at)}
            </p>
            <p className="mt-2 font-mono text-2xs text-ink-subtle" title="Encoded in the bag's QR label">
              QR: {b.qr_payload}
            </p>
          </li>
        ))}
      </ul>
      <div className="mt-5">
        <Button variant="secondary" onClick={onNext}>
          Next donor
        </Button>
      </div>
    </Card>
  );
}
