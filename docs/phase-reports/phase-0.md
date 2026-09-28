# PHASE STATUS — Phase 0: Architecture & Foundation

Date: 2026-09-28 · Product: **VEYRA — Intelligent Blood Network**

**Status: scaffold complete, on-machine verification PENDING.**
Both of Claude's sandboxes (the cloud workspace and the Linux sandbox on your PC) are blocked from npm/PyPI by the org's egress policy, and neither has a Docker daemon. So dependencies could not be installed and the real test suites have **not been run yet**. Run `scripts\bootstrap.cmd` on Windows (see "How to verify"). It fills in the missing results in `docs/phase-reports/phase-0-verification.log`.

## Implemented (foundation only, no product features)

- **Monorepo:** pnpm workspaces (`apps/web`, `packages/*`) + uv-managed Python API. Root `Makefile` (WSL/Linux) and `scripts/bootstrap.cmd`/`.ps1` (Windows).
- **API foundation (FastAPI):**
  - App factory, typed `VEYRA_*` settings with production guards (they refuse demo verification, placeholder secrets and wildcard CORS)
  - RFC 9457 problem+json errors (no stack traces, input values not echoed back)
  - Request-ID + security-header ASGI middleware, CORS allow-list, structured JSON logging with redaction
  - UUIDv7 IDs, injectable Clock, `SourceMeta` provenance contract (`simulated` flag)
  - Lazy async SQLAlchemy engine + Redis client, `/healthz`, `/readyz` (per-dependency, no error leakage), `/api/v1/meta`
  - Alembic (async) with a baseline migration that creates the domain schemas
  - OpenAPI export script
- **Design system foundations:**
  - `@veyra/design-tokens`: colour roles (light/dark), type scale, space, radius, elevation and motion tokens, with reduced-motion collapse
  - Tailwind v4 mapping; UI primitives: Button, Badge, SimulatedBadge, Card, Skeleton, EmptyState, ErrorState, StatusBeacon
  - VEYRA wordmark, the signature `FlowLines` network motif (pure SVG/CSS, reduced-motion safe)
  - `useReducedMotion` hook
- **Web (Next.js App Router):**
  - Root layout with fonts and metadata, a global `DemoRibbon` in every non-production env
  - Phase 0 landing page, `/disclosures` page, `/system` living design-system reference (hidden in production), 404 page
  - Same-origin `/api/*` proxy, security headers + CSP
  - Live API status using the generated client (loading/ok/error states)
- **API client:** `@veyra/api-client` (openapi-fetch + generated types, RFC 9457 helper).
- **Infra:** docker-compose (postgres 16, redis 7, api, web) with healthchecks; non-root API and web Dockerfiles; `.dockerignore`.
- **CI:** GitHub Actions. The api job runs ruff, format, mypy, migrations, pytest and an OpenAPI drift check. The web job runs the client drift check, lint, typecheck, tests and build.
- **Docs:**
  - Architecture (renamed to VEYRA), ADR-0001…0008, `demo-disclosures.md`
  - README
  - `.env.example`; `.env` is git-ignored

## Files created (104)

Root: `README.md`, `package.json`, `pnpm-workspace.yaml`, `Makefile`, `.env.example`, `.gitignore`, `.gitattributes`, `.editorconfig`, `.dockerignore`, `.nvmrc`, `.github/workflows/ci.yml`, `scripts/{bootstrap.cmd,bootstrap.ps1,pin-versions.mjs}`

`apps/api/`:
- `pyproject.toml`, `README.md`, `alembic.ini`
- `app/main.py`
- `app/core/{config,logging,errors,middleware,request_context,ids,clock,provenance,db,redis,readiness}.py`
- `app/modules/system/{router,service,schemas}.py`
- `app/scripts/export_openapi.py`
- `migrations/{env.py,script.py.mako,versions/0001_baseline_schemas.py}`
- `tests/{conftest,test_system,test_errors_and_middleware,test_config,test_core_primitives,test_integration_infra}.py`

`apps/web/`:
- Config: `package.json`, `tsconfig.json`, `next.config.ts`, `postcss.config.mjs`, `eslint.config.mjs`, `vitest.config.ts`, `vitest.setup.ts`
- App: `app/{layout.tsx,globals.css,not-found.tsx,(marketing)/{layout,page,disclosures/page}.tsx,system/{page,motion-specimen}.tsx}`
- Components: `components/{ui/{button,badge,simulated-badge,card,states}.tsx,brand/{wordmark,flow-lines}.tsx,shell/{demo-ribbon,site-header,site-footer}.tsx,system/api-status.tsx}`
- Lib: `lib/{api,cn,env,use-reduced-motion}.ts`
- Tests: `ui.test.tsx`, `shell.test.tsx`, `api-status.test.tsx`

`packages/design-tokens/`: `package.json`, `tsconfig.json`, `src/{tokens.css,index.ts,tokens.test.ts}`

`packages/api-client/`: `package.json`, `tsconfig.json`, `src/{index.ts,index.test.ts}`

`infra/`: `docker-compose.yml`, `docker/{api,web}.Dockerfile`

`docs/`: `architecture/phase0-architecture.md`, `adr/0001…0008`, `demo-disclosures.md`, `phase-reports/phase-0.md`

## Files modified

None. This is a greenfield repo with no pre-existing code. (The architecture doc was updated to the VEYRA name.)

## Tests executed

| Check | Where | Result |
|---|---|---|
| Python syntax compile (all API + tests) | cloud | ✅ pass |
| UUIDv7 version/timestamp smoke | cloud | ✅ pass |
| Production guard rejects placeholder secret | cloud | ✅ pass |
| `SourceMeta.simulated` serialises | cloud | ✅ pass |
| Token colour contrast (WCAG AA, all text roles, light + dark) | cloud | ✅ pass (after fixing `ink-subtle`: 4.49 → 4.98) |
| pytest (26 test functions, 30 cases incl. parametrised) | Windows | ⏳ not run |
| vitest: tokens (5), api-client (2), web (15 tests, 17 cases) | Windows | ⏳ not run |
| ruff / mypy / eslint / tsc | Windows | ⏳ not run |
| `next build` | Windows | ⏳ not run |
| Alembic migration on real Postgres | Docker | ⏳ not run |

**Tests passed:** 5 offline checks. The real suites are pending.

## Docker / services status

Not started. There's no Docker daemon in either sandbox. Docker Desktop is installed on your PC (shortcut found), so `docker compose -f infra/docker-compose.yml up --build` is the next check once the bootstrap passes.

## Existing functionality verified

N/A. There was no prior functionality.

## Known issues

1. **Verification pending** (see above). This is the main open item.
2. `packages/api-client/openapi.json` and `src/schema.d.ts` are **generated** by the bootstrap. Until then, web and client typecheck will fail.
3. Dependencies use `"latest"` until the first install. `scripts/pin-versions.mjs` then pins them to exact `^x.y.z`, and the lockfiles (`pnpm-lock.yaml`, `uv.lock`) are created. Commit both.
4. `eslint.config.mjs` assumes the flat config exported by `eslint-config-next` ≥ 16. If an older version resolves, it needs a one-line change.
5. `next/font/google` downloads fonts at build time, so it needs internet on the build machine.
6. `Desktop\veyra-phase0.tar.gz` (transfer archive) is left on your Desktop. Deleting files needs your permission; you can delete it yourself.

## Technical debt introduced

- CSP uses `'unsafe-inline'` for scripts (a Next.js requirement without nonces). Move to a nonce-based CSP in Phase 11.
- The API container runs `alembic upgrade head` on start. Move it to a one-off migration job before hosted deploys (Phase 11).
- `SecurityHeadersMiddleware` exempts `/docs` from the strict CSP. Docs are disabled in production anyway.
- There's no import-lint test yet for "routers must not import repositories" (planned for Phase 1).

## How to verify (Windows)

```
Double-click  Desktop\veyra\scripts\bootstrap.cmd
```

Or, in PowerShell:

```
cd $HOME\Desktop\veyra
powershell -ExecutionPolicy Bypass -File scripts\bootstrap.ps1
```

Results go to `docs\phase-reports\phase-0-verification.log` and `bootstrap-started.txt`. Then:

```
docker compose -f infra/docker-compose.yml up --build
```

Open http://localhost:3000 and http://localhost:8000/readyz.

## Recommended Phase 1: Authentication & RBAC

Gate before starting: the Phase 0 verification log is all PASS.

1. **Models and migration:**
   - `identity.users`, `sessions`, `verification_challenges`, `facility_invites`
   - `network.donors` (registration fields: full name, email, mobile E.164, blood group, address, city, state, 6-digit PIN code, password)
2. **Passwords:** Argon2id with a pepper, policy checks and lockout/backoff.
3. **`VerificationProvider` port:**
   - `DemoLast4VerificationProvider` (`is_demo=True`, attempt-limited, refused in production)
   - `SmsOtpVerificationProvider` interface stub
   - API responses carry `verification_mode: "demo"`
4. **Sessions:** JWT access token (15 min) + rotating opaque refresh token with reuse detection, both in httpOnly cookies. Double-submit CSRF.
5. **`AuthContext` + permission-string RBAC** with scope checks, and role-specific serializers.
6. **Admin-issued facility invites** for HOSPITAL / BLOOD_BANK.
7. **Tests:** a full RBAC matrix (endpoint × role × own/other), auth flow tests, an import-lint layering test.
8. **UI:**
   - Register / verify / sign-in screens on the design system
   - The mandatory disclaimer: *"Demo verification only. The last 4 digits of your mobile number are used for prototype verification instead of a real OTP."*


---

## Verification round 2 (2026-09-28)

### Results of run 1 (the user's run, log timestamp 09:31 IST)
- **API (really ran):** uv sync, OpenAPI export, ruff format, ruff check and mypy passed. pytest: **25 passed, 3 failed, 1 skipped**.
- **pnpm:** `corepack enable` failed with `EPERM ... C:\Program Files\nodejs\pnpm.CMD`, so pnpm install, client generation, typecheck, lint, vitest and build **never ran**.
- **Bootstrap bug:** it reported those steps as PASS. `$LASTEXITCODE` is not set when a command is not found, and `$?` came from `Tee-Object`, not from the command itself.

### Fixes
| Failure | Root cause | Fix |
|---|---|---|
| pnpm EPERM | corepack writes shims next to node.exe (Program Files needs admin) | `corepack enable pnpm --install-directory %LOCALAPPDATA%\veyra\bin`, added to PATH (process + user); npm `--prefix` fallback |
| False PASS | exit status came from Tee-Object, not the command; a missing command didn't set LASTEXITCODE | `Invoke-Native`: refuses a missing command, checks each command's own exit code and throws. A step is PASS only if every command exits 0. The script exits 1 on any failure. UTF-8 log (run 1's log was UTF-8/UTF-16 mixed) |
| `test_validation_error_does_not_echo_input` loc `["query","body"]` | the probe model was defined inside a function under `from __future__ import annotations`, so FastAPI couldn't resolve the string annotation and treated it as a query param | model moved to module level (`ProbeBody`) |
| `test_malformed_request_id_is_replaced` UnicodeEncodeError | the test sent non-ASCII, which httpx rejects before the request is sent | parametrised with 4 HTTP-valid ASCII malformed IDs (spaces/brackets, too short, too long, separators); asserts the server replaced each with a generated 32-hex ID |
| `test_meta_...` env `dev` ≠ `test` | **real bug:** `/meta` depended on the process-global `get_settings()`, so it ignored `create_app(settings)` | `app.state.settings` + `get_app_settings` dependency; fixture uses `_env_file=None`; new regression test (demo/test) |

### Other hardening found while fixing
- Next.js bakes `rewrites()` in at build time, so the web image now receives `VEYRA_API_INTERNAL_URL=http://api:8000` as a build arg. Without it, the container's proxy would have pointed at localhost.
- Docker host ports changed to 55432 (Postgres) and 56379 (Redis), so they don't clash with a local Postgres/Redis. Config defaults, `.env.example` and `.env` were updated to match.
- The integration test fails (instead of skipping) when `VEYRA_REQUIRE_INFRA=1`, which the bootstrap sets.
- pnpm 10 build-script allow-list (`onlyBuiltDependencies`); TypeScript pinned `~5.9.2` and ESLint `^9` for toolchain compatibility; web `typecheck` = `next typegen && tsc --noEmit`.
- ApiStatus effect no longer calls setState synchronously (react-hooks lint compliance); explicit `ReactNode` imports.

### New verification scope (scripts/bootstrap.ps1)
toolchain (node ≥ 22, pnpm, uv) → pnpm install → pin versions → uv sync → export OpenAPI → generate client → client `--check` → ruff format/check → mypy → pytest (unit) → `pnpm typecheck` → `pnpm lint` → `pnpm test` → `pnpm build` → docker engine → compose config → postgres+redis healthy → alembic upgrade head → pytest (integration, strict) → full stack build+up → e2e `/healthz`, `/readyz`, web home, web→API proxy `/api/v1/meta`.

### Status: NOT YET VERIFIED
As of 04:24 UTC, `phase-0-verification.log` still holds run 1 (09:31 IST). There is no `node_modules` and no `pnpm-lock.yaml`, so the fixed bootstrap has not been executed yet. Phase 0 stays open until that log shows `OVERALL: PASS`.
