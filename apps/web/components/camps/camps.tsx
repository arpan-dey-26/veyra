"use client";

import type {
  CampDashboard,
  CampList,
  CampOut,
  CampRegistrationList,
  CampRegistrationOut,
  FacilityOut,
  MyCampRegistrations,
  PublicCampList,
  PublicCampOut,
} from "@veyra/api-client";
import Link from "next/link";
import { useState, type FormEvent } from "react";

import { PageHeader, StatTile } from "@/components/app/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardLabel } from "@/components/ui/card";
import { Field, InlineAlert, SelectInput, TextInput } from "@/components/ui/field";
import { Retry } from "@/components/ui/retry";
import { EmptyState, Skeleton } from "@/components/ui/states";
import { api } from "@/lib/api";
import { useLiveRefresh } from "@/lib/live";
import { BLOOD_GROUPS, COMPONENTS, displayGroup, formatDateTime } from "@/lib/network";
import {
  CAMP_ACTION_LABEL,
  CAMP_DISCLAIMER,
  CAMP_STATUS,
  CAMP_TOPICS,
  isoToLocal,
  localToIso,
  REGISTRATION_STATUS,
} from "@/lib/phase8";
import { toFailure, type ApiFailure } from "@/lib/problem";
import { useLoad } from "@/lib/use-load";
import { useReload } from "@/lib/use-reload";

type Action = CampOut["allowed_actions"][number];

export function CampDisclaimer() {
  return (
    <p role="note" data-testid="camp-disclaimer" className="rounded-md bg-surface-sunken px-4 py-3 text-sm text-ink-muted">
      {CAMP_DISCLAIMER}
    </p>
  );
}

export function CampStatusBadge({ status }: { status: string }) {
  const s = CAMP_STATUS[status] ?? { label: status, tone: "neutral" as const, icon: "•" };
  return (
    <Badge tone={s.tone} data-status={status}>
      <span aria-hidden>{s.icon}</span> {s.label}
    </Badge>
  );
}

function RegBadge({ status }: { status: string }) {
  const s = REGISTRATION_STATUS[status] ?? { label: status, tone: "neutral" as const };
  return (
    <Badge tone={s.tone} data-status={status}>
      {s.label}
    </Badge>
  );
}

function when(c: { starts_at: string; ends_at: string }): string {
  return `${formatDateTime(c.starts_at)} – ${formatDateTime(c.ends_at)}`;
}

// ---------------------------------------------------------------- camp form (create / edit)

interface FormValues {
  title: string;
  venue: string;
  city: string;
  state: string;
  starts_at: string;
  ends_at: string;
  capacity: string;
  description: string;
  contact_name: string;
  contact_phone: string;
  contact_email: string;
  organizer_facility_id: string;
}

function initialValues(camp?: CampOut): FormValues {
  const start = new Date(Date.now() + 3 * 86_400_000);
  start.setMinutes(0, 0, 0);
  const end = new Date(start.getTime() + 6 * 3_600_000);
  return {
    title: camp?.title ?? "",
    venue: camp?.venue ?? "",
    city: camp?.city ?? "",
    state: camp?.state ?? "West Bengal",
    starts_at: isoToLocal(camp?.starts_at ?? start.toISOString()),
    ends_at: isoToLocal(camp?.ends_at ?? end.toISOString()),
    capacity: String(camp?.capacity ?? 50),
    description: camp?.description ?? "",
    contact_name: camp?.contact_name ?? "",
    contact_phone: camp?.contact_phone ?? "",
    contact_email: camp?.contact_email ?? "",
    organizer_facility_id: camp?.organizer_facility_id ?? "",
  };
}

export function CampForm({
  camp,
  banks,
  onSaved,
  onCancel,
}: {
  camp?: CampOut;
  banks?: FacilityOut[] | null;
  onSaved: (camp: CampOut) => void;
  onCancel?: () => void;
}) {
  const [v, setV] = useState<FormValues>(() => initialValues(camp));
  const [failure, setFailure] = useState<ApiFailure | null>(null);
  const [busy, setBusy] = useState(false);
  const set = (k: keyof FormValues) => (e: { target: { value: string } }) => setV((cur) => ({ ...cur, [k]: e.target.value }));

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setFailure(null);
    const body = {
      title: v.title,
      venue: v.venue,
      city: v.city,
      state: v.state,
      starts_at: localToIso(v.starts_at),
      ends_at: localToIso(v.ends_at),
      capacity: Number(v.capacity),
      description: v.description || null,
      contact_name: v.contact_name,
      contact_phone: v.contact_phone || null,
      contact_email: v.contact_email || null,
    };
    const res = camp
      ? await api.PATCH("/api/v1/camps/{camp_id}", { params: { path: { camp_id: camp.id } }, body })
      : await api.POST("/api/v1/camps", {
          body: { ...body, organizer_facility_id: v.organizer_facility_id || null },
        });
    setBusy(false);
    if (res.data) onSaved(res.data);
    else setFailure(toFailure(res.error, res.response));
  }

  const err = (k: string) => failure?.fields[k] ?? null;
  return (
    <form onSubmit={onSubmit} noValidate className="flex flex-col gap-4" aria-label={camp ? "Edit camp" : "New camp"}>
      {failure && <InlineAlert title="Couldn't save the camp">{failure.message}</InlineAlert>}
      {banks && !camp && (
        <Field label="Organizing blood bank" error={err("organizer_facility_id")}>
          {(p) => (
            <SelectInput {...p} value={v.organizer_facility_id} onChange={set("organizer_facility_id")} required>
              <option value="">Choose a blood bank</option>
              {banks.map((b) => (
                <option key={b.id} value={b.id}>
                  {b.name}
                </option>
              ))}
            </SelectInput>
          )}
        </Field>
      )}
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Camp title" error={err("title")}>
          {(p) => <TextInput {...p} value={v.title} onChange={set("title")} required maxLength={120} />}
        </Field>
        <Field label="Venue" error={err("venue")}>
          {(p) => <TextInput {...p} value={v.venue} onChange={set("venue")} required maxLength={160} />}
        </Field>
        <Field label="City" error={err("city")}>
          {(p) => <TextInput {...p} value={v.city} onChange={set("city")} required maxLength={80} />}
        </Field>
        <Field label="State" error={err("state")}>
          {(p) => <TextInput {...p} value={v.state} onChange={set("state")} required maxLength={64} />}
        </Field>
        <Field label="Starts" error={err("starts_at")}>
          {(p) => <TextInput {...p} type="datetime-local" value={v.starts_at} onChange={set("starts_at")} required />}
        </Field>
        <Field label="Ends" error={err("ends_at")}>
          {(p) => <TextInput {...p} type="datetime-local" value={v.ends_at} onChange={set("ends_at")} required />}
        </Field>
        <Field label="Capacity (donors)" error={err("capacity")}>
          {(p) => (
            <TextInput {...p} type="number" min={1} max={5000} value={v.capacity} onChange={set("capacity")} required />
          )}
        </Field>
        <Field label="Contact name" error={err("contact_name")}>
          {(p) => <TextInput {...p} value={v.contact_name} onChange={set("contact_name")} required maxLength={80} />}
        </Field>
        <Field label="Contact phone (optional)" error={err("contact_phone")} hint="Demo contact details only">
          {(p) => <TextInput {...p} type="tel" value={v.contact_phone} onChange={set("contact_phone")} />}
        </Field>
        <Field label="Contact email (optional)" error={err("contact_email")}>
          {(p) => <TextInput {...p} type="email" value={v.contact_email} onChange={set("contact_email")} />}
        </Field>
      </div>
      <Field label="Description (optional)" error={err("description")} hint="No medical or screening details.">
        {(p) => (
          <textarea
            {...p}
            value={v.description}
            onChange={set("description")}
            maxLength={2000}
            rows={3}
            className="w-full rounded-md border border-line-strong bg-surface-raised px-3.5 py-2 text-[0.95rem] text-ink"
          />
        )}
      </Field>
      <div className="flex flex-wrap gap-2">
        <Button type="submit" disabled={busy}>
          {camp ? "Save changes" : "Create camp"}
        </Button>
        {onCancel && (
          <Button variant="ghost" onClick={onCancel}>
            Cancel
          </Button>
        )}
      </div>
    </form>
  );
}

// ---------------------------------------------------------------- management (bank / admin)

function CampRow({ camp }: { camp: CampOut }) {
  return (
    <li>
      <Link
        href={`/camps/${camp.id}`}
        className="flex flex-col gap-2 rounded-lg border border-line bg-surface-raised p-4 shadow-1 hover:border-line-strong sm:flex-row sm:items-center sm:justify-between"
      >
        <div>
          <p className="font-medium">{camp.title}</p>
          <p className="text-xs text-ink-subtle">
            {camp.code} · {camp.venue}, {camp.city} · {when(camp)}
          </p>
          <p className="text-xs text-ink-subtle">{camp.organizer_name}</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-sm text-ink-muted">
            {camp.registered_count}/{camp.capacity} registered
          </span>
          <CampStatusBadge status={camp.status} />
        </div>
      </Link>
    </li>
  );
}

export function CampManagement({ isAdmin }: { isAdmin: boolean }) {
  const [version, reload] = useReload();
  useLiveRefresh([...CAMP_TOPICS], reload);
  const dash = useLoad<CampDashboard>(() => api.GET("/api/v1/camps/dashboard"), version);
  const list = useLoad<CampList>(() => api.GET("/api/v1/camps"), version);
  const banks = useLoad<{ data: FacilityOut[] }>(
    () => api.GET("/api/v1/admin/facilities", { params: { query: { limit: 100 } } }),
    0,
    isAdmin,
  );
  const [creating, setCreating] = useState(false);
  const [filter, setFilter] = useState<"all" | "upcoming" | "active" | "done">("all");

  const header = (
    <PageHeader
      eyebrow={isAdmin ? "Network" : "Blood bank"}
      title="Donation camps"
      description="Plan camps, open registration, confirm attendance and link donations recorded at the desk."
      actions={
        !creating && (
          <Button variant="vital" onClick={() => setCreating(true)}>
            New camp
          </Button>
        )
      }
    />
  );
  const error = list.error ?? dash.error;
  if (error && !list.data) {
    return (
      <>
        {header}
        <Retry title="Camps unavailable" error={error} onRetry={reload} />
      </>
    );
  }
  const camps = list.data?.camps ?? [];
  const shown = camps.filter((c) =>
    filter === "all"
      ? true
      : filter === "upcoming"
        ? ["planned", "published", "registration_open"].includes(c.status)
        : filter === "active"
          ? c.status === "ongoing"
          : ["completed", "cancelled"].includes(c.status),
  );
  const d = dash.data;
  return (
    <div className="flex flex-col gap-6">
      {header}
      <CampDisclaimer />
      {creating && (
        <Card>
          <CardLabel>New camp</CardLabel>
          <div className="mt-4">
            <CampForm
              banks={isAdmin ? (banks.data?.data ?? []).filter((f) => f.type === "BLOOD_BANK") : null}
              onSaved={() => {
                setCreating(false);
                reload();
              }}
              onCancel={() => setCreating(false)}
            />
          </div>
        </Card>
      )}
      {d ? (
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4" data-testid="camp-dashboard">
          <StatTile label="Upcoming" value={d.upcoming} note="Planned, published or open" />
          <StatTile label="Active" value={d.active} note="Ongoing now" />
          <StatTile label="Completed" value={d.completed} note={`${d.cancelled} cancelled`} />
          <StatTile
            label="Registrations"
            value={d.total_registered}
            note={`${d.total_attended} attended · ${d.donations_recorded} donations · ${d.bags_collected} bags`}
          />
        </div>
      ) : (
        <Skeleton className="h-28 w-full" />
      )}
      <div className="flex flex-wrap gap-2" role="group" aria-label="Filter camps">
        {(["all", "upcoming", "active", "done"] as const).map((f) => (
          <Button key={f} size="sm" variant={filter === f ? "primary" : "secondary"} aria-pressed={filter === f} onClick={() => setFilter(f)}>
            {{ all: "All", upcoming: "Upcoming", active: "Active", done: "Completed / cancelled" }[f]}
          </Button>
        ))}
      </div>
      {!list.data ? (
        <Skeleton className="h-40 w-full" />
      ) : shown.length === 0 ? (
        <EmptyState
          title={camps.length === 0 ? "No camps yet" : "No camps match"}
          description={camps.length === 0 ? "Create a camp to plan a donation drive." : "Try another filter."}
        />
      ) : (
        <ul className="flex flex-col gap-3" data-testid="camp-list">
          {shown.map((c) => (
            <CampRow key={c.id} camp={c} />
          ))}
        </ul>
      )}
    </div>
  );
}

function DonationForm({ reg, onDone }: { reg: CampRegistrationOut; onDone: () => void }) {
  const [group, setGroup] = useState("O+");
  const [volume, setVolume] = useState<350 | 450>(450);
  const [components, setComponents] = useState<string[]>(["PRBC", "FFP"]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    const { data, error: err, response } = await api.POST("/api/v1/donations", {
      body: {
        donor_id: reg.donor_id,
        blood_group: group as (typeof BLOOD_GROUPS)[number],
        volume_ml: volume,
        components: components as ("WHOLE_BLOOD" | "PRBC" | "FFP" | "PLATELETS" | "CRYO")[],
        camp_registration_id: reg.id,
      },
    });
    setBusy(false);
    if (data) onDone();
    else setError(toFailure(err, response).message);
  }

  return (
    <form onSubmit={submit} className="mt-3 flex flex-col gap-3 rounded-md bg-surface-sunken p-4" aria-label={`Record donation for ${reg.donor_name}`}>
      <p className="text-xs text-ink-subtle">
        Recorded through the normal donation desk: donor verification, the donation interval and collection-time rules
        still apply. Screening and eligibility remain the staff&apos;s decision.
      </p>
      {error && <InlineAlert title="Donation not recorded">{error}</InlineAlert>}
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Blood group (typed at collection)">
          {(p) => (
            <SelectInput {...p} value={group} onChange={(e) => setGroup(e.target.value)}>
              {BLOOD_GROUPS.map((g) => (
                <option key={g} value={g}>
                  {displayGroup(g)}
                </option>
              ))}
            </SelectInput>
          )}
        </Field>
        <Field label="Volume">
          {(p) => (
            <SelectInput {...p} value={volume} onChange={(e) => setVolume(Number(e.target.value) as 350 | 450)}>
              <option value={450}>450 ml</option>
              <option value={350}>350 ml</option>
            </SelectInput>
          )}
        </Field>
      </div>
      <fieldset className="flex flex-wrap gap-3 text-sm">
        <legend className="mb-1 text-sm font-medium">Components</legend>
        {COMPONENTS.filter((c) => c.code !== "WHOLE_BLOOD").map((c) => (
          <label key={c.code} className="inline-flex items-center gap-1.5">
            <input
              type="checkbox"
              checked={components.includes(c.code)}
              onChange={(e) =>
                setComponents((cur) => (e.target.checked ? [...cur, c.code] : cur.filter((x) => x !== c.code)))
              }
            />
            {c.label}
          </label>
        ))}
      </fieldset>
      <div>
        <Button type="submit" size="sm" disabled={busy || components.length === 0}>
          Record donation
        </Button>
      </div>
    </form>
  );
}

function Registrations({ camp, version, onChange }: { camp: CampOut; version: number; onChange: () => void }) {
  const regs = useLoad<CampRegistrationList>(
    () => api.GET("/api/v1/camps/{camp_id}/registrations", { params: { path: { camp_id: camp.id } } }),
    version,
  );
  const [notice, setNotice] = useState<string | null>(null);
  const [donating, setDonating] = useState<string | null>(null);

  async function attend(r: CampRegistrationOut) {
    setNotice(null);
    const { error, response } = await api.POST("/api/v1/camps/{camp_id}/registrations/{registration_id}/attend", {
      params: { path: { camp_id: camp.id, registration_id: r.id } },
    });
    if (error) setNotice(toFailure(error, response).message);
    onChange();
  }

  if (regs.error && !regs.data) return <Retry title="Registrations unavailable" error={regs.error} onRetry={onChange} />;
  if (!regs.data) return <Skeleton className="h-32 w-full" />;
  const rows = regs.data.registrations;
  return (
    <Card>
      <CardLabel>Registrations</CardLabel>
      {notice && (
        <div className="mt-3">
          <InlineAlert>{notice}</InlineAlert>
        </div>
      )}
      {rows.length === 0 ? (
        <div className="mt-4">
          <EmptyState title="No registrations yet" description="Donors can register once registration is open." />
        </div>
      ) : (
        <ul className="mt-4 flex flex-col divide-y divide-line" data-testid="camp-registrations">
          {rows.map((r) => (
            <li key={r.id} className="py-3">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <p className="font-medium">{r.donor_name}</p>
                  <p className="text-xs text-ink-subtle">
                    {r.mobile_masked} · registered {formatDateTime(r.registered_at)}
                  </p>
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  <RegBadge status={r.status} />
                  {r.donation_id && <Badge tone="verified">Donation recorded</Badge>}
                  {camp.status === "ongoing" && r.status === "registered" && (
                    <Button size="sm" variant="secondary" onClick={() => void attend(r)}>
                      Confirm attendance
                    </Button>
                  )}
                  {camp.status === "ongoing" && r.status === "attended" && !r.donation_id && donating !== r.id && (
                    <Button size="sm" variant="secondary" onClick={() => setDonating(r.id)}>
                      Record donation
                    </Button>
                  )}
                </div>
              </div>
              {donating === r.id && (
                <DonationForm
                  reg={r}
                  onDone={() => {
                    setDonating(null);
                    onChange();
                  }}
                />
              )}
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

export function CampDetail({ campId }: { campId: string }) {
  const [version, reload] = useReload();
  useLiveRefresh([...CAMP_TOPICS], reload);
  const { data: camp, error, status } = useLoad<CampOut>(
    () => api.GET("/api/v1/camps/{camp_id}", { params: { path: { camp_id: campId } } }),
    version,
  );
  const [editing, setEditing] = useState(false);
  const [confirmCancel, setConfirmCancel] = useState(false);
  const [reason, setReason] = useState("");
  const [actionError, setActionError] = useState<string | null>(null);

  async function run(action: Action) {
    setActionError(null);
    const { error: e, response } = await api.POST("/api/v1/camps/{camp_id}/actions/{action}", {
      params: { path: { camp_id: campId, action } },
      body: action === "cancel" ? { reason: reason || null } : undefined,
    });
    if (e) setActionError(toFailure(e, response).message);
    setConfirmCancel(false);
    reload();
  }

  if (error && !camp) {
    if (status === 404 || status === 422) {
      return (
        <EmptyState
          title="Camp not found"
          description="It doesn't exist or isn't managed by your facility."
          action={
            <Link href="/camps" className="text-sm font-medium underline">
              Back to camps
            </Link>
          }
        />
      );
    }
    return <Retry title="Camp unavailable" error={error} onRetry={reload} />;
  }
  if (!camp) return <Skeleton className="h-96 w-full" />;
  const s = camp.stats;
  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        eyebrow={`Camp ${camp.code}`}
        title={camp.title}
        description={`${camp.venue}, ${camp.city}, ${camp.state} · ${when(camp)}`}
        actions={<CampStatusBadge status={camp.status} />}
      />
      <CampDisclaimer />
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4" data-testid="camp-stats">
        <StatTile label="Registered" value={`${camp.registered_count}/${camp.capacity}`} note={`${s.seats_left} seats left`} />
        <StatTile label="Attended" value={s.attended} note={`${s.no_show} did not attend · ${s.cancelled} cancelled`} />
        <StatTile label="Donations" value={s.donations_recorded} note="Recorded through the desk" />
        <StatTile label="Bags collected" value={s.bags_collected} note="From linked donations" />
      </div>
      {actionError && <InlineAlert title="Action refused">{actionError}</InlineAlert>}
      <div className="flex flex-wrap gap-2" aria-label="Camp actions">
        {camp.allowed_actions
          .filter((a) => a !== "cancel")
          .map((a) => (
            <Button key={a} variant="primary" onClick={() => void run(a)}>
              {CAMP_ACTION_LABEL[a]}
            </Button>
          ))}
        {camp.editable && !editing && (
          <Button variant="secondary" onClick={() => setEditing(true)}>
            Edit details
          </Button>
        )}
        {camp.allowed_actions.includes("cancel") && !confirmCancel && (
          <Button variant="ghost" onClick={() => setConfirmCancel(true)}>
            Cancel camp
          </Button>
        )}
      </div>
      {confirmCancel && (
        <Card>
          <CardLabel>Cancel this camp?</CardLabel>
          <p className="mt-2 text-sm text-ink-muted">Every active registration is cancelled. This can&apos;t be undone.</p>
          <div className="mt-3 flex flex-col gap-3 sm:flex-row sm:items-end">
            <Field label="Reason (optional)" className="grow">
              {(p) => <TextInput {...p} value={reason} maxLength={200} onChange={(e) => setReason(e.target.value)} />}
            </Field>
            <Button variant="vital" onClick={() => void run("cancel")}>
              Confirm cancellation
            </Button>
            <Button variant="ghost" onClick={() => setConfirmCancel(false)}>
              Keep camp
            </Button>
          </div>
        </Card>
      )}
      {editing && (
        <Card>
          <CardLabel>Edit camp</CardLabel>
          <div className="mt-4">
            <CampForm
              camp={camp}
              onSaved={() => {
                setEditing(false);
                reload();
              }}
              onCancel={() => setEditing(false)}
            />
          </div>
        </Card>
      )}
      <Card>
        <CardLabel>Details</CardLabel>
        <dl className="mt-3 grid gap-3 text-sm sm:grid-cols-2">
          <div>
            <dt className="text-ink-subtle">Organizer</dt>
            <dd>{camp.organizer_name}</dd>
          </div>
          <div>
            <dt className="text-ink-subtle">Contact</dt>
            <dd>
              {camp.contact_name}
              {camp.contact_phone && ` · ${camp.contact_phone}`}
              {camp.contact_email && ` · ${camp.contact_email}`}
            </dd>
          </div>
          {camp.description && (
            <div className="sm:col-span-2">
              <dt className="text-ink-subtle">Description</dt>
              <dd className="whitespace-pre-line">{camp.description}</dd>
            </div>
          )}
          {camp.cancel_reason && (
            <div className="sm:col-span-2">
              <dt className="text-ink-subtle">Cancellation reason</dt>
              <dd>{camp.cancel_reason}</dd>
            </div>
          )}
        </dl>
      </Card>
      <Registrations camp={camp} version={version} onChange={reload} />
    </div>
  );
}

// ---------------------------------------------------------------- donors (and read-only hospitals)

function PublicCampCard({
  camp,
  canRegister,
  onChanged,
}: {
  camp: PublicCampOut;
  canRegister: boolean;
  onChanged: () => void;
}) {
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const mine = camp.my_registration_status;

  async function act(kind: "register" | "cancel") {
    setBusy(true);
    setError(null);
    const res =
      kind === "register"
        ? await api.POST("/api/v1/camps/{camp_id}/register", { params: { path: { camp_id: camp.id } } })
        : await api.POST("/api/v1/camps/{camp_id}/register/cancel", { params: { path: { camp_id: camp.id } } });
    setBusy(false);
    if (res.error) setError(toFailure(res.error, res.response).message);
    onChanged();
  }

  const active = mine === "registered" || mine === "attended";
  return (
    <Card className="flex flex-col gap-3" data-testid="public-camp">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <Link href={`/camps/${camp.id}`} className="font-medium underline-offset-2 hover:underline">
            {camp.title}
          </Link>
          <p className="text-xs text-ink-subtle">
            {camp.venue}, {camp.city} · {when(camp)}
          </p>
          <p className="text-xs text-ink-subtle">Organized by {camp.organizer_name}</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <CampStatusBadge status={camp.status} />
          {mine && <RegBadge status={mine} />}
        </div>
      </div>
      <p className="text-sm text-ink-muted">
        {camp.seats_left > 0 ? `${camp.seats_left} of ${camp.capacity} places left` : "Full"}
      </p>
      {error && <InlineAlert>{error}</InlineAlert>}
      {canRegister && (
        <div className="flex flex-wrap gap-2">
          {camp.registration_open && !active && (
            <Button size="sm" variant="vital" disabled={busy || camp.seats_left === 0} onClick={() => void act("register")}>
              Register
            </Button>
          )}
          {mine === "registered" && camp.status !== "completed" && camp.status !== "cancelled" && (
            <Button size="sm" variant="secondary" disabled={busy} onClick={() => void act("cancel")}>
              Cancel my registration
            </Button>
          )}
        </div>
      )}
    </Card>
  );
}

export function DonorCamps({ canRegister }: { canRegister: boolean }) {
  const [version, reload] = useReload();
  const [q, setQ] = useState("");
  const [city, setCity] = useState("");
  const [applied, setApplied] = useState({ q: "", city: "" });
  const list = useLoad<PublicCampList>(
    () =>
      api.GET("/api/v1/camps/public", {
        params: { query: { ...(applied.q ? { q: applied.q } : {}), ...(applied.city ? { city: applied.city } : {}) } },
      }),
    version,
  );
  const mine = useLoad<MyCampRegistrations>(() => api.GET("/api/v1/camps/me/registrations"), version, canRegister);

  function search(e: FormEvent) {
    e.preventDefault();
    setApplied({ q: q.trim(), city: city.trim() });
    reload();
  }

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        eyebrow="Donate"
        title="Blood donation camps"
        description="Find a camp near you and reserve a place. Staff at the camp confirm your eligibility on the day."
      />
      <CampDisclaimer />
      <form onSubmit={search} className="grid gap-3 sm:grid-cols-[1fr_1fr_auto] sm:items-end" role="search" aria-label="Search camps">
        <Field label="Search">
          {(p) => <TextInput {...p} value={q} onChange={(e) => setQ(e.target.value)} placeholder="Camp, venue or code" />}
        </Field>
        <Field label="City">
          {(p) => <TextInput {...p} value={city} onChange={(e) => setCity(e.target.value)} placeholder="Any city" />}
        </Field>
        <Button type="submit" variant="secondary">
          Search
        </Button>
      </form>
      {list.error && !list.data ? (
        <Retry title="Camps unavailable" error={list.error} onRetry={reload} />
      ) : !list.data ? (
        <Skeleton className="h-40 w-full" />
      ) : list.data.camps.length === 0 ? (
        <EmptyState title="No camps found" description="No published camps match. Check back soon or clear the search." />
      ) : (
        <div className="grid gap-4 md:grid-cols-2">
          {list.data.camps.map((c) => (
            <PublicCampCard key={c.id} camp={c} canRegister={canRegister} onChanged={reload} />
          ))}
        </div>
      )}
      {canRegister && (
        <section aria-labelledby="my-regs" className="flex flex-col gap-3">
          <h2 id="my-regs" className="text-lg font-medium">
            My registrations
          </h2>
          {mine.error && !mine.data ? (
            <Retry title="Registrations unavailable" error={mine.error} onRetry={reload} />
          ) : !mine.data ? (
            <Skeleton className="h-24 w-full" />
          ) : mine.data.registrations.length === 0 ? (
            <EmptyState title="No registrations yet" description="Register for a camp and it will appear here." />
          ) : (
            <ul className="flex flex-col gap-2" data-testid="my-registrations">
              {mine.data.registrations.map((r) => (
                <li key={r.id} className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-line bg-surface-raised p-4">
                  <div>
                    <Link href={`/camps/${r.camp.id}`} className="font-medium hover:underline">
                      {r.camp.title}
                    </Link>
                    <p className="text-xs text-ink-subtle">{when(r.camp)}</p>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    <RegBadge status={r.status} />
                    {r.donation_recorded && <Badge tone="verified">Donation recorded</Badge>}
                  </div>
                </li>
              ))}
            </ul>
          )}
        </section>
      )}
    </div>
  );
}

export function PublicCampDetail({ campId, canRegister }: { campId: string; canRegister: boolean }) {
  const [version, reload] = useReload();
  const { data, error, status } = useLoad<PublicCampOut>(
    () => api.GET("/api/v1/camps/public/{camp_id}", { params: { path: { camp_id: campId } } }),
    version,
  );
  if (error && !data) {
    if (status === 404 || status === 422) {
      return (
        <EmptyState
          title="Camp not found"
          description="This camp isn't published."
          action={
            <Link href="/camps" className="text-sm font-medium underline">
              Back to camps
            </Link>
          }
        />
      );
    }
    return <Retry title="Camp unavailable" error={error} onRetry={reload} />;
  }
  if (!data) return <Skeleton className="h-64 w-full" />;
  return (
    <div className="flex flex-col gap-6">
      <PageHeader eyebrow={`Camp ${data.code}`} title={data.title} description={`${data.venue}, ${data.city}, ${data.state}`} />
      <CampDisclaimer />
      <PublicCampCard camp={data} canRegister={canRegister} onChanged={reload} />
      <Card>
        <CardLabel>About this camp</CardLabel>
        <dl className="mt-3 grid gap-3 text-sm sm:grid-cols-2">
          <div>
            <dt className="text-ink-subtle">When</dt>
            <dd>{when(data)}</dd>
          </div>
          <div>
            <dt className="text-ink-subtle">Contact</dt>
            <dd>
              {data.contact_name}
              {data.contact_phone && ` · ${data.contact_phone}`}
              {data.contact_email && ` · ${data.contact_email}`}
            </dd>
          </div>
          {data.description && (
            <div className="sm:col-span-2">
              <dt className="text-ink-subtle">Description</dt>
              <dd className="whitespace-pre-line">{data.description}</dd>
            </div>
          )}
        </dl>
      </Card>
    </div>
  );
}
