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

    # Phone verification. demo_last4 is DEMO ONLY and refused in production.
    verification_provider: VerificationProviderName = "demo_last4"
    verification_ttl_seconds: int = Field(default=900, ge=60)
    verification_max_attempts: int = Field(default=5, ge=1, le=10)

    # Sessions (Phase 1): short-lived JWT access token + rotating opaque refresh token.
    access_token_ttl_seconds: int = Field(default=900, ge=60)
    refresh_token_ttl_seconds: int = Field(default=7 * 24 * 3600, ge=3600)
    # None = secure cookies exactly when running in production.
    cookie_secure: bool | None = None

    # Passwords: Argon2id with a server-side pepper (Argon2 "secret" input).
    # When unset, the pepper is derived from VEYRA_SECRET_KEY (HKDF, separate label).
    password_pepper: SecretStr | None = None
    password_hash_memory_kib: int = Field(default=65536, ge=1024)
    password_hash_iterations: int = Field(default=3, ge=1)
    login_max_failures: int = Field(default=5, ge=1)
    login_lockout_seconds: int = Field(default=900, ge=60)

    # Blood network (Phase 2). Prototype defaults; verify against current national guidelines.
    min_donation_interval_days: int = Field(default=90, ge=1)
    # Dashboards bucket "today" / per-day series in this fixed offset (India, UTC+05:30).
    # A fixed offset avoids a tz database dependency on Windows.
    report_utc_offset_minutes: int = Field(default=330, ge=-720, le=840)
    # Simulated partner blood banks (DEMO). None = enabled exactly when not in production.
    enable_mock_blood_banks: bool | None = None
    outbox_relay_interval_seconds: float = Field(default=0.5, gt=0)
    # Simulated IoT telemetry (Phase 5, DEMO). None = enabled exactly when not in production.
    enable_telemetry_simulator: bool | None = None
    # Background simulator cadence for devices set to "running" (0 disables the ticker).
    telemetry_tick_seconds: float = Field(default=15.0, ge=0)
    # Simulated logistics controls (Phase 7, DEMO). None = enabled exactly when not in production.
    enable_logistics_simulator: bool | None = None

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

    @property
    def mock_blood_banks_enabled(self) -> bool:
        if self.enable_mock_blood_banks is None:
            return self.demo_mode
        return self.enable_mock_blood_banks

    @property
    def telemetry_simulator_enabled(self) -> bool:
        if self.enable_telemetry_simulator is None:
            return self.demo_mode
        return self.enable_telemetry_simulator

    @property
    def logistics_simulator_enabled(self) -> bool:
        if self.enable_logistics_simulator is None:
            return self.demo_mode
        return self.enable_logistics_simulator

    @property
    def secure_cookies(self) -> bool:
        return self.is_production if self.cookie_secure is None else self.cookie_secure

    @model_validator(mode="after")
    def _guard_production(self) -> Settings:
        if not self.is_production:
            return self
        secret = self.secret_key.get_secret_value()
        if len(secret) < 32 or any(m in secret for m in _PLACEHOLDER_SECRET_MARKERS):
            raise ValueError("VEYRA_SECRET_KEY must be a real secret (>= 32 chars) in production")
        if self.password_pepper is not None:
            pepper = self.password_pepper.get_secret_value()
            if len(pepper) < 16 or any(m in pepper for m in _PLACEHOLDER_SECRET_MARKERS):
                raise ValueError("VEYRA_PASSWORD_PEPPER must be a real secret (>= 16 chars)")
        if self.cookie_secure is False:
            raise ValueError("Insecure cookies are not allowed in production")
        if self.verification_provider == "demo_last4":
            raise ValueError(
                "Demo verification (last 4 digits of mobile) is not allowed in production. "
                "Configure a real OTP provider."
            )
        if self.enable_mock_blood_banks:
            raise ValueError("Simulated (mock) blood banks cannot be enabled in production")
        if self.enable_telemetry_simulator:
            raise ValueError("The simulated IoT telemetry simulator cannot run in production")
        if self.enable_logistics_simulator:
            raise ValueError("The simulated logistics controls cannot run in production")
        if any("*" in o for o in self.cors_allowed_origins):
            raise ValueError("Wildcard CORS origins are not allowed in production")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
