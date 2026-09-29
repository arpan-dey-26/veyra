# Phase 8 — Product completion: Compatibility Matrix, Donation Camps, QR Bag Scanning

**Result:** real Windows bootstrap `OVERALL: PASS (41/41 steps passed)` on Windows + Docker PostgreSQL 16 + Redis 7. The run is saved as `docs/phase-reports/phase-8-verification.log` (2026-09-29 23:06 IST).

The first Windows run (`phase-8-run1.log.txt`) was 38/41. It exposed audit finding #5 (a race that returned 500) and three test-side mistakes: an `AsyncEngine` attribute path, asyncpg returning `"char"` as bytes, and a vitest `beforeEach` that returned the mock and so ran it as a teardown. The race was fixed at its root and the tests were corrected without weakening any assertion. The second run above is fully green.

Phase 8 adds exactly three product features on top of Phases 1–7, plus the audit fixes below. No other feature work was started.

- **Compatibility Matrix:** "Informational prototype reference only; final transfusion decisions require authorized clinical confirmation."
- **Camp Management:** "Prototype camp-management workflow; donor eligibility and medical screening remain governed by authorized staff."
- **QR:** "QR is a traceability identifier, not an authentication credential or medical authorization."

## 1. Phase 7 audit findings (Step 0)

The audit covered the 20 areas asked for: bugs, security, RBAC and scope, CSRF, atomicity, races, SSE, migrations, append-only storage and hash chains, shipment transitions, cold chain, ETA, frontend states, a11y, mobile, dark mode, simulator guards, privacy, flaky tests and docs.

Each genuine defect was reproduced, fixed at its root, and given a regression test that fails on the old code:

| # | Defect | Root cause | Fix | Regression test |
|---|---|---|---|---|
| 1 | The shipment ETA and the destination checkpoint's expected time disagreed after early or late pickup, depart, checkpoint or resume. | Progress moved `eta_at` but left later checkpoints on the original plan. | `engine.replan` re-anchors every later checkpoint to "now", keeping the planned leg times. `destination_eta` derives the ETA from the schedule. | `test_eta_and_checkpoint_schedule_stay_consistent` |
| 2 | The Operations page showed a different ETA from the shipment. The dispatched-request estimate also drifted every hour. | Operations recomputed an hourly-bucket estimate for dispatched requests. | Routing uses the live shipment (remaining minutes, delay status, `shipment.eta_at`). Plain dispatches are anchored to the dispatch time. | `test_operations_eta_matches_the_live_shipment`, `test_plain_dispatch_route_is_anchored_to_the_dispatch_time` |
| 3 | Identity data could reach logs. An unexpected DB error (e.g. the Phase 7 VARCHAR overflow) was logged with SQLAlchemy's `[parameters: …]`, which can include emails and mobiles. | The engine was created without `hide_parameters`. | `create_async_engine(..., hide_parameters=True)`. | `test_database_errors_never_carry_bound_parameters_into_logs`, `test_live_engine_hides_bound_parameters` (PostgreSQL) |
| 4 | Web pages could stay stuck after a failed load. "Recent donations" stayed on its loading skeleton forever. My/incoming requests, inventory and the live network stayed in error even after a later refresh succeeded. Donor history had no retry. | The error was never cleared on success, and one list had no error branch. | Errors are cleared on success, and every error has a "Try again" button (`role="alert"`). | `components/network/recovery.test.tsx` |
| 5 | Two simultaneous receipts of one shipment returned 500 to the loser, not 409. Found by the new PostgreSQL race test on the first Windows run. | An optimistic-version `StaleDataError` surfaced from an **autoflush** inside a later query, bypassing the repository's explicit-flush mapping. | `register_persistence_errors` maps `StaleDataError` and `IntegrityError` to the same 409 problems. The unit of work has already rolled back. | `test_a_concurrent_change_surfacing_in_autoflush_is_a_409_not_a_500`, `test_concurrent_receipts_record_exactly_one_receipt` (PostgreSQL) |

Verified with no defect found:

- CSRF on every unsafe endpoint. This is an OpenAPI-driven test; only the five pre-session auth endpoints are allowlisted.
- Donor 403 on every operational read (OpenAPI-driven).
- Unrelated-facility 404 on every scoped resource.
- Production defaults disable every simulator.
- Append-only triggers are installed and enabled.
- Every bag chain in the database verifies.
- Concurrent relays never publish twice.
- Races resolve correctly: the same request is fulfilled once, and one bag goes to exactly one of two confirmed dispatches.
- Plain FEFO dispatch creates no shipment, legacy receipt still works, received bags are never dispatchable again, and shipment actions never change the bag lifecycle.

## 2. Compatibility Matrix

- **Domain:** `app/modules/compatibility/engine.py` is pure and deterministic, and is the single copy of the rules. The web renders the API results and never re-implements them.
  - Red cells (PRBC): the donor's A/B antigens must be ⊆ the recipient's. Rh-negative recipients get Rh-negative units.
  - Whole blood: ABO-identical, plus the red-cell Rh rule.
  - Plasma (FFP): the recipient's A/B antigens must be ⊆ the donor's. Rh is not considered.
  - Platelets: plasma-compatible ABO plus the Rh rule (conservative).
  - Cryoprecipitate: plasma-compatible ABO (conservative).
  - The notes say institutions often relax the platelet and cryo rules.
- **API** (read-only, `compatibility:read`: hospital, blood bank and admin; donor 403, anonymous 401):
  - `GET /api/v1/compatibility/matrix[?component=]` returns 8 recipient rows × compatible donors for each of the 5 components, with the rule text, label and disclaimer.
  - `GET /api/v1/compatibility/check?donor_group&recipient_group&component` returns `compatible`, `result`, reason, rule, both donor/recipient lists, `requires_clinical_confirmation: true` and the disclaimer. Invalid groups or components return 422.
- **Safety:** no persistence and no side effects (a test asserts that outbox, audit, requests and bags are unchanged). Nothing in allocation or dispatch calls it.
- **Web:** `/compatibility` has donor, recipient and component selectors with an API verdict, a matrix grid (text + glyph, accessible labels per cell), a recipient filter, a "compatible donors only" list view, and loading, empty, error and retry states. The disclaimer banner is always visible.

## 3. Camp Management

- **Data:** migration `0007` is additive only. It adds `network.camps` and `network.camp_registrations`, both registered in `models_registry.py`.
  - A camp has id, public code `CMP-XXXX-XXXX`, title, organizer facility, venue, city/state, start/end, capacity, `registered_count`, status, description, demo contact, cancel reason, timestamps and version.
  - A registration has donor, status, registered/cancelled/attended times, the staff member who confirmed, and the linked donation. **It stores no medical data.**
  - DB checks: status, capacity 1–5000, `registered_count <= capacity`, `ends_at > starts_at`, unique code, unique `(camp_id, donor_id)`, unique `donation_id`.
- **Lifecycle:**
  - The explicit table is `planned → published → registration_open → ongoing → completed`, with `cancel` allowed from planned, published or registration_open.
  - Anything else returns 409 `invalid_camp_transition`.
  - Edits are allowed only up to registration_open, and capacity can never drop below current registrations.
  - `complete` marks unconfirmed registrations `no_show`. This is not an eligibility decision.
  - `cancel` cancels the active registrations.
- **Registration:**
  - Only verified (active) donors can register, and only while registration is open.
  - Capacity is enforced under a camp row lock.
  - A duplicate returns 409 `already_registered`. A full camp returns 409 `camp_full`.
  - A donor can cancel their own registration, and may re-register later using the same row.
- **Attendance and donation:** staff confirm attendance only while the camp is ongoing. A camp donation is recorded through the **existing** `POST /donations` with an optional `camp_registration_id`. The link is validated *before* anything is written. Every donation control still applies: verified donor, 90-day interval (tested), collection time, and this bank's own camp.
- **RBAC and scope:**
  - Blood bank: `camp:manage:own_facility`, own camps only; other banks get 404.
  - Admin: `camp:manage:network`, and must name an active blood bank.
  - Donor: `camp:register:self`.
  - Hospital: read-only access to published camps.
- **Mutations:** all are authenticated, CSRF-protected and audited (`camp.created|updated|published|registration_opened|started|completed|cancelled`, `camp.registration_created|registration_cancelled`, `camp.attendance_confirmed`, `camp.donation_linked`).
- **Live events:** SSE `camp.updated` goes to the organizing bank only, with counts and never donor identity.
- **API:**
  - Management and dashboard: `GET|POST /camps`, `GET /camps/dashboard`, `GET|PATCH /camps/{id}`, `POST /camps/{id}/actions/{publish|open-registration|start|complete|cancel}`, `GET /camps/{id}/registrations`, `POST /camps/{id}/registrations/{rid}/attend`
  - Donors: `GET /camps/public[?q&city&status]`, `GET /camps/public/{id}`, `GET /camps/me/registrations`, `POST /camps/{id}/register`, `POST /camps/{id}/register/cancel`
- **Web:** `/camps` depends on the role.
  - Bank and admin see a dashboard (upcoming, active, completed, registrations, attended, donations, bags), filters, a create form, and a camp list.
  - `/camps/[id]` shows stats, lifecycle buttons (cancel asks for confirmation inline), editing, registrations with "Confirm attendance", and "Record donation" through the desk.
  - Donors get search and city filters, register and cancel buttons, and "My registrations".
  - Hospitals get a read-only list.
  - Every view has loading, empty, error, retry and not-found states.

## 4. QR Scanning / QR-based bag traceability

- **Payload:** the payload is the public id only: `veyra:bag:VYR-XXXX-XXXX`. It is deterministic and was already on every bag since Phase 2. There is no donor or patient data, no token and no secret. No schema change was needed.
- **Encoder:** `app/modules/bags/qr.py` is a dependency-free QR encoder (byte mode, level M, versions 1–4). It was verified during development against an independent decoder (OpenCV) for 34 payloads, and is pinned by a golden digest plus structural tests (finders, timing, dark module).
- **API** (same `bag_trace:read` permission and custody scope as the trace: anonymous 401, donor 403, facility outside the custody chain 404, admin network-wide):
  - `GET /api/v1/bags/scan?payload=` accepts a label or typed id and returns lifecycle, usable flag, location, simulated cold chain, shipment, hash-chain status, last event, `trace_path` and the disclaimer. Malformed payloads return 422 `invalid_qr` (the input is not echoed); nonexistent bags return 404.
  - `GET /api/v1/bags/{id}/qr` returns the module matrix.
  - Scanning is read-only.
- **Web:** `/scan` supports camera scanning via the browser `BarcodeDetector` where available.
  - Frames are decoded on the device and are **never stored or uploaded**.
  - There are clear camera-unavailable and permission-denied states, and manual id entry as the fallback.
  - The result card has a link to the full trace.
  - The bag page's QR card gains "Show QR" (fetched on demand, shown as an SVG that stays dark-on-white in dark mode) and "Print label".

## 5. Navigation

The nav gains **Camps** (donor, blood bank, admin), **Compatibility** (hospital, blood bank, admin) and **Bag scanner** (**Bag trace** for admin). Existing pages and tabs are unchanged.

## 6. Tests (real Windows run)

| Suite | Result |
|---|---|
| API unit + API tests (memory UoW) | **670 passed** (Phase 1–7 unchanged + Phase 8 features/regression/RBAC rows) |
| PostgreSQL + Redis integration | **23 passed** (includes Phase 8 races, triggers, chain validity, camp→QR→receipt on PostgreSQL) |
| Web (vitest) | **158 passed** (15 files) · api-client 9 · design-tokens 5 |
| ruff / ruff format / mypy strict / tsc strict / eslint / next build | clean |
| Migrations | upgrade head, `alembic check`, scratch-DB round-trip `base → head → base → head`, schema identical to the dev DB |
| RBAC matrix | +17 Phase 8 rows × 5 roles |

## 7. End-to-end demo (bootstrap step `e2e: phase 8 …`, safe demo data)

1. The bank creates a camp; an invalid transition gets 409.
2. The bank publishes the camp and opens registration.
3. A freshly registered demo donor finds the camp by search.
4. The donor registers; a duplicate registration gets 409.
5. Staff start the camp, confirm attendance, and record the donation through the desk with `camp_registration_id`. The camp stats show 1 attended, 1 donation and 1 bag.
6. A bag is created.
7. The bag's QR payload is `veyra:bag:<id>`, and the QR matrix is 25×25.
8. Compatibility: A+ → AB+ PRBC is compatible and AB+ → O− PRBC is not; the matrix has 5 components.
9. The bag is scanned by the bank.
10. The scan shows no donor identity. Access checks: anonymous 401, donor 403, unrelated hospital 404, malformed QR 422.
11. The scan shows a valid chain.
12. A simulated device is attached, and the scan shows the cold chain.
13. An emergency request, confirmed dispatch and shipment follow; the hospital's scan shows the shipment as pickup_pending.
14. Advance ×4, arrive, then the hospital receives the shipment.
15. The final scan shows received / received with a valid chain. The trace contains COLLECTED, DEVICE_ATTACHED, DISPATCHED, SHIPMENT_CREATED, SHIPMENT_ARRIVED, RECEIVED and SHIPMENT_RECEIVED. The camp completes. SSE `camp.updated` reaches the bank only.

## 8. Real vs simulated

| Real (implemented, exercised by tests) | Simulated / prototype (labelled) |
|---|---|
| Auth, sessions, CSRF, RBAC + facility scope, audit, request ids, safe errors | Demo phone verification, demo accounts, demo invitations |
| PostgreSQL persistence, append-only triggers, SHA-256 hash-chained bag trace | Partner blood banks (mock provider) |
| Donations, bags, FEFO dispatch, requests, receipt, outbox → SSE | IoT telemetry (software simulator) |
| Camp lifecycle, registrations, capacity, attendance, desk-linked donations | Logistics couriers, routes, ETAs |
| Compatibility rules engine (deterministic, simplified) | Synthetic ML demand data |
| QR encoding, scan lookup, camera decoding in the browser | Compatibility content is a **simplified reference**, not clinical |

There are no GPS, maps, courier, hospital, LIS or production integrations, and no medical validation claims.

## 9. Known limitations

- Compatibility is simplified ABO/Rh only. It has no antibody screen, crossmatch, irradiation or CMV rules, no pediatric rules, and no institutional policy. The platelet and cryoprecipitate rules are deliberately conservative.
- Camps have no email or SMS notifications, no waitlist and no recurring camps. Times are shown in the browser's zone. Walk-ins must register first.
- Camera scanning depends on `BarcodeDetector` (Chromium and Android; not Firefox or iOS Safari yet). Manual entry covers every browser.
- The QR is not signed. Knowing an id grants nothing, because the scope is enforced server-side.
- The shipments list does per-row lookups; it is bounded to 200 rows and was measured as acceptable for the prototype.

## 10. Future production work

- Clinical governance of compatibility content: versioned rule sets reviewed by transfusion medicine, and LIS crossmatch integration.
- Camp notifications, attendance kiosk, waitlists, and organizer staff roles.
- Signed or expiring label payloads, and label printer integration.
- On-chain anchoring of trace heads.
- Real courier and IoT integrations behind the existing provider ports.
