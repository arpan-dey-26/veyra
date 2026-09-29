"use client";

import type {
  CreatedInvite,
  CreateFacilityRequest,
  FacilityOut,
  RegistrationReference,
  UserOut,
} from "@veyra/api-client";
import { useCallback, useEffect, useState, type FormEvent } from "react";

import { PageHeader, StatTile } from "@/components/app/page-header";
import { AdminOverview } from "@/components/dashboard/admin-overview";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardLabel } from "@/components/ui/card";
import { Field, InlineAlert, SelectInput, Spinner, TextInput } from "@/components/ui/field";
import { SimulatedBadge } from "@/components/ui/simulated-badge";
import { EmptyState, ErrorState, Skeleton } from "@/components/ui/states";
import { api } from "@/lib/api";
import { toFailure } from "@/lib/problem";
import { isRole, ROLE_LABEL } from "@/lib/roles";

type RoleFilter = "" | "DONOR" | "HOSPITAL" | "BLOOD_BANK" | "ADMIN";

interface Snapshot {
  users: UserOut[];
  usersTotal: number;
  facilities: FacilityOut[];
  facilitiesTotal: number;
}

export function AdminDashboard() {
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [roleFilter, setRoleFilter] = useState<RoleFilter>("");
  const [states, setStates] = useState<string[]>([]);
  const [version, setVersion] = useState(0);

  useEffect(() => {
    let active = true;
    const query = roleFilter ? { role: roleFilter, limit: 50 } : { limit: 50 };
    void Promise.all([
      api.GET("/api/v1/admin/users", { params: { query } }),
      api.GET("/api/v1/admin/facilities", { params: { query: { limit: 100 } } }),
    ]).then(([users, facilities]) => {
      if (!active) return;
      if (users.data && facilities.data) {
        setSnapshot({
          users: users.data.data,
          usersTotal: users.data.meta.total,
          facilities: facilities.data.data,
          facilitiesTotal: facilities.data.meta.total,
        });
      } else {
        const failed = users.data ? facilities : users;
        setError(toFailure(failed.error, failed.response).message);
      }
    });
    return () => {
      active = false;
    };
  }, [roleFilter, version]);

  useEffect(() => {
    let active = true;
    void api.GET("/api/v1/reference/registration").then(({ data }) => {
      if (active && data) setStates((data as RegistrationReference).states);
    });
    return () => {
      active = false;
    };
  }, []);

  const refresh = useCallback(() => setVersion((v) => v + 1), []);

  if (error) return <ErrorState description={error} />;
  if (!snapshot) {
    return (
      <div aria-busy="true" className="flex flex-col gap-4">
        <Skeleton className="h-24 w-full" />
        <Skeleton className="h-72 w-full" />
      </div>
    );
  }

  const hospitals = snapshot.facilities.filter((f) => f.type === "HOSPITAL").length;
  const banks = snapshot.facilities.filter((f) => f.type === "BLOOD_BANK").length;

  return (
    <>
      <PageHeader
        eyebrow="Administration"
        title="Network overview"
        description="Network health, activity and accounts. Onboard hospitals and blood banks and invite their staff. Admins never see donor health data."
      />
      <AdminOverview />

      <h2 className="mt-10 text-lg font-medium">Accounts &amp; facilities</h2>
      <div className="mt-3 grid gap-4 sm:grid-cols-3">
        <StatTile label="Accounts" value={roleFilter ? "—" : snapshot.usersTotal} note={roleFilter ? "Filter active" : undefined} />
        <StatTile label="Hospitals" value={hospitals} />
        <StatTile label="Blood banks" value={banks} />
      </div>

      <div className="mt-8 grid gap-6 xl:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
        <FacilitiesPanel facilities={snapshot.facilities} states={states} onChanged={refresh} />
        <UsersPanel users={snapshot.users} roleFilter={roleFilter} onFilter={setRoleFilter} />
      </div>
    </>
  );
}

function UsersPanel({
  users,
  roleFilter,
  onFilter,
}: {
  users: UserOut[];
  roleFilter: RoleFilter;
  onFilter: (r: RoleFilter) => void;
}) {
  return (
    <Card className="p-0">
      <div className="flex items-center justify-between gap-3 border-b border-line px-5 py-4">
        <CardLabel>Accounts</CardLabel>
        <SelectInput
          aria-label="Filter by role"
          className="h-9 w-40 text-sm"
          value={roleFilter}
          onChange={(e) => onFilter(e.target.value as RoleFilter)}
        >
          <option value="">All roles</option>
          <option value="DONOR">Donors</option>
          <option value="HOSPITAL">Hospitals</option>
          <option value="BLOOD_BANK">Blood banks</option>
          <option value="ADMIN">Admins</option>
        </SelectInput>
      </div>
      {users.length === 0 ? (
        <div className="p-5">
          <EmptyState title="No accounts" description="No accounts match this filter yet." />
        </div>
      ) : (
        <ul className="divide-y divide-line">
          {users.map((u) => (
            <li key={u.id} className="flex items-center justify-between gap-3 px-5 py-3">
              <div className="min-w-0">
                <p className="truncate text-sm font-medium">{u.full_name}</p>
                <p className="truncate text-xs text-ink-subtle">{u.email}</p>
              </div>
              <div className="flex shrink-0 items-center gap-1.5">
                {u.is_demo && <SimulatedBadge label="Demo" subject="Seeded demo account" />}
                <Badge tone={u.status === "active" ? "verified" : "warn"} dot>
                  {u.status === "active" ? "Active" : "Pending"}
                </Badge>
                <Badge>{isRole(u.role) ? ROLE_LABEL[u.role] : u.role}</Badge>
              </div>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

const EMPTY_FACILITY: CreateFacilityRequest = {
  type: "HOSPITAL",
  name: "",
  registration_number: "",
  address: "",
  city: "",
  state: "",
  pin_code: "",
};

function FacilitiesPanel({
  facilities,
  states,
  onChanged,
}: {
  facilities: FacilityOut[];
  states: string[];
  onChanged: () => void;
}) {
  const [creating, setCreating] = useState(false);
  const [inviteFor, setInviteFor] = useState<FacilityOut | null>(null);

  return (
    <Card className="p-0">
      <div className="flex items-center justify-between border-b border-line px-5 py-4">
        <CardLabel>Facilities</CardLabel>
        {!creating && (
          <Button size="sm" onClick={() => setCreating(true)}>
            Onboard facility
          </Button>
        )}
      </div>
      {creating && (
        <div className="border-b border-line bg-surface-sunken/60 px-5 py-5">
          <CreateFacilityForm
            states={states}
            onCancel={() => setCreating(false)}
            onCreated={() => {
              setCreating(false);
              onChanged();
            }}
          />
        </div>
      )}
      {facilities.length === 0 ? (
        <div className="p-5">
          <EmptyState
            title="No facilities yet"
            description="Onboard the first hospital or blood bank, then invite its staff."
          />
        </div>
      ) : (
        <ul className="divide-y divide-line">
          {facilities.map((f) => (
            <li key={f.id} className="px-5 py-4">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <p className="font-medium">{f.name}</p>
                  <p className="text-xs text-ink-subtle">
                    {f.type === "HOSPITAL" ? "Hospital" : "Blood bank"} · {f.city}, {f.state}
                    {f.registration_number ? ` · ${f.registration_number}` : ""}
                  </p>
                </div>
                <Button size="sm" variant="secondary" onClick={() => setInviteFor(f)}>
                  Invite staff
                </Button>
              </div>
              {inviteFor?.id === f.id && (
                <InvitePanel facility={f} onClose={() => setInviteFor(null)} />
              )}
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

function CreateFacilityForm({
  states,
  onCancel,
  onCreated,
}: {
  states: string[];
  onCancel: () => void;
  onCreated: () => void;
}) {
  const [values, setValues] = useState<CreateFacilityRequest>(EMPTY_FACILITY);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const set = (field: keyof CreateFacilityRequest, value: string) =>
    setValues((v) => ({ ...v, [field]: value }));

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSaving(true);
    setFormError(null);
    try {
      const body = { ...values, registration_number: values.registration_number || null };
      const { data, error, response } = await api.POST("/api/v1/admin/facilities", { body });
      if (data) {
        onCreated();
        return;
      }
      const failure = toFailure(error, response);
      setErrors(failure.fields);
      setFormError(failure.message);
    } catch {
      setFormError(toFailure(undefined).message);
    } finally {
      setSaving(false);
    }
  }

  const text = (field: keyof CreateFacilityRequest, label: string) => (
    <Field label={label} error={errors[field]}>
      {(p) => (
        <TextInput
          {...p}
          value={(values[field] as string | null | undefined) ?? ""}
          onChange={(e) => set(field, e.target.value)}
        />
      )}
    </Field>
  );

  return (
    <form onSubmit={onSubmit} noValidate className="flex flex-col gap-4">
      <div className="grid gap-4 sm:grid-cols-[10rem_1fr]">
        <Field label="Type" error={errors.type}>
          {(p) => (
            <SelectInput {...p} value={values.type} onChange={(e) => set("type", e.target.value)}>
              <option value="HOSPITAL">Hospital</option>
              <option value="BLOOD_BANK">Blood bank</option>
            </SelectInput>
          )}
        </Field>
        {text("name", "Name")}
      </div>
      <div className="grid gap-4 sm:grid-cols-2">
        {text("registration_number", "Registration no. (optional)")}
        {text("address", "Address")}
      </div>
      <div className="grid gap-4 sm:grid-cols-[1fr_1fr_8rem]">
        {text("city", "City")}
        <Field label="State / UT" error={errors.state}>
          {(p) => (
            <SelectInput {...p} value={values.state} onChange={(e) => set("state", e.target.value)}>
              <option value="">Select…</option>
              {states.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </SelectInput>
          )}
        </Field>
        {text("pin_code", "PIN code")}
      </div>
      {formError && <InlineAlert>{formError}</InlineAlert>}
      <div className="flex gap-2">
        <Button type="submit" disabled={saving}>
          {saving && <Spinner />}
          {saving ? "Saving…" : "Create facility"}
        </Button>
        <Button variant="ghost" onClick={onCancel} disabled={saving}>
          Cancel
        </Button>
      </div>
    </form>
  );
}

function InvitePanel({ facility, onClose }: { facility: FacilityOut; onClose: () => void }) {
  const [email, setEmail] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [created, setCreated] = useState<CreatedInvite | null>(null);
  const [saving, setSaving] = useState(false);
  const [copied, setCopied] = useState(false);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSaving(true);
    setError(null);
    try {
      const { data, error: apiError, response } = await api.POST(
        "/api/v1/admin/facilities/{facility_id}/invites",
        { params: { path: { facility_id: facility.id } }, body: { email } },
      );
      if (data) setCreated(data);
      else {
        const failure = toFailure(apiError, response);
        setError(failure.fields.email ?? failure.message);
      }
    } catch {
      setError(toFailure(undefined).message);
    } finally {
      setSaving(false);
    }
  }

  if (created) {
    const link =
      typeof window === "undefined" ? created.accept_path : `${window.location.origin}${created.accept_path}`;
    return (
      <div className="veyra-rise mt-4 flex flex-col gap-3 rounded-md border border-line bg-surface p-4">
        <div className="flex items-center gap-2">
          <SimulatedBadge label="Demo" subject="Invitation delivery" />
          <p className="text-xs text-ink-muted">{created.delivery.note}</p>
        </div>
        <p className="text-sm">
          Invitation for <span className="font-medium">{created.email}</span>
        </p>
        <div className="flex gap-2">
          <TextInput readOnly value={link} aria-label="One-time invitation link" className="font-mono text-xs" />
          <Button
            variant="secondary"
            onClick={async () => {
              try {
                await navigator.clipboard.writeText(link);
                setCopied(true);
              } catch {
                setCopied(false);
              }
            }}
          >
            {copied ? "Copied" : "Copy"}
          </Button>
        </div>
        <Button size="sm" variant="ghost" className="self-start" onClick={onClose}>
          Done
        </Button>
      </div>
    );
  }

  return (
    <form onSubmit={onSubmit} noValidate className="veyra-rise mt-4 flex flex-col gap-3 sm:flex-row sm:items-start">
      <div className="flex-1">
        <Field label={`Staff email for ${facility.name}`} error={error}>
          {(p) => (
            <TextInput
              {...p}
              type="email"
              autoFocus
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
          )}
        </Field>
      </div>
      <div className="flex gap-2 sm:pt-7">
        <Button type="submit" size="md" disabled={saving || !email}>
          {saving && <Spinner />}
          Create invite
        </Button>
        <Button variant="ghost" onClick={onClose}>
          Cancel
        </Button>
      </div>
    </form>
  );
}
