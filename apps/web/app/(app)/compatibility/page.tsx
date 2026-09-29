"use client";

import { RoleGate } from "@/components/app/app-shell";
import { CompatibilityPage } from "@/components/compatibility/compatibility";

export default function Page() {
  return (
    <RoleGate roles={["HOSPITAL", "BLOOD_BANK", "ADMIN"]}>
      <CompatibilityPage />
    </RoleGate>
  );
}
