"use client";

import type { BagScanResult } from "@veyra/api-client";
import Link from "next/link";
import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";

import { PageHeader } from "@/components/app/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardLabel } from "@/components/ui/card";
import { InlineAlert, Spinner, TextInput } from "@/components/ui/field";
import { SimulatedBadge } from "@/components/ui/simulated-badge";
import { EmptyState, ErrorState } from "@/components/ui/states";
import { api } from "@/lib/api";
import { BAG_STATUS, componentLabel, displayGroup, EVENT_LABEL, formatDate, formatDateTime, parseBagId } from "@/lib/network";
import { QR_DISCLAIMER } from "@/lib/phase8";
import { toFailure } from "@/lib/problem";
import { formatTemp } from "@/lib/telemetry";

// Minimal typing for the (optional) browser BarcodeDetector API.
interface DetectedCode {
  rawValue: string;
}
interface BarcodeDetectorLike {
  detect(source: HTMLVideoElement): Promise<DetectedCode[]>;
}
type BarcodeDetectorCtor = new (opts: { formats: string[] }) => BarcodeDetectorLike;

function detectorCtor(): BarcodeDetectorCtor | null {
  if (typeof window === "undefined") return null;
  const ctor = (window as unknown as { BarcodeDetector?: BarcodeDetectorCtor }).BarcodeDetector;
  return ctor ?? null;
}

export function cameraSupport(): "ok" | "no-camera" | "no-detector" {
  if (typeof navigator === "undefined" || !navigator.mediaDevices?.getUserMedia) return "no-camera";
  return detectorCtor() ? "ok" : "no-detector";
}

type LookupState =
  | { kind: "idle" }
  | { kind: "loading"; id: string }
  | { kind: "found"; result: BagScanResult }
  | { kind: "invalid"; message: string }
  | { kind: "not-found"; id: string }
  | { kind: "error"; message: string; payload: string };

const COLD: Record<string, { label: string; tone: "neutral" | "verified" | "warn" | "critical" }> = {
  unmonitored: { label: "Not monitored", tone: "neutral" },
  unknown: { label: "Awaiting readings", tone: "neutral" },
  normal: { label: "In range", tone: "verified" },
  warning: { label: "Warning", tone: "warn" },
  critical: { label: "Critical", tone: "critical" },
};

/**
 * Camera scanning (where the browser supports it) with manual entry as the fallback.
 * Frames are decoded in this browser only: nothing is stored or uploaded; only the decoded
 * text (a public bag id) is sent, and the API applies authentication and custody scope.
 */
function Camera({ onCode }: { onCode: (text: string) => void }) {
  const video = useRef<HTMLVideoElement>(null);
  const stream = useRef<MediaStream | null>(null);
  const timer = useRef<number | null>(null);
  const [state, setState] = useState<"off" | "starting" | "on" | "denied" | "failed">("off");
  const support = cameraSupport();

  const stop = useCallback(() => {
    if (timer.current !== null) window.clearInterval(timer.current);
    timer.current = null;
    stream.current?.getTracks().forEach((t) => t.stop());
    stream.current = null;
  }, []);

  useEffect(() => stop, [stop]);

  async function start() {
    const Ctor = detectorCtor();
    if (!Ctor) return;
    setState("starting");
    try {
      const s = await navigator.mediaDevices.getUserMedia({ video: { facingMode: "environment" }, audio: false });
      stream.current = s;
      if (video.current) {
        video.current.srcObject = s;
        await video.current.play().catch(() => undefined);
      }
      setState("on");
      const detector = new Ctor({ formats: ["qr_code"] });
      let busy = false;
      timer.current = window.setInterval(() => {
        if (busy || !video.current) return;
        busy = true;
        void detector
          .detect(video.current)
          .then((codes) => {
            const first = codes[0]?.rawValue;
            if (first) {
              stop();
              setState("off");
              onCode(first);
            }
          })
          .catch(() => undefined)
          .finally(() => {
            busy = false;
          });
      }, 250);
    } catch (e) {
      stop();
      setState(e instanceof DOMException && e.name === "NotAllowedError" ? "denied" : "failed");
    }
  }

  if (support !== "ok") {
    return (
      <InlineAlert tone="info" title="Camera scanning isn't available here">
        {support === "no-camera"
          ? "This browser can't open a camera. Type the bag ID printed under the QR instead."
          : "This browser can't decode QR codes from the camera. Type the bag ID printed under the QR instead."}
      </InlineAlert>
    );
  }
  return (
    <div className="flex flex-col gap-3">
      <div className={state === "on" || state === "starting" ? "block" : "hidden"}>
        <video
          ref={video}
          muted
          playsInline
          aria-label="Camera preview for QR scanning"
          className="aspect-square w-full max-w-sm rounded-md bg-ink object-cover"
        />
      </div>
      {state === "denied" && (
        <InlineAlert title="Camera permission denied">
          Allow camera access in your browser settings, or type the bag ID below.
        </InlineAlert>
      )}
      {state === "failed" && (
        <InlineAlert title="Camera couldn't start">Another app may be using it. Type the bag ID below instead.</InlineAlert>
      )}
      <div className="flex flex-wrap gap-2">
        {state === "on" || state === "starting" ? (
          <Button
            variant="secondary"
            onClick={() => {
              stop();
              setState("off");
            }}
          >
            Stop camera
          </Button>
        ) : (
          <Button variant="primary" onClick={() => void start()}>
            Scan with camera
          </Button>
        )}
        {state === "starting" && <Spinner />}
      </div>
      <p className="text-xs text-ink-subtle">Frames are decoded on this device and never stored or uploaded.</p>
    </div>
  );
}

export function ScanResultView({ result }: { result: BagScanResult }) {
  const { bag, cold_chain: cold, shipment, chain } = result;
  const status = BAG_STATUS[result.lifecycle_status] ?? { label: result.lifecycle_status, tone: "neutral" as const };
  const coldInfo = COLD[cold.status] ?? { label: cold.status, tone: "neutral" as const };
  return (
    <div className="flex flex-col gap-4" data-testid="scan-result">
      <Card>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <CardLabel>Bag</CardLabel>
            <p className="mt-1 font-mono text-lg font-medium">{result.public_id}</p>
            <p className="text-sm text-ink-muted">
              {displayGroup(bag.blood_group)} · {componentLabel(bag.component)} · {bag.volume_ml} ml
            </p>
          </div>
          <span className="font-display text-3xl text-vital">{displayGroup(bag.blood_group)}</span>
        </div>
        <dl className="mt-4 grid gap-3 text-sm sm:grid-cols-2">
          <div>
            <dt className="text-ink-subtle">Lifecycle</dt>
            <dd className="mt-1 flex flex-wrap gap-2">
              <Badge tone={status.tone} data-status={result.lifecycle_status}>
                {status.label}
              </Badge>
              {bag.is_expired && <Badge tone="critical">Expired</Badge>}
            </dd>
          </div>
          <div>
            <dt className="text-ink-subtle">Held by</dt>
            <dd className="mt-1 font-medium">{result.location || "—"}</dd>
          </div>
          <div>
            <dt className="text-ink-subtle">Collected / expires</dt>
            <dd className="mt-1">
              {formatDate(bag.collected_at)} → {formatDate(bag.expires_at)}
            </dd>
          </div>
          <div>
            <dt className="text-ink-subtle">Last event</dt>
            <dd className="mt-1">
              {result.last_event_type ? (EVENT_LABEL[result.last_event_type] ?? result.last_event_type) : "—"}
              {result.last_event_at && <span className="text-ink-subtle"> · {formatDateTime(result.last_event_at)}</span>}
            </dd>
          </div>
        </dl>
      </Card>
      <div className="grid gap-4 md:grid-cols-3">
        <Card>
          <CardLabel>Trace integrity</CardLabel>
          <p className="mt-2 font-medium" data-testid="scan-chain">
            {chain.valid ? `✓ Chain verified · ${chain.length} events` : "✕ Chain broken — treat the history as unreliable"}
          </p>
        </Card>
        <Card>
          <div className="flex items-center justify-between gap-2">
            <CardLabel>Cold chain</CardLabel>
            {cold.monitored && <SimulatedBadge subject="IoT sensor" />}
          </div>
          <p className="mt-2 flex flex-wrap items-center gap-2">
            <Badge tone={coldInfo.tone} data-status={cold.status}>
              {coldInfo.label}
            </Badge>
            {cold.excursion_active && <span className="text-sm text-critical">Excursion active</span>}
          </p>
          {cold.monitored && (
            <p className="mt-2 text-sm text-ink-muted">
              {cold.current_c !== null ? formatTemp(cold.current_c) : "No reading yet"}
              {cold.last_reading_at && ` · ${formatDateTime(cold.last_reading_at)}`}
            </p>
          )}
        </Card>
        <Card>
          <div className="flex items-center justify-between gap-2">
            <CardLabel>Shipment</CardLabel>
            {shipment && <SimulatedBadge subject="Logistics" />}
          </div>
          {shipment ? (
            <div className="mt-2 text-sm">
              <p className="font-medium">
                <Link className="underline" href={`/shipments/${shipment.id}`}>
                  {shipment.reference}
                </Link>{" "}
                · {shipment.status.replace("_", " ")}
              </p>
              <p className="text-ink-muted">
                {shipment.source_name} → {shipment.destination_name}
              </p>
              <p className="text-xs text-ink-subtle">
                Simulated ETA {formatDateTime(shipment.eta_at)}
                {shipment.delay_active && " · delayed"}
              </p>
            </div>
          ) : (
            <p className="mt-2 text-sm text-ink-muted">Not in a shipment.</p>
          )}
        </Card>
      </div>
      <div className="flex flex-wrap items-center gap-3">
        <Link href={result.trace_path} className="text-sm font-medium underline">
          Open the complete bag trace
        </Link>
        <span className="text-xs text-ink-subtle">
          {result.usable ? "Available and unexpired — still subject to human checks." : "Not available for use."}
        </span>
      </div>
    </div>
  );
}

export function BagScanner() {
  const [value, setValue] = useState("");
  const [state, setState] = useState<LookupState>({ kind: "idle" });
  const [inputError, setInputError] = useState<string | null>(null);

  const lookup = useCallback(async (payload: string) => {
    const id = parseBagId(payload);
    if (!id) {
      setState({ kind: "invalid", message: "That isn't a VEYRA bag label. Bag IDs look like VYR-7F3K-2QXM." });
      return;
    }
    setState({ kind: "loading", id });
    const { data, error, response } = await api.GET("/api/v1/bags/scan", { params: { query: { payload } } });
    if (data) setState({ kind: "found", result: data });
    else if (response?.status === 404) setState({ kind: "not-found", id });
    else if (response?.status === 422) setState({ kind: "invalid", message: toFailure(error, response).message });
    else setState({ kind: "error", message: toFailure(error, response).message, payload });
  }, []);

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    if (!value.trim()) {
      setInputError("Enter a bag ID like VYR-7F3K-2QXM.");
      return;
    }
    setInputError(null);
    void lookup(value);
  }

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        eyebrow="Traceability"
        title="Bag scanner"
        description="Scan a bag's QR label or type its ID to see its status, custody, cold chain and trace."
      />
      <div role="note" className="rounded-md bg-surface-sunken px-4 py-3 text-sm text-ink-muted" data-testid="qr-disclaimer">
        {QR_DISCLAIMER}
      </div>
      <div className="grid gap-4 md:grid-cols-2">
        <Card>
          <CardLabel>Scan QR</CardLabel>
          <div className="mt-3">
            <Camera
              onCode={(text) => {
                setValue(text);
                void lookup(text);
              }}
            />
          </div>
        </Card>
        <Card>
          <CardLabel>Enter bag ID</CardLabel>
          <form onSubmit={onSubmit} className="mt-3 flex flex-col gap-2" noValidate>
            <label htmlFor="scan-manual" className="text-sm font-medium">
              Bag ID or QR text
            </label>
            <div className="flex gap-2">
              <TextInput
                id="scan-manual"
                className="font-mono uppercase"
                placeholder="VYR-XXXX-XXXX"
                autoComplete="off"
                value={value}
                aria-invalid={Boolean(inputError)}
                aria-describedby={inputError ? "scan-manual-error" : undefined}
                onChange={(e) => {
                  setValue(e.target.value);
                  setInputError(null);
                }}
              />
              <Button type="submit" disabled={state.kind === "loading"}>
                Look up
              </Button>
            </div>
            {inputError && (
              <p id="scan-manual-error" role="alert" className="text-xs font-medium text-critical">
                {inputError}
              </p>
            )}
          </form>
        </Card>
      </div>
      <section aria-live="polite" aria-label="Scan result">
        {state.kind === "idle" && (
          <EmptyState title="Nothing scanned yet" description="Scan a label or enter a bag ID to see it here." />
        )}
        {state.kind === "loading" && (
          <p className="flex items-center gap-2 text-sm text-ink-muted" aria-busy="true">
            <Spinner /> Looking up {state.id}…
          </p>
        )}
        {state.kind === "invalid" && (
          <InlineAlert title="Not a VEYRA bag label">{state.message}</InlineAlert>
        )}
        {state.kind === "not-found" && (
          <EmptyState
            title="No bag found"
            description={`No bag you're authorized to see has the ID ${state.id}. Check the label, or ask the facility holding it.`}
          />
        )}
        {state.kind === "error" && (
          <ErrorState
            title="Lookup failed"
            description={state.message}
            action={
              <Button size="sm" variant="secondary" onClick={() => void lookup(state.payload)}>
                Try again
              </Button>
            }
          />
        )}
        {state.kind === "found" && <ScanResultView result={state.result} />}
      </section>
    </div>
  );
}
