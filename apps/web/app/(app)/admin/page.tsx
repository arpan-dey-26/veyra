"use client";

import { AdminDashboard } from "@/components/admin/admin-dashboard";
import { RoleGate } from "@/components/app/app-shell";
import { LiveEventsProvider } from "@/lib/live";

export default function AdminPage() {
  return (
    <RoleGate roles={["ADMIN"]}>
      <LiveEventsProvider>
        <AdminDashboard />
      </LiveEventsProvider>
    </RoleGate>
  );
}
