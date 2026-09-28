from __future__ import annotations

from collections.abc import AsyncIterator

from fastapi import Request

from app.core.errors import AppError
from app.persistence.repositories import UnitOfWork


class PersistenceUnavailableError(AppError):
    status, code, title = 503, "persistence_unavailable", "Service temporarily unavailable"


async def get_uow(request: Request) -> AsyncIterator[UnitOfWork]:
    """One unit of work (DB transaction) per request."""
    factory = getattr(request.app.state, "uow_factory", None)
    if factory is None:
        raise PersistenceUnavailableError()
    async with factory() as uow:
        yield uow
