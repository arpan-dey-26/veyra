# ADR-0009: Authentication, sessions and persistence ports

- Status: Accepted (2026-09-28, Phase 1)

## Decision

- **Passwords:** Argon2id via `cryptography` (PHC string), with the pepper fed in as the Argon2 `secret`. The pepper is `VEYRA_PASSWORD_PEPPER`, or an HKDF-derived key from `VEYRA_SECRET_KEY`. Unknown-account logins spend the same work as real ones. After 5 failures the account locks for 15 minutes.
- **Sessions:** a 15-minute HS256 access JWT bound to a server-side session (`sid`), plus an opaque refresh token (only its SHA-256 is stored) that rotates on every use. Replaying a rotated token revokes the whole family (theft detection). Every request re-checks that the session is still active, so logout is immediate. The role is read from the database, not from the token.
- **Cookies:** `veyra_access` (httpOnly, path `/`), `veyra_refresh` (httpOnly, path `/api/v1/auth`) and `veyra_csrf` (readable by JS). All are SameSite=Lax and Secure in production. Cookie-authenticated unsafe requests must send `X-CSRF-Token` (double submit). Bearer clients are exempt.
- **Phone verification:** the `VerificationProvider` port. `demo_last4` is DEMO ONLY: it is labelled in the API (`mode: "demo"`, `disclaimer`) and the UI, and refused in production. `sms` has the real design (random code, only the hash stored) but needs an `SmsGateway`, which is not integrated. Startup fails loudly rather than pretending to send.
- **RBAC:** permission strings per role (`app/core/rbac.py`), always combined with a scope check in the service (own profile, own facility). An endpoint × role matrix test is the contract.
- **Facility accounts:** only by an admin-issued, single-use, 72-hour invite. Only the token's hash is stored. The demo "delivery" returns the link once, labelled, instead of emailing it.
- **Persistence:** services depend on the `UnitOfWork` protocol. `SqlUnitOfWork` (PostgreSQL) is the real implementation. `MemoryUnitOfWork` mirrors its observable behaviour (including unique constraints) so the API suite runs without a database. Integration tests run the SQL implementation against real Postgres, and `alembic check` guards model/migration drift.
- **Audit:** `audit.audit_logs` is append-only, enforced by a trigger. It never stores passwords, tokens, codes or health data. Hash chaining arrives in Phase 8.

## Consequences

- Two repository implementations to keep in sync. This is mitigated by running the same API flows against both (unit suite + integration suite).
- Blood group is self-declared until a blood bank confirms it (Phase 2).
