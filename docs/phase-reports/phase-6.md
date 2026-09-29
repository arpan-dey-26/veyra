# PHASE STATUS — Phase 6: Operational Intelligence & Emergency Response

> **Operational recommendation — prototype.** This is an operational engineering prototype. Recommendations are not clinical decisions or medical advice. Every recommendation shows its reasons, and nothing is dispatched until a person confirms it.

## Phase 5 final gate
Real Windows bootstrap: **`OVERALL: PASS (37/37 steps passed)`**, saved as `docs/phase-reports/phase-5-verification.log`.

## Architecture

```
app/modules/operations/
  engine.py    pure, deterministic rules: priority, pressure, bag ranking, simulated routing
  service.py   scoped read views + the one mutation (priority change) + outbox event helpers
  schemas.py   structured reasons everywhere (code, text, points, tone)
  router.py    /operations/*
```

- **Same modular monolith.** Router → service → UnitOfWork, with SQL and in-memory implementations. Events go outbox → relay → SSE; there is no second event system.
- **It combines what already exists:**
  - real requests and real inventory
  - the Phase 4 synthetic forecast, via the new `facility_daily_mean()`, which reuses the committed model artifact
  - the Phase 5 simulated device state
- **No migration.** Urgency (`routine | urgent | emergency`) already existed on requests. Everything else is computed at read time. `alembic check` stays clean.
- **One new read-only repository method,** `bags.list_usable(...)`. It is an unlocked FEFO listing, so reading a recommendation never takes row locks away from a concurrent dispatch.

## Emergency request management
- `GET /operations/requests` returns the open and in-transit requests in scope, sorted by operational priority. Each one carries:
  - priority (urgency)
  - requested time, age in minutes and needed-by
  - component, blood group, quantity and status
  - a priority object, and a simulated ETA while dispatched
- Counts: open, emergency_open, dispatched, expected_units and received_units_7d.
- **Emergency requests stand out.** They are sorted first, shown with a "▲ Emergency" badge and a red card border, and raise a `request.operational_alert`.
- The existing lifecycle, endpoints and FEFO behaviour are unchanged.
  - `POST /requests/{id}/fulfil` with `{}` still dispatches strict FEFO.
  - Its body gains an **optional** `bag_public_ids`, so the bank can confirm the recommended bags through the same workflow.

## Operational priority engine
The score is the sum of its reasons, capped at 100. There is no hidden model: the points are listed with each reason.

| Reason | Points |
|---|---|
| Emergency / urgent / routine request | 50 / 30 / 10 |
| Past the needed-by time / needed ≤ 2 h / needed ≤ 6 h | 15 / 10 / 5 |
| Waiting ≥ 2 h / ≥ 30 min | 10 / 5 |
| Large request (≥ 4 units) | 5 |
| Not enough compatible stock without cold-chain concern (bank view) | 10 |
| Target bank reports limited / no stock (hospital view, banded) | 10 |
| Low projected coverage / coverage under 7 days (synthetic forecast input) | 10 / 5 |
| Cold-chain concern on compatible bags | 3 |
| Available compatible stock · compatible bags expire within 72 h | 0 (info) |

**Bands:**
- **immediate** at 65 or more
- **high** at 45 or more
- **standard** otherwise
- Closed requests score 0.

**Recommended action** is one of:
- `review_and_dispatch`
- `review_flagged` (only bags with concerns can cover the request)
- `insufficient_stock`
- `await_bank`
- `await_receipt`
- `simulated_partner`
- `none`

It is always phrased as a suggestion. This is never called a clinical or risk score.

## Smart allocation recommendation
`GET /operations/requests/{id}/recommendations` is for the target blood bank only.

**Candidates** follow the **existing compatibility rule**:
- same blood group and component
- `available` and unexpired
- held by this bank

No cross-group substitution is suggested.

**Ranking:**
1. Cold-chain concern first: none or unmonitored, then stale or warning, then critical.
2. Then FEFO position.
3. The first *n* candidates without a concern are **recommended**.

**Returned per bag:**
- rank and FEFO position
- expiry and hours left
- cold-chain state, simulated device id and latest temperature
- current facility
- `recommended` / `deprioritized`
- reasons, for example "First-expiry-first-out position 1", "Bag expires within 72 h — use first", "Cold-chain critical — deprioritised; review before any dispatch"

**For comparison,** `fefo_default_bag_ids` is what a plain dispatch would take.

**Nothing is dispatched.** Dispatch happens only when the user confirms with the existing `POST /requests/{id}/fulfil`, passing `bag_public_ids`.
- The service validates the selection exactly like FEFO: exact count, each bag usable, matching and held here.
- It takes the same `FOR UPDATE SKIP LOCKED` locks. An invalid selection returns 409 `bag_not_eligible`.
- The audit entry records `{"selection": "confirmed_bags" | "fefo"}`.

## Forecast + inventory pressure
`GET /operations/facilities/{id}/pressure` gives 24 rows (8 groups × PRBC/platelets/FFP), plus any other group/component with stock or open requests.

**Inputs:**
- **real stock**
- **open requested units** (pending requests targeted at a blood bank)
- the **synthetic 7-day forecast mean**

**Rule:** free = stock − open, and coverage = free ÷ daily forecast.
- **elevated:** coverage < 3 days, or open > stock
- **watch:** coverage < 7 days
- **normal:** otherwise
- Components without a forecast use stock vs open only.

The response is labelled **"Synthetic forecast input — prototype"** with `source.kind = synthetic`. It is not a medical emergency prediction.

## Cold-chain awareness
- **Flagged, never dropped:** a bag with a critical temperature, an active excursion, or a stale/offline device is marked and deprioritised with a reason, but stays in the candidate list. Nothing is discarded by the engine.
- **New event:** when a Phase 5 reading raises a warning or critical transition on an available or in-transit bag, the telemetry state machine also emits `cold_chain.operational_alert`.
- **`GET /operations/alerts`** lists:
  - open emergency requests
  - cold-chain warnings/critical and stale devices
  - bags expiring within 72 h
  - one summary alert for elevated pressure

## Routing simulation
- **`GET /operations/routing/estimate`** takes a source, a destination and an urgency. It is deterministic and schematic:
  - distance comes from a SHA-256 hash of the facility pair within a band: same city 3–15 km, same state 40–200 km, otherwise 250–1150 km
  - simulated speed: emergency 45, urgent 38, routine 32 km/h
  - handover: 10 / 15 / 20 min
  - a simulated route status (clear / slow / delayed, +0/20/45 %) that varies by hour bucket
- **`GET /operations/routing`** gives ETAs for dispatched requests in scope.
- Labelled **"Simulated routing — prototype"** with `source.kind = simulated`. No GPS, maps or traffic APIs are used.

## Real-time SSE (existing outbox)

| Topic | When | Audience |
|---|---|---|
| `request.priority_changed` | hospital changes its open request's priority | hospital + bank |
| `request.operational_alert` | emergency request created, or escalated to emergency | hospital + bank |
| `allocation.recommendation_updated` | emergency request created or priority changed | target bank |
| `routing.updated` | emergency request dispatched (simulated ETA) | hospital + bank |
| `forecast.pressure_changed` | an emergency create/dispatch changes a pressure **level** | bank |
| `cold_chain.operational_alert` | warning/critical transition on an available or in-transit bag | holder (+ destination in transit) |

- Routine and urgent requests keep exactly the Phase 2 event stream; its test asserts the exact topic list.
- Last-Event-ID replay, audience scoping and id ordering/de-duplication are unchanged and tested.

## Security, privacy and audit
- **The one mutation** is `POST /operations/requests/{id}/priority`:
  - the requesting hospital only, for pending or acknowledged requests
  - CSRF-protected and audited as `blood_request.priority_changed` with `{from, to, reason}`
  - the reason is a **code**, never free text, so no personal details reach the audit log
- **Permissions:**
  - `operations:read:scoped` for hospitals and blood banks
  - `allocation:recommend:own_facility` for blood banks only
  - admins use `network:read`
- **Scope:**
  - A hospital sees its own requests. Bank stock appears only as bands (sufficient / limited / none).
  - Recommendations are for the target bank only (hospital 403, other bank 404).
  - Pressure and route estimates are for the caller's own facility (others 404).
  - Donors get 403 everywhere; anonymous callers get 401.
- **Privacy:** payloads carry facility names, request facts and bag ids only. There is no donor, patient or user identity (tested on every endpoint and event).
- **Audit:** read-only endpoints add no audit entries, following existing policy.

## Web
- **Blood bank and hospital:** a new **Operations** tab.
  - disclaimer
  - emergency queue with band (text + glyph), score, age and needed-by
  - "Why this priority?" reasons
  - **Blood bank only:**
    - "Needs attention" alerts
    - recommendation table (rank, deprioritised badge, cold-chain status, facility, reasons)
    - forecast pressure and simulated route
    - **two-step "Dispatch recommended bags… → Confirm dispatch"**
    - dispatch queue with simulated ETAs
  - **Hospital only:**
    - priority change (reason codes)
    - expected deliveries with ETA
    - banded network availability
    - own pressure
- **Admin:** network emergency activity. Counts, open emergencies, cold-chain warning counts, banks with elevated pressure, and the simulated routing overview.
- **Every view:**
  - loading skeleton, error with **Try again**, empty states
  - labelled tables and selects
  - `aria-expanded` toggles and a keyboard-only flow
  - horizontally scrollable tables on mobile
  - design tokens for light and dark mode
  - statuses always as text + glyph

## Tests
- **API** `test_phase6_operations.py` (22):
  - engine: priority determinism, bands and reasons; hospital banding (no counts); pressure levels (7 cases); ranking (cold chain before FEFO, nothing dropped); routing determinism, bands and speeds
  - emergency workflow: queue, recommendation, invalid selections, confirmed dispatch, audit meta, hospital ETA, events
  - plain FEFO unchanged
  - scope/RBAC (hospital, other bank, other hospital, admin, donor, anonymous)
  - priority change: audit, codes only, CSRF, events, 409s
  - pressure: real stock + open + synthetic mean
  - pressure-changed only on a level change
  - alerts: emergency, cold chain, expiry, summarised pressure
  - route scope
  - privacy
  - SSE: scope, replay, unique ordered ids
- **API** `test_integration_phase6.py` (PostgreSQL): recommendation with a critical bag, pressure, alerts, scope, confirmed dispatch, routing, SSE.
- **RBAC matrix:** +8 rows × 5 roles.
- **Web** `operations.test.tsx` (19):
  - helpers and verbatim disclaimer
  - queue: skeleton, order, band text, score label
  - reasons with sr-only tone and `aria-expanded`
  - empty, error and retry states
  - SSE refetch
  - priority change posts a reason code
  - ETA
  - allocation: ranking, deprioritised explanation, mobile scroll, confirmation required, cancel/no-dispatch when only flagged bags exist
  - pressure filter and label
  - alerts, bank workspace, hospital bands, admin view
- **Bootstrap:** `e2e: phase 6 emergency operations (...)`
  1. The hospital creates an emergency request.
  2. The bank sees it in the queue and inspects the priority reasons.
  3. It inspects the recommendation: the critical bag is deprioritised with its reason, and nothing has been dispatched.
  4. It inspects pressure and the simulated route (checked for determinism).
  5. It **explicitly confirms** dispatch of the recommended bag.
  6. Checks: SSE replay for bank and hospital; the unrelated hospital receives nothing; audit.
  7. The hospital sees its dispatched request with an ETA, and no exact stock, then receives it.
  8. An unrelated hospital, onboarded once through the admin + invite flow, gets 404. A donor gets 403.
  9. The bank discards the simulated-excursion bag (a person's action).

## Known limitations
- The rules and weights are hand-chosen prototype values. They are not calibrated or validated, and are not for real-world triage.
- Compatibility is exact group/component matching only, which is the existing rule. No substitution logic.
- Routing is schematic: no roads, traffic or courier state.
- Pressure uses the synthetic forecast, and open requests count only for blood banks.
- Operational events for routine/urgent requests are not emitted, to keep the Phase 2 stream unchanged. Their priority is always visible through the API.
- Pressure is recomputed per request (24 forecast series per facility). That's fine for a prototype; a cache is needed at scale.

## Future production work
- Validated, configurable rules with governance and clinical/operational review before any decision use.
- Real routing and courier tracking (Phase 7), with acknowledgements and escalation for alerts.
- Real demand history for the forecast input, and caching of pressure.
