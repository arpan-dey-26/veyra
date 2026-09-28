# ADR-0005: Provenance and honest demo labelling

- Status: Accepted (2026-09-28)

## Decision
Every provider-backed payload includes `SourceMeta {provider, kind, simulated}`, where `kind` is `internal | simulated | synthetic | external`. The UI must render `SimulatedBadge` when `simulated` is true, and must show `DemoRibbon` in every non-production environment. Production config refuses demo verification.

## Why
Credibility. Mock or synthetic systems must never be presented as real integrations.
