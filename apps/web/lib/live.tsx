"use client";

import type { NetworkEvent } from "@veyra/api-client";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";

export type LiveStatus = "connecting" | "live" | "reconnecting" | "offline";

type Listener = (event: NetworkEvent) => void;

interface LiveContextValue {
  status: LiveStatus;
  lastEventAt: Date | null;
  subscribe: (topics: string[] | "*", listener: Listener) => () => void;
}

const LiveContext = createContext<LiveContextValue | null>(null);

export const STREAM_URL = "/api/v1/stream";
export const TOPICS = [
  "inventory.updated",
  "bag.discarded",
  "request.created",
  "request.dispatched",
  "request.fulfilled",
  "request.rejected",
  "request.cancelled",
  // Phase 5: simulated IoT telemetry / cold chain
  "telemetry.updated",
  "temperature.warning",
  "temperature.critical",
  "temperature.recovered",
  // Phase 6: operational intelligence (prototype)
  "request.priority_changed",
  "request.operational_alert",
  "allocation.recommendation_updated",
  "routing.updated",
  "forecast.pressure_changed",
  "cold_chain.operational_alert",
  // Phase 7: simulated logistics
  "shipment.created",
  "shipment.picked_up",
  "shipment.in_transit",
  "shipment.delayed",
  "shipment.resumed",
  "shipment.checkpoint_reached",
  "shipment.arrived",
  "shipment.received",
  "shipment.cold_chain_alert",
] as const;

/**
 * One EventSource per signed-in facility tab. The browser reconnects on its own and resends
 * Last-Event-ID, so missed events are replayed from the outbox. Events are de-duplicated by id.
 */
export function LiveEventsProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<LiveStatus>(() =>
    typeof EventSource === "undefined" ? "offline" : "connecting",
  );
  const [lastEventAt, setLastEventAt] = useState<Date | null>(null);
  const listeners = useRef(new Set<{ topics: string[] | "*"; listener: Listener }>());
  const seen = useRef(new Set<string>());

  useEffect(() => {
    if (typeof EventSource === "undefined") return;
    const source = new EventSource(STREAM_URL, { withCredentials: true });
    source.onopen = () => setStatus("live");
    source.onerror = () =>
      setStatus(source.readyState === EventSource.CLOSED ? "offline" : "reconnecting");
    const handle = (message: MessageEvent<string>) => {
      let event: NetworkEvent;
      try {
        event = JSON.parse(message.data) as NetworkEvent;
      } catch {
        return;
      }
      if (seen.current.has(event.event_id)) return;
      seen.current.add(event.event_id);
      if (seen.current.size > 500) seen.current.clear();
      setLastEventAt(new Date());
      for (const { topics, listener } of listeners.current) {
        if (topics === "*" || topics.includes(event.topic)) listener(event);
      }
    };
    for (const topic of TOPICS) source.addEventListener(topic, handle);
    return () => source.close();
  }, []);

  const subscribe = useCallback((topics: string[] | "*", listener: Listener) => {
    const entry = { topics, listener };
    listeners.current.add(entry);
    return () => {
      listeners.current.delete(entry);
    };
  }, []);

  const value = useMemo<LiveContextValue>(
    () => ({ status, lastEventAt, subscribe }),
    [status, lastEventAt, subscribe],
  );

  return <LiveContext.Provider value={value}>{children}</LiveContext.Provider>;
}

const noopSubscribe = () => () => undefined;
const OFFLINE: LiveContextValue = { status: "offline", lastEventAt: null, subscribe: noopSubscribe };

export function useLive(): LiveContextValue {
  return useContext(LiveContext) ?? OFFLINE;
}

/** Re-run `onEvent` whenever one of `topics` arrives (e.g. to refetch a list). */
export function useLiveRefresh(topics: string[], onEvent: () => void): void {
  const { subscribe } = useLive();
  const callback = useRef(onEvent);
  useEffect(() => {
    callback.current = onEvent;
  });
  const key = topics.join("|");
  useEffect(() => subscribe(key.split("|"), () => callback.current()), [subscribe, key]);
}
