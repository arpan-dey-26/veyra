"use client";

import { PageHeader } from "@/components/app/page-header";
import { RoleGate } from "@/components/app/app-shell";
import { LiveNetwork, NETWORK_DISCLAIMER } from "@/components/network/live-network";
import { LiveEventsProvider } from "@/lib/live";
import { useSession } from "@/lib/session";

export default function NetworkPage() {
  const { me } = useSession();
  const admin = me?.user.role === "ADMIN";
  return (
    <RoleGate roles={["HOSPITAL", "BLOOD_BANK", "ADMIN"]}>
      <LiveEventsProvider>
        <PageHeader
          eyebrow="Live network"
          title="Blood network, live"
          description={`${NETWORK_DISCLAIMER} Lines are requests from the last 30 days; pulses move as requests are raised, dispatched and received.`}
        />
        <LiveNetwork scopeLabel={admin ? "Network-wide (administrator)" : "Scoped to your facility"} />
      </LiveEventsProvider>
    </RoleGate>
  );
}
