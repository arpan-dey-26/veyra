# VEYRA — Phase 0 Architecture Report

**VEYRA — Intelligent Blood Network** · Status: Phase 0 approved (architecture + foundation scaffolding)
Date: 2026-09-28 · Author: Lead architect (Claude) for Arpan

> Naming (confirmed): the product is **VEYRA** — *Intelligent Blood Network*. It is used for UI, docs, packages (`@veyra/*`, `veyra-api`), env vars (`VEYRA_*`) and seed/demo branding. There is no separate sub-brand.

---

## A. Current project assessment

What I inspected, and what I found:

| Location | Finding |
|---|---|
| Cloud workspace (`/home/claude`) | Only tooling caches and config. **No source code.** |
| Uploaded files | **None.** |
| claude.ai Project "VEYRA" | Description only. **No docs, files or instructions.** |
| Your computer (desktop-n5cgubq, Windows x64) | **No folder connected** to this session. Folder names in Desktop, Documents and Downloads include `marigold`, `codeguard-ai-*`, `hiver-phase0_3`, `StayVista-*` and `arpan-portfolio-foundation_8`. **None is named VEYRA, VEYRA or blood-anything.** I could not see file contents. |

**Conclusion:** No VEYRA codebase exists that I can see. This is a **greenfield** project. So far nothing has been built, nothing is at risk of breaking, and there's no legacy to preserve.

**If a repo does exist elsewhere** (another drive, GitHub or a private folder), connect it with "Add folder" before Phase 1. (Superseded: the user confirmed greenfield; code lives in the connected `veyra` folder.)

**What "should not be changed later":** there is no existing code to protect. What *does* become frozen is the set of **foundation contracts** this report defines. After Phase 1 lands, these change only through an explicit ADR (Architecture Decision Record):

1. Monorepo layout and module boundaries (§R)
2. `AuthContext` + permission-string RBAC model (§H)
3. ID strategy (UUIDv7 internal; separate public IDs for bags) and UTC `timestamptz` everywhere
4. API envelope, error format and versioning prefix `/api/v1` (§I)
5. Provider interfaces (§P): method signatures only; implementations are free to change
6. Domain event names and payload shape (`bag.status_changed`, etc.)
7. Design tokens (color, type, spacing, motion) (§Q)
8. Database naming conventions and migration-only schema changes (§F)

---

## B. Recommended final tech stack

| Layer | Choice | Why |
|---|---|---|
| Monorepo | **pnpm workspaces** (+ `uv` for Python) | One repo, and shared API types stay in sync. Turborepo/Nx is overkill for one developer over 11 days. |
| Frontend | **Next.js (App Router, current stable) + TypeScript (strict)** | File-based route groups map cleanly to roles. SSR helps the landing page's SEO and first paint. Largest ecosystem for motion and 3D. |
| Styling | **Tailwind CSS v4 + CSS variables for design tokens** | Tokens live in CSS, so theming, dark mode and reduced motion are central. Tailwind keeps spacing disciplined. |
| Components | **Radix primitives (via shadcn/ui, copied in, then restyled)** | Accessible by default (focus, ARIA, keyboard). We own the code, so the visual identity stays original. |
| Motion | **Motion (formerly Framer Motion)** for UI + **GSAP ScrollTrigger** only on marketing scroll stories + **Lenis** (marketing pages only) | Motion handles layout, presence and gestures in React. GSAP is best-in-class for scrubbed scroll timelines. Restricting each to its job avoids two libraries fighting over the same element. |
| 3D | **React Three Fiber + drei**, lazy-loaded | Declarative Three.js in React. Loaded only on the hero and the Network view, with a static poster fallback. |
| Charts | **visx** (custom) + **Recharts** for standard dashboards | visx for signature charts (demand forecast with interval bands, telemetry); Recharts for fast standard ones. |
| Maps | **MapLibre GL JS** | Open source, no mandatory vendor key, WebGL performance. |
| Data fetching | **TanStack Query** + generated TS client from OpenAPI | Caching, retries and optimistic updates. The generated client means the frontend cannot drift from the backend schema. |
| Client state | **Zustand** (small, UI-only) | Server state lives in TanStack Query. Zustand is only for UI state (panels, filters). No Redux. |
| Forms | **React Hook Form + Zod** | Fast, typed. Zod schemas mirror backend Pydantic rules for instant UX feedback; **the backend stays authoritative.** |
| Backend | **Python 3.12 + FastAPI**, modular monolith | ML (scikit-learn/XGBoost/SHAP), blockchain (web3.py) and AI SDKs are all first-class in Python. One backend language instead of Node API + Python ML sidecar. Pydantic v2 validation and automatic OpenAPI. |
| ORM / migrations | **SQLAlchemy 2.0 (async) + Alembic** | Mature, explicit and repository-friendly. Every schema change is a migration. |
| Database | **PostgreSQL 16** | Relational integrity for a chain-of-custody domain. JSONB for flexible payloads. Handles IoT volume at prototype scale with partitioning and BRIN indexes. |
| Cache / realtime / jobs | **Redis** (pub/sub + rate limits) + **ARQ** (async job queue) | SSE fan-out, background jobs (agent steps, anchoring, retraining) and rate limiting. ARQ is lighter than Celery and async-native. |
| Realtime transport | **Server-Sent Events (SSE)** | Dashboards need server→client streams only. SSE works over plain HTTP, auto-reconnects and is simpler than WebSockets. |
| ML | **scikit-learn, XGBoost (or LightGBM), SHAP, pandas** | Explainable gradient-boosted models on tabular time features. SHAP gives per-prediction explanations. |
| AI | **Provider-agnostic LLM adapter** (Anthropic / OpenAI / Gemini / deterministic Mock) | Avoids vendor lock-in. The Mock provider makes tests deterministic and lets the demo run without keys. |
| Blockchain | **Solidity + Hardhat** (local chain); optional **public EVM testnet** (e.g. Polygon Amoy) | Free, fast and reproducible for the demo. The testnet is a config switch, not a rewrite. |
| ZKP | **Circom + snarkjs (Groth16)** | The most documented toolchain. Proofs are generated in the browser (private data never leaves the device). snarkjs exports a Solidity verifier. |
| QR | `qrcode` (Python, server-side generation) + `@zxing/browser` (scan) | Proven, small libraries. |
| Local infra | **Docker Compose** (Postgres, Redis, Hardhat node, optional Mosquitto) | One command to start everything. **Required on your Windows machine:** run via **WSL2** (Circom and Hardhat tooling are painful natively on Windows). |
| CI | **GitHub Actions** | Lint, type-check, test and build on every push. |

**Explicitly rejected (for now):** microservices (too much operational cost for 11 days); GraphQL (REST + OpenAPI is enough, and simpler to secure per endpoint); MongoDB (chain-of-custody needs relational constraints); Kafka (Redis pub/sub is enough at prototype scale); LSTM as default (see §K); Hyperledger/private permissioned chains (heavy setup, and an EVM local chain proves the same concept).

---

## C. Architecture diagram (text)

```
                               ┌────────────────────────────────────────────────┐
                               │                 apps/web (Next.js)             │
                               │ (marketing) (auth) (app)/donor|hospital|bank|admin │
                               │ Design system · Motion · R3F · MapLibre · SSE   │
                               └───────────────▲───────────────┬────────────────┘
                                   generated TS client (OpenAPI) │ HTTPS, httpOnly cookies
                                               │               ▼
┌──────────────────────────────────────────────┴──────────────────────────────────────────────┐
│                               apps/api (FastAPI modular monolith)                            │
│                                                                                               │
│  Middleware: request-id · CORS · rate limit · CSRF · auth → AuthContext · audit · error map   │
│                                                                                               │
│  Routers (/api/v1) ─► Services (business rules + RBAC policy checks) ─► Repositories (SQL)    │
│                                                                                               │
│  Domain modules:  identity · donors · facilities · inventory · donations · bags · requests    │
│                   emergency · logistics · telemetry · ledger · eligibility · forecasting      │
│                   assistant · notifications · analytics · reports · audit · admin             │
│                                                                                               │
│  AI layer:  LLM adapter ◄─► Tool Registry (typed, permissioned) ──► Services (never repos)     │
│  Agent:     Emergency state machine + Policy engine (autonomy levels) ──► Services            │
│  ML:        Model registry loader ──► Forecast service (artifacts produced by /ml pipeline)   │
│                                                                                               │
│  Provider ports (interfaces)                                                                  │
│   Verification │ BloodBank │ Routing │ Telemetry source │ Ledger │ LLM │ Notification │ ZK    │
│   Demo/Mock ✓  │ Mock ✓    │ Mock ✓  │ Simulator ✓      │ Hardhat│ Mock│ In-app ✓     │ snarkjs│
│   Real later → │ Internal ✓│ OSRM/ORS│ HTTP/MQTT device │ Testnet│ Real│ Email/SMS    │       │
└───────┬────────────────┬───────────────────┬───────────────────┬──────────────┬──────────────┘
        │                │                   │                   │              │
   PostgreSQL 16      Redis             ARQ workers        Hardhat / EVM    External APIs
 (OLTP + telemetry   (pub/sub, rate    (agent steps,      (TraceRegistry,   (LLM, routing,
  partitions, audit)  limits, cache)    anchoring, ML)     EligibilityVerifier) maps, SMS later)

   simulators/iot ──HTTP (HMAC-signed)──► /api/v1/telemetry/ingest
   ml/ (offline pipeline) ──► model artifacts + metadata ──► api loads by version
   zk/ (circuits) ──► wasm + zkey to web, verifier.sol to contracts/
```

Data flow for traceability:

```
Donor ─► Donation ─► BloodBag(public_id, QR) ─► Storage(bank) ─► Transport ─► Hospital receipt
                          │                         │               │
                          └── bag_events (append-only, hash-chained) ◄── telemetry windows (Merkle root)
                                              │
                                   periodic anchor ─► TraceRegistry contract (hash only, no PII)
```

---

## D. Frontend architecture

**Route groups (Next.js App Router)**

```
app/
  (marketing)/          landing, about-the-network, how-it-works, privacy, demo-disclaimer
  (auth)/               sign-in, register (donor), verify, facility-onboarding
  (app)/
    layout.tsx          authenticated shell: nav, command palette, notifications, SSE provider
    donor/              overview, donations, eligibility, rewards, notifications, profile
    hospital/           overview, inventory, requests, emergency, forecast, assistant, reports
    blood-bank/         overview, inventory, incoming, outgoing, bags, transport, telemetry
    admin/              network, users, facilities, audit, system, config
    network/            Live Blood Network (role-filtered view)
    trace/[publicId]/   bag trace page (QR landing; public view shows no PII)
```

**Layering rules**

- `features/<domain>/`: queries, mutations, components and hooks for one domain. Features never import from other features' internals. They share via `components/` or `lib/`.
- `components/ui/`: design-system primitives (Button, Card, Stat, Badge, Sheet, DataTable, EmptyState, Skeleton).
- `components/motion/`: motion primitives (`Reveal`, `Counter`, `Magnetic`, `PageTransition`, `Pulse`, `StatusBeacon`). All of them respect reduced motion.
- `components/viz/`: Network, Route, Telemetry and Forecast renderers. These are **pure presentational components that take normalized DTOs** (see "Live Blood Network" below).
- `lib/api/`: the generated OpenAPI client plus TanStack Query key factories.
- `lib/realtime/`: one SSE connection per session, multiplexed by topic, feeding the Query cache.

**Why:** a feature-sliced structure lets each phase add a folder without touching previous phases. That matters most for backward compatibility between phases.

**Route protection:** Next.js middleware redirects based on a lightweight role claim, **for UX only**. Every authorization decision is re-checked by the API. The frontend is never trusted.

**Live Blood Network (signature experience), decoupled design**

```
API  /api/v1/network/snapshot  → NetworkSnapshot { nodes[], edges[], transports[], alerts[], generated_at }
API  /api/v1/stream?topics=network → NetworkEvent deltas (node.stock_changed, transport.moved, bag.verified…)
        │
lib/network/store.ts   (applies deltas to snapshot; pure functions, unit-tested)
        │
components/viz/network/
   NetworkCanvas2D   (SVG/Canvas: default, mobile, reduced motion)
   NetworkScene3D    (R3F: desktop, lazy)
   NetworkMap        (MapLibre: geographic mode)
```

The visualization knows nothing about SQL, roles or providers. It renders a DTO. Role filtering (for example, hospitals see stock *levels*, never donor identities) happens in the API serializer.

---

## E. Backend architecture

**Style:** modular monolith with a strict three-layer rule inside each module:

```
router.py      HTTP only: parse, validate (Pydantic), call service, map to response schema
service.py     business rules, RBAC policy checks, transactions, domain events
repository.py  the ONLY place that touches SQLAlchemy sessions/queries
models.py      ORM models        schemas.py  Pydantic I/O     policies.py  permission rules
```

**Rules:**

- Routers never import repositories.
- AI tools and agents call **services**, never repositories. So the same RBAC and validation apply to humans and AI.
- Cross-module calls go through the other module's service interface, not its tables.
- Side effects (notifications, anchoring, SSE) are triggered by **domain events** published after commit (transactional outbox table → worker). A crash cannot emit an event for a rolled-back transaction.

**Why a monolith:** one deploy, one database transaction boundary, and trivial local debugging. Module boundaries give us microservice-style separation without the network cost. Any module could be extracted later.

**Cross-cutting core (`app/core/`):** settings (pydantic-settings, env-only), DB session, security (hashing, tokens, CSRF), structured JSON logging with request ID, error types → RFC 9457 problem responses, rate limiting, pagination, clock abstraction (for testable time), and ID generation.

---

## F. Database architecture

- **PostgreSQL 16**, a single database with schemas grouping domains: `identity`, `network`, `trace`, `telemetry`, `ai`, `ml`, `audit`.
- **Conventions:** `snake_case`, plural table names, UUIDv7 primary keys (time-ordered, index-friendly), `created_at`/`updated_at` as `timestamptz` UTC, soft delete only where legally or operationally needed (`deleted_at`), and CHECK constraints for enums at the DB level too.
- **Sensitive columns:** donor medical and screening fields are encrypted at application level (AES-GCM via `cryptography`, key from env/KMS) and stored in a **separate table** (`donor_health_records`) that only the donor and authorized blood-bank screeners can reach. Hospitals have no path to it.
- **Append-only tables:** `bag_events`, `audit_logs` and `telemetry_readings` get no UPDATE or DELETE. This is enforced by DB role grants plus a trigger. Each `bag_events` and `audit_logs` row stores `prev_hash` and `row_hash` (a tamper-evident hash chain) *before* anything touches a blockchain.
- **Telemetry:** `telemetry_readings` is range-partitioned by month with a BRIN index on `recorded_at`. **TimescaleDB is optional** and only needed if volume demands it (it won't at demo scale).
- **Geo:** lat/lng columns plus a haversine SQL function to start. PostGIS is deferred until we need polygons or complex spatial queries. For about 50 facilities, haversine is exact enough.
- **Migrations:** Alembic only. There is never a manual schema change. Seed data comes from idempotent scripts, clearly labelled `DEMO`.

**Why Postgres over NoSQL:** chain of custody is fundamentally relational (a bag belongs to a donation, is held by a facility, is moved by a transport). Foreign keys and transactions protect integrity. JSONB covers the flexible parts (event payloads, agent step data).

---

## G. Authentication architecture

**Registration (donor):** full name, email, mobile (E.164, +91 default), blood group (enum), address, city, state (enum of Indian states/UTs), PIN code (6 digits, regex-validated), password.

**Password security:**

- **Argon2id** (via `argon2-cffi` / `pwdlib`) with a pepper from env.
- Minimum length 10, checked against a small common-password list, and never logged.

**Why Argon2id:** it is the current OWASP-recommended default and memory-hard, which resists GPU cracking.

**Verification: a pluggable port, not hardcoded logic**

```python
class VerificationProvider(Protocol):
    async def start(self, channel: Channel, destination: str, purpose: Purpose) -> ChallengeRef
    async def verify(self, ref: ChallengeRef, code: str) -> VerificationResult
    is_demo: bool
```

- `DemoLast4VerificationProvider` (active in the prototype): the "code" is the last 4 digits of the registered mobile number. `is_demo=True`.
  - The UI **must** show: *"Demo verification only. The last 4 digits of your mobile number are used for prototype verification instead of a real OTP."*
  - The API response includes `verification_mode: "demo"`, so the UI cannot silently hide it.
  - It is **disabled when `APP_ENV=production`**: startup fails if the demo provider is configured in production.
  - Rate-limited and attempt-limited anyway (5 attempts / 15 minutes), so the flow's shape matches a real OTP.
- `SmsOtpVerificationProvider` (future): real random 6-digit code, hashed at rest, 5-minute TTL, provider adapter (e.g. an Indian DLT-registered SMS gateway). **Swapping it in is a config change.** The auth service only knows the interface.

**Sessions**

- Short-lived **access token** (JWT, 15 min, signed with rotating keys, `kid` header) plus a **refresh token** (opaque, random, stored *hashed* in `sessions`, rotated on every use, with reuse detection that revokes the whole family).
- Both are delivered as **httpOnly, Secure, SameSite=Lax cookies**. The web app calls the API through a same-origin proxy (`/api/*` → FastAPI) so cookies stay first-party.
- **CSRF:** double-submit token header on all state-changing requests.

**Why cookies over localStorage tokens:** an XSS bug cannot exfiltrate httpOnly tokens.

**Facility accounts (hospital / blood bank):** created by an Admin invite (not self-registration). The invite token is single-use with a 72h TTL. Facility users are linked to a `facility_id` through `facility_memberships`. **Why:** anyone could otherwise register as a "hospital" and request blood.

---

## H. RBAC architecture

**Model:** roles → permission strings, plus **resource scoping** (ownership / facility membership). Role alone is never enough. Every check is `permission AND scope`.

```
AuthContext { user_id, role, facility_id?, permissions: frozenset[str], session_id, is_demo_account }
```

Permissions are `resource:action[:scope]`. Examples:

| Permission | DONOR | HOSPITAL | BLOOD_BANK | ADMIN |
|---|:-:|:-:|:-:|:-:|
| `donor_profile:read:self` / `update:self` | ✓ | | | |
| `donation:read:self` | ✓ | | | |
| `eligibility:prove:self` | ✓ | | | |
| `donor_health:read` (screening data) | self only | ✗ **never** | ✓ own-bank donors, screener only | ✗ (break-glass, audited) |
| `inventory:read:own_facility` | | ✓ | ✓ | |
| `inventory:update:own_facility` | | ✓ | ✓ | |
| `inventory:read:network_aggregate` (levels only, no donor links) | | ✓ | ✓ | ✓ |
| `blood_request:create` | | ✓ | | |
| `blood_request:respond` | | | ✓ | |
| `emergency:create` / `emergency:approve_dispatch` | | ✓ | ✓ (respond) | ✓ |
| `bag:read:custody` (bags it holds or held) | | ✓ | ✓ | ✓ |
| `bag:transition` | | ✓ (receive) | ✓ | |
| `forecast:read:own_facility` | | ✓ | ✓ | ✓ |
| `telemetry:read:own_facility` | | ✓ | ✓ | ✓ |
| `user:manage`, `facility:manage`, `config:manage`, `audit:read` | | | | ✓ |

**Enforcement points:**

1. Route dependency `require("inventory:update:own_facility")` rejects early.
2. The service applies the scope (`WHERE facility_id = ctx.facility_id`), so a hospital cannot pass another hospital's ID.
3. **Response serializers are role-specific.** A hospital viewing a bag gets `blood_group, component, expiry, custody chain (facility names)`, never donor name or contact details. The trace chain references `donation_id` as opaque.
4. Admins do **not** get raw donor health data by default. Break-glass access requires a reason and writes a high-severity audit entry.

**Why permission strings instead of `if role == ...`:** roles change (e.g. adding a "Transport Operator" or "Screener" role later) without touching business code. Tests can assert a full permission matrix.

**Tests:** a parametrized RBAC matrix (every endpoint × every role × own/other resource) runs in CI. This test suite is the security boundary's contract.

---

## I. API architecture

- REST, JSON, under `/api/v1`. OpenAPI generated by FastAPI, and a **TS client generated** from it (`openapi-typescript` + `openapi-fetch`).
- **Success:** resource or `{ data, meta: { page, page_size, total } }` for lists (cursor pagination for event streams).
- **Errors:** RFC 9457 `application/problem+json` → `{ type, title, status, detail, code, request_id, errors[] }`. Stack traces are never returned.
- **Idempotency:** `Idempotency-Key` header required on `POST` for requests, emergencies, dispatches and bag transitions. Keys are stored for 24h. **Why:** emergency flows get retried, and a double dispatch is a real-world failure.
- **Concurrency:** optimistic locking (`version` column) on inventory and bag state, so two banks cannot allocate the same bag.
- **Realtime:** `GET /api/v1/stream?topics=...` (SSE). Topics are authorized per `AuthContext`.
- **Demo transparency:** any response built from simulated or mock providers carries `"source": {"provider": "mock_blood_bank", "simulated": true}`. The UI renders a "Simulated" badge from this field.
- **Versioning:** breaking changes go to `/api/v2`. Phases are additive only.

---

## J. AI architecture

```
User ─► /assistant/messages (SSE stream)
          │
     AssistantOrchestrator
          ├─ builds system prompt (role-aware, no secrets, no raw data dumps)
          ├─ LLMProvider (Anthropic | OpenAI | Gemini | MockLLM)
          │        ▲  tool_call(name, args)
          ▼        │  tool_result (sanitized DTO)
     ToolRegistry ─┘
          ├─ each Tool = { name, description, input_schema (Pydantic), required_permission, handler }
          ├─ validates args → checks ctx permission → calls SERVICE with the user's AuthContext
          ├─ result passes through the same role-specific serializer (no PII leakage)
          └─ writes ai_tool_calls audit row (args, latency, outcome; truncated)
```

**Initial tools (read-only):** `get_hospital_inventory`, `search_blood_bank_availability`, `get_demand_forecast`, `get_bag_status`, `get_emergency_status`, `generate_report` (returns a report job ID).

**Hard boundaries:**

- **No SQL, no repository access and no free-form HTTP** from the LLM. The model only sees tools the user's role permits (the tool list is filtered per `AuthContext`).
- **Write actions are never executed by the assistant directly.** Tools like `draft_blood_request` return a *proposal* the user confirms in the UI. The confirmation hits the normal API with normal RBAC.
- **Prompt-injection hygiene:** tool results are wrapped as data. Free-text fields from other users (notes, names) are delimited and marked untrusted. Max tool-call depth is 5 per turn, with a token and cost budget per user per day.
- **Honest failure:** if no LLM key is configured, `MockLLM` answers from deterministic intent rules and the UI shows "Offline assistant (demo mode)".

**Why this split (LLM reasoning ≠ tools ≠ database):** the LLM becomes one more *client* of our service layer, subject to identical authorization. Tools are unit-testable without any LLM.

---

## K. ML architecture

```
ml/
  data/generate_synthetic.py   documented generator (seed-fixed), labeled SYNTHETIC
  features/                    calendar, lags (1,7,14,28), rolling means/std, holidays/festivals,
                               seasonal flags (e.g. monsoon/dengue season → platelets), facility size
  models/baseline.py           seasonal-naive + moving average  (the bar to beat)
  models/gbm.py                XGBoost/LightGBM per (blood_group × component), quantile objective
  evaluate.py                  walk-forward (rolling-origin) CV; MAE, MAPE, sMAPE, interval coverage
  explain.py                   SHAP global + per-prediction top factors
  export.py                    joblib artifact + model_card.json (data, metrics, version, created_at)
api/app/modules/forecasting    loads a pinned model version; /forecast endpoints; caches results
```

**Data honesty:**

- We have **no real hospital demand data**. The pipeline trains on a **synthetic dataset with documented assumptions** (weekly cycle, seasonal peaks, festival and accident-weekend effects, trauma-centre vs district-hospital scale).
- Every prediction response carries `model_version`, `trained_on: "synthetic"`, metrics and a prediction interval. The UI shows "Model trained on synthetic data".
- These are **real model outputs on synthetic training data**, never random numbers. The pipeline accepts a real CSV with the same schema later without code changes.

**Model choice and why:**

- Gradient-boosted trees on lag and calendar features usually beat or match LSTMs on short, multi-series tabular demand data. They train in seconds, and SHAP makes them explainable.
- **Acceptance gate:** the GBM must beat the seasonal-naive baseline on walk-forward MAE, or we ship the baseline and say so.
- **LSTM is excluded** unless evaluation justifies it. Random Forest is kept as a comparison model in the evaluation report.

**Serving:** in-process in the API (loaded at startup from `ML_MODEL_DIR`). **Why:** at this scale, a separate model server adds latency and operations with no benefit. Retraining runs as an ARQ job or CLI, and a model is promoted by updating `ml.model_versions.is_active`.

---

## L. Autonomous emergency logistics agent

**Design:** a **deterministic state machine** plus a **policy engine**. The LLM is optional and only used for explanation text. **Why:** emergency logistics must be auditable, reproducible and safe. A free-running LLM loop is none of those.

```
DETECTED ─► ASSESSING ─► SOURCING ─► AWAITING_CONFIRMATION ─► DISPATCH_REQUESTED
   ▲                                     │ (human/bank confirms)         │
 trigger:                               ▼                               ▼
 inventory < critical threshold     REJECTED/EXPIRED ─► SOURCING(next)   IN_TRANSIT ─► DELIVERED
 or manual emergency                                                        │
                                                                   FAILED / CANCELLED (any state)
```

**Steps:**

1. **Detect:** an inventory event or a scheduled check compares stock with the facility's threshold and the forecast (if available).
2. **Assess:** compute units needed, urgency and the time window.
3. **Source:** `BloodBankProvider.search_availability()` across providers. Rank by (compatible units, ETA from `RoutingProvider`, expiry-first/FEFO, reliability score).
4. **Request:** send a `blood_request` to the top candidate(s) with idempotency keys and a response deadline.
5. **Transport:** get routes and ETA, then create a `transport` record.
6. **Track:** subscribe to bag events and telemetry, and escalate on delay or temperature excursion.

**Autonomy levels (configured per facility by Admin):**

| Level | Agent may… |
|---|---|
| L0 Advise | Only recommend. A human performs every action. (**Default**) |
| L1 Assisted | Draft requests. A human clicks confirm. |
| L2 Bounded auto | Auto-send requests (never auto-dispatch) within limits: ≤ N units, only to pre-approved partner banks, and only when urgency is critical. |

**Boundaries:**

- The agent runs with a **service identity** (`agent:emergency`) whose permissions are a strict subset of the hospital's.
- Every step is persisted in `agent_runs` / `agent_run_steps` (inputs, decision, rationale and outputs), so the run is replayable and shows up in the UI timeline.
- There is a kill switch in admin config.

---

## M. Blockchain architecture

**Principle:** the chain stores **commitments, not data**. No PII, no raw readings.

**Contracts (`contracts/`):**

- `TraceRegistry.sol`
  - `anchor(bytes32 batchRoot, uint64 fromSeq, uint64 toSeq, bytes32 kind)` emits `Anchored`.
  - Callable only by the backend's anchoring key (Ownable / AccessControl).
- `EligibilityVerifier.sol`: generated by snarkjs (Groth16 verifier), used in §O.

**Flow:**

```
bag_events / telemetry windows (DB, hash-chained)
   → every K minutes or N events: build Merkle tree of row_hashes
   → anchor(root) on chain  → store tx_hash, block, root in ledger_anchors
Verification (UI "Verify integrity"):
   recompute row hashes from DB → Merkle proof → compare with on-chain root → ✓ / ✗ tampered
```

**Why batching with Merkle roots:** one transaction covers thousands of events (cheap and fast). Any single event is still individually provable with a Merkle proof.

**`LedgerProvider` port:**

- `LocalHardhatLedger` (demo default)
- `EvmTestnetLedger` (config: RPC URL + key from env)
- `NullLedger` (DB hash chain only; UI shows "Not anchored")

The UI always states which network was used. **A local Hardhat chain is labelled "Local demo chain", never "blockchain-verified" without qualification.**

---

## N. IoT architecture

```
simulators/iot (Python) ──► POST /api/v1/telemetry/ingest  (device_id, seq, readings[], HMAC-SHA256 signature, timestamp)
  (future: real device / MQTT → bridge worker → same ingest service)
        │
  TelemetryService: verify HMAC + replay window + seq monotonic → store readings (partitioned table)
        │
  RuleEngine (per storage profile)  → excursion detection with duration + hysteresis
        │                               e.g. RBC/whole blood 2–6 °C, platelets 20–24 °C (agitated),
        │                               plasma/FFP frozen ≤ −18 °C (exact limits configurable,
        │                               to be verified against current national guidelines)
        ├─► temperature_alerts → notifications + SSE + bag_events("excursion") → may quarantine bag
        └─► window closer (e.g. 5 min) → Merkle root of readings → ledger batch (§M)
```

- **Devices:** a `devices` table with a per-device secret (stored hashed/encrypted). Each device is bound to a storage unit or a transport. Bags link to the device through `bag_custody` time ranges, so any bag's temperature history is a time-range join.
- **Simulator scenarios** (normal, door-open spike, cooler failure, sensor dropout) are reproducible by seed. Every simulated device is `is_simulated=true` and badged in the UI.
- **Why HTTP ingest first, MQTT later:** it needs no broker to operate and uses the same security model as the rest of the API. An MQTT bridge can feed the same `TelemetryService` later without changes downstream.

---

## O. Privacy / ZKP architecture

**Goal:** a donor proves *"I meet the donation eligibility rules"* to a verifier (a donation camp or partner hospital) **without revealing** age, weight, haemoglobin or last-donation date.

**The honest problem:** a proof over self-typed numbers proves nothing. So the private inputs are **attested**:

```
1. Screening (blood bank screener) records values → computes Poseidon commitment
   C = Poseidon(age, weight, hb_x10, days_since_last, donor_secret)
   and signs C (EdDSA-BabyJubJub, issuer key). Values stored encrypted; only C + signature shared with donor.
2. Donor device (browser) holds values + secret; runs circuit:
   public:  C, issuer_pubkey, rule_set_id, today
   private: age, weight, hb, days_since_last, donor_secret, signature
   proves:  Poseidon(private…) == C  ∧  sig valid  ∧  18 ≤ age ≤ 65 ∧ weight ≥ 45 ∧ hb ≥ 12.5 ∧ interval ≥ rule
3. Verifier: POST /eligibility/verify {proof, publicSignals} → backend verifies (snarkjs verifier contract via eth_call,
   or snarkjs verify in a tiny sidecar) → returns ELIGIBLE / NOT_PROVEN + nullifier to prevent replay.
```

- Rule thresholds are **placeholders** until checked against current Indian national blood transfusion guidelines. They live in a versioned `rule_set`, and a rule change means a new circuit/rule version.
- **Limitation, stated in the UI:** *"Prototype. Demonstrates privacy-preserving eligibility; not a medical certification or clinical decision system."*
- **Why Groth16/Circom:** small proofs, fast browser verification and the best documentation. The trusted-setup ceremony for the prototype is a local one and is disclosed as such.

---

## P. External provider abstraction

Every external dependency sits behind a **port** (Python `Protocol`) in `app/providers/<port>/`. The implementation is chosen by env config at startup. Every result carries a `ProviderMeta { provider, simulated: bool, fetched_at }`.

| Port | Demo implementation (Phase 1–11) | Real/future implementation |
|---|---|---|
| `VerificationProvider` | `DemoLast4` | SMS OTP gateway |
| `BloodBankProvider` | `MockBloodBankProvider` (seeded partner banks), `InternalBloodBankProvider` (banks onboarded in VEYRA itself) | `ExternalBloodBankProvider` (a future government or partner API; **not integrated and not claimed**) |
| `RoutingProvider` | `StraightLineRouting` (haversine × road factor, labelled "Estimated") | OSRM / OpenRouteService (public demo servers are rate-limited and not for production) |
| `MapTiles` (frontend) | Free OSM-based tiles within usage policy | Paid tile provider key |
| `TelemetrySource` | `IoTSimulator` | HTTP/MQTT devices |
| `LedgerProvider` | `LocalHardhatLedger`, `NullLedger` | `EvmTestnetLedger` |
| `LLMProvider` | `MockLLM` | Anthropic / OpenAI / Gemini |
| `NotificationProvider` | `InAppNotifier` (+ console email in dev) | Email (SMTP/API), SMS, push |
| `ZkVerifier` | `SnarkjsVerifier` | same (production would need an audited circuit and a real ceremony) |

```python
class BloodBankProvider(Protocol):
    meta: ProviderInfo
    async def search_availability(self, q: AvailabilityQuery) -> list[AvailabilityResult]
    async def request_units(self, r: UnitRequest, idem_key: str) -> RequestAck
    async def get_request_status(self, external_ref: str) -> RequestStatus
```

A `ProviderRegistry` fans out queries across providers and merges results. The agent and AI tools never know which implementation answered.

---

## Q. Frontend motion & design architecture

**Identity (original, not derivative):**

- **Palette:** "clinical calm plus one vital color".
  - Warm off-white / near-black neutrals.
  - One deep **haem red** (a desaturated oxblood, not neon) reserved for blood and critical meaning.
  - A cool **plasma teal** for "healthy/verified".
  - Amber for warnings.
  - **Red is used sparingly**, so emergencies actually stand out.
- **Typography** (Google Fonts, self-hosted via `next/font`): a precise grotesk for UI (e.g. *Inter Tight* or *Manrope*), an editorial serif for sparing display moments (e.g. *Instrument Serif*), and a mono for telemetry and IDs (e.g. *JetBrains Mono*). Final pick happens in the Phase 1 design pass.
- **Visual motif:** "flow lines". Thin vein-like curves that carry pulses along network paths. This one motif is reused across the hero, the network, bag tracking and route lines. There are no random floating blobs.

**Tokens (`packages/design-tokens` → CSS variables):**

- color (semantic: `--surface`, `--ink`, `--vital`, `--verified`, `--warn`, `--critical`)
- space (4-pt scale), radius, elevation (2 levels only), type scale
- **motion:** `--dur-instant 100ms`, `--dur-fast 180ms`, `--dur-base 280ms`, `--dur-slow 520ms`, `--dur-story 900ms`; easings `standard`, `emphasized`, `exit`, and one spring preset

**Motion rules:**

1. Every animation must answer "what does this tell the user?" (state change, causality, spatial continuity or attention for emergencies).
2. Only transform and opacity animate. Layout animation uses Motion's FLIP.
3. `prefers-reduced-motion`: components switch to fades or no motion, counters jump to the final value, and 3D swaps to a static poster.
4. Emergency state has a distinct, restrained pulse, used only for true criticals.
5. Performance budget: LCP < 2.5s on mid-range mobile, no long tasks > 50ms from animation, and 3D ≤ 60 fps desktop / disabled below a GPU tier (detect-gpu).

**Signature sequences (planned):**

- **Hero:** blood-cell particle field forming the network.
- **Scroll story:** donor → bank → transport → hospital, told with GSAP-scrubbed flow lines and intentional imagery.
- **Bag trace:** a timeline "drawn" along a vein line.
- **Verify:** Merkle leaves collapsing into a root and a chain checkmark.
- **Telemetry:** a live sparkline with a safe-band corridor.
- **Assistant:** typing, tool-use chips ("Checking 12 blood banks…").

**Imagery:** a small curated set of licensed photographs (a clinical lab, a donor with a nurse, a cold-chain box), plus our own 3D/illustration renders. Credits and licenses are tracked in `apps/web/public/images/CREDITS.md`. No section is filled with filler stock photos.

**States kit:** every data view ships Skeleton, Empty (with a next action), Error (with retry and request ID) and Success.

---

## R. Folder structure

```
veyra/
├── apps/
│   ├── web/                         Next.js
│   │   ├── app/ (marketing) (auth) (app)/…
│   │   ├── components/ ui/ motion/ viz/{network,route,telemetry,forecast,trace}/
│   │   ├── features/ auth/ donor/ inventory/ requests/ emergency/ bags/ telemetry/ assistant/ admin/
│   │   ├── lib/ api/ (generated) realtime/ network/ utils/
│   │   ├── styles/ tokens.css globals.css
│   │   └── tests/ (vitest) e2e/ (playwright)
│   └── api/                         FastAPI
│       ├── app/
│       │   ├── main.py
│       │   ├── core/ config.py db.py security.py errors.py logging.py ratelimit.py ids.py clock.py events.py
│       │   ├── modules/
│       │   │   ├── identity/ donors/ facilities/ inventory/ donations/ bags/ requests/
│       │   │   ├── emergency/ logistics/ telemetry/ ledger/ eligibility/ forecasting/
│       │   │   ├── assistant/ notifications/ analytics/ reports/ audit/ admin/ network/
│       │   │   └── (each: router.py schemas.py service.py repository.py models.py policies.py)
│       │   ├── providers/ verification/ bloodbank/ routing/ ledger/ llm/ notification/ telemetry/ zk/
│       │   ├── ai/ registry.py tools/ orchestrator.py prompts/
│       │   ├── agents/ emergency/ state_machine.py policy.py runner.py
│       │   └── workers/ (ARQ tasks: outbox, anchoring, agent, retrain, reports)
│       ├── migrations/ (alembic)
│       ├── seeds/ (demo data, labeled)
│       └── tests/ unit/ integration/ rbac/ contract/
├── ml/                              training pipeline (own pyproject), notebooks/, reports/
├── contracts/                       Hardhat: TraceRegistry.sol, EligibilityVerifier.sol, test/
├── zk/                              circom circuits, build scripts, test vectors
├── simulators/iot/                  device simulator + scenarios
├── packages/
│   ├── design-tokens/
│   └── api-client/                  generated from OpenAPI (CI checks it is up to date)
├── infra/ docker-compose.yml  docker/  (Dockerfiles)  caddy/ (optional reverse proxy)
├── docs/ adr/  architecture/  phase-reports/  demo-disclosures.md
├── .github/workflows/ci.yml
├── .env.example                     (no secrets; real .env git-ignored)
└── README.md
```

---

## S. Database entity / relationship plan

```
identity
  users(id, email UNIQUE, mobile UNIQUE, password_hash, role, status, is_demo, verified_at, created_at)
  sessions(id, user_id→users, refresh_hash, family_id, expires_at, revoked_at, ip, ua)
  verification_challenges(id, user_id, purpose, provider, code_hash?, attempts, expires_at)
  facility_invites(id, facility_id, email, role, token_hash, expires_at, used_at)
network
  facilities(id, type[HOSPITAL|BLOOD_BANK], name, reg_no, address, city, state, pin, lat, lng,
             provider_kind[internal|mock|external], is_simulated, status)
  facility_memberships(user_id→users, facility_id→facilities, facility_role)
  donors(id, user_id→users UNIQUE, full_name, blood_group, address, city, state, pin, lat?, lng?)
  donor_health_records(id, donor_id→donors, encrypted_payload, screened_by→users, screened_at)   ← restricted
  eligibility_commitments(id, donor_id, commitment, issuer_sig, rule_set_id, issued_at, revoked_at)
  inventory_lots(id, facility_id, blood_group, component, units, expiring_within_72h, version)  (materialized from bags)
  inventory_thresholds(facility_id, blood_group, component, min_units, critical_units)
  donations(id, donor_id, facility_id(bank), donated_at, volume_ml, status, screening_result)
trace
  blood_bags(id, public_id UNIQUE, donation_id→donations, blood_group, component, collected_at,
             expires_at, status, current_facility_id, version)
  bag_events(id, bag_id, seq, type, actor_id, facility_id, payload JSONB, occurred_at, prev_hash, row_hash)  ← append-only
  bag_custody(bag_id, holder_facility_id|transport_id, device_id?, from_ts, to_ts)
  blood_requests(id, requesting_facility_id, target_facility_id, blood_group, component, units,
                 urgency, status, due_by, idempotency_key, created_by)
  request_allocations(request_id, bag_id)
  emergencies(id, facility_id, trigger[threshold|manual], status, agent_run_id?)
  transports(id, request_id, mode, origin_facility_id, dest_facility_id, route_polyline, eta, status, provider_meta)
telemetry
  devices(id, kind, facility_id?, transport_id?, secret_enc, storage_profile, is_simulated)
  telemetry_readings(device_id, recorded_at, temp_c, humidity?, seq)  (partitioned)
  temperature_alerts(id, device_id, bag_ids[], kind, started_at, ended_at, peak_c, status)
ledger
  ledger_anchors(id, kind, from_seq, to_seq, merkle_root, network, tx_hash, block_number, anchored_at)
ai / agents
  assistant_conversations(id, user_id, created_at) · assistant_messages(id, conv_id, role, content, created_at)
  ai_tool_calls(id, message_id, tool, args_redacted, status, latency_ms)
  agent_runs(id, emergency_id, autonomy_level, state, started_at, ended_at)
  agent_run_steps(id, run_id, step, input JSONB, decision JSONB, rationale, created_at)
ml
  model_versions(id, target, algo, trained_on[synthetic|real], metrics JSONB, artifact_uri, is_active, created_at)
  forecasts(id, facility_id, blood_group, component, horizon_date, yhat, lo, hi, model_version_id)
platform
  notifications(id, user_id, kind, title, body, read_at, created_at)
  audit_logs(id, actor_id, actor_type[user|agent|system], action, resource, resource_id, ip, meta, prev_hash, row_hash)
  outbox_events(id, topic, payload, created_at, published_at)
  idempotency_keys(key, user_id, route, response_hash, created_at)
  system_config(key, value JSONB, updated_by, updated_at)
```

Key relationships:

- User 1–1 Donor
- User N–M Facility (through memberships)
- Donor 1–N Donation 1–N BloodBag (a donation can be split into components)
- BloodBag 1–N BagEvent, and 1–N Custody → Device → Readings
- Request N–M Bag (through allocations); Request 1–1 Transport
- Emergency 1–1 AgentRun 1–N Steps

---

## T. Major API endpoint plan (`/api/v1`)

| Area | Endpoints | Roles |
|---|---|---|
| Auth | `POST /auth/register`, `POST /auth/verify/start`, `POST /auth/verify`, `POST /auth/login`, `POST /auth/refresh`, `POST /auth/logout`, `GET /auth/me`, `POST /auth/invites/accept` | public / any |
| Donor | `GET/PATCH /donors/me`, `GET /donors/me/donations`, `GET /donors/me/eligibility`, `GET /donors/me/rewards` | DONOR |
| Facilities | `GET /facilities` (public directory fields), `GET /facilities/{id}`, `POST /admin/facilities`, `POST /admin/facilities/{id}/invites` | any / ADMIN |
| Inventory | `GET /facilities/me/inventory`, `PATCH /facilities/me/thresholds`, `GET /network/availability?group=&component=&near=` | HOSPITAL, BLOOD_BANK |
| Donations & bags | `POST /donations`, `POST /donations/{id}/bags`, `GET /bags/{public_id}`, `POST /bags/{id}/transitions`, `GET /bags/{id}/events`, `GET /bags/{id}/qr` | BLOOD_BANK (+ HOSPITAL receive) |
| Trace (public) | `GET /trace/{public_id}` (signed QR token → non-PII chain + verification status) | public |
| Requests | `POST /requests`, `GET /requests?direction=in|out`, `POST /requests/{id}/respond`, `POST /requests/{id}/allocate` | HOSPITAL / BLOOD_BANK |
| Emergency & agent | `POST /emergencies`, `GET /emergencies/{id}`, `GET /emergencies/{id}/agent-run`, `POST /agent-runs/{id}/confirm`, `POST /agent-runs/{id}/cancel` | HOSPITAL, BLOOD_BANK, ADMIN |
| Logistics | `GET /transports/{id}`, `POST /transports/{id}/status`, `GET /routing/estimate` | HOSPITAL, BLOOD_BANK |
| Telemetry | `POST /telemetry/ingest` (device HMAC), `GET /devices/{id}/readings`, `GET /alerts`, `POST /alerts/{id}/ack` | device / facility |
| Ledger | `GET /ledger/anchors`, `GET /ledger/verify/bag/{id}` | HOSPITAL, BLOOD_BANK, ADMIN |
| Eligibility (ZK) | `POST /eligibility/commitments` (screener), `GET /eligibility/rule-sets/current`, `POST /eligibility/verify` | BLOOD_BANK / DONOR / verifier |
| Forecast | `GET /forecasts?facility=me&horizon=14`, `GET /forecasts/models/active` | HOSPITAL, BLOOD_BANK, ADMIN |
| Assistant | `POST /assistant/conversations`, `POST /assistant/conversations/{id}/messages` (SSE) | HOSPITAL, BLOOD_BANK, ADMIN (donor: limited FAQ tools) |
| Network | `GET /network/snapshot`, `GET /stream?topics=` (SSE) | role-filtered |
| Notifications | `GET /notifications`, `POST /notifications/{id}/read` | any |
| Reports & analytics | `POST /reports` (job), `GET /reports/{id}`, `GET /analytics/overview` | HOSPITAL, BLOOD_BANK, ADMIN |
| Admin | `GET/PATCH /admin/users`, `GET /admin/audit-logs`, `GET/PATCH /admin/config`, `GET /admin/system/health` | ADMIN |
| Ops | `GET /healthz`, `GET /readyz` | public (no internals exposed) |

---

## U. Dependency recommendations

**Backend (Python):**

- `fastapi`, `uvicorn[standard]`, `pydantic`, `pydantic-settings`
- `sqlalchemy[asyncio]`, `asyncpg`, `alembic`
- `argon2-cffi` (or `pwdlib[argon2]`), `pyjwt[crypto]`, `cryptography`
- `redis`, `arq`, `slowapi` (or a custom Redis limiter), `sse-starlette`, `httpx`, `structlog`
- `qrcode[pil]`, `web3`
- **ML (separate extras group):** `pandas`, `numpy`, `scikit-learn`, `xgboost` (or `lightgbm`), `shap`, `joblib`
- **LLM SDKs (optional extras):** `anthropic` / `openai`
- **Dev:** `pytest`, `pytest-asyncio`, `ruff`, `mypy`, `testcontainers` (or compose test DB), `freezegun`, `hypothesis` (for hash-chain and rule-engine properties)

**Frontend (TypeScript):**

- `next`, `react`, `typescript`, `tailwindcss`
- Radix via shadcn/ui (copied), `motion`, `gsap`, `lenis`
- `three`, `@react-three/fiber`, `@react-three/drei`, `detect-gpu`
- `@tanstack/react-query`, `zustand`, `react-hook-form`, `zod`
- `visx` (selected packages), `recharts`, `maplibre-gl`
- `openapi-typescript`, `openapi-fetch`, `@zxing/browser`, `snarkjs`
- **Dev:** `vitest`, `@testing-library/react`, `playwright`, `@axe-core/playwright`, `eslint`, `prettier`

**Chain / ZK:** `hardhat`, `@openzeppelin/contracts`, `circom` (2.x), `circomlib`, `snarkjs`.

**Rule:** a dependency gets added only when a phase needs it. Nothing is pre-installed "just in case".

---

## V. Testing strategy

| Level | What | Tool |
|---|---|---|
| Unit | Services with fake repositories; rule engine; agent state machine transitions; Merkle/hash chain; ranking; provider mocks | pytest, hypothesis |
| Integration | API + real Postgres (compose or testcontainers), migrations applied from zero | pytest + httpx |
| **RBAC matrix** | Every endpoint × role × own/other resource → expected status; **no PII fields** in hospital responses (schema assertion) | pytest parametrized |
| Contract | OpenAPI snapshot diff in CI; generated TS client must be current | CI script |
| AI | Tool registry: permission filtering, arg validation, audit rows; orchestrator with `MockLLM` scripted tool calls; prompt-injection fixtures | pytest |
| ML | Pipeline reproducibility (seed); GBM beats baseline on walk-forward MAE; interval coverage within tolerance; no data leakage (lags only from the past) | pytest + evaluation report |
| Chain | Contract access control, anchor events, verify flow | Hardhat tests |
| ZK | Circuit test vectors (valid, and each rule violated → proof fails), replay nullifier | circom tests + snarkjs |
| Frontend | Components, network store reducers, form validation | Vitest + Testing Library |
| E2E | Register → verify (demo) → login per role; emergency happy path; bag trace; reduced motion on | Playwright |
| Accessibility | axe checks on key pages; keyboard-only paths | @axe-core/playwright |
| Performance | Lighthouse CI budgets on landing and dashboards | Lighthouse CI |

**Phase gate:** each phase must leave `make test` green, including all earlier phases' tests. That is how backward compatibility is proven, not just asserted.

---

## W. Security strategy

- **Secrets:** env vars only; `.env.example` is committed and `.env` is git-ignored plus caught by a pre-commit secret scanner (gitleaks). Startup validates required settings and refuses demo providers in production.
- **AuthN:** Argon2id, rotating refresh tokens with reuse detection, account lockout/backoff, rate limits on auth routes.
- **AuthZ:** permission + scope on every endpoint, role-specific serializers, and CI-enforced RBAC matrix tests.
- **Input:** Pydantic strict models on every endpoint, size limits, and parameterized SQL only (ORM).
- **Web:** CSP (strict, with nonces), HSTS, `X-Content-Type-Options`, `Referrer-Policy`, `frame-ancestors 'none'`, CORS allow-list, and CSRF double-submit.
- **Data minimization:** health data is encrypted and isolated. Hospitals never see donor identity. QR codes contain only a signed opaque token and never PII. Logs redact email, mobile and health fields.
- **Tamper evidence:** hash-chained audit logs and bag events, anchored on chain.
- **Devices:** per-device HMAC keys, timestamp window plus seq to stop replays, and key rotation.
- **AI:** permission-filtered tools, no raw DB access, untrusted-content delimiting, per-user budget, and full tool audit.
- **Agent:** service identity with a subset of permissions, autonomy levels, a kill switch, and idempotency.
- **Compliance awareness:** design follows data-protection principles in line with India's Digital Personal Data Protection Act 2023 (consent, purpose limitation, minimization). **This prototype makes no compliance claim.**
- **Supply chain:** lockfiles committed, plus Dependabot/`pip-audit` and `pnpm audit` in CI.

---

## X. Deployment strategy

- **Local (primary for the demo):** `docker compose up` runs postgres, redis, api, worker, web, hardhat, and optionally mosquitto and the simulator. On Windows, run inside **WSL2** with Docker Desktop.
- **Hosted demo (Phase 11), as an example setup:** web on a Next.js-friendly host (e.g. Vercel), API and worker as containers (e.g. Render / Railway / Fly.io), managed Postgres (e.g. Neon / Supabase) and managed Redis (e.g. Upstash). The chain is either an EVM testnet via an RPC provider, or `NullLedger` with a clear label if we don't want public-testnet dependencies during judging.
- **Config:** 12-factor, with `APP_ENV` in `{dev, test, demo, production}`. `demo` enables simulated providers *and* shows a global "Demo environment" ribbon.
- **CI/CD:** GitHub Actions runs lint, type-check, tests (api, web, contracts, zk), builds images, then deploys on `main`.
- **Observability:** structured logs with request IDs, `/healthz`, `/readyz`, and basic metrics (request latency, SSE clients, agent runs). OpenTelemetry is optional.

---

## Y. Phase-by-phase roadmap (≈ 11 days)

I kept your order with **three deliberate adjustments**, each with a reason:

1. **Design system foundations move into Phase 0/1.** Auth screens are the first UI anyone sees; building them without tokens means restyling them later.
2. **Provider ports (Mock + Internal blood-bank provider) are created in Phase 2**, not Phase 7. The core network and the agent (Phase 6) need them. Phase 7 becomes "hardening + provider registry fan-out + external-ready adapter + admin provider config".
3. **The bag lifecycle data model (bags, events, custody, hash chain) lands in Phase 2.** Phase 8 adds QR, the public trace page and on-chain anchoring on top. Traceability is the spine of the domain, and bolting it on later would force a schema restructure.

| Phase | Day | Scope | Exit criteria |
|---|---|---|---|
| **0 — Architecture & Foundation** | D0–D1 (am) | This report (approved) → scaffold monorepo, docker compose, FastAPI skeleton (core, errors, logging, health), Next.js skeleton, design tokens, CI, `.env.example`, ADR-001..008 | `docker compose up` works; `/healthz` green; CI green; landing placeholder renders with tokens |
| **1 — Auth & RBAC** | D1 | Register/login/refresh/logout, DemoLast4 verification (+ disclaimer), Argon2id, sessions, facility invites, permission model, RBAC matrix tests, auth UI | All roles can log in; RBAC matrix passes; demo disclaimer visible; no demo provider in prod config |
| **2 — Core Blood Network** | D2–D3 | Facilities, donors, donations, bags + bag_events hash chain, inventory, thresholds, requests, allocations, provider ports (Mock + Internal blood bank, straight-line routing), seed data, outbox + SSE | End-to-end: donation → bag → request → allocation → receipt via API; hash chain verifies |
| **3 — Dashboards & UX** | D4 | App shell, role dashboards, states kit, charts, landing page v1 (hero + scroll story), Live Blood Network 2D, reduced motion | Each role has a usable dashboard; Lighthouse budgets met; a11y checks pass |
| **4 — ML Prediction** | D5 | Synthetic generator + model card, baseline vs GBM, walk-forward eval, SHAP, forecast API + dashboard chart | GBM beats baseline (or baseline shipped with a note); predictions labelled synthetic-trained |
| **5 — AI Assistant** | D6 | LLM adapter + MockLLM, tool registry, 6 read tools, SSE chat UI, tool audit | Tools respect RBAC (tests); works with no API key in mock mode |
| **6 — Emergency Agent** | D7 | State machine, policy/autonomy levels, sourcing + ranking, confirmations, run timeline UI | Critical stock triggers a run; L0/L1 behave correctly; idempotent; fully audited |
| **7 — Blood-Bank Integration Abstraction** | D7 (pm) | Provider registry fan-out, admin provider config, external-ready adapter + contract tests, simulated badges | Swapping providers is config-only; contract tests pass for all implementations |
| **8 — QR + Blockchain** | D8 | QR generation/scan, public trace page, Hardhat TraceRegistry, Merkle anchoring worker, verify UI animation | Tampering with a DB event is detected on verify |
| **9 — IoT Monitoring** | D9 | Device registry, HMAC ingest, simulator scenarios, rule engine, alerts, telemetry UI, window anchoring | Excursion scenario → alert → bag flagged → visible in trace |
| **10 — Privacy/ZKP** | D10 | Circuit, commitments by screener, in-browser proving, verifier (contract or sidecar), nullifiers, UI | Valid proof verifies; every rule violation fails; no raw values leave the device |
| **11 — Integration, Security, Perf, Deploy** | D11 | 3D network scene, polish, security review, load sanity, E2E suite, hosted demo, demo-disclosures page, final docs | All tests green; deployed; demo script rehearsed |

**If time runs short, cut in this order** (least demo damage first): hosted testnet → MQTT → 3D network scene (keep 2D) → L2 autonomy → report PDFs. **Never cut:** RBAC tests, demo labelling, or hash-chain integrity.

**Phase gate template** (reported at the end of every phase, then I stop and wait for your approval):

```
PHASE STATUS — Phase N
Implemented features · Files created · Files modified · Tests executed · Tests passed
Existing functionality verified · Known issues · Technical debt introduced · Recommended next phase
```

---

## Z. Risks & technical constraints

| Risk | Impact | Mitigation |
|---|---|---|
| **Scope vs 11 days** (29 capability areas, 1 developer) | High | Strict phase gates; "cut order" above; mock-first providers; no speculative dependencies |
| **ZK toolchain on Windows** | High | WSL2/Docker; pre-built circuit artifacts committed; keep the circuit small (4 constraints + signature) |
| Circuit correctness / honest claims | Med | Test vectors for each rule; disclaimer; attested commitments instead of self-declared values |
| **No real demand data** | Med | Documented synthetic generator; baseline comparison; clear "synthetic" labelling; real-CSV-ready schema |
| LLM keys/cost/availability | Med | MockLLM mode; per-user budgets; the assistant is not on the critical path of any workflow |
| Public routing/tile services rate-limited | Med | Straight-line estimate default; cache routes; label estimates |
| 3D/motion hurting performance or accessibility | Med | Lazy-load, GPU-tier gating, 2D fallback, reduced-motion paths, Lighthouse CI budgets |
| Medical rule accuracy (eligibility, temperature ranges) | Med | Configurable versioned rule sets; verify against current national guidelines before Phases 9/10; "not a medical system" disclaimer |
| Mock data mistaken for real integrations | High (credibility) | `simulated: true` in every provider response, UI badges, demo ribbon, `docs/demo-disclosures.md` |
| Blockchain seen as gimmick | Low–Med | Show the real value: tamper detection via Merkle proof against an anchored root, demonstrated live |
| Cookie auth across separate hosted domains | Med | Same-origin proxy via Next.js rewrites; tested in the Phase 11 deploy |
| Schema churn between phases | Med | Bag/trace model in Phase 2; migrations only; ADR required for contract changes |

---

## Approval record

- 2026-09-28: architecture approved by Arpan; product name set to VEYRA; revised roadmap adopted; build location = local folder on user's computer.
