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
