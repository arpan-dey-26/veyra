"""Password hashing and session tokens.

- Passwords: Argon2id (OWASP-recommended, memory-hard) via `cryptography`, stored as a PHC
  string. A server-side pepper is fed in as the Argon2 `secret`, so a leaked database alone
  is not enough to brute-force hashes.
- Access tokens: short-lived HS256 JWTs bound to a server-side session id (`sid`).
- Refresh / CSRF / invite tokens: opaque random values; only their SHA-256 is stored.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

import jwt
from cryptography.exceptions import InvalidKey
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.argon2 import Argon2id
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from app.core.config import Settings

_PHC_PARAMS = re.compile(r"^\$argon2id\$v=19\$m=(\d+),t=(\d+),p=(\d+)\$")
_LANES = 4
_SALT_BYTES = 16
_HASH_BYTES = 32

IAT_LEEWAY_SECONDS = 60
JWT_ALGORITHM = "HS256"
JWT_ISSUER = "veyra"


def derive_key(secret: str, label: str) -> bytes:
    """Derive an independent 32-byte key from the app secret (HKDF-SHA256)."""
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=label.encode()).derive(
        secret.encode()
    )


class PasswordHasher:
    def __init__(self, *, pepper: bytes, memory_kib: int, iterations: int) -> None:
        self._pepper = pepper
        self._memory_kib = memory_kib
        self._iterations = iterations
        # Used to keep login timing similar for unknown accounts.
        self._dummy_hash = self.hash(secrets.token_urlsafe(16))

    @classmethod
    def from_settings(cls, settings: Settings) -> PasswordHasher:
        if settings.password_pepper is not None:
            pepper = settings.password_pepper.get_secret_value().encode()
        else:
            pepper = derive_key(settings.secret_key.get_secret_value(), "veyra/password-pepper")
        return cls(
            pepper=pepper,
            memory_kib=settings.password_hash_memory_kib,
            iterations=settings.password_hash_iterations,
        )

    def _kdf(self, salt: bytes) -> Argon2id:
        return Argon2id(
            salt=salt,
            length=_HASH_BYTES,
            iterations=self._iterations,
            lanes=_LANES,
            memory_cost=self._memory_kib,
            secret=self._pepper,
        )

    def hash(self, password: str) -> str:
        return self._kdf(os.urandom(_SALT_BYTES)).derive_phc_encoded(password.encode())

    def verify(self, password: str, encoded: str) -> bool:
        try:
            Argon2id.verify_phc_encoded(password.encode(), encoded, secret=self._pepper)
        except (InvalidKey, ValueError):
            return False
        return True

    def verify_dummy(self, password: str) -> None:
        """Spend the same work as a real verification (unknown-account path)."""
        self.verify(password, self._dummy_hash)

    def needs_rehash(self, encoded: str) -> bool:
        m = _PHC_PARAMS.match(encoded)
        if not m:
            return True
        m_cost, t_cost, lanes = (int(x) for x in m.groups())
        return (m_cost, t_cost, lanes) != (self._memory_kib, self._iterations, _LANES)


def new_opaque_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def constant_time_equals(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())


@dataclass(frozen=True)
class AccessClaims:
    user_id: UUID
    session_id: UUID
    role: str
    expires_at: datetime


class TokenError(Exception):
    """Raised for any invalid, expired or malformed access token."""


class AccessTokenCodec:
    def __init__(self, *, key: bytes, ttl_seconds: int) -> None:
        self._key = key
        self._ttl = timedelta(seconds=ttl_seconds)

    @classmethod
    def from_settings(cls, settings: Settings) -> AccessTokenCodec:
        key = derive_key(settings.secret_key.get_secret_value(), "veyra/access-token")
        return cls(key=key, ttl_seconds=settings.access_token_ttl_seconds)

    @property
    def ttl(self) -> timedelta:
        return self._ttl

    def encode(self, *, user_id: UUID, session_id: UUID, role: str, now: datetime) -> str:
        payload = {
            "iss": JWT_ISSUER,
            "sub": str(user_id),
            "sid": str(session_id),
            "role": role,
            "iat": int(now.timestamp()),
            "exp": int((now + self._ttl).timestamp()),
            "typ": "access",
        }
        return jwt.encode(payload, self._key, algorithm=JWT_ALGORITHM)

    def decode(self, token: str, *, now: datetime) -> AccessClaims:
        try:
            payload = jwt.decode(
                token,
                self._key,
                algorithms=[JWT_ALGORITHM],
                issuer=JWT_ISSUER,
                options={
                    "require": ["exp", "iat", "sub", "sid", "iss"],
                    "verify_exp": False,
                    "verify_iat": False,
                },
            )
        except jwt.PyJWTError as exc:
            raise TokenError("invalid token") from exc
        # Expiry and issued-at are checked against the injectable clock, not the wall clock.
        ts = int(now.timestamp())
        if payload.get("typ") != "access" or int(payload["exp"]) <= ts:
            raise TokenError("expired or wrong token type")
        if int(payload["iat"]) > ts + IAT_LEEWAY_SECONDS:
            raise TokenError("token issued in the future")
        try:
            return AccessClaims(
                user_id=UUID(payload["sub"]),
                session_id=UUID(payload["sid"]),
                role=str(payload["role"]),
                expires_at=datetime.fromtimestamp(int(payload["exp"]), tz=now.tzinfo),
            )
        except (KeyError, ValueError) as exc:
            raise TokenError("malformed claims") from exc
