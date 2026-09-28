"""UUIDv7 identifiers (RFC 9562): time-ordered, index-friendly primary keys.

Python 3.12 has no stdlib ``uuid7``, so we build one: 48-bit unix-ms timestamp,
version 7, RFC 4122 variant, and 74 random bits.
"""

from __future__ import annotations

import os
import time
import uuid


def uuid7(unix_ms: int | None = None) -> uuid.UUID:
    ms = time.time_ns() // 1_000_000 if unix_ms is None else unix_ms
    if not 0 <= ms < (1 << 48):
        raise ValueError("timestamp out of range for UUIDv7")
    rand = int.from_bytes(os.urandom(10), "big")  # 80 bits, we use 74
    rand_a = (rand >> 62) & 0xFFF  # 12 bits
    rand_b = rand & ((1 << 62) - 1)  # 62 bits
    value = (ms << 80) | (0x7 << 76) | (rand_a << 64) | (0b10 << 62) | rand_b
    return uuid.UUID(int=value)


def uuid7_timestamp_ms(value: uuid.UUID) -> int:
    return value.int >> 80
