from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.core.clock import FixedClock
from app.core.db import DOMAIN_SCHEMAS, NAMING_CONVENTION, Base
from app.core.ids import uuid7, uuid7_timestamp_ms
from app.core.provenance import SourceKind, SourceMeta


def test_uuid7_version_variant_and_timestamp() -> None:
    u = uuid7(unix_ms=1_760_000_000_000)
    assert u.version == 7
    assert (u.int >> 62) & 0b11 == 0b10  # RFC 4122 variant
    assert uuid7_timestamp_ms(u) == 1_760_000_000_000


def test_uuid7_sorts_by_time() -> None:
    ids = [uuid7(unix_ms=t) for t in (1_000, 2_000, 3_000, 4_000)]
    assert sorted(ids) == ids


def test_uuid7_uniqueness() -> None:
    assert len({uuid7() for _ in range(5_000)}) == 5_000


def test_uuid7_rejects_out_of_range() -> None:
    with pytest.raises(ValueError):
        uuid7(unix_ms=-1)


def test_fixed_clock_requires_timezone() -> None:
    at = datetime(2026, 9, 28, tzinfo=UTC)
    assert FixedClock(at).now() == at
    with pytest.raises(ValueError):
        FixedClock(datetime(2026, 9, 28))  # intentionally naive


@pytest.mark.parametrize(
    ("kind", "simulated"),
    [
        (SourceKind.INTERNAL, False),
        (SourceKind.EXTERNAL, False),
        (SourceKind.SIMULATED, True),
        (SourceKind.SYNTHETIC, True),
    ],
)
def test_source_meta_simulated_flag_is_serialized(kind: SourceKind, simulated: bool) -> None:
    meta = SourceMeta(provider="mock_blood_bank", kind=kind)
    assert meta.model_dump()["simulated"] is simulated


def test_db_foundation_contracts() -> None:
    assert Base.metadata.naming_convention == NAMING_CONVENTION
    assert set(DOMAIN_SCHEMAS) == {"identity", "network", "trace", "telemetry", "ai", "ml", "audit"}
