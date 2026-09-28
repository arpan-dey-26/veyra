"use client";

import { useParams } from "next/navigation";

import { RoleGate } from "@/components/app/app-shell";
import { BagTraceView } from "@/components/network/bag-trace";
import { LiveEventsProvider } from "@/lib/live";

export default function BagTracePage() {
  const params = useParams<{ publicId: string }>();
  const publicId = decodeURIComponent(params.publicId ?? "").toUpperCase();
  return (
    <RoleGate roles={["HOSPITAL", "BLOOD_BANK", "ADMIN"]}>
      <LiveEventsProvider>
        <BagTraceView publicId={publicId} />
      </LiveEventsProvider>
    </RoleGate>
  );
}
