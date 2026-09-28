import type { Metadata } from "next";
import { Suspense } from "react";

import { SignInForm } from "@/components/auth/sign-in-form";
import { Skeleton } from "@/components/ui/states";

export const metadata: Metadata = { title: "Sign in" };

export default function SignInPage() {
  return (
    <>
      <h1 className="font-display text-display-sm leading-(--leading-tight) tracking-(--tracking-display)">
        Sign in
      </h1>
      <p className="mt-3 mb-8 text-ink-muted">Donors, hospital and blood-bank staff, and admins.</p>
      <Suspense fallback={<Skeleton className="h-56 w-full" />}>
        <SignInForm />
      </Suspense>
    </>
  );
}
