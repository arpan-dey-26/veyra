"use client";

import { RoleGate } from "@/components/app/app-shell";
import { DonorDashboard } from "@/components/donor/donor-dashboard";

export default function DonorPage() {
  return (
    <RoleGate roles={["DONOR"]}>
      <DonorDashboard />
    </RoleGate>
  );
}
