"use client";

import type { InvitePreview } from "@veyra/api-client";
import { useRouter } from "next/navigation";
import { useEffect, useState, type FormEvent } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardLabel } from "@/components/ui/card";
import {
  Field,
  InlineAlert,
  PasswordInput,
  Spinner,
  TextInput,
} from "@/components/ui/field";
import { Skeleton } from "@/components/ui/states";
import { api } from "@/lib/api";
import { toFailure } from "@/lib/problem";
import { homeFor, ROLE_LABEL, isRole } from "@/lib/roles";
import { useSession } from "@/lib/session";
import { validate } from "@/lib/validation";

type Values = { full_name: string; mobile: string; password: string };
const FIELDS = ["full_name", "mobile", "password"] as const;

export function AcceptInviteForm({ token }: { token: string }) {
  const router = useRouter();
  const { setMe } = useSession();
  const [invite, setInvite] = useState<InvitePreview | null | "invalid">(null);
  const [values, setValues] = useState<Values>({ full_name: "", mobile: "", password: "" });
  const [errors, setErrors] = useState<Partial<Record<keyof Values, string>>>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    let active = true;
    void api
      .GET("/api/v1/auth/invites/{token}", { params: { path: { token } } })
      .then(({ data }) => {
        if (active) setInvite(data ?? "invalid");
      })
      .catch(() => {
        if (active) setInvite("invalid");
      });
    return () => {
      active = false;
    };
  }, [token]);

  if (invite === null) {
    return (
      <div aria-busy="true" className="flex flex-col gap-3">
        <Skeleton className="h-24 w-full" />
        <Skeleton className="h-11 w-full" />
      </div>
    );
  }
  if (invite === "invalid") {
    return (
      <InlineAlert title="This invitation can't be used">
        It may have expired, been used already, or the link is incomplete. Ask your VEYRA
        administrator for a new invitation.
      </InlineAlert>
    );
  }

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const clientErrors = validate(values, FIELDS);
    setErrors(clientErrors);
    if (Object.keys(clientErrors).length) return;
    setSubmitting(true);
    setFormError(null);
    try {
      const { data, error, response } = await api.POST("/api/v1/auth/invites/accept", {
        body: { token, ...values },
      });
      if (data) {
        setMe(data);
        router.replace(homeFor(data.user.role));
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

  const roleLabel = isRole(invite.role) ? ROLE_LABEL[invite.role] : invite.role;

  return (
    <div className="flex flex-col gap-6">
      <Card className="p-5">
        <CardLabel>You&apos;re invited to join</CardLabel>
        <p className="mt-2 text-lg font-medium">{invite.facility.name}</p>
        <p className="text-sm text-ink-muted">
          {roleLabel} · {invite.facility.city}, {invite.facility.state}
        </p>
        <p className="mt-3 font-mono text-xs text-ink-subtle">{invite.email}</p>
      </Card>
      <form onSubmit={onSubmit} noValidate className="flex flex-col gap-4">
        <Field label="Full name" error={errors.full_name}>
          {(p) => (
            <TextInput
              {...p}
              autoComplete="name"
              value={values.full_name}
              onChange={(e) => setValues((v) => ({ ...v, full_name: e.target.value }))}
            />
          )}
        </Field>
        <Field label="Mobile number" error={errors.mobile}>
          {(p) => (
            <TextInput
              {...p}
              type="tel"
              inputMode="tel"
              autoComplete="tel-national"
              value={values.mobile}
              onChange={(e) => setValues((v) => ({ ...v, mobile: e.target.value }))}
            />
          )}
        </Field>
        <Field label="Create a password" error={errors.password} hint="At least 10 characters">
          {(p) => (
            <PasswordInput
              {...p}
              autoComplete="new-password"
              value={values.password}
              onChange={(e) => setValues((v) => ({ ...v, password: e.target.value }))}
            />
          )}
        </Field>
        {formError && <InlineAlert>{formError}</InlineAlert>}
        <Button type="submit" size="lg" disabled={submitting}>
          {submitting && <Spinner />}
          {submitting ? "Creating account…" : "Accept invitation"}
        </Button>
      </form>
    </div>
  );
}
