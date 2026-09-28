"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";

import { homeFor } from "@/lib/roles";
import { useSession } from "@/lib/session";

/** /dashboard → the signed-in user's role home. */
export default function DashboardRedirect() {
  const { me } = useSession();
  const router = useRouter();
  useEffect(() => {
    if (me) router.replace(homeFor(me.user.role));
  }, [me, router]);
  return null;
}
