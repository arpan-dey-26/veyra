# VEYRA — Intelligent Blood Network

VEYRA is a prototype of an intelligent blood-supply network. It connects donors, blood banks, hospitals and administrators, with traceable blood bags, demand forecasting, emergency logistics and privacy-preserving eligibility.

> **Prototype status.** VEYRA is a student engineering prototype, not a certified medical system. Every simulated or demo component (mock blood banks, synthetic ML data, simulated IoT, local blockchain, demo verification) is labelled as such in the API and UI. See [`docs/demo-disclosures.md`](docs/demo-disclosures.md).

## Current phase

**Phase 6: operational intelligence & emergency response (prototype).**

- Explainable operational priority for every request: a score, a band (immediate / high / standard), a recommended action and the structured reasons behind them. No hidden model, and not a clinical score.
- Allocation recommendations for blood banks: exact-match candidates, ranked by cold-chain concern then FEFO, each with its reasons. **Nothing is dispatched automatically.** Staff confirm through the existing dispatch action, optionally with the recommended bag ids.
- Operational pressure: real stock and open requests against the synthetic forecast ("Synthetic forecast input — prototype").
- Deterministic simulated routing and ETAs ("Simulated routing — prototype").
- Scoped `/operations/*` API. Live events: `request.operational_alert`, `request.priority_changed`, `allocation.recommendation_updated`, `routing.updated`, `forecast.pressure_changed`, `cold_chain.operational_alert`.
- New Operations tab for blood banks and hospitals, and network emergency activity for admins.
- This is an operational engineering prototype. Recommendations are not clinical decisions or medical advice. See the [Phase 6 report](docs/phase-reports/phase-6.md).

Phase 5, still in place: **simulated IoT blood-bag telemetry & cold-chain traceability (prototype).**

- A simulated smart-bag device (device id `SIM-XXXX-XXXX`, simulated RFID, battery, last seen) can be attached to a bag. A deterministic demo simulator takes readings, runs live, pauses, injects an excursion and restores normal temperature. No hardware is involved.
- Prototype thresholds per component (normal / warning / critical). Current, min, max, excursion start, duration and recovery are tracked.
- Excursions and recoveries are recorded in the bag's append-only, SHA-256 hash-chained trace without changing the bag's lifecycle status.
- Scoped reads: `/bags/{id}/telemetry`, `/telemetry/summary`, `/cold-chain`, `/device`, plus `/telemetry/monitored`. Separate CSRF-protected simulator endpoints under `/simulator/bags/{id}/…` are open only to the facility holding the bag and are disabled in production.
- Live SSE topics: `telemetry.updated`, `temperature.warning`, `temperature.critical`, `temperature.recovered`.
- There is a blood-bank **Cold chain** tab, a telemetry panel on `/bags/[publicId]`, and an admin network card.
- Labelled everywhere: **"Simulated IoT telemetry — prototype"**. It is not a certified medical monitoring system. See the [Phase 5 report](docs/phase-reports/phase-5.md).

Phase 4, still in place: ML demand forecasting (synthetic, prototype).

- Deterministic synthetic demand generator, a transparent seasonal baseline and a pure-Python gradient-boosted model, compared on a chronological split. The model artifact is versioned and reproducible (`uv run python -m app.scripts.train_forecast --check`).
- Scoped read-only API: `/forecast/demand`, `/forecast/summary`, `/forecast/model`.
- Forecast tab for hospitals and blood banks (with blood-bank supply vs forecast), and a network forecast plus model evaluation for admins.
- Everything is labelled **"Synthetic ML forecast — prototype"**. It is not clinical guidance. See the [model card](docs/model-cards/demand-forecast.md).

Phase 3, still in place: dashboards & UX.

- Role dashboards with charts from real API data: donor impact, hospital and blood-bank overviews, admin network overview with system health and an audit summary.
- **Live Blood Network 2D** (`/network`): a scoped, schematic facility graph updated live over SSE. It is a "Prototype network visualization — not a geographic map."
- Landing page v1: purpose, workflow, roles, security and privacy principles, what is simulated, and a prototype disclaimer.

Phase 2, still in place:

- Blood-bank donation desk: find a verified donor, record a collection, create labelled bags (`VYR-XXXX-XXXX`, QR payload `veyra:bag:<id>`).
- Facility inventory by blood group × component, with expiry (72 h warning) and discard.
- Hospital blood requests: banded network availability (never exact stock), idempotent submission, first-expiry-first-out dispatch, receipt.
- Append-only, SHA-256 hash-chained custody trail per bag (tamper-evident in the database; **not** a blockchain, on-chain anchoring is Phase 8).
- Blood-bank provider port: internal banks, plus **simulated** partner banks (`MockBloodBankProvider`, labelled "Simulated", refused in production).
- Transactional outbox → Server-Sent Events, with a live indicator in the UI.

Phase 1 (still in place): donor registration with **demo** phone verification (last 4 digits of the mobile, labelled, never presented as OTP), Argon2id passwords, rotating refresh sessions, CSRF protection, permission + scope RBAC, admin facility onboarding and staff invitations.

See the [Phase 6 report](docs/phase-reports/phase-6.md), [Phase 5 report](docs/phase-reports/phase-5.md), [Phase 4 report](docs/phase-reports/phase-4.md), [Phase 3 report](docs/phase-reports/phase-3.md), [Phase 2 report](docs/phase-reports/phase-2.md), [Phase 1 report](docs/phase-reports/phase-1.md), [Phase 0 report](docs/phase-reports/phase-0.md) and the [architecture](docs/architecture/phase0-architecture.md).

Demo sign-ins after `scripts\bootstrap.cmd` (**DEMO ONLY**, password `veyra-demo-console-2026` for all three):

| Role | Email |
| --- | --- |
| Administrator | `admin@veyra.demo` |
| Blood bank (VEYRA Central Blood Bank, Demo) | `bank@veyra.demo` |
| Hospital (VEYRA City Hospital, Demo) | `hospital@veyra.demo` |

Donors self-register at `/register`.

## Repository layout

```
apps/api/               FastAPI modular monolith (Python 3.12)
apps/web/               Next.js (App Router, TypeScript, Tailwind v4)
packages/design-tokens/ VEYRA design tokens (CSS variables + TS motion tokens)
packages/api-client/    OpenAPI-generated TypeScript client for the API
infra/                  docker-compose + Dockerfiles
docs/                   architecture, ADRs, disclosures, phase reports
```

These folders arrive in later phases: `ml/`, `contracts/`, `zk/`, `simulators/iot/`.

## Prerequisites

- Node.js ≥ 22 and pnpm ≥ 10 (`corepack enable`)
- Python ≥ 3.12 and [uv](https://docs.astral.sh/uv/)
- Docker (optional, for Postgres + Redis). On Windows use **WSL2** + Docker Desktop.

## Quick start

```bash
cp .env.example .env              # never commit .env
pnpm install
(cd apps/api && uv sync)

# Option A: everything in Docker
docker compose -f infra/docker-compose.yml up --build

# Option B: run locally (Postgres/Redis optional in Phase 0)
make api-dev                      # http://localhost:8000  (docs at /docs outside production)
make web-dev                      # http://localhost:3000
```

## Common commands

| Command | What it does |
|---|---|
| `make test` | API tests (pytest) + web tests (vitest) |
| `make lint` | ruff + mypy + eslint + tsc |
| `make gen-api` | Export OpenAPI from the API and regenerate `@veyra/api-client` |
| `make migrate` | Apply Alembic migrations |

## Engineering rules (short version)

1. Routers → services → repositories. Nothing else touches the database.
2. Every endpoint checks permission **and** scope (from Phase 1).
3. Schema changes go through Alembic migrations only.
4. Anything simulated carries `simulated: true` and a visible UI label.
5. Secrets come from environment variables only. `.env` is git-ignored.
6. Changes to foundation contracts require an ADR (`docs/adr/`).
