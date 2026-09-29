"""Server-Sent Events: live network events for the caller's facility.

Events come from the transactional outbox, so a client that reconnects with
``Last-Event-ID`` replays everything it missed (at-least-once; de-duplicate by ``event_id``).
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.responses import StreamingResponse

from app.core.rbac import AuthContext, Permission, Role
from app.modules.identity.deps import require
from app.modules.outbox.service import BrokerMessage, EventBroker, to_message
from app.persistence.deps import PersistenceUnavailableError
from app.persistence.sql import UowFactory

router = APIRouter(tags=["events"])

HEARTBEAT_SECONDS = 15.0
REPLAY_LIMIT = 500  # events visible to the caller, per replay
REPLAY_SCAN_LIMIT = 5000  # outbox rows examined per replay (bounded work)
# `after=0` asks for "everything": that is the recent history window, not the whole table,
# which grows without bound in a long-lived database.
REPLAY_WINDOW = 2000


def format_sse(message: BrokerMessage) -> str:
    data = json.dumps(message.data, separators=(",", ":"), default=str)
    return f"id: {message.cursor}\nevent: {message.topic}\ndata: {data}\n\n"


def visible_to(ctx: AuthContext, message: BrokerMessage) -> bool:
    if ctx.role is Role.ADMIN:
        return True
    return ctx.facility_id is not None and str(ctx.facility_id) in message.audience


def get_broker(request: Request) -> EventBroker:
    broker: EventBroker | None = getattr(request.app.state, "broker", None)
    if broker is None:
        broker = EventBroker()
        request.app.state.broker = broker
    return broker


async def _replay(factory: UowFactory, ctx: AuthContext, after: int) -> list[BrokerMessage]:
    """Events after ``after`` that the caller may see (oldest first).

    Filtering happens before the limit, so other facilities' events never crowd out the
    caller's own. ``after=0`` starts at the retention window (the last REPLAY_WINDOW rows).
    """
    out: list[BrokerMessage] = []
    async with factory() as uow:
        cursor = after
        if after == 0:
            cursor = max(0, await uow.outbox.last_id() - REPLAY_WINDOW)
        scanned = 0
        while len(out) < REPLAY_LIMIT and scanned < REPLAY_SCAN_LIMIT:
            rows = await uow.outbox.list_after(cursor, limit=REPLAY_LIMIT)
            if not rows:
                break
            scanned += len(rows)
            cursor = rows[-1].id
            out.extend(m for m in map(to_message, rows) if visible_to(ctx, m))
    return out[:REPLAY_LIMIT]


@router.get(
    "/stream",
    summary="Live events (Server-Sent Events)",
    response_class=StreamingResponse,
    responses={200: {"content": {"text/event-stream": {}}}},
)
async def stream(
    request: Request,
    after: int | None = Query(default=None, ge=0, description="Replay events after this id"),
    once: bool = Query(default=False, description="Replay then close (smoke tests, polling)"),
    last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
    ctx: AuthContext = Depends(require(Permission.EVENTS_SUBSCRIBE)),
    broker: EventBroker = Depends(get_broker),
) -> StreamingResponse:
    factory: UowFactory | None = getattr(request.app.state, "uow_factory", None)
    if factory is None:
        raise PersistenceUnavailableError()
    cursor = after
    if last_event_id and last_event_id.isdigit():
        cursor = int(last_event_id)
    if once and cursor is None:
        cursor = 0

    async def events() -> AsyncIterator[str]:
        queue = None if once else broker.subscribe()  # subscribe first: no gap
        try:
            last = cursor or 0
            yield "retry: 3000\n: connected\n\n"
            if cursor is not None:
                for message in await _replay(factory, ctx, cursor):
                    last = max(last, message.cursor)
                    yield format_sse(message)
            if queue is None:
                return
            while True:
                try:
                    message = await asyncio.wait_for(queue.get(), timeout=HEARTBEAT_SECONDS)
                except TimeoutError:
                    if await request.is_disconnected():
                        return
                    yield ": heartbeat\n\n"
                    continue
                if message.cursor <= last or not visible_to(ctx, message):
                    continue
                last = message.cursor
                yield format_sse(message)
        finally:
            if queue is not None:
                broker.unsubscribe(queue)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        # no-transform: proxies (incl. the Next.js server) must not gzip-buffer the stream.
        headers={"Cache-Control": "no-store, no-transform", "X-Accel-Buffering": "no"},
    )
