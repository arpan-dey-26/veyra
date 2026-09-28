"""In-process unit of work for fast API tests (no database).

Mirrors the SQL implementation's observable behaviour, including the unique constraints
the service layer relies on (email, mobile, refresh-token hash, registration number).
Not used by the running application.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from uuid import UUID

from app.core.errors import ConflictError
from app.modules.audit.models import AuditLog
from app.modules.donors.models import Donor
from app.modules.facilities.models import Facility, FacilityMembership
from app.modules.identity.errors import EmailTakenError, MobileTakenError
from app.modules.identity.models import (
    AuthSession,
    FacilityInvite,
    User,
    VerificationChallenge,
)
from app.persistence.repositories import UnitOfWork
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


class MemoryUnitOfWork:
    def __init__(self, db: MemoryDatabase) -> None:
        self.users = _MemUsers(db)
        self.sessions = _MemSessions(db)
        self.challenges = _MemChallenges(db)
        self.donors = _MemDonors(db)
        self.facilities = _MemFacilities(db)
        self.invites = _MemInvites(db)
        self.audit = _MemAudit(db)

    async def commit(self) -> None:
        return None

    async def rollback(self) -> None:
        return None


def memory_uow_factory(db: MemoryDatabase) -> UowFactory:
    @asynccontextmanager
    async def _uow() -> AsyncIterator[UnitOfWork]:
        yield MemoryUnitOfWork(db)

    return _uow
