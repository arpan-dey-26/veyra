import type { Metadata } from "next";

import { SimulatedBadge } from "@/components/ui/simulated-badge";

export const metadata: Metadata = { title: "Demo disclosures" };

/** Mirrors docs/demo-disclosures.md. Keep both in sync. */
const ITEMS = [
  {
    subject: "Hospitals & blood banks",
    label: "Simulated" as const,
    body: "Partner blood banks and hospitals in the demo are mock providers with seeded data. VEYRA is not connected to any real hospital or government blood-bank system.",
  },
  {
    subject: "Demand forecasts",
    label: "Synthetic data" as const,
    body: "Forecasts are real model outputs, but the models are trained on a documented synthetic dataset, not real hospital demand.",
  },
  {
    subject: "Temperature sensors",
    label: "Simulated" as const,
    body: "Cold-chain telemetry comes from a software simulator, not physical IoT devices.",
  },
  {
    subject: "Blockchain",
    label: "Demo" as const,
    body: "Integrity records are anchored on a local development chain, not a production blockchain network.",
  },
  {
    subject: "Phone verification",
    label: "Demo" as const,
    body: "Demo verification only. The last 4 digits of your mobile number are used for prototype verification instead of a real OTP.",
  },
  {
    subject: "Staff invitations",
    label: "Demo" as const,
    body: "No email is sent. An administrator sees a one-time invitation link, labelled as demo delivery, and shares it with the invitee.",
  },
  {
    subject: "Privacy-preserving eligibility",
    label: "Demo" as const,
    body: "The zero-knowledge eligibility check is a technical prototype. It is not a medical certification or clinical decision system.",
  },
];

export default function DisclosuresPage() {
  return (
    <section className="mx-auto max-w-3xl px-(--gutter) pt-10 pb-24">
      <h1 className="font-display text-display-sm leading-(--leading-tight) tracking-(--tracking-display)">
        What is simulated in VEYRA
      </h1>
      <p className="mt-4 text-ink-muted">
        VEYRA is a prototype. Anything that is not a real-world integration is labelled
        wherever it appears in the product, with the same badges shown below.
      </p>
      <ul className="mt-10 divide-y divide-line rounded-lg border border-line bg-surface-raised">
        {ITEMS.map((item) => (
          <li key={item.subject} className="flex flex-col gap-2 p-6 sm:flex-row sm:gap-6">
            <div className="flex min-w-48 items-start gap-2 sm:flex-col">
              <p className="font-medium">{item.subject}</p>
              <SimulatedBadge subject={item.subject} label={item.label} />
            </div>
            <p className="text-sm text-ink-muted">{item.body}</p>
          </li>
        ))}
      </ul>
    </section>
  );
}
