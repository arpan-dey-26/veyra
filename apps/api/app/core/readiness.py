"""Readiness checks. Each dependency registers a named async check.

Checks are injectable (stored on ``app.state``), so tests can swap them without
real infrastructure. Error details are logged, never returned to clients.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Literal

logger = logging.getLogger("veyra.readiness")

Check = Callable[[], Awaitable[None]]
CheckStatus = Literal["ok", "unavailable"]


async def run_checks(checks: dict[str, Check], timeout_s: float = 2.0) -> dict[str, CheckStatus]:
    async def _one(name: str, check: Check) -> tuple[str, CheckStatus]:
        try:
            await asyncio.wait_for(check(), timeout=timeout_s)
            return name, "ok"
        except Exception as exc:  # any failure means "not ready"
            logger.warning("readiness_check_failed", extra={"extra_fields": {"check": name}})
            logger.debug("readiness_check_error", exc_info=exc)
            return name, "unavailable"

    results = await asyncio.gather(*(_one(n, c) for n, c in checks.items()))
    return dict(results)
