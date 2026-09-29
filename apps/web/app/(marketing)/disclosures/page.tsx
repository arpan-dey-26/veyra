import type { Metadata } from "next";

import { SimulatedBadge } from "@/components/ui/simulated-badge";

export const metadata: Metadata = { title: "Demo disclosures" };

/** Mirrors docs/demo-disclosures.md. Keep both in sync. */
const ITEMS = [
  {
    subject: "Partner blood banks",
    label: "Simulated" as const,
    body: "Blood banks marked Simulated are mock providers with generated availability. Requests to them are acknowledged automatically and nothing is dispatched. VEYRA is not connected to any real hospital or government blood-bank system.",
  },
  {
    subject: "Demo facilities",
    label: "Demo" as const,
    body: "“VEYRA Central Blood Bank (Demo)” and “VEYRA City Hospital (Demo)” are demo accounts that run the real VEYRA workflows on demo data.",
  },
  {
    subject: "Bag trace chain",
    label: "Demo" as const,
    body: "Each bag's custody trail is append-only and SHA-256 hash-chained inside the VEYRA database, so edits are detectable. It is not anchored on any blockchain yet.",
  },
  {
    subject: "Demand forecasts",
    label: "Synthetic data" as const,
    body: "Forecasts are real model outputs, but the models are trained on a documented synthetic dataset, not real hospital demand.",
  },
  {
    subject: "Temperature sensors",
    label: "Simulated" as const,
    body: "Cold-chain telemetry comes from a software simulator: simulated device ids, RFID tags, battery and readings, with prototype thresholds. There are no physical IoT devices. This is simulated IoT telemetry for a student engineering prototype and is not a certified medical monitoring system.",
  },
  {
    subject: "Routing and ETAs",
    label: "Simulated" as const,
    body: "Estimated travel times are deterministic schematic simulations (no GPS, maps or traffic data), labelled “Simulated routing — prototype”.",
  },
  {
    subject: "Logistics and shipments",
    label: "Simulated" as const,
    body: "Couriers are fictional, routes are schematic checkpoints and ETAs are deterministic simulations. This is a simulated logistics prototype. Routes, courier status and ETAs are not real-world navigation or delivery guarantees. A person always confirms receipt.",
  },
  {
    subject: "Operational recommendations",
    label: "Demo" as const,
    body: "Priority scores, pressure bands and bag rankings are explainable prototype rules with their reasons shown. This is an operational engineering prototype. Recommendations are not clinical decisions or medical advice, and nothing is dispatched without a person confirming it.",
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
