"""Phone verification port.

``VerificationProvider`` is the only thing the auth service knows about. Swapping the demo
provider for a real SMS OTP provider is a configuration change, not an auth rewrite.

- ``DemoLast4VerificationProvider``: DEMO ONLY. The "code" is the last 4 digits of the
  registered mobile number. It is not an OTP and provides no proof of phone ownership.
  Settings refuse it in production.
- ``SmsOtpVerificationProvider``: real flow (random 6-digit code, only its hash stored).
  It needs an ``SmsGateway``; none is integrated yet, so selecting it without one fails
  loudly at startup rather than pretending to send messages.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from typing import Protocol

from app.core.config import Settings
from app.core.security import constant_time_equals, hash_token

DEMO_DISCLAIMER = (
    "Demo verification only. The last 4 digits of your mobile number are used for "
    "prototype verification instead of a real OTP."
)


@dataclass(frozen=True)
class ChallengeStart:
    """What the service persists after starting a challenge."""

    code_hash: str | None  # None for providers that don't issue codes (demo)
    destination_hint: str


class VerificationProvider(Protocol):
    name: str
    is_demo: bool
    channel: str
    disclaimer: str | None

    async def start(self, *, mobile: str) -> ChallengeStart: ...

    def check(self, *, mobile: str, code_hash: str | None, code: str) -> bool: ...


def mask_mobile(mobile: str) -> str:
    """'+919876543210' → '+91 98••••••••' (never reveals the digits used as the demo code)."""
    if mobile.startswith("+91") and len(mobile) == 13:
        return f"+91 {mobile[3:5]}{'•' * 8}"
    return "•" * max(len(mobile) - 2, 4)


class DemoLast4VerificationProvider:
    name = "demo_last4"
    is_demo = True
    channel = "sms"
    disclaimer: str | None = DEMO_DISCLAIMER

    async def start(self, *, mobile: str) -> ChallengeStart:
        return ChallengeStart(code_hash=None, destination_hint=mask_mobile(mobile))

    def check(self, *, mobile: str, code_hash: str | None, code: str) -> bool:
        return len(code) == 4 and code.isdigit() and constant_time_equals(code, mobile[-4:])


class SmsGateway(Protocol):
    async def send(self, *, to: str, text: str) -> None: ...


class SmsOtpVerificationProvider:
    name = "sms"
    is_demo = False
    channel = "sms"
    disclaimer: str | None = None

    def __init__(self, gateway: SmsGateway) -> None:
        self._gateway = gateway

    async def start(self, *, mobile: str) -> ChallengeStart:
        code = f"{secrets.randbelow(1_000_000):06d}"
        await self._gateway.send(to=mobile, text=f"Your VEYRA verification code is {code}")
        return ChallengeStart(code_hash=hash_token(code), destination_hint=mask_mobile(mobile))

    def check(self, *, mobile: str, code_hash: str | None, code: str) -> bool:
        if code_hash is None or not (len(code) == 6 and code.isdigit()):
            return False
        return constant_time_equals(hash_token(code), code_hash)


class ProviderNotConfiguredError(RuntimeError):
    pass


def build_verification_provider(
    settings: Settings, *, sms_gateway: SmsGateway | None = None
) -> VerificationProvider:
    if settings.verification_provider == "demo_last4":
        return DemoLast4VerificationProvider()
    if sms_gateway is None:
        raise ProviderNotConfiguredError(
            "VEYRA_VERIFICATION_PROVIDER=sms requires an SMS gateway integration, "
            "which is not implemented yet."
        )
    return SmsOtpVerificationProvider(sms_gateway)
