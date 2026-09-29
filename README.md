# VEYRA — Intelligent Blood Network

VEYRA is a prototype of an intelligent blood-supply network. It connects donors, blood banks, hospitals and administrators, with traceable blood bags, demand forecasting, emergency logistics and privacy-preserving eligibility.

> **Prototype status.** VEYRA is a student engineering prototype, not a certified medical system. Every simulated or demo component (mock blood banks, synthetic ML data, simulated IoT, local blockchain, demo verification) is labelled as such in the API and UI. See [`docs/demo-disclosures.md`](docs/demo-disclosures.md).

## Current phase

**Phase 3: Dashboards & UX** (on top of the Phase 2 core blood network and Phase 1 auth & RBAC).

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

See the [Phase 3 report](docs/phase-reports/phase-3.md), [Phase 2 report](docs/phase-reports/phase-2.md), [Phase 1 report](docs/phase-reports/phase-1.md), [Phase 0 report](docs/phase-reports/phase-0.md) and the [architecture](docs/architecture/phase0-architecture.md).

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
