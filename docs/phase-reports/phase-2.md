# PHASE STATUS — Phase 2: Core Blood Network

VEYRA now runs one complete, end-to-end blood-network loop:

**donor → donation → labelled bags → inventory → hospital request → FEFO dispatch → receipt → tamper-evident trace**

The loop runs through the API, PostgreSQL and the UI, with live updates.

## Implemented

### A. Inventory
- Endpoints:
  - `GET /inventory/summary`: stock by blood group × component for the caller's facility.
  - `GET /inventory/bags`: paged and filterable by status, group and component.
- Summary fields per cell:
  - `available`: usable (not expired) units.
  - `expiring_soon`: units expiring within 72 h.
  - `expired`: units still on the shelf, awaiting discard.
  - `next_expiry`.
- Scope:
  - A blood bank sees what it stores.
  - A hospital sees what it has received.
  - Nobody sees another facility's inventory.

### B. Donations
- Endpoints:
  - `POST /donors/lookup`: the donation desk finds a verified donor by mobile. It's a POST so the number never appears in URLs or logs. It returns only the name, masked mobile, blood group and eligibility, and is audited.
  - `POST /donations`: records a collection and creates one bag per component, each with a COLLECTED trace event.
  - `GET /donations`: the facility's donations.
  - `GET /donors/me/donations`: the donor's own history.
- Recording a donation:
  - The bank's typing confirms, or corrects, the donor's self-declared group (`blood_group_status` becomes `confirmed`).
  - The minimum donation interval is enforced (`donor_not_eligible`, 409).
  - Collection time can't be in the future or more than 48 h old.
  - Whole blood can't be combined with separated components.
- The donor's history shows impact (in storage, sent to hospitals, not used). It never names the receiving hospital or patient.

### C. Blood bags
- Each bag gets a unique public ID `VYR-XXXX-XXXX`:
  - Crockford base32, 40 random bits.
  - Unambiguous on a label.
  - Separate from the primary key.
  - QR payload: `veyra:bag:<id>`.
- Components and shelf lives:
  - Whole blood 35 d, packed red cells (PRBC) 42 d, fresh frozen plasma (FFP) 365 d, platelets 5 d, cryoprecipitate 365 d.
  - These are prototype defaults and are labelled as such in the UI.
- Lifecycle: `available → in_transit → received`, and `available|received → discarded`.
  - Every change goes through one function, which validates the transition (`invalid_transition`, 409).
  - That function is also the only writer of trace events.
  - Optimistic locking uses `version_id_col`; a concurrent change returns 409.
- Discard: `POST /bags/{id}/discard`, with a reason. Only the facility holding the bag can discard it.

### D. Append-only trace events
- `trace.bag_events` stores `seq`, `prev_hash` and `row_hash`.
  - `row_hash = sha256(prev_hash | canonical JSON of the event)`.
  - Timestamps are normalised to UTC so the hash survives a PostgreSQL round-trip.
- A PostgreSQL trigger blocks UPDATE and DELETE. `(bag_id, seq)` is unique.
- `GET /bags/{id}` returns the bag, its events and the result of recomputing the chain (`chain.valid`).
  - The UI shows "Chain verified" or "Chain broken".
  - It is labelled plainly: not anchored on a blockchain yet (Phase 8).
- Visibility:
  - Only facilities in the bag's custody chain, plus network admins, can trace a bag.
  - Everyone else gets 404, so the API doesn't reveal that the bag exists.

### E. Blood requests
- Hospital:
  - `GET /network/availability`: banded results (`sufficient` / `limited` / `none`), never exact stock.
  - `POST /requests`: supports `Idempotency-Key`.
    - A replay with the same key returns the original request (200).
    - The same key with a different body is rejected (422).
  - `/cancel` and `/receive`.
- Blood bank:
  - `GET /requests`: its incoming queue.
  - `/fulfil`: allocates first-expiry-first-out.
    - It uses `SELECT … FOR UPDATE SKIP LOCKED`, so a bag is never allocated twice.
    - Fulfilment is all or nothing: `insufficient_stock` (409) leaves the request pending.
  - `/reject`: needs a reason.
- State machine:
  - `pending → dispatched → fulfilled`.
  - `pending → rejected | cancelled`.
  - For mock providers: `acknowledged → cancelled`.
  - Illegal moves return `invalid_request_state` (409).
- Scope: only the requesting hospital and the target bank can see a request. Everyone else gets 404.

### F. Provider port
- `BloodBankProvider` protocol, injected via `app.state.bloodbank_providers`:
  - **`InternalBloodBankProvider`**: banks onboarded in VEYRA (real workflows in our DB).
  - **`MockBloodBankProvider`**: three fictional partner banks.
    - Availability is deterministic and generated.
    - Every result carries `source.kind = simulated` plus a disclosure note.
    - Requests to them are auto-acknowledged and never dispatched.
    - Refused in production by config validation (`VEYRA_ENABLE_MOCK_BLOOD_BANKS`).

### G. Transactional outbox
- `network.outbox_events` is written in the **same transaction** as the change it describes. A failed command writes no event, and a test covers this.
- A relay task in the API lifespan claims batches with `FOR UPDATE SKIP LOCKED` and publishes them to an in-process broker. Delivery is at-least-once; consumers de-duplicate by `event_id`.
- Payloads carry no donor identity or health data.
- Each event has an audience: the facilities involved.

### H. Server-Sent Events
- `GET /stream`:
  - Filtered by audience; admins see all events.
  - Sends a heartbeat every 15 s.
  - Supports `Last-Event-ID` / `?after=` replay from the outbox.
  - `?once=true` replays and then closes (used for smoke tests).
- `Cache-Control: no-store, no-transform`, so proxies (including Next.js compression) don't buffer the stream.

### I. UI
- Blood bank tabs:
  - **Inventory**: group × component matrix, expiry warnings, bag table with discard.
  - **Donation desk**: lookup → eligibility → record → printable bag labels with QR payload.
  - **Incoming requests**: dispatch, or decline with a reason; a "new" badge appears when a request arrives live.
  - **Trace**.
- Hospital tabs:
  - **Request blood**: banded availability, with "Simulated" badges on mock banks and an idempotent send.
  - **My requests**: live status and confirm receipt.
  - **Received stock**.
  - **Trace**.
- `/bags/[id]`: custody timeline with hashes, integrity panel, QR payload. The trace box accepts a bag ID or a pasted QR payload.
- Donor dashboard: donation history and next eligible date.
- Live indicator (EventSource) in the facility header; lists refresh on relevant events.
- Disclosures page and `docs/demo-disclosures.md` updated.

### J. Security boundaries
- New permissions:
  - `blood_request:read:own_facility`, `bag_trace:read:scoped`, `events:subscribe:scoped`
  - `bag:receive:own_facility`, `availability:read:network`, `donation:record:own_facility`
- The RBAC matrix now covers 17 Phase 2 endpoints × 5 roles.
- The service layer does all scope checks; cross-facility access returns 404.
- CSRF is enforced on every new unsafe endpoint.

### K. Migration `0003_core_blood_network`
- Adds six tables, `donors.blood_group_confirmed_at`, and the `trace.bag_events` append-only trigger.
- Fully reversible. `downgrade` was verified to remove everything, and re-upgrade was verified.

### Demo data (labelled DEMO ONLY)
- `app.scripts.seed_demo` now also creates:
  - "VEYRA Central Blood Bank (Demo)" with login `bank@veyra.demo`.
  - "VEYRA City Hospital (Demo)" with login `hospital@veyra.demo`.
- Password: `veyra-demo-console-2026`, the same documented demo credential as the admin; it passes the unchanged password policy.

## Defects found and fixed during Phase 2

- **The access-token `iat` check used the wall clock** (PyJWT) while `exp` used the injected clock.
  - Tokens were valid, but any test (or clock-skewed host) moved past real time was rejected.
  - `iat` is now checked against the service clock with 60 s leeway; the strictness is the same.
  - A regression test was added.
- **Hash-chain timezone drift**: a collection time sent with `+05:30` would have been hashed with that offset but read back from PostgreSQL in UTC, so the chain would falsely report "broken".
  - The hash input and stored times are now UTC.
  - A regression test was added.

## Phase 1 gate fixes (same delivery)

| Failure in 27/32 run | Root cause | Fix |
|---|---|---|
| `pnpm test` (session.test.ts) | Test helper built `new Response(body, {status: 204})`, which is invalid for null-body statuses | Helper returns `new Response(null, {status})` for 204/205/304 |
| Integration 409s (×2) and E2E donor 409 | No ORM relationships, so SQLAlchemy's unit of work inserted `donors` before `users` (FK violation → mapped to 409) | Each repository `add()` flushes immediately (insert order = call order). Unit test asserts flush order; flush-time IntegrityError/StaleDataError map to domain errors |
| Seed demo admin | Demo password contained the email name "admin" (policy correctly rejected it) | New documented DEMO password `veyra-demo-console-2026`; test asserts it passes the policy (policy unchanged) |
| E2E admin login 401 | Consequence of the failed seed | Fixed by the seed fix |
| (latent) Integration tests reused mobiles across runs | Deterministic test data | Mobiles derived from a fresh UUID |
| (latent) web vitest never ran | `pnpm -r` bailed on the first package failure | Root scripts use `pnpm -r --no-bail` |

## Tests

| Suite | Result (cloud run, Python 3.11) |
|---|---|
| API unit + API + RBAC (memory UoW) | **249 passed**, 6 skipped (Postgres integration: no asyncpg in the cloud sandbox) |
| ruff check / ruff format --check | clean (98 files) |
| mypy --strict `app` | clean (78 files) |
| Web `tsc --noEmit` (strict, `noUncheckedIndexedAccess`) | clean for app code |
| Migration vs models (`pg_dump -s` diff, PostgreSQL 16) | identical, apart from the trigger-function bodies, which are migration-only by design |
| Trigger / constraints / downgrade / re-upgrade on PostgreSQL 16 | verified |

Phase 2 tests added:
- `test_phase2_units.py`:
  - bag IDs, expiry and lifecycle
  - hash chain (edit, reorder and remove are all detected) and timezone stability
  - availability bands
  - mock and internal providers
  - production refusal of mock banks
  - broker fan-out and drop-oldest
- `test_phase2_network.py`: 21 API test functions (27 cases with parametrisation).
  - donations: desk lookup fields, genesis trace, interval rule, input validation
  - inventory: expiry, scope
  - discard: holder only, lifecycle
  - requests: banded availability with simulated labelling; the full lifecycle with FEFO and trace extension; idempotency replay and mismatch; insufficient stock; expired bags never dispatched; reject/cancel state rules; input rules; mock provider
  - privacy and integrity: donor history privacy, tamper detection, trace ID normalisation
  - outbox + SSE replay: transactional, audience-scoped, `Last-Event-ID`
  - live SSE push over raw ASGI, never delivered to other facilities
  - audit entries; demo seed idempotent, with working logins
- `test_rbac_matrix.py`: +17 endpoint rows × 5 roles.
- `test_integration_phase2.py` (real PostgreSQL):
  - the full vertical slice through the web API
  - concurrent fulfilment racing for one bag, which yields exactly one 200 and one 409 (`SKIP LOCKED`)
  - the `trace.bag_events` append-only trigger
- Web `network.test.tsx`:
  - bag-ID / QR parsing, expiry formatting
  - RequestCard simulated label
  - trace search validation
  - trace view: verified, broken and 404
  - live indicator
  - availability → idempotent request
- Bootstrap E2E step `e2e: phase 2 donation -> request -> FEFO dispatch -> receive -> trace -> SSE`: runs through the Next.js proxy against the Docker stack.

## Verification status on Windows

Run `powershell -NoProfile -ExecutionPolicy Bypass -File scripts\bootstrap.ps1`. There are now **33 steps**: the 32 Phase 1 steps, with "seed demo admin" renamed to include the demo facilities, plus the Phase 2 E2E step. Phase 2 is complete only when the log ends with `OVERALL: PASS (33/33 steps passed)`.

These parts have not run in the cloud sandbox and are proven only by that Windows run:
- the Postgres integration tests (asyncpg is unavailable there)
- ESLint, vitest and `next build` (the npm registry is blocked there)

## Known limitations / technical debt

- Fulfilment is all or nothing: there's no partial fulfilment or split across banks yet.
- The QR is a plain payload (`veyra:bag:<id>`), not a rendered image or signed token. Signed QR and on-chain anchoring are Phase 8.
- The SSE broker is in-process. With several API replicas, each replica's relay only feeds its own subscribers. Replay from the outbox still gives every client every event on reconnect, and Redis pub/sub fan-out is planned.
- Hospitals can't discard or mark transfused units yet, since transfusion isn't modelled.
- Shelf lives and the 90-day interval are prototype defaults, not clinical guidance.
- No Redis rate limiter on donor lookup yet; lookups are audited.
- Deliberately deferred from the roadmap's Phase 2 list, following "a smaller complete slice over many incomplete features":
  - per-facility low-stock **thresholds**
  - the straight-line **routing** provider
- Hospitals never see donor identity: bag and trace responses carry no donor, donation or actor fields.

## Recommended next phase

**Phase 3 — Dashboards & UX**, per the roadmap:
- app shell and role dashboards
- charts
- landing page v1
- Live Blood Network 2D, fed by the Phase 2 SSE stream

Carried over from Phase 2:
- low-stock thresholds and alerts
- straight-line routing estimates (roadmap items deferred to keep the slice complete)
- partial fulfilment
- Redis fan-out for SSE
- a transfusion / used-unit event
