"""Typed application settings, loaded from environment variables only.

All variables use the ``VEYRA_`` prefix. Startup refuses unsafe combinations,
e.g. demo verification or placeholder secrets in production.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

Environment = Literal["dev", "test", "demo", "production"]
VerificationProviderName = Literal["demo_last4", "sms"]

PRODUCT_NAME = "VEYRA"
PRODUCT_TAGLINE = "Intelligent Blood Network"

_PLACEHOLDER_SECRET_MARKERS = ("change-me", "not-a-real-secret")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="VEYRA_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    env: Environment = "dev"
    app_version: str = "0.0.0-phase0"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    api_prefix: str = "/api/v1"

    secret_key: SecretStr = SecretStr("change-me-dev-only-not-a-real-secret-000000")

    database_url: str = "postgresql+asyncpg://veyra:veyra@localhost:55432/veyra"
    redis_url: str = "redis://localhost:56379/0"
    cors_allowed_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])

    # Implemented in Phase 1. Declared now so the production guard exists from day one.
    verification_provider: VerificationProviderName = "demo_last4"

    @property
    def is_production(self) -> bool:
        return self.env == "production"

    @property
    def demo_mode(self) -> bool:
        """True whenever simulated/demo components may be active."""
        return not self.is_production

    @property
    def docs_enabled(self) -> bool:
        return not self.is_production

    @model_validator(mode="after")
    def _guard_production(self) -> Settings:
        if not self.is_production:
            return self
        secret = self.secret_key.get_secret_value()
        if len(secret) < 32 or any(m in secret for m in _PLACEHOLDER_SECRET_MARKERS):
            raise ValueError("VEYRA_SECRET_KEY must be a real secret (>= 32 chars) in production")
        if self.verification_provider == "demo_last4":
            raise ValueError(
                "Demo verification (last 4 digits of mobile) is not allowed in production. "
                "Configure a real OTP provider."
            )
        if any("*" in o for o in self.cors_allowed_origins):
            raise ValueError("Wildcard CORS origins are not allowed in production")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
