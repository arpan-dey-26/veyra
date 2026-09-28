/**
 * Signature motif (Phase 0 preview of the Live Blood Network):
 * many donors → blood bank → transport → hospital, drawn as vein-like paths with a
 * pulse travelling along each. Purpose: communicate the chain of custody at a glance.
 *
 * Pure SVG + CSS: no JS animation, no dependencies. Under prefers-reduced-motion the
 * pulses are removed and the static network remains fully legible.
 */

type Segment = { id: string; d: string; delay: number };

const SEGMENTS: Segment[] = [
  { id: "d1-bank", d: "M60 92 C 140 92, 170 190, 250 200", delay: 0 },
  { id: "d2-bank", d: "M40 222 C 120 222, 170 205, 250 200", delay: 1.2 },
  { id: "d3-bank", d: "M80 352 C 160 352, 180 215, 250 200", delay: 2.4 },
  { id: "bank-transit", d: "M250 200 C 320 195, 350 140, 420 150", delay: 1.6 },
  { id: "transit-hospital", d: "M420 150 C 500 160, 520 255, 580 262", delay: 3.2 },
];

const LABEL = "font-mono text-[11px] tracking-[0.06em] uppercase";

export function FlowLines({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 640 440"
      className={className}
      role="img"
      aria-labelledby="veyra-flow-title veyra-flow-desc"
      data-testid="flow-lines"
    >
      <title id="veyra-flow-title">The VEYRA network</title>
      <desc id="veyra-flow-desc">
        Donations from several donors flow into a blood bank, then travel by transport to a hospital.
      </desc>

      {/* base veins */}
      <g fill="none" strokeLinecap="round">
        {SEGMENTS.map((s) => (
          <path key={s.id} d={s.d} stroke="var(--color-line-strong)" strokeWidth="1.5" />
        ))}
      </g>

      {/* travelling pulses */}
      <g fill="none" strokeLinecap="round">
        {SEGMENTS.map((s) => (
          <path
            key={`${s.id}-pulse`}
            d={s.d}
            pathLength={100}
            className="veyra-flow-pulse"
            stroke="var(--color-vital)"
            strokeWidth="2.5"
            style={{ animationDelay: `${s.delay}s` }}
          />
        ))}
      </g>

      {/* nodes */}
      {[
        [60, 92],
        [40, 222],
        [80, 352],
      ].map(([cx, cy]) => (
        <circle key={`${cx}-${cy}`} cx={cx} cy={cy} r="4.5" fill="var(--color-ink-subtle)" />
      ))}

      <circle cx="250" cy="200" r="13" fill="var(--color-verified-soft)" />
      <circle cx="250" cy="200" r="6.5" fill="var(--color-verified)" />

      <circle cx="420" cy="150" r="5.5" fill="var(--color-surface-raised)" stroke="var(--color-ink)" strokeWidth="1.5" />

      <circle className="veyra-beacon" cx="580" cy="262" r="8" fill="var(--color-vital)" />
      <circle cx="580" cy="262" r="8" fill="var(--color-vital)" />

      {/* labels */}
      <g fill="var(--color-ink-muted)">
        <text x="40" y="392" className={LABEL}>Donors</text>
        <text x="222" y="238" className={LABEL}>Blood bank</text>
        <text x="392" y="128" className={LABEL}>Transport</text>
        <text x="540" y="300" className={LABEL}>Hospital</text>
      </g>
    </svg>
  );
}
