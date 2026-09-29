# PHASE STATUS — Phase 5: IoT Blood-Bag Telemetry & Cold-Chain Traceability

> **Simulated IoT telemetry — prototype.** This is simulated IoT telemetry for a student engineering prototype and is not a certified medical monitoring system. No hardware is used. The thresholds below are prototype values, not clinical guidance.

## Phase 4 final gate
Real Windows bootstrap: **`OVERALL: PASS (36/36 steps passed)`**. The run is saved as `docs/phase-reports/phase-4-verification.log`.

## Architecture

```
app/modules/telemetry/
  models.py    telemetry.devices (one simulated device per bag), telemetry.readings (append-only)
  rules.py     component thresholds, classification, deterministic simulator, device status
  service.py   scoped reads, simulator actions, take_reading() excursion state machine
  router.py    read endpoints + separate /simulator router (CSRF, holder-only)
  ticker.py    background "live readings" loop for running devices (demo mode only)
  errors.py / schemas.py
migrations/versions/0004_telemetry_cold_chain.py
```

- **Same modular monolith.** Router → service → UnitOfWork, with SQL and in-memory implementations. Events go through the transactional outbox, then the relay, then SSE.
- **One simulated device per bag.** It has:
  - a `device_id` (`SIM-XXXX-XXXX`)
  - a simulated RFID/EPC (`E280-…`)
  - battery %, which drains 0.2 per reading
  - `last_seen_at` and a readings count
  - simulator state: running, and mode normal / excursion / recovering
  - the current cold-chain status
  - an optimistic `version`
- **Device status** is one of awaiting first reading, online, low battery (< 20 %), paused, or offline/stale (no reading for more than 5 min).
- **Attaching is explicit** (a simulator action), not automatic at donation. Existing Phase 2 lifecycles, their trace lengths and the Phase 1–4 E2E steps are therefore unchanged.

## Cold-chain thresholds (prototype)

| Component | Nominal | Normal | Warning | Critical |
|---|---|---|---|---|
| PRBC, whole blood | 4 °C | 2–6 °C | outside normal | < 1 or > 8 °C |
| Platelets | 22 °C | 20–24 °C | outside normal | < 18 or > 26 °C |
| FFP, cryo | −25 °C | −40 to −18 °C | outside normal | < −45 or > −10 °C |

Tracked per bag:
- current, min and max temperature
- excursion start, duration, severity and peak
- recovery

Excursions are also derived from the readings: consecutive non-normal readings form one excursion, ending at the first normal reading.

## Deterministic simulator
- A reading is `simulated_temperature(device_id, component, seq, mode, step, last)`. The noise is SHA-256-seeded from the device id and sequence, so the same device and actions always produce the same readings.
- **Normal:** nominal ± small noise.
- **Excursion:** ramps warm, reaching warning on the first reading and critical by the second or third.
- **Recovering:** returns to the normal range over two readings.
- **Controls:** attach, take readings (`tick`, 1–20), start/pause live readings, inject excursion, restore normal.
  - Live readings come from the background ticker, one reading per running device every `VEYRA_TELEMETRY_TICK_SECONDS` (15 s), using `FOR UPDATE SKIP LOCKED`.
- **Enabled only in demo mode.** `VEYRA_ENABLE_TELEMETRY_SIMULATOR` defaults to demo mode. Enabling it with `VEYRA_ENV=production` is refused at startup. When disabled, simulator endpoints return 403 `simulator_disabled`.

## Traceability (hash chain)
New trace event types:

| Event | Recorded when | Meta |
|---|---|---|
| `DEVICE_ATTACHED` | a device is attached | `device_id`, `simulated: true` |
| `TEMP_EXCURSION` | on entering warning, and again on escalating to critical | `severity`, `temperature_c`, `device_id` |
| `TEMP_RECOVERED` | on return to normal | `duration_seconds`, `max_severity`, `peak_c` |

- They are **observation events**. `append_event` validates lifecycle transitions only for lifecycle events, so observation events never change bag status.
- They are chained into the same append-only SHA-256 trace. Chain verification covers them, and tests assert the chain stays valid.
- Readings themselves are **not** in the trace: that would be one row per reading. They live in `telemetry.readings`, which a database trigger makes append-only (UPDATE/DELETE raise).

## API
**Reads** (`bag:trace:read`, custody-chain scope from `BagService.visible_bag`: a bag outside the caller's chain returns **404**):

| Endpoint | Returns |
|---|---|
| `GET /bags/{public_id}/device` | Simulated device (404 `no_device` when not monitored) |
| `GET /bags/{public_id}/telemetry?limit≤500` | Readings series + thresholds + disclaimer |
| `GET /bags/{public_id}/telemetry/summary` | Status, current/min/max, battery, active excursion + duration |
| `GET /bags/{public_id}/cold-chain` | Excursions, cold-chain trace entries, `chain_valid` |
| `GET /telemetry/monitored` | Blood bank / hospital: own facility. Admin: network level. Includes counts. |

**Simulator** (`telemetry:simulate:own_facility`, CSRF double-submit, only the facility currently holding the bag, anyone else gets 404):
- `POST /simulator/bags/{id}/attach` (201; 409 if already attached or the bag is discarded)
- `POST /simulator/bags/{id}/start`, `/pause`, `/tick` (`{count: 1..20}`), `/excursion`, `/recover`

Every simulator action is audited (`telemetry.device_attached`, `telemetry.simulator_started/paused`, `telemetry.excursion_injected`, `telemetry.recovery_started`, `telemetry.readings_generated`). Payloads carry no donor, patient or user identity.

## RBAC and scope

| Role | Access |
|---|---|
| Blood bank / hospital | Telemetry of bags in their custody chain. A hospital sees a bag once it is dispatched to it; unrelated bags return 404. Simulator only for bags they currently hold. |
| Admin | Network-level monitored view and any bag's reads. No simulator (403). |
| Donor | 403 on every telemetry and simulator endpoint |
| Anonymous | 401 |

The RBAC matrix gains 11 rows × 5 roles.

## Live events (SSE)
- Topics: `telemetry.updated` (every reading), `temperature.warning`, `temperature.critical`, `temperature.recovered` (with `duration_seconds`).
- The audience is the facility holding the bag, plus the destination while the bag is in transit. Admins see all.
- Events come from the outbox, so `Last-Event-ID` / `after=` replay works as in Phase 2. It is tested in the API suite and in the E2E step.

## Web
- **Blood bank → Cold chain tab** (Smart Bag monitoring):
  - disclaimer
  - tiles: monitored / normal / warning / critical / offline-paused
  - a monitored table with latest temperature, reading time, battery, device status and excursion duration
  - "Start monitoring" for unmonitored available bags
  - refreshes live over SSE
- **`/bags/[publicId]`:** a Cold chain panel under the custody trail.
  - device and simulated RFID
  - status, current/min/max, battery, excursion duration
  - temperature chart: normal band, critical limits, warning/critical markers, tooltip, and a Table view
  - excursions list, and the number of cold-chain entries with chain status
  - demo simulator buttons, only for the holding facility
- **Admin:** a network cold-chain card with counts only.
- **Every view:** loading skeletons, error with **Try again**, empty states. Status is never shown by colour alone.

## Migration `0004_telemetry_cold_chain`
- Creates `telemetry.devices` and `telemetry.readings`, with indexes and uniques (`device_id`, `rfid`, `bag_id`, `(device_pk, seq)`).
- Adds the append-only trigger on readings.
- Widens the `bag_events` event-type CHECK.
- Registered in `models_registry.py`. `alembic check` is clean, and a PostgreSQL 16 `pg_dump` of migrated vs model schema shows no drift.
- **Reversible:** downgrade drops the tables and restores the previous CHECK as `NOT VALID`, so existing rows are kept. Upgrade → downgrade → upgrade was verified.
- No Phase 2 table is dropped or recreated.

## Tests
- **API** `test_phase5_telemetry.py`:
  - thresholds (parametrised)
  - simulator determinism and the normal → warning → critical → recovery walk
  - device identity and status
  - attach + trace
  - full excursion lifecycle with durations and a valid chain
  - ticker
  - monitored counts
  - scope, including a hospital after dispatch
  - holder-only simulator, CSRF, count bounds
  - disabled config + production guard
  - discarded bag 409
  - privacy + audit
  - SSE outbox, relay, replay and other-facility isolation
  - excursion grouping
- **API** `test_integration_phase5.py` (PostgreSQL): the excursion journey, the ticker, outsider 404, and the append-only trigger.
- **RBAC matrix**: +11 rows.
- **Web** `telemetry.test.tsx`: 20 tests.
  - helpers
  - verbatim disclaimer
  - chart: accessible label, legend, table view, empty state
  - bag panel: data, warning/critical, read-only viewers, "Not monitored" → attach, simulator transitions, error + retry, SSE refresh for this bag only
  - Smart Bag monitor: table, counts, attach, empty, error + retry, SSE refresh
  - admin card
  - bag page with session: controls for the holder only
- **Bootstrap**, new step `e2e: phase 5 simulated IoT cold chain (excursion -> trace -> SSE, scoped)`:
  1. The bank signs in and opens the blood-bank page (monitoring).
  2. It records a donation, opens the bag page, attaches a device and takes normal readings.
  3. It injects an excursion: warning, then critical. Then it restores normal: recovered.
  4. Reads: telemetry, summary, cold-chain, device. The trace has 5 events, a valid chain, and the bag is still available.
  5. The SSE `Last-Event-ID` replay contains all four topics for the bag.
  6. The hospital gets 404 on all four reads and on the simulator, and receives no events for the bag.
  7. The admin sees the bag in the network view. A donor gets 403.

## Known limitations
- Everything is simulated: there are no devices, RFID readers or gateways, and readings arrive only through the simulator.
- The thresholds are fixed prototype values. There's no per-product or per-site configuration and no clinical validation.
- Live readings run in the API process. With several API replicas, `SKIP LOCKED` prevents double readings, but the tick rate scales with the replica count.
- Offline/stale is derived from `last_seen_at` at read time. No "device offline" event is emitted.
- No alert escalation (notifications, acknowledgement) beyond SSE and the UI.

## Future production work
- Real device ingestion (MQTT/HTTPS gateway) with device identity, signed payloads and clock-skew handling.
- Configurable, validated thresholds; excursion acknowledgement and disposition workflow; notifications.
- A retention policy and time-series storage for readings; anchoring cold-chain trace hashes (Phase 8).
