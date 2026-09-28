import type { Metadata } from "next";

import { RegisterForm } from "@/components/auth/register-form";

export const metadata: Metadata = { title: "Become a donor" };

export default function RegisterPage() {
  return (
    <>
      <h1 className="font-display text-display-sm leading-(--leading-tight) tracking-(--tracking-display)">
        Become a donor
      </h1>
      <p className="mt-3 mb-10 text-ink-muted">
        Create your VEYRA donor account. It takes about two minutes.
      </p>
      <RegisterForm />
    </>
  );
}
