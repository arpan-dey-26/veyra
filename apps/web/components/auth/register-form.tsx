"use client";

import type { RegistrationReference } from "@veyra/api-client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState, type FormEvent } from "react";

import { BloodGroupPicker } from "@/components/auth/blood-group-picker";
import { DemoVerificationNotice } from "@/components/auth/demo-verification-notice";
import { Button } from "@/components/ui/button";
import {
  Field,
  InlineAlert,
  PasswordInput,
  SelectInput,
  Spinner,
  TextInput,
} from "@/components/ui/field";
import { api } from "@/lib/api";
import { toFailure } from "@/lib/problem";
import { passwordStrength, validate, type FieldName } from "@/lib/validation";

const FIELDS = [
  "full_name",
  "email",
  "mobile",
  "blood_group",
  "address",
  "city",
  "state",
  "pin_code",
  "password",
] as const satisfies readonly FieldName[];

type Values = Record<(typeof FIELDS)[number], string>;

const EMPTY: Values = {
  full_name: "",
  email: "",
  mobile: "",
  blood_group: "",
  address: "",
  city: "",
  state: "",
  pin_code: "",
  password: "",
};

export function RegisterForm() {
  const router = useRouter();
  const [values, setValues] = useState<Values>(EMPTY);
  const [errors, setErrors] = useState<Partial<Record<keyof Values, string>>>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [reference, setReference] = useState<RegistrationReference | null>(null);

  useEffect(() => {
    let active = true;
    void api.GET("/api/v1/reference/registration").then(({ data }) => {
      if (active && data) setReference(data);
    });
    return () => {
      active = false;
    };
  }, []);

  const set = (field: keyof Values) => (value: string) => {
    setValues((v) => ({ ...v, [field]: value }));
    if (errors[field]) setErrors((e) => ({ ...e, [field]: undefined }));
  };

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setFormError(null);
    const clientErrors = validate(values, FIELDS);
    if (Object.keys(clientErrors).length > 0) {
      setErrors(clientErrors);
      setFormError("Please correct the highlighted fields.");
      return;
    }
    setSubmitting(true);
    try {
      const { data, error, response } = await api.POST("/api/v1/auth/register", {
        body: values,
      });
      if (data) {
        const params = new URLSearchParams({
          challenge: data.verification.challenge_id,
          hint: data.verification.destination_hint,
        });
        router.push(`/verify?${params.toString()}`);
        return;
      }
      const failure = toFailure(error, response);
      setErrors(failure.fields);
      setFormError(failure.message);
    } catch {
      setFormError(toFailure(undefined).message);
    } finally {
      setSubmitting(false);
    }
  }

  const strength = passwordStrength(values.password);

  return (
    <form onSubmit={onSubmit} noValidate className="flex flex-col gap-8">
      <section aria-labelledby="reg-you" className="flex flex-col gap-4">
        <h2 id="reg-you" className="text-2xs font-semibold tracking-(--tracking-label) text-ink-subtle uppercase">
          About you
        </h2>
        <Field label="Full name" error={errors.full_name}>
          {(p) => (
            <TextInput
              {...p}
              autoComplete="name"
              value={values.full_name}
              onChange={(e) => set("full_name")(e.target.value)}
            />
          )}
        </Field>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Email" error={errors.email}>
            {(p) => (
              <TextInput
                {...p}
                type="email"
                autoComplete="email"
                inputMode="email"
                value={values.email}
                onChange={(e) => set("email")(e.target.value)}
              />
            )}
          </Field>
          <Field
            label="Mobile number"
            error={errors.mobile}
            hint="Indian mobile, e.g. 98765 43210"
          >
            {(p) => (
              <TextInput
                {...p}
                type="tel"
                autoComplete="tel-national"
                inputMode="tel"
                placeholder="98765 43210"
                value={values.mobile}
                onChange={(e) => set("mobile")(e.target.value)}
              />
            )}
          </Field>
        </div>
        <DemoVerificationNotice compact />
      </section>

      <section aria-labelledby="reg-blood" className="flex flex-col gap-4">
        <h2 id="reg-blood" className="text-2xs font-semibold tracking-(--tracking-label) text-ink-subtle uppercase">
          Blood
        </h2>
        <BloodGroupPicker
          value={values.blood_group}
          onChange={set("blood_group")}
          groups={reference?.blood_groups}
          error={errors.blood_group}
        />
      </section>

      <section aria-labelledby="reg-address" className="flex flex-col gap-4">
        <h2 id="reg-address" className="text-2xs font-semibold tracking-(--tracking-label) text-ink-subtle uppercase">
          Where you live
        </h2>
        <Field label="Address" error={errors.address}>
          {(p) => (
            <TextInput
              {...p}
              autoComplete="street-address"
              value={values.address}
              onChange={(e) => set("address")(e.target.value)}
            />
          )}
        </Field>
        <div className="grid gap-4 sm:grid-cols-[1fr_1fr_8.5rem]">
          <Field label="City" error={errors.city}>
            {(p) => (
              <TextInput
                {...p}
                autoComplete="address-level2"
                value={values.city}
                onChange={(e) => set("city")(e.target.value)}
              />
            )}
          </Field>
          <Field label="State / UT" error={errors.state}>
            {(p) => (
              <SelectInput
                {...p}
                autoComplete="address-level1"
                value={values.state}
                onChange={(e) => set("state")(e.target.value)}
              >
                <option value="">{reference ? "Select…" : "Loading…"}</option>
                {reference?.states.map((s) => (
                  <option key={s} value={s}>
                    {s}
                  </option>
                ))}
              </SelectInput>
            )}
          </Field>
          <Field label="PIN code" error={errors.pin_code}>
            {(p) => (
              <TextInput
                {...p}
                autoComplete="postal-code"
                inputMode="numeric"
                maxLength={7}
                value={values.pin_code}
                onChange={(e) => set("pin_code")(e.target.value)}
              />
            )}
          </Field>
        </div>
      </section>

      <section aria-labelledby="reg-security" className="flex flex-col gap-4">
        <h2 id="reg-security" className="text-2xs font-semibold tracking-(--tracking-label) text-ink-subtle uppercase">
          Security
        </h2>
        <Field
          label="Password"
          error={errors.password}
          hint={
            <span className="flex items-center gap-2">
              <span aria-hidden className="flex gap-1">
                {[1, 2, 3].map((i) => (
                  <span
                    key={i}
                    className={
                      "h-1 w-6 rounded-pill transition-colors duration-(--dur-base) " +
                      (strength.score >= i ? "bg-verified" : "bg-line-strong")
                    }
                  />
                ))}
              </span>
              {strength.label}
            </span>
          }
        >
          {(p) => (
            <PasswordInput
              {...p}
              autoComplete="new-password"
              value={values.password}
              onChange={(e) => set("password")(e.target.value)}
            />
          )}
        </Field>
      </section>

      {formError && <InlineAlert>{formError}</InlineAlert>}

      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <Button type="submit" variant="vital" size="lg" disabled={submitting}>
          {submitting && <Spinner />}
          {submitting ? "Creating account…" : "Create donor account"}
        </Button>
        <p className="text-sm text-ink-muted">
          Already registered?{" "}
          <Link href="/sign-in" className="font-medium text-ink underline underline-offset-4">
            Sign in
          </Link>
        </p>
      </div>
    </form>
  );
}
