import type { Role } from "@veyra/api-client";

export const ROLE_HOME: Record<Role, string> = {
  DONOR: "/donor",
  HOSPITAL: "/hospital",
  BLOOD_BANK: "/blood-bank",
  ADMIN: "/admin",
};

export const ROLE_LABEL: Record<Role, string> = {
  DONOR: "Donor",
  HOSPITAL: "Hospital",
  BLOOD_BANK: "Blood bank",
  ADMIN: "Administrator",
};

export function isRole(value: string): value is Role {
  return value in ROLE_HOME;
}

export function homeFor(role: string): string {
  return isRole(role) ? ROLE_HOME[role] : "/";
}

/** Only allow same-site relative redirects (prevents open redirects via ?next=). */
export function safeNext(next: string | null | undefined): string | null {
  if (!next || !next.startsWith("/") || next.startsWith("//") || next.includes("\\")) return null;
  return next;
}
