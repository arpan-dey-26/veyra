"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useState, type FormEvent } from "react";

import { DemoVerificationNotice } from "@/components/auth/demo-verification-notice";
import { Button } from "@/components/ui/button";
import { Field, InlineAlert, Spinner, TextInput } from "@/components/ui/field";
import { api } from "@/lib/api";
import { toFailure } from "@/lib/problem";
import { homeFor } from "@/lib/roles";
import { useSession } from "@/lib/session";

const DEAD_END_CODES = new Set(["challenge_expired", "too_many_attempts", "challenge_not_found"]);

export function VerifyForm() {
  const router = useRouter();
  const params = useSearchParams();
  const { setMe } = useSession();
  const challengeId = params.get("challenge");
  const hint = params.get("hint");
  const [code, setCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [deadEnd, setDeadEnd] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  if (!challengeId) {
    return (
      <InlineAlert title="No verification in progress">
        Start by{" "}
        <Link href="/register" className="underline">
          creating an account
        </Link>{" "}
        or{" "}
        <Link href="/sign-in" className="underline">
          signing in
        </Link>
        .
      </InlineAlert>
    );
  }

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!/^\d{4}$/.test(code)) {
      setError("Enter the 4 digits.");
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      const { data, error: apiError, response } = await api.POST("/api/v1/auth/verify", {
        body: { challenge_id: challengeId as string, code },
      });
      if (data) {
        setMe(data);
        router.replace(homeFor(data.user.role));
        return;
      }
      const failure = toFailure(apiError, response);
      setError(failure.message);
      setDeadEnd(DEAD_END_CODES.has(failure.problem.code));
      setCode("");
    } catch {
      setError(toFailure(undefined).message);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form onSubmit={onSubmit} noValidate className="flex flex-col gap-6">
      <DemoVerificationNotice />
      <Field
        label="Verification code"
        error={error}
        hint={hint ? `Enter the last 4 digits of the mobile number ${hint}.` : undefined}
      >
        {(p) => (
          <TextInput
            {...p}
            autoFocus
            inputMode="numeric"
            autoComplete="one-time-code"
            maxLength={4}
            placeholder="••••"
            disabled={deadEnd}
            value={code}
            onChange={(e) => setCode(e.target.value.replace(/\D/g, "").slice(0, 4))}
            className="h-14 text-center font-mono text-2xl tracking-[0.6em]"
          />
        )}
      </Field>
      {deadEnd ? (
        <InlineAlert tone="info" title="This verification can't be completed">
          <Link href="/sign-in" className="font-medium underline">
            Sign in
          </Link>{" "}
          with your email and password to start a new verification.
        </InlineAlert>
      ) : (
        <Button type="submit" variant="vital" size="lg" disabled={submitting || code.length !== 4}>
          {submitting && <Spinner />}
          {submitting ? "Verifying…" : "Verify and continue"}
        </Button>
      )}
    </form>
  );
}
