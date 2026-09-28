"use client";

import { AdminDashboard } from "@/components/admin/admin-dashboard";
import { RoleGate } from "@/components/app/app-shell";

export default function AdminPage() {
  return (
    <RoleGate roles={["ADMIN"]}>
      <AdminDashboard />
    </RoleGate>
  );
}
