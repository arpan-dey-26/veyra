"use client";

import { useParams } from "next/navigation";

import { AcceptInviteForm } from "@/components/auth/accept-invite-form";

export default function InvitePage() {
  const params = useParams<{ token: string }>();
  return (
    <>
      <h1 className="font-display text-display-sm leading-(--leading-tight) tracking-(--tracking-display)">
        Join your facility on VEYRA
      </h1>
      <p className="mt-3 mb-8 text-ink-muted">Set up your staff account.</p>
      <AcceptInviteForm token={params.token} />
    </>
  );
}
