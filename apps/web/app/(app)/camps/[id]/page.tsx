"use client";

import { useParams } from "next/navigation";

import { RoleGate } from "@/components/app/app-shell";
import { CampDetail, PublicCampDetail } from "@/components/camps/camps";
import { LiveEventsProvider } from "@/lib/live";
import { useSession } from "@/lib/session";

function CampForRole({ id }: { id: string }) {
  const { me } = useSession();
  const role = me?.user.role;
  if (role === "BLOOD_BANK" || role === "ADMIN") {
    return (
      <LiveEventsProvider>
        <CampDetail campId={id} />
      </LiveEventsProvider>
    );
  }
  return <PublicCampDetail campId={id} canRegister={role === "DONOR"} />;
}

export default function CampPage() {
  const params = useParams<{ id: string }>();
  const id = decodeURIComponent(params.id ?? "");
  return (
    <RoleGate roles={["DONOR", "HOSPITAL", "BLOOD_BANK", "ADMIN"]}>
      <CampForRole id={id} />
    </RoleGate>
  );
}
