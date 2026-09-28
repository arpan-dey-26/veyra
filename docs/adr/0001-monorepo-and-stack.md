# ADR-0001: Monorepo and core stack

- Status: Accepted (2026-09-28)

## Decision
One pnpm-workspace monorepo. The frontend is Next.js (App Router, TypeScript strict, Tailwind v4). The backend is Python 3.12 + FastAPI, managed with uv. The data layer is PostgreSQL 16 and Redis. The API contract is shared through a generated TypeScript client (`@veyra/api-client`).

## Why
Keeping ML, blockchain (web3.py) and LLM SDKs in one backend language avoids a second service. OpenAPI generation keeps the frontend and backend from drifting apart. A single repo makes phase-by-phase changes atomic.

## Consequences
Two toolchains (Node + Python). On Windows, development runs in WSL2.
