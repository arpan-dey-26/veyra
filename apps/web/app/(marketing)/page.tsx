import Link from "next/link";

import { FlowLines } from "@/components/brand/flow-lines";
import { Badge } from "@/components/ui/badge";
import { SimulatedBadge } from "@/components/ui/simulated-badge";
import { LANDING_DISCLAIMER } from "@/lib/landing";

/**
 * Landing page v1 (Phase 3). Describes what the prototype does today, what is simulated,
 * and how data is protected. No clinical claims; prototype defaults are labelled as such.
 */

const WORKFLOW = [
  {
    n: "01",
    title: "Donate",
    body: "A verified donor gives blood at a blood bank. The bank records the collection and types the blood group.",
  },
  {
    n: "02",
    title: "Label",
    body: "Each component gets its own bag ID (VYR-XXXX-XXXX) and QR payload, and the first entry in its custody trail.",
  },
  {
    n: "03",
    title: "Request",
    body: "A hospital sees which banks can cover a request, shown as availability bands, and sends it with one click.",
  },
  {
    n: "04",
    title: "Dispatch",
    body: "The bank dispatches the bags that expire first. Everyone involved sees the status change live.",
  },
  {
    n: "05",
    title: "Receive & trace",
    body: "The hospital confirms receipt. Every step is chained with SHA-256, so an edited record is detectable.",
  },
] as const;

const PRINCIPLES = [
  {
    title: "Least access, always scoped",
    body: "Every request is checked against a permission and a scope: your record, your facility. Anything outside your scope looks the same as not existing.",
  },
  {
    title: "Donor privacy by design",
    body: "Hospitals never see donor identity. Donors see what their donation became, never who received it. Dashboards show counts, not people.",
  },
  {
    title: "No stock oversharing",
    body: "Hospitals see whether a bank can cover a request (sufficient, limited, none), never another facility's exact inventory.",
  },
  {
    title: "Tamper-evident records",
    body: "Custody events and audit entries are append-only in the database. Bag trails are hash-chained and re-verified on every view.",
  },
  {
    title: "Hardened sessions",
    body: "Argon2id passwords, short-lived access tokens, rotating refresh sessions with reuse detection, and CSRF protection on every change.",
  },
  {
    title: "Honest labelling",
    body: "Anything simulated, synthetic or demo-only is labelled wherever it appears, and refused in a production configuration.",
  },
] as const;

const SIMULATED = [
  { subject: "Partner blood banks", label: "Simulated" as const, body: "Mock banks with generated availability; no real blood bank is contacted." },
  { subject: "Phone verification", label: "Demo" as const, body: "Demo verification only. The last 4 digits of your mobile number are used for prototype verification instead of a real OTP." },
  { subject: "Demand forecasts", label: "Synthetic data" as const, body: "A real model, trained and run on synthetic demand data. Not clinical guidance." },
  { subject: "Demo facilities", label: "Demo" as const, body: "The seeded demo blood bank and hospital run real workflows on demo data." },
  { subject: "Blockchain anchoring", label: "Demo" as const, body: "Not yet: trace hashes live in the VEYRA database only (planned for a later phase)." },
] as const;

const ROLES = [
  { title: "Donors", body: "Register, verify, and follow what each donation became.", href: "/register", cta: "Become a donor" },
  { title: "Blood banks", body: "Record donations, label bags, manage stock and dispatch requests.", href: "/sign-in", cta: "Sign in (invited staff)" },
  { title: "Hospitals", body: "Check network availability, request blood and confirm receipt.", href: "/sign-in", cta: "Sign in (invited staff)" },
  { title: "Administrators", body: "Onboard facilities, invite staff and watch network health.", href: "/sign-in", cta: "Administrator sign-in" },
] as const;

const CTA_PRIMARY =
  "inline-flex h-12 items-center rounded-pill bg-vital px-6 text-sm font-medium text-on-vital shadow-1 transition-transform duration-(--dur-fast) ease-standard hover:bg-vital-strong active:scale-[0.98]";
const CTA_SECONDARY =
  "inline-flex h-12 items-center rounded-pill border border-line-strong px-6 text-sm font-medium text-ink transition-colors duration-(--dur-fast) hover:border-ink/40";

function SectionTitle({ id, eyebrow, children }: { id: string; eyebrow: string; children: string }) {
  return (
    <div>
      <p className="text-2xs font-semibold tracking-(--tracking-label) text-ink-subtle uppercase">{eyebrow}</p>
      <h2 id={id} className="mt-2 font-display text-display-sm leading-(--leading-tight) tracking-(--tracking-display)">
        {children}
      </h2>
    </div>
  );
}

export default function HomePage() {
  return (
    <>
      <section className="mx-auto grid max-w-(--layout-max) items-center gap-12 px-(--gutter) pt-10 pb-20 md:grid-cols-[1.05fr_1fr] md:pt-16">
        <div className="veyra-rise">
          <Badge tone="neutral" className="mb-8">
            Prototype · Phase 8: complete demo network
          </Badge>
          <h1 className="font-display text-display leading-(--leading-tight) tracking-(--tracking-display) text-ink">
            Every unit of blood,
            <br />
            <em className="text-vital">accounted for.</em>
          </h1>
          <p className="mt-6 max-w-[34rem] text-lg text-ink-muted">
            VEYRA connects donors, blood banks and hospitals in one traceable network. It shows
            where blood is available, moves requests between facilities, and keeps a
            tamper-evident record of every bag from donation to receipt.
          </p>
          <div className="mt-10 flex flex-wrap items-center gap-3">
            <Link href="/register" className={CTA_PRIMARY}>
              Register as a donor
            </Link>
            <Link href="/sign-in" className={CTA_SECONDARY}>
              Sign in
            </Link>
            <Link href="/disclosures" className="px-2 text-sm font-medium text-ink-muted underline-offset-4 hover:text-ink hover:underline">
              What is simulated?
            </Link>
          </div>
        </div>

        <div className="relative">
          <div className="rounded-lg border border-line bg-surface-raised p-4 shadow-2 sm:p-8">
            <FlowLines className="h-auto w-full" />
          </div>
          <p className="mt-3 text-xs text-ink-subtle">Illustrative network diagram, not live data.</p>
        </div>
      </section>

      <section aria-labelledby="workflow-heading" className="border-t border-line bg-surface-sunken">
        <div className="mx-auto max-w-(--layout-max) px-(--gutter) py-20">
          <SectionTitle id="workflow-heading" eyebrow="How it works">
            One chain of custody.
          </SectionTitle>
          <ol className="mt-12 grid gap-px overflow-hidden rounded-lg border border-line bg-line sm:grid-cols-2 lg:grid-cols-5">
            {WORKFLOW.map((s) => (
              <li key={s.n} className="bg-surface-raised p-6">
                <p className="font-mono text-xs text-vital">{s.n}</p>
                <p className="mt-4 text-lg font-medium">{s.title}</p>
                <p className="mt-2 text-sm text-ink-muted">{s.body}</p>
              </li>
            ))}
          </ol>
        </div>
      </section>

      <section aria-labelledby="roles-heading" className="mx-auto max-w-(--layout-max) px-(--gutter) py-20">
        <SectionTitle id="roles-heading" eyebrow="Who it's for">
          One network, four roles.
        </SectionTitle>
        <ul className="mt-10 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {ROLES.map((r) => (
            <li key={r.title} className="flex flex-col rounded-lg border border-line bg-surface-raised p-6 shadow-1">
              <p className="text-lg font-medium">{r.title}</p>
              <p className="mt-2 flex-1 text-sm text-ink-muted">{r.body}</p>
              <Link href={r.href} className="mt-5 text-sm font-medium text-vital underline-offset-4 hover:underline">
                {r.cta} →
              </Link>
            </li>
          ))}
        </ul>
        <p className="mt-4 text-xs text-ink-subtle">
          Blood-bank and hospital accounts are created by invitation from an administrator; they cannot self-register.
        </p>
      </section>

      <section aria-labelledby="security-heading" className="border-t border-line">
        <div className="mx-auto max-w-(--layout-max) px-(--gutter) py-20">
          <SectionTitle id="security-heading" eyebrow="Security & privacy">
            Built to share only what is needed.
          </SectionTitle>
          <ul className="mt-10 grid gap-x-10 gap-y-8 sm:grid-cols-2 lg:grid-cols-3">
            {PRINCIPLES.map((p) => (
              <li key={p.title}>
                <p className="font-medium">{p.title}</p>
                <p className="mt-2 text-sm text-ink-muted">{p.body}</p>
              </li>
            ))}
          </ul>
        </div>
      </section>

      <section aria-labelledby="transparency-heading" className="border-t border-line bg-surface-sunken">
        <div className="mx-auto max-w-(--layout-max) px-(--gutter) py-20">
          <SectionTitle id="transparency-heading" eyebrow="Transparency">
            What is real, and what is simulated.
          </SectionTitle>
          <p className="mt-4 max-w-prose text-ink-muted">
            Donations, bags, inventory, requests, dispatch, receipt and trace are real workflows on
            data inside VEYRA. These parts are simulated or demo-only, and labelled wherever they appear:
          </p>
          <ul className="mt-8 grid gap-4 md:grid-cols-2" data-testid="landing-disclosures">
            {SIMULATED.map((d) => (
              <li key={d.subject} className="flex flex-col gap-2 rounded-lg border border-line bg-surface-raised p-5">
                <div className="flex items-center justify-between gap-3">
                  <p className="font-medium">{d.subject}</p>
                  <SimulatedBadge subject={d.subject} label={d.label} />
                </div>
                <p className="text-sm text-ink-muted">{d.body}</p>
              </li>
            ))}
          </ul>
          <Link href="/disclosures" className="mt-6 inline-block text-sm font-medium underline underline-offset-4">
            Read every disclosure
          </Link>
        </div>
      </section>

      <section aria-labelledby="cta-heading" className="mx-auto max-w-(--layout-max) px-(--gutter) py-20">
        <div className="flex flex-col items-start gap-6 rounded-lg border border-line bg-surface-raised p-8 shadow-1 md:flex-row md:items-center md:justify-between">
          <div>
            <h2 id="cta-heading" className="font-display text-display-sm leading-(--leading-tight)">
              Try the prototype.
            </h2>
            <p className="mt-2 text-sm text-ink-muted">Register as a donor, or sign in with an invited facility account.</p>
          </div>
          <div className="flex flex-wrap gap-3">
            <Link href="/register" className={CTA_PRIMARY}>
              Become a donor
            </Link>
            <Link href="/sign-in" className={CTA_SECONDARY}>
              Sign in
            </Link>
          </div>
        </div>
        <p role="note" className="mt-6 max-w-prose text-xs text-ink-subtle" data-testid="landing-disclaimer">
          {LANDING_DISCLAIMER}
        </p>
      </section>
    </>
  );
}
