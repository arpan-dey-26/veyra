import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

import { colorRoles, duration, easing, seconds } from "./index";

const css = readFileSync(fileURLToPath(new URL("./tokens.css", import.meta.url)), "utf8");
const lightBlock = css.slice(css.indexOf(":root {"), css.indexOf("@media (prefers-color-scheme"));

function hex(role: string, block: string): string {
  const m = block.match(new RegExp(`--color-${role}:\\s*(#[0-9a-f]{6})`, "i"));
  if (!m?.[1]) throw new Error(`missing --color-${role}`);
  return m[1];
}

function luminance(h: string): number {
  const [r, g, b] = [1, 3, 5].map((i) => {
    const c = parseInt(h.slice(i, i + 2), 16) / 255;
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  }) as [number, number, number];
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

function contrast(a: string, b: string): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x) as [number, number];
  return (hi + 0.05) / (lo + 0.05);
}

describe("design tokens", () => {
  it("TS durations mirror tokens.css", () => {
    for (const [name, ms] of Object.entries(duration)) {
      expect(css).toContain(`--dur-${name}: ${ms}ms;`);
    }
  });

  it("TS easings mirror tokens.css", () => {
    for (const [name, pts] of Object.entries(easing)) {
      expect(css).toContain(`--ease-${name}: cubic-bezier(${pts.join(", ")});`);
    }
  });

  it("every colour role exists in light, dark(media) and dark(forced) themes", () => {
    const darkForced = css.slice(css.indexOf(':root[data-theme="dark"]'));
    const darkMedia = css.slice(
      css.indexOf("@media (prefers-color-scheme"),
      css.indexOf(':root[data-theme="dark"]'),
    );
    for (const role of colorRoles) {
      expect(lightBlock, role).toContain(`--color-${role}:`);
      expect(darkMedia, role).toContain(`--color-${role}:`);
      expect(darkForced, role).toContain(`--color-${role}:`);
    }
  });

  it("reduced motion zeroes every duration", () => {
    const reduced = css.slice(css.indexOf("@media (prefers-reduced-motion: reduce)"));
    for (const name of Object.keys(duration)) {
      expect(reduced).toContain(`--dur-${name}: 0ms;`);
    }
    expect(seconds("slow", true)).toBe(0);
    expect(seconds("slow")).toBeCloseTo(0.52);
  });

  it("text colours meet WCAG AA on light surfaces", () => {
    const surface = hex("surface", lightBlock);
    const raised = hex("surface-raised", lightBlock);
    for (const role of ["ink", "ink-muted", "ink-subtle", "vital", "verified", "warn", "simulated"]) {
      expect(contrast(hex(role, lightBlock), surface), role).toBeGreaterThanOrEqual(4.5);
      expect(contrast(hex(role, lightBlock), raised), role).toBeGreaterThanOrEqual(4.5);
    }
    expect(contrast(hex("on-vital", lightBlock), hex("vital", lightBlock))).toBeGreaterThanOrEqual(4.5);
  });
});
