"use client";

import { useParams } from "next/navigation";

import { RoleGate } from "@/components/app/app-shell";
import { ShipmentDetailView } from "@/components/logistics/logistics";
import { LiveEventsProvider } from "@/lib/live";

export default function ShipmentPage() {
  const params = useParams<{ id: string }>();
  const id = decodeURIComponent(params.id ?? "");
  return (
    <RoleGate roles={["HOSPITAL", "BLOOD_BANK", "ADMIN"]}>
      <LiveEventsProvider>
        <ShipmentDetailView shipmentId={id} />
      </LiveEventsProvider>
    </RoleGate>
  );
}
