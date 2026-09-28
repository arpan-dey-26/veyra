"""Transactional outbox: write, relay, broadcast.

- ``emit`` adds an event to the CURRENT unit of work; it commits (or rolls back) together
  with the blood-network change it describes.
- ``relay_once`` claims unpublished rows (``FOR UPDATE SKIP LOCKED`` on PostgreSQL), hands them
  to the in-process ``EventBroker`` and marks them published. Delivery is at-least-once:
  consumers de-duplicate by ``event_id``.
- ``EventBroker`` fans events out to live SSE subscribers of this API process.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from app.core.clock import Clock
from app.core.ids import uuid7
from app.modules.outbox.models import OutboxEvent
from app.persistence.repositories import UnitOfWork
from app.persistence.sql import UowFactory

logger = logging.getLogger("veyra.outbox")


async def emit(
    uow: UnitOfWork,
    clock: Clock,
    *,
    topic: str,
    aggregate_type: str,
    aggregate_id: str,
    audience: Iterable[UUID | None],
    payload: dict[str, Any],
) -> None:
    """Never put donor identity or health data in ``payload``: it is broadcast to facilities."""
    await uow.outbox.add(
        OutboxEvent(
            event_id=uuid7(),
            topic=topic,
            aggregate_type=aggregate_type,
            aggregate_id=aggregate_id,
            audience=sorted({str(a) for a in audience if a is not None}),
            payload=payload,
            created_at=clock.now(),
            published_at=None,
            attempts=0,
            last_error=None,
        )
    )


@dataclass(frozen=True)
class BrokerMessage:
    cursor: int
    event_id: str
    topic: str
    audience: tuple[str, ...]
    data: dict[str, Any]


def to_message(row: OutboxEvent) -> BrokerMessage:
    return BrokerMessage(
        cursor=row.id,
        event_id=str(row.event_id),
        topic=row.topic,
        audience=tuple(row.audience),
        data={
            "event_id": str(row.event_id),
            "topic": row.topic,
            "aggregate_type": row.aggregate_type,
            "aggregate_id": row.aggregate_id,
            "created_at": row.created_at.isoformat(),
            **row.payload,
        },
    )


class EventBroker:
    """In-process pub/sub. Slow subscribers drop their oldest message instead of blocking."""

    def __init__(self, queue_size: int = 256) -> None:
        self._subscribers: set[asyncio.Queue[BrokerMessage]] = set()
        self._size = queue_size

    def subscribe(self) -> asyncio.Queue[BrokerMessage]:
        queue: asyncio.Queue[BrokerMessage] = asyncio.Queue(self._size)
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[BrokerMessage]) -> None:
        self._subscribers.discard(queue)

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)

    def publish(self, message: BrokerMessage) -> None:
        for queue in list(self._subscribers):
            if queue.full():
                with contextlib.suppress(asyncio.QueueEmpty):
                    queue.get_nowait()
            queue.put_nowait(message)


async def relay_once(
    uow_factory: UowFactory, broker: EventBroker, clock: Clock, *, batch: int = 100
) -> int:
    """Publish one batch. Returns how many rows were marked published."""
    async with uow_factory() as uow:
        rows = await uow.outbox.claim_unpublished(limit=batch)
        published = 0
        for row in rows:
            try:
                broker.publish(to_message(row))
            except Exception as exc:  # keep the row for the next attempt
                row.attempts += 1
                row.last_error = f"{type(exc).__name__}: {exc}"[:255]
                continue
            row.published_at = clock.now()
            published += 1
        if rows:
            await uow.commit()
        return published


async def run_relay(
    uow_factory: UowFactory, broker: EventBroker, clock: Clock, *, interval: float
) -> None:
    """Background loop started by the API lifespan. Errors never kill the loop."""
    while True:
        try:
            await relay_once(uow_factory, broker, clock)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("outbox_relay_failed")
        await asyncio.sleep(interval)
