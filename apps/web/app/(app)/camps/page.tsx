"use client";

import { RoleGate } from "@/components/app/app-shell";
import { CampManagement, DonorCamps } from "@/components/camps/camps";
import { LiveEventsProvider } from "@/lib/live";
import { useSession } from "@/lib/session";

function CampsForRole() {
  const { me } = useSession();
  const role = me?.user.role;
  if (role === "BLOOD_BANK" || role === "ADMIN") {
    return (
      <LiveEventsProvider>
        <CampManagement isAdmin={role === "ADMIN"} />
      </LiveEventsProvider>
    );
  }
  // Donors register; hospitals get a read-only view of published camps.
  return <DonorCamps canRegister={role === "DONOR"} />;
}

export default function CampsPage() {
  return (
    <RoleGate roles={["DONOR", "HOSPITAL", "BLOOD_BANK", "ADMIN"]}>
      <CampsForRole />
    </RoleGate>
  );
}
