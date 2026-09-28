from __future__ import annotations

from app.core.config import PRODUCT_NAME, PRODUCT_TAGLINE, Settings
from app.core.readiness import Check, run_checks
from app.modules.system.schemas import DemoDisclosure, MetaResponse, ReadinessResponse

CURRENT_PHASE = "0 — Architecture & Foundation"


class SystemService:
    def __init__(self, settings: Settings, checks: dict[str, Check]) -> None:
        self._settings = settings
        self._checks = checks

    async def readiness(self) -> ReadinessResponse:
        results = await run_checks(self._checks)
        ok = all(v == "ok" for v in results.values())
        return ReadinessResponse(status="ready" if ok else "degraded", checks=results)

    def meta(self) -> MetaResponse:
        disclosures: list[DemoDisclosure] = []
        if self._settings.demo_mode:
            disclosures.append(
                DemoDisclosure(
                    component="environment",
                    label="Demo environment",
                    detail="This is a prototype. Simulated and demo components are labelled "
                    "wherever they appear.",
                )
            )
        return MetaResponse(
            name=PRODUCT_NAME,
            tagline=PRODUCT_TAGLINE,
            version=self._settings.app_version,
            environment=self._settings.env,
            demo_mode=self._settings.demo_mode,
            phase=CURRENT_PHASE,
            disclosures=disclosures,
        )
