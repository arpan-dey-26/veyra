# ADR-0007: Configuration and secrets

- Status: Accepted (2026-09-28)

## Decision
All configuration comes from `VEYRA_*` environment variables through pydantic-settings, with the environment set by `VEYRA_ENV ∈ {dev,test,demo,production}`. `.env` is git-ignored and `.env.example` is committed. Production startup fails on a placeholder secret, on demo verification, or on wildcard CORS. API docs are disabled in production.
