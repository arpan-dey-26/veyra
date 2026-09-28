import Link from "next/link";

import { isProductionEnv, publicEnv, type VeyraEnv } from "@/lib/env";

/** Global, always-visible demo disclosure. Hidden only in production. */
export function DemoRibbon({ env = publicEnv() }: { env?: VeyraEnv }) {
  if (isProductionEnv(env)) return null;
  return (
    <div
      role="note"
      aria-label="Demo environment notice"
      className="border-b border-line bg-simulated-soft text-simulated"
    >
      <p className="mx-auto flex max-w-(--layout-max) flex-wrap items-center gap-x-2 px-(--gutter) py-1.5 text-xs">
        <span className="font-semibold">Demo environment</span>
        <span aria-hidden>·</span>
        <span>Prototype build. Simulated components are always labelled.</span>
        <Link href="/disclosures" className="underline underline-offset-2 hover:text-ink">
          What is simulated?
        </Link>
      </p>
    </div>
  );
}
