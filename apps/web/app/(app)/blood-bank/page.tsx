"use client";

import { RoleGate } from "@/components/app/app-shell";
import { FacilityDashboard } from "@/components/facility/facility-dashboard";

export default function BloodBankPage() {
  return (
    <RoleGate roles={["BLOOD_BANK"]}>
      <FacilityDashboard kind="BLOOD_BANK" />
    </RoleGate>
  );
}
