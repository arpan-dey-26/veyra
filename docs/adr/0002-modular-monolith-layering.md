# ADR-0002: Modular monolith, router → service → repository

- Status: Accepted (2026-09-28)

## Decision
Each domain module under `apps/api/app/modules/<name>/` owns `router.py`, `service.py`, `repository.py`, `models.py`, `schemas.py` and `policies.py`.

Rules:
- Routers never import repositories.
- Modules call each other only through services.
- AI tools and agents call services, never repositories.

## Why
This gives microservice-style boundaries without network cost. It also means one authorization path for humans, the AI and agents.

## Consequences
Rule violations are caught in code review, and from Phase 1 by an import-lint test.
