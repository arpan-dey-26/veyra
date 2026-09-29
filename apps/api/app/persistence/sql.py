"""PostgreSQL unit of work (SQLAlchemy AsyncSession). The only place SQL is written."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from datetime import datetime
from uuid import UUID

from sqlalchemy import case, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm.exc import StaleDataError

from app.core.errors import AppError, ConflictError
from app.modules.audit.models import AuditLog
from app.modules.bags.models import BagEvent, BloodBag
from app.modules.donations.models import Donation
from app.modules.donors.models import Donor
from app.modules.facilities.models import Facility, FacilityMembership
from app.modules.identity.errors import (
    EmailTakenError,
    MobileTakenError,
    RegistrationNumberTakenError,
)
from app.modules.identity.models import (
    AuthSession,
    FacilityInvite,
    User,
    VerificationChallenge,
)
from app.modules.outbox.models import OutboxEvent
from app.modules.requests.models import BloodRequest, RequestAllocation
from app.modules.telemetry.errors import DeviceAlreadyAttachedError
from app.modules.telemetry.models import TelemetryDevice, TelemetryReading
from app.persistence.repositories import InventoryCount, UnitOfWork

# Unique-constraint name → domain error (names come from the frozen naming convention).
_CONSTRAINT_ERRORS: dict[str, type[AppError]] = {
    "uq_users_email": EmailTakenError,
    "uq_users_mobile": MobileTakenError,
    "uq_facilities_registration_number": RegistrationNumberTakenError,
    "uq_devices_bag_id": DeviceAlreadyAttachedError,
}

_CONCURRENT_CHANGE = "This record was changed by someone else. Reload and try again."


def _domain_error(exc: IntegrityError) -> AppError:
    message = str(exc.orig)
    for constraint, error in _CONSTRAINT_ERRORS.items():
        if constraint in message:
            return error()
    return ConflictError()


class _Repo:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def _add(self, row: object) -> None:
        """Add a row and flush it immediately (INSERT order == call order).

        The models declare column-level FKs without ORM ``relationship()``s, so SQLAlchemy
        does not order INSERTs by dependency: a donor/session/membership row could be sent
        before its user row and fail PostgreSQL's (immediate) FK check. Flushing the parent
        right away guarantees it exists first; constraint errors are mapped as at commit.
        """
        self._s.add(row)
        await self._flush()

    async def _flush(self) -> None:
        try:
            await self._s.flush()
        except IntegrityError as exc:
            await self._s.rollback()
            raise _domain_error(exc) from exc
        except StaleDataError as exc:  # optimistic-lock (version_id_col) mismatch
            await self._s.rollback()
            raise ConflictError(_CONCURRENT_CHANGE) from exc


class SqlUserRepository(_Repo):
    async def add(self, user: User) -> None:
        await self._add(user)

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
        await self._add(session)

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
        await self._add(challenge)

    async def get(self, challenge_id: UUID) -> VerificationChallenge | None:
        return await self._s.get(VerificationChallenge, challenge_id)


class SqlDonorRepository(_Repo):
    async def add(self, donor: Donor) -> None:
        await self._add(donor)

    async def get(self, donor_id: UUID) -> Donor | None:
        return await self._s.get(Donor, donor_id)

    async def get_by_user_id(self, user_id: UUID) -> Donor | None:
        return await self._s.scalar(select(Donor).where(Donor.user_id == user_id))


class SqlFacilityRepository(_Repo):
    async def add(self, facility: Facility) -> None:
        await self._add(facility)

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
        await self._add(membership)

    async def get_membership(self, user_id: UUID) -> FacilityMembership | None:
        return await self._s.get(FacilityMembership, user_id)

    async def list_active_by_type(self, facility_type: str) -> list[Facility]:
        rows = await self._s.scalars(
            select(Facility)
            .where(Facility.type == facility_type, Facility.status == "active")
            .order_by(Facility.name)
        )
        return list(rows)


class SqlInviteRepository(_Repo):
    async def add(self, invite: FacilityInvite) -> None:
        await self._add(invite)

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
        await self._add(entry)


class SqlDonationRepository(_Repo):
    async def add(self, donation: Donation) -> None:
        await self._add(donation)

    async def get(self, donation_id: UUID) -> Donation | None:
        return await self._s.get(Donation, donation_id)

    async def list_for_facility(
        self, facility_id: UUID, *, limit: int, offset: int
    ) -> tuple[list[Donation], int]:
        where = Donation.collection_facility_id == facility_id
        rows = await self._s.scalars(
            select(Donation)
            .where(where)
            .order_by(Donation.collected_at.desc(), Donation.id.desc())
            .limit(limit)
            .offset(offset)
        )
        total = await self._s.scalar(select(func.count()).select_from(Donation).where(where))
        return list(rows), int(total or 0)

    async def list_for_donor(self, donor_id: UUID) -> list[Donation]:
        rows = await self._s.scalars(
            select(Donation)
            .where(Donation.donor_id == donor_id)
            .order_by(Donation.collected_at.desc())
        )
        return list(rows)

    async def last_collected_at(self, donor_id: UUID) -> datetime | None:
        return await self._s.scalar(
            select(func.max(Donation.collected_at)).where(
                Donation.donor_id == donor_id, Donation.status == "collected"
            )
        )


class SqlBagRepository(_Repo):
    async def add(self, bag: BloodBag) -> None:
        await self._add(bag)

    async def get(self, bag_id: UUID) -> BloodBag | None:
        return await self._s.get(BloodBag, bag_id)

    async def get_by_public_id(self, public_id: str) -> BloodBag | None:
        return await self._s.scalar(select(BloodBag).where(BloodBag.public_id == public_id))

    async def list_for_donation(self, donation_id: UUID) -> list[BloodBag]:
        rows = await self._s.scalars(
            select(BloodBag).where(BloodBag.donation_id == donation_id).order_by(BloodBag.component)
        )
        return list(rows)

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
        conds = [BloodBag.current_facility_id == facility_id]
        if status:
            conds.append(BloodBag.status == status)
        if blood_group:
            conds.append(BloodBag.blood_group == blood_group)
        if component:
            conds.append(BloodBag.component == component)
        rows = await self._s.scalars(
            select(BloodBag)
            .where(*conds)
            .order_by(BloodBag.expires_at, BloodBag.id)
            .limit(limit)
            .offset(offset)
        )
        total = await self._s.scalar(select(func.count()).select_from(BloodBag).where(*conds))
        return list(rows), int(total or 0)

    async def usable_fefo(
        self, facility_id: UUID, *, blood_group: str, component: str, now: datetime, limit: int
    ) -> list[BloodBag]:
        rows = await self._s.scalars(
            select(BloodBag)
            .where(
                BloodBag.current_facility_id == facility_id,
                BloodBag.status == "available",
                BloodBag.blood_group == blood_group,
                BloodBag.component == component,
                BloodBag.expires_at > now,
            )
            .order_by(BloodBag.expires_at, BloodBag.id)  # first-expiry-first-out
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        return list(rows)

    async def count_usable_by_facility(
        self, *, blood_group: str, component: str, now: datetime
    ) -> dict[UUID, int]:
        rows = await self._s.execute(
            select(BloodBag.current_facility_id, func.count())
            .where(
                BloodBag.status == "available",
                BloodBag.blood_group == blood_group,
                BloodBag.component == component,
                BloodBag.expires_at > now,
            )
            .group_by(BloodBag.current_facility_id)
        )
        return {fid: int(n) for fid, n in rows.all()}

    async def inventory_counts(
        self, facility_id: UUID, *, now: datetime, soon: datetime
    ) -> list[InventoryCount]:
        # On hand = stored at a bank (available) or received at a hospital.
        on_hand = BloodBag.status.in_(("available", "received"))
        usable = on_hand & (BloodBag.expires_at > now)
        rows = await self._s.execute(
            select(
                BloodBag.blood_group,
                BloodBag.component,
                func.count().filter(usable),
                func.count().filter(on_hand & (BloodBag.expires_at <= now)),
                func.count().filter(usable & (BloodBag.expires_at <= soon)),
                func.min(case((usable, BloodBag.expires_at))),
            )
            .where(BloodBag.current_facility_id == facility_id, on_hand)
            .group_by(BloodBag.blood_group, BloodBag.component)
        )
        return [
            InventoryCount(g, c, int(a), int(e), int(s), nxt) for g, c, a, e, s, nxt in rows.all()
        ]

    async def add_event(self, event: BagEvent) -> None:
        await self._add(event)

    async def list_events(self, bag_id: UUID) -> list[BagEvent]:
        rows = await self._s.scalars(
            select(BagEvent).where(BagEvent.bag_id == bag_id).order_by(BagEvent.seq)
        )
        return list(rows)


class SqlRequestRepository(_Repo):
    async def add(self, request: BloodRequest) -> None:
        await self._add(request)

    async def get(self, request_id: UUID) -> BloodRequest | None:
        return await self._s.get(BloodRequest, request_id)

    async def get_by_idempotency_key(self, hospital_id: UUID, key: str) -> BloodRequest | None:
        return await self._s.scalar(
            select(BloodRequest).where(
                BloodRequest.hospital_id == hospital_id, BloodRequest.idempotency_key == key
            )
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
        conds = []
        if hospital_id is not None:
            conds.append(BloodRequest.hospital_id == hospital_id)
        if target_facility_id is not None:
            conds.append(BloodRequest.target_facility_id == target_facility_id)
        if status:
            conds.append(BloodRequest.status == status)
        rows = await self._s.scalars(
            select(BloodRequest)
            .where(*conds)
            .order_by(BloodRequest.created_at.desc(), BloodRequest.id.desc())
            .limit(limit)
            .offset(offset)
        )
        total = await self._s.scalar(select(func.count()).select_from(BloodRequest).where(*conds))
        return list(rows), int(total or 0)

    async def add_allocation(self, allocation: RequestAllocation) -> None:
        await self._add(allocation)

    async def allocated_bag_ids(self, request_id: UUID) -> list[UUID]:
        rows = await self._s.scalars(
            select(RequestAllocation.bag_id).where(RequestAllocation.request_id == request_id)
        )
        return list(rows)


class SqlOutboxRepository(_Repo):
    async def add(self, event: OutboxEvent) -> None:
        await self._add(event)

    async def list_after(self, cursor: int, *, limit: int) -> list[OutboxEvent]:
        rows = await self._s.scalars(
            select(OutboxEvent).where(OutboxEvent.id > cursor).order_by(OutboxEvent.id).limit(limit)
        )
        return list(rows)

    async def claim_unpublished(self, *, limit: int) -> list[OutboxEvent]:
        """Lock a batch for this relay; concurrent relays skip locked rows (no double publish)."""
        rows = await self._s.scalars(
            select(OutboxEvent)
            .where(OutboxEvent.published_at.is_(None))
            .order_by(OutboxEvent.id)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        return list(rows)


_ON_HAND = ("available", "received")


class SqlStatsRepository(_Repo):
    async def request_status_counts(
        self, *, hospital_id: UUID | None, target_facility_id: UUID | None
    ) -> dict[str, int]:
        q = select(BloodRequest.status, func.count()).group_by(BloodRequest.status)
        if hospital_id is not None:
            q = q.where(BloodRequest.hospital_id == hospital_id)
        if target_facility_id is not None:
            q = q.where(BloodRequest.target_facility_id == target_facility_id)
        return {status: int(n) for status, n in (await self._s.execute(q)).all()}

    async def requests_since(
        self, *, facility_id: UUID | None, since: datetime
    ) -> list[BloodRequest]:
        q = select(BloodRequest).where(BloodRequest.created_at >= since)
        if facility_id is not None:
            q = q.where(
                (BloodRequest.hospital_id == facility_id)
                | (BloodRequest.target_facility_id == facility_id)
            )
        return list(await self._s.scalars(q.order_by(BloodRequest.created_at)))

    async def donation_times_since(
        self, *, facility_id: UUID | None, since: datetime
    ) -> list[datetime]:
        q = select(Donation.collected_at).where(Donation.collected_at >= since)
        if facility_id is not None:
            q = q.where(Donation.collection_facility_id == facility_id)
        return list(await self._s.scalars(q))

    async def bag_events_since(
        self, *, facility_id: UUID | None, since: datetime, event_types: tuple[str, ...]
    ) -> list[BagEvent]:
        q = select(BagEvent).where(
            BagEvent.occurred_at >= since, BagEvent.event_type.in_(event_types)
        )
        if facility_id is not None:
            q = q.where(
                (BagEvent.from_facility_id == facility_id)
                | (BagEvent.to_facility_id == facility_id)
            )
        return list(await self._s.scalars(q.order_by(BagEvent.occurred_at)))

    async def on_hand_expiries(self, facility_id: UUID) -> list[datetime]:
        q = select(BloodBag.expires_at).where(
            BloodBag.current_facility_id == facility_id, BloodBag.status.in_(_ON_HAND)
        )
        return list(await self._s.scalars(q))

    async def bag_status_counts(self) -> dict[str, int]:
        q = select(BloodBag.status, func.count()).group_by(BloodBag.status)
        return {status: int(n) for status, n in (await self._s.execute(q)).all()}

    async def user_counts(self) -> list[tuple[str, str, int]]:
        q = select(User.role, User.status, func.count()).group_by(User.role, User.status)
        return [(role, status, int(n)) for role, status, n in (await self._s.execute(q)).all()]

    async def active_facilities(self) -> list[Facility]:
        q = select(Facility).where(Facility.status == "active").order_by(Facility.name)
        return list(await self._s.scalars(q))

    async def recent_outbox(self, *, limit: int) -> list[OutboxEvent]:
        q = select(OutboxEvent).order_by(OutboxEvent.id.desc()).limit(limit)
        return list(await self._s.scalars(q))

    async def recent_audit(self, *, limit: int) -> list[AuditLog]:
        q = select(AuditLog).order_by(AuditLog.created_at.desc(), AuditLog.id.desc()).limit(limit)
        return list(await self._s.scalars(q))

    async def audit_action_counts_since(self, since: datetime) -> dict[str, int]:
        q = (
            select(AuditLog.action, func.count())
            .where(AuditLog.created_at >= since)
            .group_by(AuditLog.action)
        )
        return {action: int(n) for action, n in (await self._s.execute(q)).all()}


class SqlTelemetryRepository(_Repo):
    async def add_device(self, device: TelemetryDevice) -> None:
        await self._add(device)

    async def device_for_bag(self, bag_id: UUID, *, lock: bool = False) -> TelemetryDevice | None:
        q = select(TelemetryDevice).where(TelemetryDevice.bag_id == bag_id)
        if lock:
            q = q.with_for_update()
        return await self._s.scalar(q)

    async def devices_at(self, facility_id: UUID | None) -> list[tuple[TelemetryDevice, BloodBag]]:
        q = select(TelemetryDevice, BloodBag).join(BloodBag, BloodBag.id == TelemetryDevice.bag_id)
        if facility_id is not None:
            q = q.where(BloodBag.current_facility_id == facility_id)
        q = q.where(BloodBag.status != "discarded").order_by(BloodBag.public_id)
        return [(d, b) for d, b in (await self._s.execute(q)).all()]

    async def running_devices(self, *, limit: int) -> list[TelemetryDevice]:
        """Devices the background simulator should tick (concurrent tickers skip locked)."""
        q = (
            select(TelemetryDevice)
            .where(TelemetryDevice.sim_running.is_(True), TelemetryDevice.battery_pct > 0)
            .order_by(TelemetryDevice.last_seen_at.nulls_first(), TelemetryDevice.id)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        return list(await self._s.scalars(q))

    async def add_reading(self, reading: TelemetryReading) -> None:
        await self._add(reading)

    async def readings(self, device_pk: UUID, *, limit: int) -> list[TelemetryReading]:
        q = (
            select(TelemetryReading)
            .where(TelemetryReading.device_pk == device_pk)
            .order_by(TelemetryReading.seq.desc())
            .limit(limit)
        )
        return list(reversed(list(await self._s.scalars(q))))

    async def reading_range(self, device_pk: UUID) -> tuple[float | None, float | None]:
        q = select(
            func.min(TelemetryReading.temperature_c), func.max(TelemetryReading.temperature_c)
        ).where(TelemetryReading.device_pk == device_pk)
        lo, hi = (await self._s.execute(q)).one()
        return lo, hi


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
        self.donations = SqlDonationRepository(session)
        self.bags = SqlBagRepository(session)
        self.requests = SqlRequestRepository(session)
        self.outbox = SqlOutboxRepository(session)
        self.stats = SqlStatsRepository(session)
        self.telemetry = SqlTelemetryRepository(session)

    async def commit(self) -> None:
        try:
            await self._session.commit()
        except IntegrityError as exc:
            await self._session.rollback()
            raise _domain_error(exc) from exc
        except StaleDataError as exc:
            await self._session.rollback()
            raise ConflictError(_CONCURRENT_CHANGE) from exc

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
