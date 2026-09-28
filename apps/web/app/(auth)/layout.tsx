import Link from "next/link";
import type { ReactNode } from "react";

import { FlowLines } from "@/components/brand/flow-lines";
import { Wordmark } from "@/components/brand/wordmark";
import { SessionProvider } from "@/lib/session";

export default function AuthLayout({ children }: { children: ReactNode }) {
  return (
    <SessionProvider>
      <div className="grid min-h-[calc(100dvh-2rem)] lg:grid-cols-[minmax(0,5fr)_minmax(0,6fr)]">
        <aside className="relative hidden flex-col justify-between overflow-hidden border-r border-line bg-surface-sunken p-10 lg:flex">
          <Link href="/" aria-label="VEYRA home">
            <Wordmark withTagline />
          </Link>
          <div>
            <FlowLines className="h-auto w-full max-w-xl" />
            <p className="mt-8 max-w-sm font-display text-3xl leading-(--leading-snug)">
              One network, from the donor&apos;s arm to the patient&apos;s bedside.
            </p>
          </div>
          <p className="text-xs text-ink-subtle">
            VEYRA is a prototype, not a certified medical system.
          </p>
        </aside>
        <main id="main" className="flex items-start justify-center px-(--gutter) py-10 sm:py-16">
          <div className="veyra-rise w-full max-w-xl">
            <Link href="/" aria-label="VEYRA home" className="mb-10 inline-block lg:hidden">
              <Wordmark />
            </Link>
            {children}
          </div>
        </main>
      </div>
    </SessionProvider>
  );
}
