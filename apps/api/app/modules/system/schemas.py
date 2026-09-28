from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from app.core.config import Environment
from app.core.readiness import CheckStatus


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"


class ReadinessResponse(BaseModel):
    status: Literal["ready", "degraded"]
    checks: dict[str, CheckStatus]


class DemoDisclosure(BaseModel):
    component: str
    label: str = Field(description="Short UI label, e.g. 'Simulated'")
    detail: str


class MetaResponse(BaseModel):
    name: str = Field(examples=["VEYRA"])
    tagline: str = Field(examples=["Intelligent Blood Network"])
    version: str
    environment: Environment
    api_version: Literal["v1"] = "v1"
    demo_mode: bool = Field(description="True when simulated/demo components may be active")
    phase: str = Field(description="Current build phase of the prototype")
    disclosures: list[DemoDisclosure] = Field(
        default_factory=list,
        description="Active simulated/demo components. The UI must display these.",
    )
