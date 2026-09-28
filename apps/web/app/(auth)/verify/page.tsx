import type { Metadata } from "next";
import { Suspense } from "react";

import { VerifyForm } from "@/components/auth/verify-form";
import { Skeleton } from "@/components/ui/states";

export const metadata: Metadata = { title: "Verify your mobile" };

export default function VerifyPage() {
  return (
    <>
      <h1 className="font-display text-display-sm leading-(--leading-tight) tracking-(--tracking-display)">
        Verify your mobile
      </h1>
      <p className="mt-3 mb-8 text-ink-muted">One last step before your account is active.</p>
      <Suspense fallback={<Skeleton className="h-40 w-full" />}>
        <VerifyForm />
      </Suspense>
    </>
  );
}
