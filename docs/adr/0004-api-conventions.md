# ADR-0004: API conventions

- Status: Accepted (2026-09-28)

## Decision
- Prefix is `/api/v1`. Breaking changes go to `/api/v2`.
- Every error is RFC 9457 `application/problem+json` with `code` and `request_id`. Input values are never echoed back, and stack traces are never returned.
- Every response carries an `X-Request-ID` header.
- `Idempotency-Key` is required on emergency, request and dispatch POSTs (from Phase 2).
- Lists return `{data, meta}`.
- The browser reaches the API only through the Next.js same-origin proxy.
