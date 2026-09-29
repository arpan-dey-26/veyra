"use client";

import type { MeResponse } from "@veyra/api-client";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import { api, SESSION_EXPIRED_EVENT } from "@/lib/api";

export type SessionStatus = "loading" | "authenticated" | "anonymous" | "error";

interface SessionValue {
  status: SessionStatus;
  me: MeResponse | null;
  /** Re-read /auth/me (the client refreshes an expired access token on its own). */
  reload: () => Promise<MeResponse | null>;
  /** Replace the cached session after sign-in/verification responses. */
  setMe: (me: MeResponse | null) => void;
  signOut: () => Promise<void>;
}

const SessionContext = createContext<SessionValue | null>(null);

async function fetchMe(): Promise<{ status: SessionStatus; me: MeResponse | null }> {
  try {
    const { data, response } = await api.GET("/api/v1/auth/me");
    if (data) return { status: "authenticated", me: data };
    return { status: response.status === 401 ? "anonymous" : "error", me: null };
  } catch {
    return { status: "error", me: null };
  }
}

export function SessionProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<{ status: SessionStatus; me: MeResponse | null }>({
    status: "loading",
    me: null,
  });

  useEffect(() => {
    let active = true;
    void fetchMe().then((next) => {
      if (active) setState(next);
    });
    const onExpired = () => setState({ status: "anonymous", me: null });
    window.addEventListener(SESSION_EXPIRED_EVENT, onExpired);
    return () => {
      active = false;
      window.removeEventListener(SESSION_EXPIRED_EVENT, onExpired);
    };
  }, []);

  const reload = useCallback(async () => {
    const next = await fetchMe();
    setState(next);
    return next.me;
  }, []);

  const setMe = useCallback((me: MeResponse | null) => {
    setState({ status: me ? "authenticated" : "anonymous", me });
  }, []);

  const signOut = useCallback(async () => {
    try {
      await api.POST("/api/v1/auth/logout");
    } finally {
      setState({ status: "anonymous", me: null });
    }
  }, []);

  const value = useMemo(
    () => ({ ...state, reload, setMe, signOut }),
    [state, reload, setMe, signOut],
  );
  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession(): SessionValue {
  const ctx = useContext(SessionContext);
  if (!ctx) throw new Error("useSession must be used inside <SessionProvider>");
  return ctx;
}

/** Like useSession, but returns null outside a provider (for components also rendered standalone). */
export function useOptionalSession(): SessionValue | null {
  return useContext(SessionContext);
}
