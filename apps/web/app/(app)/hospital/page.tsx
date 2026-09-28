"use client";

import { RoleGate } from "@/components/app/app-shell";
import { FacilityDashboard } from "@/components/facility/facility-dashboard";

export default function HospitalPage() {
  return (
    <RoleGate roles={["HOSPITAL"]}>
      <FacilityDashboard kind="HOSPITAL" />
    </RoleGate>
  );
}
