from __future__ import annotations

import pytest
from pydantic import SecretStr, ValidationError

from app.core.config import Settings
from app.main import create_app

REAL_SECRET = SecretStr("x" * 48)


def test_defaults_are_dev_and_demo() -> None:
    s = Settings(_env_file=None)  # type: ignore[call-arg]
    assert s.env == "dev"
    assert s.demo_mode is True
    assert s.docs_enabled is True


def test_production_rejects_placeholder_secret() -> None:
    with pytest.raises(ValidationError, match="SECRET_KEY"):
        Settings(env="production", verification_provider="sms")


def test_production_rejects_demo_verification() -> None:
    with pytest.raises(ValidationError, match="Demo verification"):
        Settings(env="production", secret_key=REAL_SECRET, verification_provider="demo_last4")


def test_production_rejects_wildcard_cors() -> None:
    with pytest.raises(ValidationError, match="CORS"):
        Settings(
            env="production",
            secret_key=REAL_SECRET,
            verification_provider="sms",
            cors_allowed_origins=["*"],
        )


def test_valid_production_config_disables_docs_and_demo_mode() -> None:
    s = Settings(
        env="production",
        secret_key=REAL_SECRET,
        verification_provider="sms",
        cors_allowed_origins=["https://veyra.example"],
    )
    assert s.demo_mode is False
    app = create_app(s, with_infra=False)
    assert app.docs_url is None
    assert app.openapi_url is None


def test_env_prefix_is_veyra(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VEYRA_ENV", "demo")
    monkeypatch.setenv("VEYRA_APP_VERSION", "9.9.9")
    s = Settings(_env_file=None)  # type: ignore[call-arg]
    assert s.env == "demo"
    assert s.app_version == "9.9.9"


def test_hosted_demo_requires_real_secrets_and_secure_cookies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A public (Vercel) demo deployment keeps labelled demo features but never runs with the
    placeholder secret, insecure cookies or API docs exposed."""
    monkeypatch.setenv("VERCEL", "1")
    with pytest.raises(ValueError, match="real secret"):
        Settings(_env_file=None, env="demo")  # type: ignore[call-arg]
    with pytest.raises(ValueError, match="Insecure cookies"):
        Settings(_env_file=None, env="demo", secret_key=REAL_SECRET, cookie_secure=False)  # type: ignore[call-arg]
    s = Settings(_env_file=None, env="demo", secret_key=REAL_SECRET)  # type: ignore[call-arg]
    assert s.secure_cookies is True and s.docs_enabled is False
    assert s.telemetry_simulator_enabled is True  # labelled demo features stay available
    assert create_app(s, with_infra=False).docs_url is None


def test_platform_database_and_redis_urls_are_adopted(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.config import asyncpg_url

    for key in ("VEYRA_DATABASE_URL", "VEYRA_REDIS_URL"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgres://u:p@pooler.example/db?sslmode=require")
    monkeypatch.setenv(
        "DATABASE_URL_UNPOOLED",
        "postgresql://u:p@direct.example/db?sslmode=require&channel_binding=require",
    )
    monkeypatch.setenv("REDIS_URL", "rediss://default:t@redis.example:6379")
    s = Settings(_env_file=None)  # type: ignore[call-arg]
    assert s.database_url == "postgresql+asyncpg://u:p@direct.example/db?ssl=require"
    assert s.redis_url == "rediss://default:t@redis.example:6379"
    monkeypatch.setenv("VEYRA_DATABASE_URL", "postgresql+asyncpg://x@y/z")
    assert Settings(_env_file=None).database_url == "postgresql+asyncpg://x@y/z"  # type: ignore[call-arg]
    assert asyncpg_url("postgres://a@b/c") == "postgresql+asyncpg://a@b/c"
