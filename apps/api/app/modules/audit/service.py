from __future__ import annotations

from typing import Any
from uuid import UUID

from app.core.clock import Clock
from app.core.ids import uuid7
from app.modules.audit.models import AuditLog
from app.persistence.repositories import UnitOfWork


async def record(
    uow: UnitOfWork,
    clock: Clock,
    *,
    action: str,
    resource: str,
    resource_id: UUID | str | None = None,
    actor_id: UUID | None = None,
    actor_type: str = "user",
    ip: str | None = None,
    meta: dict[str, Any] | None = None,
) -> None:
    """Append an audit entry. Never put passwords, tokens, codes or health data in ``meta``."""
    await uow.audit.add(
        AuditLog(
            id=uuid7(),
            actor_id=actor_id,
            actor_type=actor_type,
            action=action,
            resource=resource,
            resource_id=str(resource_id) if resource_id is not None else None,
            ip=ip,
            meta=meta or {},
            created_at=clock.now(),
        )
    )
