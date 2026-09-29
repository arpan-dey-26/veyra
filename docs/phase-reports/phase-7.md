# PHASE STATUS — Phase 7: Logistics, Shipment Tracking & Delivery

> **Simulated logistics — prototype.** This is a simulated logistics prototype. Routes, courier status and ETAs are not real-world navigation or delivery guarantees. Couriers are fictional, checkpoints are schematic, and no GPS, maps, traffic or courier-company data is used.

## Phase 6 final gate
Real Windows bootstrap: **`OVERALL: PASS (38/38 steps passed)`**, saved as `docs/phase-reports/phase-6-verification.log`.

## Phase 7 gate
Real Windows bootstrap, 2026-09-29 16:29 IST: **`OVERALL: PASS (39/39 steps passed)`**. The run is saved as `docs/phase-reports/phase-7-verification.log`.

- **Phase 7 E2E:** shipment `SH-BVTN9V84` for request `RQ-6PKKGCHM`. It had a fictional courier (Demo Courier Echo) and 5 checkpoints, got a cold-chain warning in transit and a +18 min simulated delay, and was then received by the hospital.
- **Integration tests on PostgreSQL:** 12/12 pass.

**Earlier attempts**, fixed without changing any assertion:
- **Run 1: 36/39.** On PostgreSQL, `SHIPMENT_IN_TRANSIT` and friends overflowed `trace.bag_events.event_type VARCHAR(16)`. Fixed by migration `0006` and a regression test.
- **Run 2: 38/39.** The unchanged Phase 2 E2E replay (`after=0`) was crowded out by other facilities' events in the long-lived database. The SSE replay fix is described below.

## Architecture

```
app/modules/logistics/
  models.py   network.shipments, network.shipment_bags, network.shipment_events (append-only)
  engine.py   pure: state machine, fictional courier, schematic route, ETA
  hooks.py    state changes shared by dispatch, receipt, telemetry and simulator paths
  service.py  scoped reads + demo controls
  router.py   /shipments/* and /simulator/shipments/*
migrations/versions/0005_logistics_shipments.py
```

- **A shipment is created by a human-confirmed dispatch:** `POST /requests/{id}/fulfil` with `bag_public_ids`, the Phase 6 recommendation flow.
  - It holds the request, source and destination facilities, the bags, the simulated courier, the route checkpoints, the ETA, the delay state and a cold-chain flag.
  - It may contain several bags from the same dispatch.
- **The plain dispatch (`{}`, strict FEFO) is unchanged and creates no shipment.** Phase 2 behaviour stays exactly the same: its trace length, its event list, and the E2E that receives straight away.
- **Custody:** the bag lifecycle is unchanged. DISPATCHED makes the bag `in_transit`, and RECEIVED (through the existing receive workflow) makes it `received`. The source bank keeps custody until receipt, so it drives the demo transport and the cold-chain simulator during transit.
- **Migration `0006`** widens `trace.bag_events.event_type` from 16 to 32 characters. The shipment event names, such as `SHIPMENT_IN_TRANSIT`, are longer than 16.
  - Widening keeps every stored row and trace hash unchanged.
  - The downgrade narrows the column only when no stored event needs the width.
  - The first Windows PostgreSQL run caught the overflow; the in-memory store doesn't enforce lengths. A regression test now checks that every event type fits the column.
- **Migration `0005`**, reversible:
  - three tables in the existing `network` schema, with an append-only trigger on the timeline
  - the bag-event CHECK widened for the shipment observation types; downgrade restores it `NOT VALID`
  - registered in `models_registry.py`
  - verified on PostgreSQL 16: `pg_dump` of the migrated vs model schema shows no drift, and upgrade → downgrade → upgrade works
  - no Phase 2–6 table is dropped or recreated

## State machine

```
created → pickup_pending → picked_up → in_transit ⇄ (checkpoints) → arrived → received
                           picked_up / in_transit → delayed → resume → (previous status)
```

| Action | Allowed from | To |
|---|---|---|
| assign (automatic at creation) | created | pickup_pending |
| advance (pickup) | pickup_pending | picked_up (checkpoint 0) |
| advance (depart) | picked_up | in_transit (checkpoint 1) |
| advance (checkpoint) | in_transit, before checkpoint 3 | in_transit (checkpoints 2, 3) |
| delay (+1–240 min, reason code) | picked_up, in_transit | delayed |
| resume | delayed | the status before the delay |
| arrive | in_transit at checkpoint 3 | arrived (checkpoint 4) |
| receive (`POST /shipments/{id}/receive`) | arrived | received |
| existing `POST /requests/{id}/receive` | any open state | arrived (`confirmed_at_receipt`) → received |

- **Everything else is rejected with 409** `invalid_shipment_transition`. That includes advancing while delayed, arriving before the last checkpoint, and any action on a received shipment.
- **Receipt** on the shipment endpoint requires `arrived` (409 `shipment_not_arrived` otherwise). The receipt then runs the **existing** receive workflow: same audit, lifecycle events and request status.
- **Legacy receipt:** the existing request endpoint stays backward compatible. It is recorded explicitly as the recipient confirming arrival, so it is not a silent transition.
- **No cancellation state:** a dispatched request can't be cancelled in the existing lifecycle. `received` is the only terminal state.

## Simulated courier and route
- **Courier:** deterministic from the request id. Id `SIM-CR-####`, a fictional name ("Demo Courier Alpha…Foxtrot"), and a vehicle type ("Insulated motorbike box (simulated)" for emergencies, "Refrigerated van (simulated)" otherwise).
- **Route:** extends Phase 6 simulated routing. The schematic distance and travel time are split into five checkpoints:
  1. the source facility
  2. a collection point (simulated)
  3. a transit checkpoint (simulated)
  4. the destination area (simulated)
  5. the destination facility

  The legs are 15 / 45 / 30 / 10 % of the trip. Each checkpoint has a sequence number, a simulated cumulative distance, an expected time, the actual time once reached, and a status. No coordinates are stored or shown.

## ETA engine (deterministic, not clinical)
**How the ETA is set:**
- **At creation:** now + handover + travel.
- **On each checkpoint:** now + the planned minutes of the remaining legs.
- **On a delay of +N:** the ETA and every later checkpoint move by N.
- **On resume:** the later of the stored ETA and now + remaining.
- **On arrival:** now.

**ETA statuses:**
- `on_schedule`
- `delayed` (while a delay is active)
- `late` (past the ETA)
- `arrived`
- `delivered`

Responses include the remaining minutes and the reasons behind the ETA. The ETA is labelled **"Simulated ETA — prototype"**.

## Cold-chain integration
- `GET /shipments/{id}/telemetry` shows each bag's latest temperature, cold-chain state, active excursion, device status and last telemetry time (Phase 5, simulated).
- **A warning or critical transition on a bag that is in transit in a shipment:**
  - keeps the existing `temperature.*` and `cold_chain.operational_alert` events unchanged
  - raises the shipment's `cold_chain_alert` flag, which never goes back down
  - adds a `COLD_CHAIN_WARNING` / `COLD_CHAIN_CRITICAL` timeline entry
  - emits the logistics-scoped `shipment.cold_chain_alert` to the source and destination
- A recovery adds `COLD_CHAIN_RECOVERED`, and the flag stays for human review.
- **Nothing is discarded or received automatically.**

## Traceability
- **Trace events:** `SHIPMENT_CREATED`, `SHIPMENT_PICKED_UP`, `SHIPMENT_IN_TRANSIT`, `SHIPMENT_DELAYED`, `SHIPMENT_ARRIVED` and `SHIPMENT_RECEIVED` are **observation events** in each bag's existing append-only SHA-256 hash chain. Like the Phase 5 cold-chain events, they never change the bag status.
- **Lifecycle validation is unchanged.** A received bag's trace reads:

  COLLECTED → DISPATCHED → SHIPMENT_CREATED → SHIPMENT_PICKED_UP → SHIPMENT_IN_TRANSIT → SHIPMENT_DELAYED → SHIPMENT_ARRIVED → RECEIVED → SHIPMENT_RECEIVED

  The chain verifies throughout.
- **The full shipment timeline** also includes COURIER_ASSIGNED, CHECKPOINT_REACHED, SHIPMENT_RESUMED and cold-chain entries. It is kept in `network.shipment_events`, which is append-only via a database trigger.

## API

| Endpoint | Scope |
|---|---|
| `GET /shipments?status=` | bank: shipments it sent; hospital: incoming; admin: network. Counts: awaiting pickup, in transit, delayed, arrived, completed today, cold-chain alerts, on schedule, late; plus the average simulated delivery time |
| `GET /shipments/{id}` | detail: request, source, destination, bags (+ chain status), courier, ETA, checkpoints, cold chain, `trace_valid` |
| `GET /shipments/{id}/route` · `/timeline` · `/telemetry` | same scope |
| `POST /shipments/{id}/receive` | destination hospital (`bag:receive`), CSRF, arrived only → existing receive workflow |
| `POST /simulator/shipments/{id}/advance` · `/delay` · `/resume` · `/arrive` | source bank only (`logistics:simulate:own_facility`), CSRF, audited, disabled in production |

- **Simulator setting:** `VEYRA_ENABLE_LOGISTICS_SIMULATOR` defaults to demo mode. Enabling it with `VEYRA_ENV=production` is refused at startup. When disabled, the controls return 403 `simulator_disabled`.
- **Unrelated facilities** get 404, donors 403 and anonymous callers 401. Added to the RBAC matrix: 10 rows × 5 roles.

## SSE (existing outbox)
- **Topics:**
  - `shipment.created`
  - `shipment.picked_up`
  - `shipment.in_transit`
  - `shipment.checkpoint_reached`
  - `shipment.delayed`
  - `shipment.resumed`
  - `shipment.arrived`
  - `shipment.received`
  - plus `shipment.cold_chain_alert`
- **Audience:** the source bank and the destination hospital. Admins see all.
- Last-Event-ID replay, ordering, de-duplication and scoping are unchanged and tested.
- **Replay fix,** found by the second Windows run, where the unchanged Phase 2 E2E step `stream?once=true&after=0` failed.
  - **Cause:** in a long-lived database the outbox grows with every run. The replay took the first 500 rows *before* filtering by audience, so other facilities' events crowded out the caller's own.
  - **Now:** the replay filters by audience first (scanning at most 5,000 rows per request) and returns up to 500 of the caller's events. `after=0` means the recent history window, the last 2,000 outbox rows, not the whole table. Explicit cursors (`after=N`, `Last-Event-ID`) keep their exact semantics.
  - A regression test covers it.

## Security, privacy and audit
- **Payloads** carry facility ids, request and shipment references, status, ETA and the fictional courier. There is no donor, patient or user identity (tested on every endpoint and event).
- **Audit entries:**
  - `shipment.created` (at the confirmed dispatch)
  - `shipment.simulated_advance|delay|resume|arrive` with from/to (plus minutes and reason code for a delay; codes only, no free text)
  - `shipment.received`
- The existing `blood_request.dispatched` / `blood_request.fulfilled` audit entries are unchanged.

## Web
- **Operations tab (bank and hospital): a shipments section.**
  - Tiles: awaiting pickup, in transit, delayed, completed or received today, cold-chain alerts.
  - A scrollable table with text + glyph statuses, simulated ETA (with delay), current checkpoint and cold-chain flag, linking to the detail page.
- **`/shipments/[id]`:**
  - status, request, source → destination, trace/hash-chain status
  - ETA, delay, simulated courier, route length
  - **schematic route** (`<figure>`/`<ol>` with `aria-current="step"` and glyphs), labelled "Prototype logistics route — not a geographic map". The pulse uses `motion-safe`, so it doesn't move under reduced motion, and a Table view is available.
  - accessible timeline (`<ol>` with `<time>`)
  - cold-chain table
  - bags
  - **Source bank:** demo controls (advance, delay with minutes and reason, resume, arrive).
  - **Destination hospital:** a two-step "Receive shipment… → Confirm receipt", only once the shipment has arrived.
- **Admin:** network shipments, in transit, delayed, average simulated delivery, cold-chain alerts, and a route status summary.
- **Every view:** skeleton, error + retry, empty and not-found states, light and dark mode tokens.

## Tests
- **API** `test_phase7_logistics.py` (11):
  - state machine
  - courier and route determinism and shape
  - ETA statuses
  - creation on confirmed dispatch only (FEFO unchanged)
  - the full lifecycle with delay/resume, blocked transitions, human receipt, the complete timeline and trace, audit and counts
  - legacy receipt closing the shipment
  - scope, RBAC, CSRF and validation
  - disabled simulator and the production guard
  - a cold-chain alert in transit with no automatic action
  - privacy
  - SSE: lifecycle order, replay, de-duplication, isolation
- **API** `test_integration_phase7.py` (PostgreSQL): the real lifecycle, route, cold chain in transit, scope, receipt, trace, and the append-only trigger.
- **RBAC matrix:** +10 rows.
- **Web** `logistics.test.tsx` (11): helpers and disclaimer; list (skeleton, table, statuses, delay, cold chain, link, mobile scroll, empty, error, retry, SSE refresh); route visual; detail (ETA, courier, timeline, cold chain, table toggle, bank controls, delay notice, two-step receipt, no receipt before arrival, not-found and error); admin.
- **Bootstrap:** new step `e2e: phase 7 simulated logistics (...)`
  1. The hospital creates an emergency request.
  2. The bank inspects it and dispatches the recommended bag; a shipment is created.
  3. The shipment is picked up, goes into transit, reaches a checkpoint, and gets a **cold-chain warning in transit**.
  4. A delay of +18 is injected; advancing is blocked; it resumes and arrives.
  5. The hospital inspects the ETA, route and cold chain, then **explicitly receives** it.
  6. Checks: the request is fulfilled, the bags are received, the timeline is complete and the hash chain is valid.
  7. The SSE replay contains every shipment event; the unrelated hospital receives none (404); the donor gets 403.

## Known limitations
- Everything about transport is simulated: fictional couriers, schematic checkpoints, and hash-derived distances. No live tracking.
- The simulated ETA ignores real traffic and does not recompute continuously; it changes only on shipment actions.
- Only human-confirmed (recommendation) dispatches create shipments. Plain FEFO dispatches keep the Phase 2 workflow.
- No courier handover or signature capture, and no partial deliveries.
- The cold-chain alert flag is sticky by design, for human review. There is no "reviewed" action yet.

## Future production work
- Real courier or fleet integration with authenticated device check-ins, and real routing.
- Proof of delivery and chain-of-custody signatures; partial-delivery and return flows.
- Time-series storage of transit telemetry; alert acknowledgement and escalation.
