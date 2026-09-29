"use client";

import { RoleGate } from "@/components/app/app-shell";
import { BagScanner } from "@/components/scan/bag-scanner";

export default function ScanPage() {
  return (
    <RoleGate roles={["HOSPITAL", "BLOOD_BANK", "ADMIN"]}>
      <BagScanner />
    </RoleGate>
  );
}
