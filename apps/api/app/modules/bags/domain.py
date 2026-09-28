"""Blood-bag domain rules: components, shelf life, lifecycle, identifiers, trace hash chain.

Shelf lives and storage ranges are configurable prototype defaults, labelled as such in the
UI. They must be verified against current national blood-transfusion guidelines before any
real-world use.
"""

from __future__ import annotations

import hashlib
import json
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any


class Component(StrEnum):
    WHOLE_BLOOD = "WHOLE_BLOOD"
    PRBC = "PRBC"  # packed red blood cells
    FFP = "FFP"  # fresh frozen plasma
    PLATELETS = "PLATELETS"
    CRYO = "CRYO"  # cryoprecipitate


@dataclass(frozen=True)
class ComponentSpec:
    label: str
    shelf_life: timedelta
    default_volume_ml: int
    storage: str


COMPONENT_SPECS: dict[Component, ComponentSpec] = {
    Component.WHOLE_BLOOD: ComponentSpec("Whole blood", timedelta(days=35), 350, "2-6 °C"),
    Component.PRBC: ComponentSpec("Packed red cells", timedelta(days=42), 250, "2-6 °C"),
    Component.FFP: ComponentSpec("Fresh frozen plasma", timedelta(days=365), 200, "≤ -18 °C"),
    Component.PLATELETS: ComponentSpec("Platelets", timedelta(days=5), 50, "20-24 °C, agitated"),
    Component.CRYO: ComponentSpec("Cryoprecipitate", timedelta(days=365), 20, "≤ -18 °C"),
}


class BagStatus(StrEnum):
    AVAILABLE = "available"  # in storage at current_facility, usable
    IN_TRANSIT = "in_transit"  # dispatched against a request, not yet received
    RECEIVED = "received"  # received by the requesting hospital
    DISCARDED = "discarded"  # removed from use (expired, damaged, failed testing…)


class BagEventType(StrEnum):
    COLLECTED = "COLLECTED"
    DISPATCHED = "DISPATCHED"
    RECEIVED = "RECEIVED"
    DISCARDED = "DISCARDED"


# Allowed lifecycle transitions (event → required current status → resulting status).
TRANSITIONS: dict[BagEventType, tuple[frozenset[BagStatus], BagStatus]] = {
    BagEventType.DISPATCHED: (frozenset({BagStatus.AVAILABLE}), BagStatus.IN_TRANSIT),
    BagEventType.RECEIVED: (frozenset({BagStatus.IN_TRANSIT}), BagStatus.RECEIVED),
    BagEventType.DISCARDED: (
        frozenset({BagStatus.AVAILABLE, BagStatus.RECEIVED}),
        BagStatus.DISCARDED,
    ),
}

# Crockford base32 (no I, L, O, U): unambiguous when read aloud or typed from a label.
_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
PUBLIC_ID_PREFIX = "VYR"


def new_bag_public_id() -> str:
    """e.g. ``VYR-7F3K-2QXM``: 40 random bits, QR/label friendly, not the primary key."""
    n = secrets.randbits(40)
    chars = "".join(_CROCKFORD[(n >> (5 * i)) & 31] for i in range(8))
    return f"{PUBLIC_ID_PREFIX}-{chars[:4]}-{chars[4:]}"


def is_bag_public_id(value: str) -> bool:
    parts = value.split("-")
    return (
        len(parts) == 3
        and parts[0] == PUBLIC_ID_PREFIX
        and all(len(p) == 4 and all(c in _CROCKFORD for c in p) for p in parts[1:])
    )


def qr_payload(public_id: str) -> str:
    """Content encoded in the bag's QR label (signed tokens arrive in Phase 8)."""
    return f"veyra:bag:{public_id}"


def expiry_for(component: Component, collected_at: datetime) -> datetime:
    return collected_at + COMPONENT_SPECS[component].shelf_life


# ---------------------------------------------------------------- trace hash chain

GENESIS_HASH = "0" * 64


def event_hash(prev_hash: str, fields: dict[str, Any]) -> str:
    """SHA-256 over the previous hash and a canonical JSON of the event.

    A tamper-evident chain *inside the database*: editing or deleting any event breaks every
    later hash. It is not a blockchain; anchoring these hashes on-chain is Phase 8.
    """
    canonical = json.dumps(fields, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(f"{prev_hash}|{canonical}".encode()).hexdigest()


def event_fields(
    *,
    bag_id: str,
    seq: int,
    event_type: str,
    from_facility_id: str | None,
    to_facility_id: str | None,
    actor_id: str | None,
    occurred_at: datetime,
    meta: dict[str, Any],
) -> dict[str, Any]:
    return {
        "bag_id": bag_id,
        "seq": seq,
        "type": event_type,
        "from": from_facility_id,
        "to": to_facility_id,
        "actor": actor_id,
        # Always UTC: the database returns timestamptz in UTC, so any other offset would
        # re-serialise differently on read and break the chain.
        "at": occurred_at.astimezone(UTC).isoformat(),
        "meta": meta,
    }
