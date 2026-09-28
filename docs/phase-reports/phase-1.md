# PHASE STATUS — Phase 1: Authentication & RBAC

Date: 2026-09-28 · Product: **VEYRA — Intelligent Blood Network**

## Implemented (complete API → DB → UI flows)

| Feature | API | Persistence | UI |
|---|---|---|---|
| Donor registration (all 9 fields, server + client validation) | `POST /auth/register` | `identity.users`, `network.donors` | `/register` |
| **Demo** phone verification (last 4 digits of mobile, labelled everywhere, refused in production) | `POST /auth/verify`, `POST /auth/verify/start` | `identity.verification_challenges` (attempt-limited, 15 min TTL) | `/verify` (exact disclaimer) |
| Sign in / out, sessions | `POST /auth/login`, `/auth/refresh`, `/auth/logout`, `GET /auth/me` | `identity.sessions` (rotating refresh, family revocation) | `/sign-in`, app shell |
| RBAC (permission + scope) | `require(Permission)` on every protected route | — | role-gated dashboards |
| Donor profile (view / edit allowed fields) | `GET/PATCH /donors/me` | `network.donors` | `/donor` |
| Facility onboarding (admin) | `GET/POST /admin/facilities` | `network.facilities` | `/admin` |
| Staff invitations (single-use, 72h, demo link delivery) | `POST/GET /admin/facilities/{id}/invites`, `GET /auth/invites/{token}`, `POST /auth/invites/accept` | `identity.facility_invites`, `network.facility_memberships` | `/admin` → `/invite/[token]` |
| Facility home (own facility only) | `GET /facilities/me` | — | `/hospital`, `/blood-bank` |
| Account list (admin, no secrets) | `GET /admin/users` | — | `/admin` |
| Audit trail (append-only, DB trigger) | internal | `audit.audit_logs` | — |
| Registration reference data | `GET /reference/registration` | — | forms |
| Demo admin seed | `python -m app.scripts.seed_demo` (DEMO ONLY: `admin@veyra.demo` / `veyra-demo-console-2026`) | — | — |

Security properties:
- Argon2id passwords with a pepper, and equal work for unknown accounts.
- Lockout after 5 failures (15 min).
- 15-minute access JWT tied to a server session, so logout is immediate.
- Refresh token rotation with reuse detection.
- httpOnly cookies + double-submit CSRF.
- Role read from the DB.
- No input echo in 422s.
- Request id on every error, including 500s.

Honest labelling: `verification.mode="demo"` plus the disclaimer comes from the API. The UI shows the exact sentence. `/api/v1/meta` discloses it. Invite delivery and the demo admin are labelled. Blood group is shown as *self-declared*.

## Defects found and fixed during Phase 1

1. **Phase 0 regression:** `router.py` referenced `get_settings` without importing it (NameError). This broke ruff, mypy, pytest, OpenAPI export and the API container. Fixed by importing it and binding the existing `get_settings` dependency to each app instance via `dependency_overrides`.
2. Alembic re-applied the naming convention to CHECK constraint names (`ck_users_ck_users_role_valid`). Found by diffing a real Postgres built from the migration against one built from the models. Fixed with `op.f()`.
3. Invite acceptance turned a password-policy failure into a **500**. It is now a 422 with a field error (regression test added).
4. Unhandled 500s returned `request_id: null`: Starlette renders them outside the request-id middleware. Fixed via the scope; regression test added.
5. `clean_text` dropped tabs instead of turning them into spaces. Fixed.

## Tests

- **API, run in the cloud sandbox:**
  - 122 passed (29 Phase 0 + 93 Phase 1).
  - The RBAC matrix is 7 endpoints × 5 roles.
  - Mutation-checked: disabling family revocation, or granting admins donor access, makes the suite fail.
- **API integration** (real Postgres; Windows bootstrap, strict): full donor lifecycle, admin → facility → invite → accept, append-only audit.
- **Migration:** applied to real PostgreSQL 16; schema identical to the models apart from the intentional append-only trigger; downgrade verified.
- **Static checks** (cloud): ruff clean, **mypy --strict** clean (57 files), TypeScript type-check of web + api-client clean against the real installed `next`/`react`/`openapi-fetch` types.
- **Web unit tests** (vitest, run by the bootstrap):
  - api-client session middleware (CSRF, single-flight refresh, retry)
  - validation/roles/problem helpers
  - register, verify and sign-in forms (including the exact disclaimer)
- **E2E** (bootstrap, through the Next.js proxy on Docker):
  - register → demo verify → me → CSRF-protected update → logout → session revoked
  - demo admin sign-in

## Verification status on Windows

See `phase-0-verification.log` after running `scripts\bootstrap.cmd`. Phase 1 is only complete when that log ends with `OVERALL: PASS`.

## Known limitations / technical debt

- No real SMS/OTP or email provider (by design, labelled). `VEYRA_VERIFICATION_PROVIDER=sms` fails fast until a gateway is integrated.
- Rate limiting is per account/challenge only (no IP-level Redis limiter yet), planned with Phase 2 infra.
- Admin cannot yet disable users or revoke invites from the UI (the API models support revocation).
- Audit log is not yet hash-chained (Phase 8).
- CSP still allows inline scripts (Phase 11).

## Recommended next phase

**Phase 2 — Core Blood Network:**
- inventory, donations and blood bags with append-only trace events
- blood requests
- blood-bank provider ports (Mock + Internal)
- outbox + SSE
