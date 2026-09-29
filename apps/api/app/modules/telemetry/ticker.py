"""Background simulator: one reading per running device every ``interval`` seconds."""

from __future__ import annotations

import asyncio
import logging

from app.core.clock import Clock
from app.modules.telemetry.service import take_reading
from app.persistence.sql import UowFactory

logger = logging.getLogger("veyra.telemetry")


async def tick_running_devices(uow_factory: UowFactory, clock: Clock, *, limit: int = 100) -> int:
    async with uow_factory() as uow:
        devices = await uow.telemetry.running_devices(limit=limit)
        done = 0
        for device in devices:
            bag = await uow.bags.get(device.bag_id)
            if bag is None or bag.status == "discarded":
                continue
            await take_reading(uow, clock, device, bag, at=clock.now())
            done += 1
        if done:
            await uow.commit()
        return done


async def run_ticker(uow_factory: UowFactory, clock: Clock, *, interval: float) -> None:
    while True:
        try:
            await tick_running_devices(uow_factory, clock)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("telemetry_tick_failed")
        await asyncio.sleep(interval)
