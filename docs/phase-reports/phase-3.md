# PHASE STATUS — Phase 3: Dashboards & UX

Phase 3 puts a role-based dashboard, charts, landing page v1 and a Live Blood Network 2D view on top of the Phase 1 and Phase 2 APIs.

Every figure comes from real API data. No chart uses invented or demo data; charts with no data show an empty state instead.

## Gate fixes (before Phase 3)

| Failure (31/33 run) | Root cause | Fix |
|---|---|---|
| `alembic check`: `remove_table` for the 6 Phase 2 tables and their indexes | `migrations/env.py` imported only the 4 Phase 1 model modules. Alembic's `Base.metadata` held 8 of 14 tables, so it read the existing Phase 2 tables as "to be removed". My earlier drift check compiled DDL after importing `app.persistence.sql`, which pulls in every model, so it didn't catch this. | Added `app/models_registry.py`, which imports every ORM module; `env.py` now uses its metadata. `tests/test_models_registry.py` fails if any `app/modules/*/models.py` isn't registered, or if a fresh interpreter importing only the registry sees fewer than all 14 tables. No schema change, no new migration. |
| `pnpm lint`: 4 × `react-hooks/set-state-in-effect` | Effects called an async loader function that set state | The fetch now lives inside the effect, with `.then` and an `active` guard (the Phase 1 pattern). Live events and post-mutation refreshes bump a `useReload()` counter in the dependency list. No rule changes or disables. Behaviour kept: initial load, live refresh, loading and error states, one fetch per trigger, stale responses dropped. |

## Implemented

### A. Role-based dashboards

**Donor**
- Existing profile card.
- Impact tiles: donations, bags produced, sent to hospitals, next eligible date (labelled a prototype default), verification and blood-group confirmation status.
- Donation history.
- No hospital or patient is ever named.

**Blood bank: new "Overview" tab**
- Tiles: usable units, expiring within 72 h, open incoming requests (emergency count), donations today.
- Emergency call-out that links to the incoming queue.
- Charts: inventory by group, time to expiry, requests by status, dispatch and receipt (14 d), donations (14 d).
- Compact live network and a live activity feed.

**Hospital: new "Overview" tab**
- Tiles: received stock, expiring soon, open requests, requests received.
- Charts: received units by group, expiry, request status, dispatch and receipt.
- **Network availability overview**: group and component pickers show how many banks fall in each band (can cover, limited, no stock), plus the count of simulated partners. Never exact stock.
- Live network and activity feed.

**Admin: "Network overview"**
- Tiles: accounts, facilities, open requests, bags tracked.
- **System health**: API connectivity (via `/meta`) and the live SSE status.
- Charts: accounts by role, requests by status, bags by status, donations, dispatch and receipt, audit activity (top actions in 24 h).
- Recent audit entries showing action, actor type and time only; IP and metadata stay in the audit log.
- Network activity feed. The existing facility and staff management sits below.

**Shell**
- "Live network" navigation for facility and admin roles.
- A mobile nav row.
- Scrollable tab bar on small screens.

### B. Charts
- Hand-built HTML/SVG charts. No new dependency: the lockfile and toolchain are unchanged.
  - `BarList` for categories.
  - `ColumnChart` for time series, with one or two series.
- Every chart has:
  - a per-mark hover tooltip (bars also on keyboard focus)
  - a **Table** toggle with every value
  - an explicit empty state
  - text in ink tokens, never the series colour
- Colour:
  - Single series use VEYRA vital.
  - The two-series chart (dispatched vs received) uses a validated pair, `--viz-1`/`--viz-2`, with separately selected dark-mode steps. `validate_palette.js` PASS in light and dark: CVD ΔE ≥ 24, contrast ≥ 3:1.
  - Status bars use the status tokens (warn, verified, critical) next to text labels.
- Data mapping is pure functions in `lib/charts.ts`, unit-tested:
  - fixed blood-group and status order, so bars never re-sort or repaint
  - clean axis maxima
  - human event text built only from non-personal fields

### C. Landing page v1
- **Purpose**: hero with an honest description of what VEYRA does today.
- **Workflow**: a 5-step chain (donate → label → request → dispatch → receive & trace).
- **Roles**: four entry points, noting that facility accounts are invite-only.
- **Security & privacy**: six principles (scoping, donor privacy, banded availability, tamper evidence, sessions, labelling).
- **Transparency**: what's real vs simulated, including the verbatim demo-verification disclaimer.
- **CTA**: sign in / register.
- **Disclaimer**: VEYRA is a student engineering prototype, not a certified medical device. Values are prototype defaults, not clinical guidance.
- No clinical claims; a test checks this.

### D. Live Blood Network 2D (`/network`, plus compact on overviews)
- **Layout**: a schematic two-column graph, hospitals left and blood banks right. It is labelled verbatim **"Prototype network visualization — not a geographic map."**
- **Data**: nodes and edges from the new scoped `GET /network/graph`. Edges are the last 30 days of requests; open requests are drawn heavier in vital.
- **Encoding**:
  - Node shape carries type: squares for hospitals, circles for banks.
  - Simulated partners are dashed and labelled; your own facility is ringed.
- **Live updates over SSE**:
  - `request.created`: a pulse travels hospital → bank.
  - `dispatched` / `fulfilled`: a pulse travels bank → hospital.
  - `inventory.updated`: a ring on the bank.
- **Reducer** (`lib/network-graph.ts`):
  - de-duplicates at-least-once deliveries
  - updates edge counts
  - refetches the graph once when an event names a facility not yet drawn; it never invents nodes
- **Reduced motion**: pulses become static highlights.
- **Event log**: `aria-live`, scoped.
- To support this, request events now carry `hospital_id` and `target_facility_id`. These are facility ids only, and each event already goes only to those two facilities.

### E. UX polish
- Consistent skeletons (`aria-busy`, labelled).
- Error states with **Try again**.
- Empty states that say what to do next.
- Status badges from one map.
- Tooltips on focus.
- Mobile layout: 2-column tile grids, scrollable tabs, mobile nav.
- `aria-current` on nav, and `aria-live` on feeds.

### F. Security boundaries (new endpoints)

| Endpoint | Permission | Scope |
|---|---|---|
| `GET /dashboard/facility` | `facility:read:own_facility` (hospital, blood bank) | The caller's facility only: requests it sent or received, its donations, its bags, events addressed to it |
| `GET /dashboard/admin` | `network:read` + `audit:read` (admin) | Network-wide **counts**; audit rows without IP, metadata or actor id |
| `GET /network/graph` | `events:subscribe:scoped` | Hospital: itself, its requests' targets and onboarded banks (already discoverable), never other hospitals. Bank: itself and hospitals that requested from it. Admin: everything. |

- All endpoints are GET, read-only, authenticated, and in the RBAC matrix (3 new rows × 5 roles).
- No dashboard payload contains donor names, mobiles, emails or `donor_id`; this is tested per endpoint.
- The data comes from a new read-only `stats` repository on the unit of work (SQL and memory). The Phase 1/2 repositories are unchanged.

## Tests
- **API** `test_phase3_dashboard.py` (10):
  - bank and hospital aggregates are correct
  - other facilities see zeros
  - no donor identity in any dashboard or graph payload
  - admin counts and audit redaction
  - dashboard RBAC
  - graph scope per role, including the simulated partner node
  - request events carry facility ids
  - IST day bucketing, expiry bucket edges
- **API** `test_models_registry.py` (3): the registry guard for Alembic.
- **API** `test_integration_phase3.py` (Postgres): dashboards and graph through the SQL stats repository. All 11 stats queries were also compiled and `EXPLAIN`ed on PostgreSQL 16 against the migrated schema.
- **RBAC matrix**: +3 endpoint rows.
- **Web** `dashboard.test.tsx`:
  - chart data mapping (6)
  - chart components: empty state, table view, focus tooltip, legend only for 2 series
  - live network reducer: layout, lifecycle pulses and edges, duplicate delivery, unknown-node refetch, inventory ring and expiry
  - LiveNetwork: disclaimer, live update via a fake EventSource, single refetch, error state
  - FacilityOverview: bank tiles, emergency call-out and navigation, hospital banded availability, loading and error with retry
  - AdminOverview: audit table without IP
  - DonorDonations impact
  - Landing: sections, verbatim disclosures, disclaimer, no clinical claims
- **Bootstrap**: new E2E step `e2e: phase 3 dashboards + live network graph (scoped, via web proxy)` (the gate is now **34 steps**).

Cloud results:
- API: **277 passed**, 7 skipped (the Postgres integration tests; no asyncpg in the sandbox).
- ruff and mypy strict: clean.
- Web `tsc` (strict): clean, including `--noUnusedLocals`.

ESLint, vitest and `next build` run only in the Windows bootstrap (the npm registry is blocked in the sandbox).

## Known limitations
- Charts are hand-built. There's no zoom or brush, and the time range is fixed at 14 days (30 for the graph).
- The admin dashboard's "system health" is API reachability plus SSE status. There's no DB or Redis latency panel; `/readyz` isn't exposed through the web proxy.
- The network graph layout is schematic. With many facilities it grows tall, with no clustering or pagination.
- Activity feeds show at most 10–15 events. The outbox scan for facility activity reads the latest 200 events, which is fine for the prototype but a JSONB-containment index would be needed at scale.
- "Today" uses a fixed UTC+05:30 offset (`VEYRA_REPORT_UTC_OFFSET_MINUTES`), not a timezone database.

## Recommended next phase
**Phase 4: ML prediction.** A synthetic demand generator with a model card, a baseline vs a gradient-boosted model (GBM), and a forecast chart on the hospital and bank overviews, clearly labelled as trained on synthetic data.
