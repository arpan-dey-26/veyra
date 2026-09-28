# ADR-0003: Identifiers and time

- Status: Accepted (2026-09-28)

## Decision
- Internal primary keys are UUIDv7 (`app/core/ids.py`).
- Public identifiers (for example blood-bag `public_id`) are separate opaque values and are never the primary key.
- All timestamps are `timestamptz` in UTC.
- Services receive a `Clock` instead of calling `now()`.

## Why
UUIDv7 is time-ordered, which keeps indexes efficient, and its IDs are not guessable. An injectable clock makes expiry, eligibility and alert rules testable.
