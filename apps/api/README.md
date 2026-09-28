# veyra-api

FastAPI modular monolith for VEYRA.

## Layering (enforced by review + tests)

```
app/core/        config, logging, errors (RFC 9457), middleware, ids (UUIDv7), clock, db, redis, provenance
app/modules/<m>/ router.py → service.py → repository.py   (+ models.py, schemas.py, policies.py)
app/providers/   ports (Protocols) + demo/real implementations   (from Phase 1/2)
```

- Routers never import repositories.
- AI tools and agents (later phases) call **services**, never repositories.
- Every simulated data source returns `SourceMeta(simulated=True)`.

## Run

```bash
uv sync
uv run uvicorn app.main:app --reload
uv run pytest
uv run alembic upgrade head          # needs Postgres
```
