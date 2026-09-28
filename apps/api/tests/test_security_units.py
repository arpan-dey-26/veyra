"""Unit tests: password hashing, tokens, validation, verification providers."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from app.core import validation as v
from app.core.config import Settings
from app.core.security import (
    AccessTokenCodec,
    PasswordHasher,
    TokenError,
    derive_key,
    hash_token,
)
from app.providers.verification import (
    DEMO_DISCLAIMER,
    DemoLast4VerificationProvider,
    ProviderNotConfiguredError,
    SmsOtpVerificationProvider,
    build_verification_provider,
    mask_mobile,
)

NOW = datetime(2026, 9, 28, 9, 0, tzinfo=UTC)


def _hasher(pepper: bytes = b"p" * 32) -> PasswordHasher:
    return PasswordHasher(pepper=pepper, memory_kib=1024, iterations=1)


def test_argon2id_hash_and_verify() -> None:
    h = _hasher()
    encoded = h.hash("correct horse battery")
    assert encoded.startswith("$argon2id$v=19$m=1024,t=1,p=4$")
    assert h.verify("correct horse battery", encoded)
    assert not h.verify("wrong horse battery", encoded)
    assert h.hash("correct horse battery") != encoded  # random salt


def test_pepper_is_required_to_verify() -> None:
    encoded = _hasher(b"a" * 32).hash("secret-password")
    assert not _hasher(b"b" * 32).verify("secret-password", encoded)


def test_needs_rehash_when_parameters_change() -> None:
    encoded = _hasher().hash("pw-1234567890")
    assert not _hasher().needs_rehash(encoded)
    stronger = PasswordHasher(pepper=b"p" * 32, memory_kib=2048, iterations=2)
    assert stronger.needs_rehash(encoded)
    assert _hasher().needs_rehash("not-a-phc-string")
    assert not _hasher().verify("x", "not-a-phc-string")


def test_pepper_defaults_to_a_key_derived_from_the_secret() -> None:
    s = Settings(_env_file=None, env="test", password_hash_memory_kib=1024)  # type: ignore[call-arg]
    h1, h2 = PasswordHasher.from_settings(s), PasswordHasher.from_settings(s)
    assert h2.verify("some-password-1", h1.hash("some-password-1"))
    assert derive_key("k", "a") != derive_key("k", "b")


def test_access_token_roundtrip_expiry_and_tamper() -> None:
    codec = AccessTokenCodec(key=b"k" * 32, ttl_seconds=900)
    uid, sid = uuid4(), uuid4()
    token = codec.encode(user_id=uid, session_id=sid, role="DONOR", now=NOW)
    claims = codec.decode(token, now=NOW + timedelta(minutes=5))
    assert (claims.user_id, claims.session_id, claims.role) == (uid, sid, "DONOR")
    with pytest.raises(TokenError):
        codec.decode(token, now=NOW + timedelta(minutes=15))
    with pytest.raises(TokenError):
        AccessTokenCodec(key=b"z" * 32, ttl_seconds=900).decode(token, now=NOW)
    with pytest.raises(TokenError):
        codec.decode(token[:-2] + "xx", now=NOW)
    with pytest.raises(TokenError):
        codec.decode("garbage", now=NOW)


def test_access_token_time_checks_use_the_injected_clock() -> None:
    """exp AND iat are judged by the service clock, never the wall clock."""
    codec = AccessTokenCodec(key=b"k" * 32, ttl_seconds=900)
    later = NOW + timedelta(days=400)  # far from the wall clock in either direction
    token = codec.encode(user_id=uuid4(), session_id=uuid4(), role="DONOR", now=later)
    assert codec.decode(token, now=later + timedelta(minutes=1)).role == "DONOR"
    with pytest.raises(TokenError):  # issued "in the future" relative to the caller's clock
        codec.decode(token, now=later - timedelta(minutes=5))
    with pytest.raises(TokenError):
        codec.decode(token, now=later + timedelta(minutes=15))


def test_token_hash_is_sha256_hex() -> None:
    assert len(hash_token("abc")) == 64 and hash_token("abc") != hash_token("abd")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("9876543210", "+919876543210"),
        ("98765 43210", "+919876543210"),
        ("+91 98765-43210", "+919876543210"),
        ("919876543210", "+919876543210"),
        ("09876543210", "+919876543210"),
        ("6000000000", "+916000000000"),
    ],
)
def test_mobile_normalisation(raw: str, expected: str) -> None:
    assert v.normalize_indian_mobile(raw) == expected


@pytest.mark.parametrize("raw", ["12345", "5876543210", "98765432101", "+1 415 555 0100", "abc"])
def test_mobile_rejects_invalid(raw: str) -> None:
    with pytest.raises(ValueError):
        v.normalize_indian_mobile(raw)


def test_field_validators() -> None:
    assert v.validate_pin_code(" 700 016") == "700016"
    for bad_pin in ("012345", "70001", "7000161", "70001a"):
        with pytest.raises(ValueError):
            v.validate_pin_code(bad_pin)
    assert v.validate_state("west BENGAL") == "West Bengal"
    assert len(v.INDIAN_STATES_AND_UTS) == 36
    assert v.validate_blood_group(" ab- ") == "AB-"
    assert v.validate_blood_group("O\u2212") == "O-"
    with pytest.raises(ValueError):
        v.validate_blood_group("C+")
    assert v.validate_person_name("  A. P. J.  Abdul Kalam ") == "A. P. J. Abdul Kalam"
    assert v.validate_person_name("Sourav Gānguly") == "Sourav Gānguly"
    for bad_name in ("X", "R2D2", "<script>", "12"):
        with pytest.raises(ValueError):
            v.validate_person_name(bad_name)
    assert v.normalize_email(" Arpan@Example.IN ") == "arpan@example.in"
    for bad_email in ("a@b", "no-at.in", "a@@b.in", "a b@c.in"):
        with pytest.raises(ValueError):
            v.normalize_email(bad_email)
    assert v.clean_text("a\u0000b\tc  d") == "ab c d"


def test_password_policy() -> None:
    assert v.validate_new_password("long enough phrase") == "long enough phrase"
    for bad in ("short", "1234567890", "aaaaaaaaaaaa", "x" * 129):
        with pytest.raises(ValueError):
            v.validate_new_password(bad)
    with pytest.raises(ValueError, match="email"):
        v.validate_new_password("arpandey-2026!", email="arpandey@example.in")


async def test_demo_provider_uses_last4_and_never_reveals_it() -> None:
    p = DemoLast4VerificationProvider()
    assert p.is_demo and p.disclaimer == DEMO_DISCLAIMER
    started = await p.start(mobile="+919876543210")
    assert started.code_hash is None
    assert "3210" not in started.destination_hint and "3210" not in mask_mobile("+919876543210")
    assert p.check(mobile="+919876543210", code_hash=None, code="3210")
    assert not p.check(mobile="+919876543210", code_hash=None, code="3211")
    assert not p.check(mobile="+919876543210", code_hash=None, code="93210")


async def test_sms_provider_stores_only_a_hash_of_a_random_code() -> None:
    sent: list[str] = []

    class Gateway:
        async def send(self, *, to: str, text: str) -> None:
            sent.append(text)

    p = SmsOtpVerificationProvider(Gateway())
    assert not p.is_demo and p.disclaimer is None
    started = await p.start(mobile="+919876543210")
    code = sent[0].rsplit(" ", 1)[1]
    assert len(code) == 6 and started.code_hash == hash_token(code)
    assert p.check(mobile="+919876543210", code_hash=started.code_hash, code=code)
    assert not p.check(mobile="+919876543210", code_hash=started.code_hash, code="3210")


def test_provider_factory() -> None:
    demo = Settings(_env_file=None, env="test")  # type: ignore[call-arg]
    assert isinstance(build_verification_provider(demo), DemoLast4VerificationProvider)
    sms = Settings(_env_file=None, env="test", verification_provider="sms")  # type: ignore[call-arg]
    with pytest.raises(ProviderNotConfiguredError):
        build_verification_provider(sms)


def test_production_forbids_insecure_cookies_and_weak_pepper() -> None:
    base = {
        "_env_file": None,
        "env": "production",
        "secret_key": "s" * 48,
        "verification_provider": "sms",
        "cors_allowed_origins": ["https://veyra.example"],
    }
    assert Settings(**base).secure_cookies is True  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="cookies"):
        Settings(**base, cookie_secure=False)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="PEPPER"):
        Settings(**base, password_pepper="change-me-please-1234")  # type: ignore[arg-type]
