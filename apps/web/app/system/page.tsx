import { colorRoles, duration } from "@veyra/design-tokens";
import type { Metadata } from "next";
import { notFound } from "next/navigation";
import type { ReactNode } from "react";

import { FlowLines } from "@/components/brand/flow-lines";
import { Wordmark } from "@/components/brand/wordmark";
import { SiteHeader } from "@/components/shell/site-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardLabel } from "@/components/ui/card";
import { SimulatedBadge } from "@/components/ui/simulated-badge";
import { EmptyState, ErrorState, Skeleton, StatusBeacon } from "@/components/ui/states";
import { isProductionEnv } from "@/lib/env";

import { MotionSpecimen } from "./motion-specimen";

export const metadata: Metadata = { title: "Design system" };

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="border-t border-line py-12">
      <h2 className="mb-6 text-sm font-medium tracking-(--tracking-label) text-ink-subtle uppercase">
        {title}
      </h2>
      {children}
    </section>
  );
}

/** Internal living reference for the VEYRA design foundations. Not available in production. */
export default function SystemPage() {
  if (isProductionEnv()) notFound();

  return (
    <>
      <SiteHeader />
      <main id="main" className="mx-auto max-w-(--layout-max) px-(--gutter) pb-24">
        <div className="py-10">
          <Wordmark withTagline />
          <h1 className="mt-8 font-display text-display-sm leading-(--leading-tight) tracking-(--tracking-display)">
            Design foundations
          </h1>
          <p className="mt-3 max-w-prose text-ink-muted">
            Clinical calm, one vital colour. Tokens live in <code className="font-mono text-sm">@veyra/design-tokens</code>.
          </p>
        </div>

        <Section title="Colour roles">
          <ul className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
            {colorRoles.map((role) => (
              <li key={role} className="overflow-hidden rounded-md border border-line">
                <div className="h-14" style={{ background: `var(--color-${role})` }} />
                <p className="bg-surface-raised px-3 py-2 font-mono text-xs text-ink-muted">{role}</p>
              </li>
            ))}
          </ul>
        </Section>

        <Section title="Typography">
          <div className="space-y-5">
            <p className="font-display text-display leading-(--leading-tight) tracking-(--tracking-display)">
              Display serif
            </p>
            <p className="text-3xl font-semibold tracking-tight">Heading · Inter Tight</p>
            <p className="max-w-prose text-base text-ink-muted">
              Body text is set for long reading at 16px with generous leading, for dashboards
              people use during stressful moments.
            </p>
            <p className="font-mono text-sm text-ink-muted">BAG-7F3K-2Q · 4.2 °C · 0x9e1b…2f</p>
          </div>
        </Section>

        <Section title="Controls">
          <div className="flex flex-wrap items-center gap-3">
            <Button>Primary</Button>
            <Button variant="vital">Request blood</Button>
            <Button variant="secondary">Secondary</Button>
            <Button variant="ghost">Ghost</Button>
            <Button disabled>Disabled</Button>
            <Button size="sm" variant="secondary">
              Small
            </Button>
            <Button size="lg">Large</Button>
          </div>
        </Section>

        <Section title="Status & labels">
          <div className="flex flex-wrap items-center gap-3">
            <Badge>Neutral</Badge>
            <Badge tone="vital">O−</Badge>
            <Badge tone="verified" dot>
              Verified
            </Badge>
            <Badge tone="warn" dot>
              Expiring in 48h
            </Badge>
            <Badge tone="critical" dot>
              Critical stock
            </Badge>
            <SimulatedBadge subject="IoT sensor" />
            <SimulatedBadge label="Synthetic data" subject="Forecast" />
          </div>
          <div className="mt-6 flex flex-wrap gap-6">
            <StatusBeacon tone="verified" label="Cold chain nominal" />
            <StatusBeacon tone="warn" label="Delayed" />
            <StatusBeacon tone="critical" label="Emergency" />
            <StatusBeacon tone="idle" label="Offline" />
          </div>
        </Section>

        <Section title="States">
          <div className="grid gap-4 lg:grid-cols-3">
            <Card>
              <CardLabel>Loading</CardLabel>
              <div className="mt-4 space-y-3">
                <Skeleton className="h-6 w-2/3" />
                <Skeleton className="h-4 w-full" />
                <Skeleton className="h-4 w-5/6" />
              </div>
            </Card>
            <EmptyState
              title="No requests yet"
              description="Incoming blood requests from hospitals will appear here."
              action={<Button size="sm" variant="secondary">Refresh</Button>}
            />
            <ErrorState
              description="We couldn't load inventory. Your data is safe; try again."
              requestId="3f9c2a1be0d44c8e"
              action={<Button size="sm" variant="secondary">Retry</Button>}
            />
          </div>
        </Section>

        <Section title="Motion tokens">
          <MotionSpecimen durations={duration} />
        </Section>

        <Section title="Signature motif">
          <Card className="max-w-2xl">
            <FlowLines className="h-auto w-full" />
          </Card>
        </Section>
      </main>
    </>
  );
}
