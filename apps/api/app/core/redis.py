"""Lazy Redis client (pub/sub for SSE, rate limits, ARQ jobs in later phases)."""

from __future__ import annotations

from redis.asyncio import Redis


def create_redis(url: str) -> Redis:
    # from_url does not connect until the first command.
    return Redis.from_url(url, socket_connect_timeout=2, socket_timeout=2)


async def ping(client: Redis) -> None:
    await client.ping()
