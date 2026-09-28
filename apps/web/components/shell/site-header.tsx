import Link from "next/link";

import { Wordmark } from "@/components/brand/wordmark";
import { isProductionEnv } from "@/lib/env";

export function SiteHeader() {
  return (
    <header className="mx-auto flex max-w-(--layout-max) items-center justify-between px-(--gutter) py-5">
      <Link href="/" aria-label="VEYRA home">
        <Wordmark />
      </Link>
      <nav aria-label="Primary" className="flex items-center gap-1 text-sm">
        <Link href="/disclosures" className="rounded-pill px-3 py-1.5 text-ink-muted hover:bg-surface-sunken hover:text-ink">
          Disclosures
        </Link>
        {!isProductionEnv() && (
          <Link href="/system" className="hidden rounded-pill px-3 py-1.5 text-ink-muted hover:bg-surface-sunken hover:text-ink sm:inline-block">
            Design system
          </Link>
        )}
        <Link href="/sign-in" className="rounded-pill px-3 py-1.5 font-medium text-ink hover:bg-surface-sunken">
          Sign in
        </Link>
        <Link
          href="/register"
          className="ml-1 rounded-pill bg-vital px-4 py-1.5 font-medium text-on-vital shadow-1 transition-colors duration-(--dur-fast) hover:bg-vital-strong"
        >
          Become a donor
        </Link>
      </nav>
    </header>
  );
}
