"use client";

import type { FacilityOut } from "@veyra/api-client";
import { useEffect, useState } from "react";

import { ComingInPhase, PageHeader } from "@/components/app/page-header";
import { TraceSearch } from "@/components/network/bag-trace";
import { DonationDesk } from "@/components/network/donation-desk";
import { IncomingRequests } from "@/components/network/incoming-requests";
import { InventoryOverview } from "@/components/network/inventory-overview";
import { LiveIndicator } from "@/components/network/live-indicator";
import { MyRequests } from "@/components/network/my-requests";
import { NewRequest } from "@/components/network/new-request";
import { Badge } from "@/components/ui/badge";
import { Card, CardLabel } from "@/components/ui/card";
import { InlineAlert } from "@/components/ui/field";
import { SimulatedBadge } from "@/components/ui/simulated-badge";
import { ErrorState, Skeleton } from "@/components/ui/states";
import { api } from "@/lib/api";
import { cn } from "@/lib/cn";
import { LiveEventsProvider, useLiveRefresh } from "@/lib/live";
import { toFailure } from "@/lib/problem";

const UPCOMING = {
  HOSPITAL: [
    { phase: 4, title: "Demand forecast", description: "An explainable forecast of your demand, labelled with the data it was trained on." },
    { phase: 6, title: "Emergency assistant", description: "Critical stock triggers sourcing across the network, with you in control." },
    { phase: 7, title: "Transport routing", description: "Courier assignment and live ETAs for dispatched bags." },
  ],
  BLOOD_BANK: [
    { phase: 5, title: "Donor outreach", description: "Invite eligible donors of the groups you are short of." },
    { phase: 8, title: "Signed QR & anchoring", description: "Signed QR labels and on-chain anchoring of the trace hashes." },
    { phase: 9, title: "Cold-chain monitoring", description: "Temperature telemetry and excursion alerts for storage and transport." },
  ],
} as const;

const TABS = {
  HOSPITAL: [
    { id: "request", label: "Request blood" },
    { id: "requests", label: "My requests" },
    { id: "stock", label: "Received stock" },
    { id: "trace", label: "Trace" },
  ],
  BLOOD_BANK: [
    { id: "inventory", label: "Inventory" },
    { id: "donations", label: "Donation desk" },
    { id: "incoming", label: "Incoming requests" },
    { id: "trace", label: "Trace" },
  ],
} as const;

type TabId = (typeof TABS)[keyof typeof TABS][number]["id"];

export function FacilityDashboard({ kind }: { kind: "HOSPITAL" | "BLOOD_BANK" }) {
  const [facility, setFacility] = useState<FacilityOut | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    void api.GET("/api/v1/facilities/me").then(({ data, error: apiError, response }) => {
      if (!active) return;
      if (data) setFacility(data);
      else setError(toFailure(apiError, response).message);
    });
    return () => {
      active = false;
    };
  }, []);

  if (error) return <ErrorState description={error} />;
  if (!facility) return <Skeleton className="h-48 w-full" />;

  return (
    <LiveEventsProvider>
      <PageHeader
        eyebrow={kind === "HOSPITAL" ? "Hospital" : "Blood bank"}
        title={facility.name}
        description={`${facility.address}, ${facility.city}, ${facility.state} ${facility.pin_code}`}
        actions={<LiveIndicator />}
      />
      <Card className="flex flex-wrap items-center gap-3">
        <CardLabel className="mr-2">Facility status</CardLabel>
        <Badge tone="verified" dot>
          {facility.status === "active" ? "Active" : facility.status}
        </Badge>
        <Badge>{facility.provider_kind === "internal" ? "Onboarded in VEYRA" : facility.provider_kind}</Badge>
        {facility.is_simulated && <SimulatedBadge subject="Facility" />}
        {facility.registration_number && (
          <span className="font-mono text-xs text-ink-subtle">Reg. {facility.registration_number}</span>
        )}
      </Card>
      <FacilityWorkspace kind={kind} />
      <div className="mt-10 grid gap-4 md:grid-cols-3">
        {UPCOMING[kind].map((m) => (
          <ComingInPhase key={m.title} {...m} />
        ))}
      </div>
    </LiveEventsProvider>
  );
}

function FacilityWorkspace({ kind }: { kind: "HOSPITAL" | "BLOOD_BANK" }) {
  const tabs = TABS[kind];
  const [tab, setTab] = useState<TabId>(tabs[0].id);
  const [created, setCreated] = useState<{ id: string; reference: string } | null>(null);
  const [incomingFlash, setIncomingFlash] = useState(0);
  useLiveRefresh(kind === "BLOOD_BANK" ? ["request.created"] : [], () => setIncomingFlash((n) => n + 1));

  return (
    <section className="mt-8">
      <div role="tablist" aria-label="Workspace" className="mb-6 flex flex-wrap gap-1 border-b border-line">
        {tabs.map((t) => (
          <button
            key={t.id}
            role="tab"
            id={`tab-${t.id}`}
            aria-selected={tab === t.id}
            aria-controls={`panel-${t.id}`}
            onClick={() => {
              setTab(t.id);
              if (t.id === "incoming") setIncomingFlash(0);
            }}
            className={cn(
              "-mb-px flex items-center gap-2 border-b-2 px-4 py-2.5 text-sm",
              tab === t.id ? "border-vital font-medium text-ink" : "border-transparent text-ink-muted hover:text-ink",
            )}
          >
            {t.label}
            {t.id === "incoming" && incomingFlash > 0 && tab !== "incoming" && (
              <Badge tone="critical">{incomingFlash} new</Badge>
            )}
          </button>
        ))}
      </div>
      <div role="tabpanel" id={`panel-${tab}`} aria-labelledby={`tab-${tab}`}>
        {tab === "inventory" && <InventoryOverview canDiscard />}
        {tab === "stock" && <InventoryOverview canDiscard={false} />}
        {tab === "donations" && <DonationDesk />}
        {tab === "incoming" && <IncomingRequests />}
        {tab === "request" && (
          <NewRequest
            onCreated={(r) => {
              setCreated({ id: r.id, reference: r.reference });
              setTab("requests");
            }}
          />
        )}
        {tab === "requests" && (
          <div className="flex flex-col gap-4">
            {created && (
              <InlineAlert tone="success">
                Request <span className="font-mono">{created.reference}</span> sent.
              </InlineAlert>
            )}
            <MyRequests highlight={created?.id ?? null} />
          </div>
        )}
        {tab === "trace" && (
          <Card className="max-w-xl">
            <TraceSearch />
            <p className="mt-3 text-xs text-ink-subtle">
              You can trace bags your facility holds or has held. Each trail is a tamper-evident hash
              chain stored in VEYRA.
            </p>
          </Card>
        )}
      </div>
    </section>
  );
}
