/**
 * Typed mirrors of the CSS tokens that JavaScript needs (motion libraries, canvas/3D, charts).
 * tokens.css is the source of truth; a unit test keeps these values in sync with it.
 */

export const duration = {
  instant: 100,
  fast: 180,
  base: 280,
  slow: 520,
  story: 900,
  pulse: 2400,
} as const;

export type DurationToken = keyof typeof duration;

/** Cubic-bezier control points, usable by Motion/GSAP (`ease: easing.standard`). */
export const easing = {
  standard: [0.2, 0, 0, 1],
  emphasized: [0.05, 0.7, 0.1, 1],
  exit: [0.3, 0, 1, 1],
} as const satisfies Record<string, readonly [number, number, number, number]>;

export type EasingToken = keyof typeof easing;

export const breakpoints = { sm: 640, md: 768, lg: 1024, xl: 1280 } as const;

/** Semantic colour roles, referenced by name so JS never hardcodes hex values. */
export const colorRoles = [
  "surface",
  "surface-raised",
  "surface-sunken",
  "ink",
  "ink-muted",
  "ink-subtle",
  "line",
  "line-strong",
  "vital",
  "vital-strong",
  "vital-soft",
  "on-vital",
  "critical",
  "critical-soft",
  "verified",
  "verified-soft",
  "warn",
  "warn-soft",
  "simulated",
  "simulated-soft",
  "focus",
] as const;

export type ColorRole = (typeof colorRoles)[number];

export const cssVar = (role: ColorRole): string => `var(--color-${role})`;

/** Seconds, for libraries (Motion/GSAP) that take seconds; returns 0 when motion is reduced. */
export const seconds = (token: DurationToken, reducedMotion = false): number =>
  reducedMotion ? 0 : duration[token] / 1000;
