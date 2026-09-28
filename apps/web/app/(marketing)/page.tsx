import Link from "next/link";

import { FlowLines } from "@/components/brand/flow-lines";
import { Badge } from "@/components/ui/badge";

/**
 * Phase 0 landing: a foundation placeholder that already uses the real identity
 * (tokens, type, motif). The full hero, scroll story and imagery arrive in Phase 3.
 */

const STAGES = [
  {
    n: "01",
    title: "Donor",
    body: "A verified donor gives blood. Private health details stay with the donor and the screening bank.",
  },
  {
    n: "02",
    title: "Blood bank",
    body: "Every bag gets an identity at collection and a custody record from the first minute.",
  },
  {
    n: "03",
    title: "Transport",
    body: "Movements between facilities are tracked, and cold-chain conditions travel with the bag.",
  },
  {
    n: "04",
    title: "Hospital",
    body: "Receipt closes the chain, and every step can be checked for tampering.",
  },
] as const;

export default function HomePage() {
  return (
    <>
      <section className="mx-auto grid max-w-(--layout-max) items-center gap-12 px-(--gutter) pt-10 pb-20 md:grid-cols-[1.05fr_1fr] md:pt-16">
        <div className="veyra-rise">
          <Badge tone="neutral" className="mb-8">
            Prototype · Phase 1: accounts &amp; access
          </Badge>
          <h1 className="font-display text-display leading-(--leading-tight) tracking-(--tracking-display) text-ink">
            Every unit of blood,
            <br />
            <em className="text-vital">accounted for.</em>
          </h1>
          <p className="mt-6 max-w-[34rem] text-lg text-ink-muted">
            VEYRA connects donors, blood banks and hospitals into one traceable network, from
            donation to transfusion, so the right unit reaches the right patient in time.
          </p>
          <div className="mt-10 flex flex-wrap items-center gap-3">
            <Link
              href="/register"
              className="inline-flex h-12 items-center rounded-pill bg-vital px-6 text-sm font-medium text-on-vital shadow-1 transition-transform duration-(--dur-fast) ease-standard active:scale-[0.98]"
            >
              Register as a donor
            </Link>
            <Link
              href="/disclosures"
              className="inline-flex h-12 items-center rounded-pill border border-line-strong px-6 text-sm font-medium text-ink transition-colors duration-(--dur-fast) hover:border-ink/40"
            >
              What is simulated?
            </Link>
          </div>
        </div>

        <div className="relative">
          <div className="rounded-lg border border-line bg-surface-raised p-4 shadow-2 sm:p-8">
            <FlowLines className="h-auto w-full" />
          </div>
          <p className="mt-3 text-xs text-ink-subtle">
            Illustrative network diagram, not live data.
          </p>
        </div>
      </section>

      <section aria-labelledby="chain-heading" className="border-t border-line bg-surface-sunken">
        <div className="mx-auto max-w-(--layout-max) px-(--gutter) py-20">
          <h2
            id="chain-heading"
            className="font-display text-display-sm leading-(--leading-tight) tracking-(--tracking-display)"
          >
            One chain of custody.
          </h2>
          <ol className="mt-12 grid gap-px overflow-hidden rounded-lg border border-line bg-line sm:grid-cols-2 lg:grid-cols-4">
            {STAGES.map((s) => (
              <li key={s.n} className="bg-surface-raised p-6">
                <p className="font-mono text-xs text-vital">{s.n}</p>
                <p className="mt-4 text-lg font-medium">{s.title}</p>
                <p className="mt-2 text-sm text-ink-muted">{s.body}</p>
              </li>
            ))}
          </ol>
        </div>
      </section>
    </>
  );
}
