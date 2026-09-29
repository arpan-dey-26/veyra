# Deployment (public demo on Vercel)

VEYRA runs publicly as a **labelled prototype demo**. Everything simulated keeps its disclosure: mock partner banks, IoT telemetry, logistics couriers/ETAs, demo phone verification and synthetic forecasts. The deployment uses real authentication, RBAC, CSRF, database persistence and hash-chained traces.

| Piece | Where | Notes |
|---|---|---|
| Website (Next.js 16) | Vercel project `veyra-web` → **https://veyra-web-sigma.vercel.app** | Root directory `apps/web`, framework Next.js, pnpm workspace install. |
| API (FastAPI) | Vercel project `veyra-api` → https://veyra-api-five.vercel.app | Python 3.12 function (`apps/api/index.py` exports `app`), lifespan supported. |
| PostgreSQL | Neon (Vercel Marketplace, free plan, iad1) | Injected as `DATABASE_URL[_UNPOOLED]`. `Settings` adopts the unpooled URL (asyncpg + `ssl=require`). |
| Redis | Redis Cloud (Vercel Marketplace, free 30 MB, iad1) | Injected as `REDIS_URL`; used by the readiness probe. |

The browser only talks to the website origin. Next.js proxies `/api/*` to `VEYRA_API_INTERNAL_URL` (a server-side variable, never shipped to the browser), so auth cookies are first-party, `Secure`, `HttpOnly` and `SameSite`. The build fails on Vercel if that variable is missing, so it can never fall back to localhost.

## Environment (set in Vercel, never in Git)

- **`veyra-api`:**
  - `VEYRA_ENV=demo` (a labelled public demo, not `production`, because demo verification and simulators are intentionally on)
  - `VEYRA_SECRET_KEY` and `VEYRA_PASSWORD_PEPPER`: random, *sensitive*
  - `VEYRA_COOKIE_SECURE=true`
  - `VEYRA_CORS_ALLOWED_ORIGINS=["https://veyra-web-sigma.vercel.app"]`
  - `VEYRA_VERIFICATION_PROVIDER=demo_last4`
  - `VEYRA_TELEMETRY_TICK_SECONDS=0`: there is no background ticker on serverless; readings come from the labelled simulator controls
  - `VEYRA_DEMO_ADMIN_PASSWORD`: *sensitive*, production only; seeds the demo accounts and is never printed
  - Marketplace-injected `DATABASE_URL*`, `POSTGRES_*`, `PG*`, `REDIS_URL`
- **`veyra-web`:** `VEYRA_API_INTERNAL_URL=https://veyra-api-five.vercel.app`, `NEXT_PUBLIC_VEYRA_ENV=demo`

When `VERCEL` is set, the API refuses to start with the placeholder secret, insecure cookies or wildcard CORS. It also hides `/docs` and `/openapi.json` and sends HSTS. `VEYRA_ENV=production` keeps its stricter guards: no demo verification and no simulators.

## Build and release

- **API build step:** `[tool.vercel.scripts] build = "python vercel_build.py"`. On production builds it runs `alembic upgrade head` and then the idempotent demo seed. Preview builds never touch the shared database.
- **One-time setup:** `scripts\vercel\login.cmd` links the Vercel CLI via the OAuth device flow; no token is stored in the repo.
- **Deploy:** `scripts\vercel\deploy.cmd` deploys the API first (from `apps/api`), then the web (from the repo root, which honours `.vercelignore`).
- **Smoke test:** `scripts\vercel\smoke.cmd` asks for the demo staff password and walks the full journey on the live site. It writes a log to `.deploy-logs\`.

## Known limitations of the serverless demo

- **Live updates:** the in-process outbox relay runs only while a function instance is alive. Clients reconnect and replay missed events from the outbox (`Last-Event-ID`), so they arrive late rather than being lost.
- **Background simulation:** the "running" background telemetry simulator is off (tick = 0). Use the simulator controls instead.
- **Free-tier limits:** Neon (0.5 GB, scale-to-zero cold starts of about a second) and Redis Cloud free (30 MB, 30 connections).
- **Demo verification:** the last four digits of the mobile number verify a donor. This is labelled everywhere; production would need a real OTP provider (`VEYRA_ENV=production` refuses to start without one).
- **Custom domain:** none; the site uses the Vercel-assigned `*.vercel.app` domain.
