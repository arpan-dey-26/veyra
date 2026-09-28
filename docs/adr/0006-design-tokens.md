# ADR-0006: Design tokens as a frozen contract

- Status: Accepted (2026-09-28)

## Decision
`packages/design-tokens/src/tokens.css` is the source of truth for colour roles, type, space, radius, elevation and motion. Tailwind utilities map to it through `@theme inline`. JS-facing motion values are mirrored in `index.ts`, and a test keeps the two in sync. Under `prefers-reduced-motion`, every duration is 0.

## Identity
"Clinical calm, one vital colour":
- warm neutrals carry the interface
- oxblood *vital* is used for blood meaning
- *critical* is used only for true emergencies
- plasma-teal *verified* signals integrity
- slate-indigo *simulated* is used only for demo labels

All text colours meet WCAG AA, enforced by a test.
