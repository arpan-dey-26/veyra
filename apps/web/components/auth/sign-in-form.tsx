"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useState, type FormEvent } from "react";

import { Button } from "@/components/ui/button";
import { Field, InlineAlert, PasswordInput, Spinner, TextInput } from "@/components/ui/field";
import { api } from "@/lib/api";
import { toFailure } from "@/lib/problem";
import { homeFor, safeNext } from "@/lib/roles";
import { useSession } from "@/lib/session";

export function SignInForm() {
  const router = useRouter();
  const params = useSearchParams();
  const { setMe } = useSession();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!email.trim() || !password) {
      setError("Enter your email and password.");
      return;
    }
    setSubmitting(true);
    setError(null);
    const credentials = { email, password };
    try {
      const { data, error: apiError, response } = await api.POST("/api/v1/auth/login", {
        body: credentials,
      });
      if (data) {
        setMe(data);
        router.replace(safeNext(params.get("next")) ?? homeFor(data.user.role));
        return;
      }
      const failure = toFailure(apiError, response);
      if (failure.problem.code === "verification_required") {
        const restart = await api.POST("/api/v1/auth/verify/start", { body: credentials });
        if (restart.data) {
          const q = new URLSearchParams({
            challenge: restart.data.challenge_id,
            hint: restart.data.destination_hint,
          });
          router.push(`/verify?${q.toString()}`);
          return;
        }
      }
      setError(failure.message);
    } catch {
      setError(toFailure(undefined).message);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form onSubmit={onSubmit} noValidate className="flex flex-col gap-5">
      <Field label="Email">
        {(p) => (
          <TextInput
            {...p}
            type="email"
            autoComplete="email"
            inputMode="email"
            autoFocus
            value={email}
            onChange={(e) => setEmail(e.target.value)}
          />
        )}
      </Field>
      <Field label="Password">
        {(p) => (
          <PasswordInput
            {...p}
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        )}
      </Field>
      {error && <InlineAlert>{error}</InlineAlert>}
      <Button type="submit" size="lg" disabled={submitting}>
        {submitting && <Spinner />}
        {submitting ? "Signing in…" : "Sign in"}
      </Button>
      <p className="text-sm text-ink-muted">
        New donor?{" "}
        <Link href="/register" className="font-medium text-ink underline underline-offset-4">
          Create an account
        </Link>
      </p>
    </form>
  );
}
