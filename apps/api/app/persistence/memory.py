"""In-process unit of work for fast API tests (no database).

Mirrors the SQL implementation's observable behaviour, including the unique constraints
the service layer relies on (email, mobile, refresh-token hash, registration number).
Not used by the running application.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime
from itertools import count
from uuid import UUID

from app.core.errors import ConflictError
from app.modules.audit.models import AuditLog
from app.modules.bags.models import BagEvent, BloodBag
from app.modules.donations.models import Donation
from app.modules.donors.models import Donor
from app.modules.facilities.models import Facility, FacilityMembership
from app.modules.identity.errors import EmailTakenError, MobileTakenError
from app.modules.identity.models import (
    AuthSession,
    FacilityInvite,
    User,
    VerificationChallenge,
)
from app.modules.outbox.models import OutboxEvent
from app.modules.requests.models import BloodRequest, RequestAllocation
from app.persistence.repositories import InventoryCount, UnitOfWork
from app.persistence.sql import UowFactory


@dataclass
class MemoryDatabase:
    users: dict[UUID, User] = field(default_factory=dict)
    sessions: dict[UUID, AuthSession] = field(default_factory=dict)
    challenges: dict[UUID, VerificationChallenge] = field(default_factory=dict)
    donors: dict[UUID, Donor] = field(default_factory=dict)
    facilities: dict[UUID, Facility] = field(default_factory=dict)
    memberships: dict[UUID, FacilityMembership] = field(default_factory=dict)
    invites: dict[UUID, FacilityInvite] = field(default_factory=dict)
    audit: list[AuditLog] = field(default_factory=list)
    donations: dict[UUID, Donation] = field(default_factory=dict)
    bags: dict[UUID, BloodBag] = field(default_factory=dict)
    bag_events: list[BagEvent] = field(default_factory=list)
    requests: dict[UUID, BloodRequest] = field(default_factory=dict)
    allocations: list[RequestAllocation] = field(default_factory=list)
    outbox: list[OutboxEvent] = field(default_factory=list)
    outbox_ids: count[int] = field(default_factory=lambda: count(1))


class _MemUsers:
    def __init__(self, db: MemoryDatabase) -> None:
        self._db = db

    async def add(self, user: User) -> None:
        if any(u.email == user.email for u in self._db.users.values()):
            raise EmailTakenError()
        if any(u.mobile == user.mobile for u in self._db.users.values()):
            raise MobileTakenError()
        self._db.users[user.id] = user

    async def get(self, user_id: UUID) -> User | None:
        return self._db.users.get(user_id)

    async def get_by_email(self, email: str) -> User | None:
        return next((u for u in self._db.users.values() if u.email == email), None)

    async def get_by_mobile(self, mobile: str) -> User | None:
        return next((u for u in self._db.users.values() if u.mobile == mobile), None)

    async def list_page(
        self, *, role: str | None, limit: int, offset: int
    ) -> tuple[list[User], int]:
        rows = [u for u in self._db.users.values() if role is None or u.role == role]
        rows.sort(key=lambda u: (u.created_at, u.id), reverse=True)
        return rows[offset : offset + limit], len(rows)


class _MemSessions:
    def __init__(self, db: MemoryDatabase) -> None:
        self._db = db

    async def add(self, session: AuthSession) -> None:
        if any(
            s.refresh_token_hash == session.refresh_token_hash for s in self._db.sessions.values()
        ):
            raise ConflictError()
        self._db.sessions[session.id] = session

    async def get(self, session_id: UUID) -> AuthSession | None:
        return self._db.sessions.get(session_id)

    async def get_by_refresh_hash(self, token_hash: str) -> AuthSession | None:
        return next(
            (s for s in self._db.sessions.values() if s.refresh_token_hash == token_hash), None
        )

    async def list_family(self, family_id: UUID) -> list[AuthSession]:
        return [s for s in self._db.sessions.values() if s.family_id == family_id]


class _MemChallenges:
    def __init__(self, db: MemoryDatabase) -> None:
        self._db = db

    async def add(self, challenge: VerificationChallenge) -> None:
        self._db.challenges[challenge.id] = challenge

    async def get(self, challenge_id: UUID) -> VerificationChallenge | None:
        return self._db.challenges.get(challenge_id)


class _MemDonors:
    def __init__(self, db: MemoryDatabase) -> None:
        self._db = db

    async def add(self, donor: Donor) -> None:
        self._db.donors[donor.id] = donor

    async def get(self, donor_id: UUID) -> Donor | None:
        return self._db.donors.get(donor_id)

    async def get_by_user_id(self, user_id: UUID) -> Donor | None:
        return next((d for d in self._db.donors.values() if d.user_id == user_id), None)


class _MemFacilities:
    def __init__(self, db: MemoryDatabase) -> None:
        self._db = db

    async def add(self, facility: Facility) -> None:
        number = facility.registration_number
        if number and any(f.registration_number == number for f in self._db.facilities.values()):
            raise ConflictError("A facility with this registration number already exists")
        self._db.facilities[facility.id] = facility

    async def get(self, facility_id: UUID) -> Facility | None:
        return self._db.facilities.get(facility_id)

    async def get_by_registration_number(self, number: str) -> Facility | None:
        return next(
            (f for f in self._db.facilities.values() if f.registration_number == number), None
        )

    async def list_page(self, *, limit: int, offset: int) -> tuple[list[Facility], int]:
        rows = sorted(self._db.facilities.values(), key=lambda f: (f.name, f.id))
        return rows[offset : offset + limit], len(rows)

    async def add_membership(self, membership: FacilityMembership) -> None:
        self._db.memberships[membership.user_id] = membership

    async def get_membership(self, user_id: UUID) -> FacilityMembership | None:
        return self._db.memberships.get(user_id)

    async def list_active_by_type(self, facility_type: str) -> list[Facility]:
        rows = [
            f
            for f in self._db.facilities.values()
            if f.type == facility_type and f.status == "active"
        ]
        return sorted(rows, key=lambda f: f.name)


class _MemInvites:
    def __init__(self, db: MemoryDatabase) -> None:
        self._db = db

    async def add(self, invite: FacilityInvite) -> None:
        self._db.invites[invite.id] = invite

    async def get_by_token_hash(self, token_hash: str) -> FacilityInvite | None:
        return next((i for i in self._db.invites.values() if i.token_hash == token_hash), None)

    async def list_for_facility(self, facility_id: UUID) -> list[FacilityInvite]:
        rows = [i for i in self._db.invites.values() if i.facility_id == facility_id]
        return sorted(rows, key=lambda i: i.created_at, reverse=True)


class _MemAudit:
    def __init__(self, db: MemoryDatabase) -> None:
        self._db = db

    async def add(self, entry: AuditLog) -> None:
        self._db.audit.append(entry)


class _MemDonations:
    def __init__(self, db: MemoryDatabase) -> None:
        self._db = db

    async def add(self, donation: Donation) -> None:
        self._db.donations[donation.id] = donation

    async def get(self, donation_id: UUID) -> Donation | None:
        return self._db.donations.get(donation_id)

    async def list_for_facility(
        self, facility_id: UUID, *, limit: int, offset: int
    ) -> tuple[list[Donation], int]:
        rows = [d for d in self._db.donations.values() if d.collection_facility_id == facility_id]
        rows.sort(key=lambda d: (d.collected_at, d.id), reverse=True)
        return rows[offset : offset + limit], len(rows)

    async def list_for_donor(self, donor_id: UUID) -> list[Donation]:
        rows = [d for d in self._db.donations.values() if d.donor_id == donor_id]
        return sorted(rows, key=lambda d: d.collected_at, reverse=True)

    async def last_collected_at(self, donor_id: UUID) -> datetime | None:
        times = [
            d.collected_at
            for d in self._db.donations.values()
            if d.donor_id == donor_id and d.status == "collected"
        ]
        return max(times, default=None)


_ON_HAND = ("available", "received")


class _MemBags:
    def __init__(self, db: MemoryDatabase) -> None:
        self._db = db

    async def add(self, bag: BloodBag) -> None:
        if any(b.public_id == bag.public_id for b in self._db.bags.values()):
            raise ConflictError()
        self._db.bags[bag.id] = bag

    async def get(self, bag_id: UUID) -> BloodBag | None:
        return self._db.bags.get(bag_id)

    async def get_by_public_id(self, public_id: str) -> BloodBag | None:
        return next((b for b in self._db.bags.values() if b.public_id == public_id), None)

    async def list_for_donation(self, donation_id: UUID) -> list[BloodBag]:
        rows = [b for b in self._db.bags.values() if b.donation_id == donation_id]
        return sorted(rows, key=lambda b: b.component)

    async def list_at_facility(
        self,
        facility_id: UUID,
        *,
        status: str | None,
        blood_group: str | None,
        component: str | None,
        limit: int,
        offset: int,
    ) -> tuple[list[BloodBag], int]:
        rows = [
            b
            for b in self._db.bags.values()
            if b.current_facility_id == facility_id
            and (status is None or b.status == status)
            and (blood_group is None or b.blood_group == blood_group)
            and (component is None or b.component == component)
        ]
        rows.sort(key=lambda b: (b.expires_at, b.id))
        return rows[offset : offset + limit], len(rows)

    async def usable_fefo(
        self, facility_id: UUID, *, blood_group: str, component: str, now: datetime, limit: int
    ) -> list[BloodBag]:
        rows = [
            b
            for b in self._db.bags.values()
            if b.current_facility_id == facility_id
            and b.status == "available"
            and b.blood_group == blood_group
            and b.component == component
            and b.expires_at > now
        ]
        rows.sort(key=lambda b: (b.expires_at, b.id))
        return rows[:limit]

    async def count_usable_by_facility(
        self, *, blood_group: str, component: str, now: datetime
    ) -> dict[UUID, int]:
        out: dict[UUID, int] = {}
        for b in self._db.bags.values():
            if (
                b.status == "available"
                and b.blood_group == blood_group
                and b.component == component
                and b.expires_at > now
            ):
                out[b.current_facility_id] = out.get(b.current_facility_id, 0) + 1
        return out

    async def inventory_counts(
        self, facility_id: UUID, *, now: datetime, soon: datetime
    ) -> list[InventoryCount]:
        groups: dict[tuple[str, str], list[BloodBag]] = {}
        for b in self._db.bags.values():
            if b.current_facility_id == facility_id and b.status in _ON_HAND:
                groups.setdefault((b.blood_group, b.component), []).append(b)
        out = []
        for (group, component), bags in sorted(groups.items()):
            usable = [b for b in bags if b.expires_at > now]
            out.append(
                InventoryCount(
                    blood_group=group,
                    component=component,
                    available=len(usable),
                    expired=len(bags) - len(usable),
                    expiring_soon=sum(1 for b in usable if b.expires_at <= soon),
                    next_expiry=min((b.expires_at for b in usable), default=None),
                )
            )
        return out

    async def add_event(self, event: BagEvent) -> None:
        if any(e.bag_id == event.bag_id and e.seq == event.seq for e in self._db.bag_events):
            raise ConflictError()  # mirrors uq_bag_events_bag_id_seq
        self._db.bag_events.append(event)

    async def list_events(self, bag_id: UUID) -> list[BagEvent]:
        return sorted((e for e in self._db.bag_events if e.bag_id == bag_id), key=lambda e: e.seq)


class _MemRequests:
    def __init__(self, db: MemoryDatabase) -> None:
        self._db = db

    async def add(self, request: BloodRequest) -> None:
        if request.idempotency_key and any(
            r.hospital_id == request.hospital_id and r.idempotency_key == request.idempotency_key
            for r in self._db.requests.values()
        ):
            raise ConflictError()
        self._db.requests[request.id] = request

    async def get(self, request_id: UUID) -> BloodRequest | None:
        return self._db.requests.get(request_id)

    async def get_by_idempotency_key(self, hospital_id: UUID, key: str) -> BloodRequest | None:
        return next(
            (
                r
                for r in self._db.requests.values()
                if r.hospital_id == hospital_id and r.idempotency_key == key
            ),
            None,
        )

    async def list_page(
        self,
        *,
        hospital_id: UUID | None,
        target_facility_id: UUID | None,
        status: str | None,
        limit: int,
        offset: int,
    ) -> tuple[list[BloodRequest], int]:
        rows = [
            r
            for r in self._db.requests.values()
            if (hospital_id is None or r.hospital_id == hospital_id)
            and (target_facility_id is None or r.target_facility_id == target_facility_id)
            and (status is None or r.status == status)
        ]
        rows.sort(key=lambda r: (r.created_at, r.id), reverse=True)
        return rows[offset : offset + limit], len(rows)

    async def add_allocation(self, allocation: RequestAllocation) -> None:
        if any(a.bag_id == allocation.bag_id for a in self._db.allocations):
            raise ConflictError()  # a bag serves at most one request
        self._db.allocations.append(allocation)

    async def allocated_bag_ids(self, request_id: UUID) -> list[UUID]:
        return [a.bag_id for a in self._db.allocations if a.request_id == request_id]


class _MemOutbox:
    def __init__(self, db: MemoryDatabase) -> None:
        self._db = db

    async def add(self, event: OutboxEvent) -> None:
        event.id = next(self._db.outbox_ids)
        self._db.outbox.append(event)

    async def list_after(self, cursor: int, *, limit: int) -> list[OutboxEvent]:
        return [e for e in self._db.outbox if e.id > cursor][:limit]

    async def claim_unpublished(self, *, limit: int) -> list[OutboxEvent]:
        return [e for e in self._db.outbox if e.published_at is None][:limit]


class MemoryUnitOfWork:
    def __init__(self, db: MemoryDatabase) -> None:
        self.users = _MemUsers(db)
        self.sessions = _MemSessions(db)
        self.challenges = _MemChallenges(db)
        self.donors = _MemDonors(db)
        self.facilities = _MemFacilities(db)
        self.invites = _MemInvites(db)
        self.audit = _MemAudit(db)
        self.donations = _MemDonations(db)
        self.bags = _MemBags(db)
        self.requests = _MemRequests(db)
        self.outbox = _MemOutbox(db)

    async def commit(self) -> None:
        return None

    async def rollback(self) -> None:
        return None


def memory_uow_factory(db: MemoryDatabase) -> UowFactory:
    @asynccontextmanager
    async def _uow() -> AsyncIterator[UnitOfWork]:
        yield MemoryUnitOfWork(db)

    return _uow
