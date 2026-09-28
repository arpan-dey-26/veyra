# ADR-0008: Realtime and background jobs

- Status: Accepted (2026-09-28). Implementation starts in Phase 2.

## Decision
- Server → client streaming uses Server-Sent Events, fanned out through Redis pub/sub.
- Background work (agent steps, anchoring, retraining, reports) runs on ARQ workers.
- Side effects are published through a transactional outbox after commit.

## Why
SSE is simpler than WebSockets for one-way dashboards. The outbox prevents events being emitted for rolled-back transactions.
