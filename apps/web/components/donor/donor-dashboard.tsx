"use client";

import type { DonorProfile, RegistrationReference } from "@veyra/api-client";
import { useEffect, useState, type FormEvent } from "react";

import { ComingInPhase, PageHeader } from "@/components/app/page-header";
import { DonorDonations } from "@/components/donor/donor-donations";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardLabel } from "@/components/ui/card";
import { Field, InlineAlert, SelectInput, Spinner, TextInput } from "@/components/ui/field";
import { SimulatedBadge } from "@/components/ui/simulated-badge";
import { ErrorState, Skeleton } from "@/components/ui/states";
import { api } from "@/lib/api";
import { toFailure } from "@/lib/problem";
import { useSession } from "@/lib/session";
import { validate } from "@/lib/validation";

type Editable = Pick<DonorProfile, "full_name" | "address" | "city" | "state" | "pin_code">;
const EDITABLE = ["full_name", "address", "city", "state", "pin_code"] as const;

function pick(p: DonorProfile): Editable {
  return {
    full_name: p.full_name,
    address: p.address,
    city: p.city,
    state: p.state,
    pin_code: p.pin_code,
  };
}

export function DonorDashboard() {
  const { reload } = useSession();
  const [profile, setProfile] = useState<DonorProfile | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);
  const [states, setStates] = useState<string[]>([]);

  useEffect(() => {
    let active = true;
    void api.GET("/api/v1/donors/me").then(({ data, error, response }) => {
      if (!active) return;
      if (data) setProfile(data);
      else setLoadError(toFailure(error, response).message);
    });
    void api.GET("/api/v1/reference/registration").then(({ data }) => {
      if (active && data) setStates((data as RegistrationReference).states);
    });
    return () => {
      active = false;
    };
  }, []);

  if (loadError) return <ErrorState description={loadError} />;
  if (!profile) {
    return (
      <div aria-busy="true" className="grid gap-4 lg:grid-cols-[1fr_2fr]">
        <Skeleton className="h-64" />
        <Skeleton className="h-64" />
      </div>
    );
  }

  const firstName = profile.full_name.split(" ")[0] ?? profile.full_name;

  return (
    <>
      <PageHeader
        eyebrow="Donor"
        title={`Hello, ${firstName}`}
        description="Your donor profile, donations and eligibility."
      />
      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,2fr)]">
        <Card className="relative overflow-hidden">
          <CardLabel>Blood group</CardLabel>
          <p
            className="mt-4 font-display text-[5.5rem] leading-none text-vital"
            aria-label={`Blood group ${profile.blood_group}`}
          >
            {profile.blood_group.replace("-", "−")}
          </p>
          <div className="mt-6 flex flex-wrap gap-2">
            <Badge tone="warn" dot>
              Self-declared
            </Badge>
            {profile.verified_at && (
              <span className="inline-flex items-center gap-1.5">
                <Badge tone="verified" dot>
                  Mobile verified
                </Badge>
                <SimulatedBadge label="Demo" subject="Phone verification" />
              </span>
            )}
          </div>
          <p className="mt-4 text-xs text-ink-subtle">
            A blood bank confirms your group at your first donation.
          </p>
        </Card>

        <Card>
          <div className="flex items-center justify-between">
            <CardLabel>Profile</CardLabel>
            {!editing && (
              <Button size="sm" variant="secondary" onClick={() => setEditing(true)}>
                Edit
              </Button>
            )}
          </div>
          {editing ? (
            <ProfileEditor
              profile={profile}
              states={states}
              onCancel={() => setEditing(false)}
              onSaved={(next) => {
                setProfile(next);
                setEditing(false);
                void reload();
              }}
            />
          ) : (
            <dl className="mt-4 grid gap-x-8 gap-y-4 sm:grid-cols-2">
              {(
                [
                  ["Name", profile.full_name],
                  ["Email", profile.email],
                  ["Mobile", profile.mobile],
                  ["Address", profile.address],
                  ["City", profile.city],
                  ["State / UT", profile.state],
                  ["PIN code", profile.pin_code],
                ] as const
              ).map(([term, value]) => (
                <div key={term}>
                  <dt className="text-xs text-ink-subtle">{term}</dt>
                  <dd className="mt-0.5 text-sm break-words">{value}</dd>
                </div>
              ))}
            </dl>
          )}
        </Card>
      </div>

      <div className="mt-6 grid gap-4 md:grid-cols-2">
        <DonorDonations verifiedAt={profile.verified_at} bloodGroupStatus={profile.blood_group_status} />
        <ComingInPhase
          phase={10}
          title="Private eligibility check"
          description="Prove you can donate without revealing your health data."
        />
      </div>
    </>
  );
}

function ProfileEditor({
  profile,
  states,
  onCancel,
  onSaved,
}: {
  profile: DonorProfile;
  states: string[];
  onCancel: () => void;
  onSaved: (p: DonorProfile) => void;
}) {
  const [values, setValues] = useState<Editable>(pick(profile));
  const [errors, setErrors] = useState<Partial<Record<keyof Editable, string>>>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const clientErrors = validate(values, EDITABLE);
    setErrors(clientErrors);
    if (Object.keys(clientErrors).length) return;
    setSaving(true);
    setFormError(null);
    try {
      const { data, error, response } = await api.PATCH("/api/v1/donors/me", { body: values });
      if (data) {
        onSaved(data);
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

  const input = (field: keyof Editable, label: string, autoComplete: string) => (
    <Field label={label} error={errors[field]}>
      {(p) => (
        <TextInput
          {...p}
          autoComplete={autoComplete}
          value={values[field]}
          onChange={(e) => setValues((v) => ({ ...v, [field]: e.target.value }))}
        />
      )}
    </Field>
  );

  return (
    <form onSubmit={onSubmit} noValidate className="mt-4 flex flex-col gap-4">
      {input("full_name", "Full name", "name")}
      {input("address", "Address", "street-address")}
      <div className="grid gap-4 sm:grid-cols-[1fr_1fr_8rem]">
        {input("city", "City", "address-level2")}
        <Field label="State / UT" error={errors.state}>
          {(p) => (
            <SelectInput
              {...p}
              value={values.state}
              onChange={(e) => setValues((v) => ({ ...v, state: e.target.value }))}
            >
              {(states.length ? states : [values.state]).map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </SelectInput>
          )}
        </Field>
        {input("pin_code", "PIN code", "postal-code")}
      </div>
      <p className="text-xs text-ink-subtle">
        Email, mobile and blood group can&apos;t be changed here: they need re-verification or a
        blood bank.
      </p>
      {formError && <InlineAlert>{formError}</InlineAlert>}
      <div className="flex gap-2">
        <Button type="submit" disabled={saving}>
          {saving && <Spinner />}
          {saving ? "Saving…" : "Save changes"}
        </Button>
        <Button variant="ghost" onClick={onCancel} disabled={saving}>
          Cancel
        </Button>
      </div>
    </form>
  );
}
