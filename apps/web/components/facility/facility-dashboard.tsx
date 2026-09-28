"use client";

import type { FacilityOut } from "@veyra/api-client";
import { useEffect, useState } from "react";

import { ComingInPhase, PageHeader } from "@/components/app/page-header";
import { Badge } from "@/components/ui/badge";
import { Card, CardLabel } from "@/components/ui/card";
import { SimulatedBadge } from "@/components/ui/simulated-badge";
import { ErrorState, Skeleton } from "@/components/ui/states";
import { api } from "@/lib/api";
import { toFailure } from "@/lib/problem";

const UPCOMING = {
  HOSPITAL: [
    { phase: 2, title: "Inventory & blood requests", description: "Your stock by group and component, and requests to partner blood banks." },
    { phase: 4, title: "Demand forecast", description: "An explainable forecast of your demand, labelled with the data it was trained on." },
    { phase: 6, title: "Emergency assistant", description: "Critical stock triggers sourcing across the network, with you in control." },
  ],
  BLOOD_BANK: [
    { phase: 2, title: "Inventory & incoming requests", description: "Bags in storage, expiry-first, and requests from hospitals." },
    { phase: 8, title: "Bag traceability", description: "QR identity and a tamper-evident custody trail for every bag." },
    { phase: 9, title: "Cold-chain monitoring", description: "Temperature telemetry and excursion alerts for storage and transport." },
  ],
} as const;

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
    <>
      <PageHeader
        eyebrow={kind === "HOSPITAL" ? "Hospital" : "Blood bank"}
        title={facility.name}
        description={`${facility.address}, ${facility.city}, ${facility.state} ${facility.pin_code}`}
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
      <div className="mt-6 grid gap-4 md:grid-cols-3">
        {UPCOMING[kind].map((m) => (
          <ComingInPhase key={m.title} {...m} />
        ))}
      </div>
    </>
  );
}
