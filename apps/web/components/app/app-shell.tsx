"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, type ReactNode } from "react";

import { Wordmark } from "@/components/brand/wordmark";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/states";
import { cn } from "@/lib/cn";
import { homeFor, isRole, ROLE_LABEL } from "@/lib/roles";
import { useSession } from "@/lib/session";

/** Authenticated frame: guards the route (UX only; the API enforces access) and shows the user. */
export function AppShell({ children }: { children: ReactNode }) {
  const { status, me, signOut } = useSession();
  const router = useRouter();
  const pathname = usePathname();

  useEffect(() => {
    if (status === "anonymous") {
      router.replace(`/sign-in?next=${encodeURIComponent(pathname)}`);
    }
  }, [status, pathname, router]);

  if (status !== "authenticated" || !me) {
    return (
      <div className="mx-auto max-w-(--layout-max) px-(--gutter) py-10" aria-busy="true">
        {status === "error" ? (
          <p role="alert" className="text-sm text-critical">
            VEYRA is unreachable right now. Refresh to try again.
          </p>
        ) : (
          <div className="flex flex-col gap-4">
            <Skeleton className="h-8 w-48" />
            <Skeleton className="h-40 w-full" />
          </div>
        )}
      </div>
    );
  }

  const role = me.user.role;
  const home = homeFor(role);

  return (
    <div className="min-h-dvh bg-surface">
      <header className="sticky top-0 z-30 border-b border-line bg-surface/90 backdrop-blur-sm">
        <div className="mx-auto flex max-w-(--layout-max) items-center justify-between gap-4 px-(--gutter) py-3">
          <div className="flex items-center gap-6">
            <Link href={home} aria-label="VEYRA dashboard">
              <Wordmark />
            </Link>
            <nav aria-label="App" className="hidden items-center gap-1 text-sm sm:flex">
              <Link
                href={home}
                className={cn(
                  "rounded-pill px-3 py-1.5",
                  pathname === home ? "bg-surface-sunken text-ink" : "text-ink-muted hover:text-ink",
                )}
              >
                Overview
              </Link>
            </nav>
          </div>
          <div className="flex items-center gap-3">
            <div className="hidden text-right sm:block">
              <p className="text-sm leading-tight font-medium">{me.user.full_name}</p>
              <p className="text-xs leading-tight text-ink-subtle">{me.user.email}</p>
            </div>
            <Badge tone={role === "ADMIN" ? "neutral" : "vital"}>
              {isRole(role) ? ROLE_LABEL[role] : role}
            </Badge>
            <Button
              size="sm"
              variant="ghost"
              onClick={async () => {
                await signOut();
                router.replace("/sign-in");
              }}
            >
              Sign out
            </Button>
          </div>
        </div>
      </header>
      <main id="main" className="veyra-rise mx-auto max-w-(--layout-max) px-(--gutter) py-8 sm:py-10">
        {children}
      </main>
    </div>
  );
}

/** Renders children only for the given roles; others are sent to their own home. */
export function RoleGate({ roles, children }: { roles: string[]; children: ReactNode }) {
  const { me } = useSession();
  const router = useRouter();
  const allowed = !!me && roles.includes(me.user.role);

  useEffect(() => {
    if (me && !allowed) router.replace(homeFor(me.user.role));
  }, [me, allowed, router]);

  return allowed ? <>{children}</> : null;
}
