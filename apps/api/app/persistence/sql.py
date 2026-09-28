"""PostgreSQL unit of work (SQLAlchemy AsyncSession). The only place SQL is written."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.errors import AppError, ConflictError
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

# Unique-constraint name → domain error (names come from the frozen naming convention).
_CONSTRAINT_ERRORS: dict[str, type[AppError]] = {
    "uq_users_email": EmailTakenError,
    "uq_users_mobile": MobileTakenError,
}


class _Repo:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session


class SqlUserRepository(_Repo):
    async def add(self, user: User) -> None:
        self._s.add(user)

    async def get(self, user_id: UUID) -> User | None:
        return await self._s.get(User, user_id)

    async def get_by_email(self, email: str) -> User | None:
        return await self._s.scalar(select(User).where(User.email == email))

    async def get_by_mobile(self, mobile: str) -> User | None:
        return await self._s.scalar(select(User).where(User.mobile == mobile))

    async def list_page(
        self, *, role: str | None, limit: int, offset: int
    ) -> tuple[list[User], int]:
        query = select(User)
        count = select(func.count()).select_from(User)
        if role is not None:
            query = query.where(User.role == role)
            count = count.where(User.role == role)
        rows = await self._s.scalars(
            query.order_by(User.created_at.desc(), User.id.desc()).limit(limit).offset(offset)
        )
        total = await self._s.scalar(count)
        return list(rows), int(total or 0)


class SqlSessionRepository(_Repo):
    async def add(self, session: AuthSession) -> None:
        self._s.add(session)

    async def get(self, session_id: UUID) -> AuthSession | None:
        return await self._s.get(AuthSession, session_id)

    async def get_by_refresh_hash(self, token_hash: str) -> AuthSession | None:
        return await self._s.scalar(
            select(AuthSession).where(AuthSession.refresh_token_hash == token_hash)
        )

    async def list_family(self, family_id: UUID) -> list[AuthSession]:
        rows = await self._s.scalars(select(AuthSession).where(AuthSession.family_id == family_id))
        return list(rows)


class SqlChallengeRepository(_Repo):
    async def add(self, challenge: VerificationChallenge) -> None:
        self._s.add(challenge)

    async def get(self, challenge_id: UUID) -> VerificationChallenge | None:
        return await self._s.get(VerificationChallenge, challenge_id)


class SqlDonorRepository(_Repo):
    async def add(self, donor: Donor) -> None:
        self._s.add(donor)

    async def get_by_user_id(self, user_id: UUID) -> Donor | None:
        return await self._s.scalar(select(Donor).where(Donor.user_id == user_id))


class SqlFacilityRepository(_Repo):
    async def add(self, facility: Facility) -> None:
        self._s.add(facility)

    async def get(self, facility_id: UUID) -> Facility | None:
        return await self._s.get(Facility, facility_id)

    async def get_by_registration_number(self, number: str) -> Facility | None:
        return await self._s.scalar(select(Facility).where(Facility.registration_number == number))

    async def list_page(self, *, limit: int, offset: int) -> tuple[list[Facility], int]:
        rows = await self._s.scalars(
            select(Facility).order_by(Facility.name, Facility.id).limit(limit).offset(offset)
        )
        total = await self._s.scalar(select(func.count()).select_from(Facility))
        return list(rows), int(total or 0)

    async def add_membership(self, membership: FacilityMembership) -> None:
        self._s.add(membership)

    async def get_membership(self, user_id: UUID) -> FacilityMembership | None:
        return await self._s.get(FacilityMembership, user_id)


class SqlInviteRepository(_Repo):
    async def add(self, invite: FacilityInvite) -> None:
        self._s.add(invite)

    async def get_by_token_hash(self, token_hash: str) -> FacilityInvite | None:
        return await self._s.scalar(
            select(FacilityInvite).where(FacilityInvite.token_hash == token_hash)
        )

    async def list_for_facility(self, facility_id: UUID) -> list[FacilityInvite]:
        rows = await self._s.scalars(
            select(FacilityInvite)
            .where(FacilityInvite.facility_id == facility_id)
            .order_by(FacilityInvite.created_at.desc())
        )
        return list(rows)


class SqlAuditRepository(_Repo):
    async def add(self, entry: AuditLog) -> None:
        self._s.add(entry)


class SqlUnitOfWork:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self.users = SqlUserRepository(session)
        self.sessions = SqlSessionRepository(session)
        self.challenges = SqlChallengeRepository(session)
        self.donors = SqlDonorRepository(session)
        self.facilities = SqlFacilityRepository(session)
        self.invites = SqlInviteRepository(session)
        self.audit = SqlAuditRepository(session)

    async def commit(self) -> None:
        try:
            await self._session.commit()
        except IntegrityError as exc:
            await self._session.rollback()
            message = str(exc.orig)
            for constraint, error in _CONSTRAINT_ERRORS.items():
                if constraint in message:
                    raise error() from exc
            raise ConflictError() from exc

    async def rollback(self) -> None:
        await self._session.rollback()


UowFactory = Callable[[], AbstractAsyncContextManager[UnitOfWork]]


def sql_uow_factory(sessionmaker: async_sessionmaker[AsyncSession]) -> UowFactory:
    @asynccontextmanager
    async def _uow() -> AsyncIterator[UnitOfWork]:
        async with sessionmaker() as session:
            uow = SqlUnitOfWork(session)
            try:
                yield uow
            except BaseException:
                await session.rollback()
                raise

    return _uow
