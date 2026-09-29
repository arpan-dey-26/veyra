"use client";

import type { BagQr } from "@veyra/api-client";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardLabel } from "@/components/ui/card";
import { Retry } from "@/components/ui/retry";
import { Skeleton } from "@/components/ui/states";
import { api } from "@/lib/api";
import { QR_DISCLAIMER } from "@/lib/phase8";
import { toFailure } from "@/lib/problem";

const QUIET = 4;

/** Crisp SVG of a QR module matrix (from the API's deterministic encoder), with quiet zone. */
export function QrSvg({ modules, label, size = 200 }: { modules: string[]; label: string; size?: number }) {
  const n = modules.length + QUIET * 2;
  const path = modules
    .flatMap((row, y) =>
      [...row].map((c, x) => (c === "1" ? `M${x + QUIET} ${y + QUIET}h1v1h-1z` : "")).filter(Boolean),
    )
    .join("");
  return (
    <svg
      role="img"
      aria-label={label}
      viewBox={`0 0 ${n} ${n}`}
      width={size}
      height={size}
      shapeRendering="crispEdges"
      className="rounded-sm"
      data-testid="bag-qr-svg"
    >
      {/* Always dark-on-white, also in dark mode: scanners need the contrast. */}
      <rect width={n} height={n} fill="#ffffff" />
      <path d={path} fill="#000000" />
    </svg>
  );
}

/** "Show QR" on the bag page: fetched on demand; printable label with the public id only. */
export function BagQrCard({ publicId, payload }: { publicId: string; payload: string }) {
  const [open, setOpen] = useState(false);
  const [qr, setQr] = useState<BagQr | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    setError(null);
    const { data, error: e, response } = await api.GET("/api/v1/bags/{public_id}/qr", {
      params: { path: { public_id: publicId } },
    });
    if (data) setQr(data);
    else setError(toFailure(e, response).message);
  }

  return (
    <Card className="print:shadow-none" data-testid="bag-qr-card">
      <CardLabel>QR label</CardLabel>
      <p className="mt-2 font-mono text-sm break-all">{payload}</p>
      <p className="mt-1 text-xs text-ink-subtle">Printed on the bag; scanning it opens this trace for authorized staff.</p>
      {!open ? (
        <Button
          size="sm"
          variant="secondary"
          className="mt-3 print:hidden"
          onClick={() => {
            setOpen(true);
            void load();
          }}
        >
          Show QR
        </Button>
      ) : error ? (
        <div className="mt-3">
          <Retry title="QR unavailable" error={error} onRetry={() => void load()} />
        </div>
      ) : !qr ? (
        <Skeleton className="mt-3 size-[200px]" />
      ) : (
        <div className="mt-3 flex flex-col items-start gap-2">
          <QrSvg modules={qr.modules} label={`QR label for bag ${qr.public_id}`} />
          <p className="font-mono text-sm font-medium">{qr.public_id}</p>
          <p className="text-xs text-ink-subtle">{QR_DISCLAIMER}</p>
          <Button size="sm" variant="ghost" className="print:hidden" onClick={() => window.print()}>
            Print label
          </Button>
        </div>
      )}
    </Card>
  );
}
