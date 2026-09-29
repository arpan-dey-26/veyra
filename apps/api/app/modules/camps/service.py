"""Phase 8: donation camp lifecycle, donor registrations and attendance.

Prototype camp-management workflow; donor eligibility and medical screening remain governed by
authorized staff. Nothing here decides eligibility: attendance is confirmed by staff, and a
donation is still recorded only through the normal donation desk (verification, interval and
collection-time controls all apply). Registrations store no medical data.
"""

from __future__ import annotations

import secrets
from datetime import datetime
from typing import Any
from uuid import UUID

from app.core.clock import Clock
from app.core.errors import NotFoundError, PermissionDeniedError
from app.core.ids import uuid7
from app.core.rbac import AuthContext, Permission
from app.modules.audit.service import record
from app.modules.camps.errors import (
    AlreadyRegisteredError,
    CampFullError,
    CampNotEditableError,
    DonorNotVerifiedError,
    InvalidCampError,
    InvalidCampTransitionError,
    InvalidRegistrationStateError,
    RegistrationClosedError,
)
from app.modules.camps.models import Camp, CampRegistration
from app.modules.camps.schemas import (
    CampAction,
    CampCreate,
    CampDashboard,
    CampList,
    CampOut,
    CampStats,
    CampUpdate,
    MyRegistration,
    MyRegistrations,
    PublicCampList,
    PublicCampOut,
    RegistrationList,
    RegistrationOut,
)
from app.modules.donations.service import mask_mobile
from app.modules.outbox.service import emit
from app.persistence.repositories import UnitOfWork

_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"

# action → (allowed from, to, audit action)
TRANSITIONS: dict[str, tuple[frozenset[str], str, str]] = {
    "publish": (frozenset({"planned"}), "published", "camp.published"),
    "open-registration": (
        frozenset({"published"}),
        "registration_open",
        "camp.registration_opened",
    ),
    "start": (frozenset({"registration_open"}), "ongoing", "camp.started"),
    "complete": (frozenset({"ongoing"}), "completed", "camp.completed"),
    "cancel": (
        frozenset({"planned", "published", "registration_open"}),
        "cancelled",
        "camp.cancelled",
    ),
}
EDITABLE = frozenset({"planned", "published", "registration_open"})
PUBLIC_STATUSES = ("published", "registration_open", "ongoing", "completed", "cancelled")
LISTED_STATUSES = ("published", "registration_open", "ongoing")
ACTIVE_REG = frozenset({"registered", "attended"})
DONOR_CANCELLABLE_CAMP = frozenset({"published", "registration_open", "ongoing"})


def new_camp_code() -> str:
    n = secrets.randbits(40)
    chars = "".join(_CROCKFORD[(n >> (5 * i)) & 31] for i in range(8))
    return f"CMP-{chars[:4]}-{chars[4:]}"


def allowed_actions(status: str) -> list[CampAction]:
    return [a for a, (src, _, _) in TRANSITIONS.items() if status in src]  # type: ignore[misc]


def _check_window(starts_at: datetime, ends_at: datetime) -> None:
    if ends_at <= starts_at:
        raise InvalidCampError("The camp must end after it starts.")
    if (ends_at - starts_at).days > 14:
        raise InvalidCampError("A camp can last at most 14 days.")


class CampService:
    def __init__(self, uow: UnitOfWork, clock: Clock) -> None:
        self._uow = uow
        self._clock = clock
        self._names: dict[UUID, str] = {}

    # ------------------------------------------------------------------ helpers

    async def _name(self, facility_id: UUID) -> str:
        if facility_id not in self._names:
            f = await self._uow.facilities.get(facility_id)
            self._names[facility_id] = f.name if f else "Unknown facility"
        return self._names[facility_id]

    @staticmethod
    def _network(ctx: AuthContext) -> bool:
        return ctx.has(Permission.CAMP_MANAGE_ANY)

    async def _managed(self, ctx: AuthContext, camp_id: UUID, *, lock: bool = False) -> Camp:
        """A camp the caller may manage; 404 (never 403) for other facilities' camps."""
        camp = await self._uow.camps.get(camp_id, lock=lock)
        if camp is None:
            raise NotFoundError("Camp not found")
        if self._network(ctx):
            return camp
        if not ctx.has(Permission.CAMP_MANAGE_OWN) or camp.organizer_facility_id != ctx.facility_id:
            raise NotFoundError("Camp not found")
        return camp

    async def _stats(self, camp: Camp, regs: list[CampRegistration] | None = None) -> CampStats:
        regs = regs if regs is not None else await self._uow.camps.registrations(camp.id)
        by: dict[str, int] = {}
        for r in regs:
            by[r.status] = by.get(r.status, 0) + 1
        bags = 0
        donations = [r.donation_id for r in regs if r.donation_id]
        for donation_id in donations:
            bags += len(await self._uow.bags.list_for_donation(donation_id))
        return CampStats(
            registered=by.get("registered", 0),
            attended=by.get("attended", 0),
            cancelled=by.get("cancelled", 0),
            no_show=by.get("no_show", 0),
            donations_recorded=len(donations),
            bags_collected=bags,
            seats_left=max(camp.capacity - camp.registered_count, 0),
        )

    async def camp_out(self, camp: Camp) -> CampOut:
        return CampOut(
            id=camp.id,
            code=camp.code,
            title=camp.title,
            organizer_facility_id=camp.organizer_facility_id,
            organizer_name=await self._name(camp.organizer_facility_id),
            venue=camp.venue,
            city=camp.city,
            state=camp.state,
            starts_at=camp.starts_at,
            ends_at=camp.ends_at,
            capacity=camp.capacity,
            registered_count=camp.registered_count,
            status=camp.status,
            registration_open=camp.status == "registration_open",
            description=camp.description,
            contact_name=camp.contact_name,
            contact_phone=camp.contact_phone,
            contact_email=camp.contact_email,
            cancel_reason=camp.cancel_reason,
            created_at=camp.created_at,
            updated_at=camp.updated_at,
            allowed_actions=allowed_actions(camp.status),
            editable=camp.status in EDITABLE,
            stats=await self._stats(camp),
        )

    async def public_out(self, camp: Camp, my_status: str | None = None) -> PublicCampOut:
        return PublicCampOut(
            id=camp.id,
            code=camp.code,
            title=camp.title,
            organizer_name=await self._name(camp.organizer_facility_id),
            venue=camp.venue,
            city=camp.city,
            state=camp.state,
            starts_at=camp.starts_at,
            ends_at=camp.ends_at,
            capacity=camp.capacity,
            registered_count=camp.registered_count,
            seats_left=max(camp.capacity - camp.registered_count, 0),
            status=camp.status,
            registration_open=camp.status == "registration_open",
            description=camp.description,
            contact_name=camp.contact_name,
            contact_phone=camp.contact_phone,
            contact_email=camp.contact_email,
            my_registration_status=my_status,
        )

    async def _audit(
        self, ctx: AuthContext, action: str, resource: str, rid: UUID, **meta: Any
    ) -> None:
        await record(
            self._uow,
            self._clock,
            action=action,
            resource=resource,
            resource_id=rid,
            actor_id=ctx.user_id,
            meta={k: str(v) for k, v in meta.items()},
        )

    async def _emit(self, camp: Camp, reason: str) -> None:
        # Operational counts only: never donor identity.
        await emit(
            self._uow,
            self._clock,
            topic="camp.updated",
            aggregate_type="camp",
            aggregate_id=str(camp.id),
            audience=[camp.organizer_facility_id],
            payload={
                "camp_id": str(camp.id),
                "code": camp.code,
                "reference": camp.code,
                "status": camp.status,
                "reason": reason,
                "registered_count": camp.registered_count,
                "capacity": camp.capacity,
            },
        )

    async def _donor(self, ctx: AuthContext) -> UUID:
        if not ctx.has(Permission.CAMP_REGISTER_SELF):
            raise PermissionDeniedError()
        donor = await self._uow.donors.get_by_user_id(ctx.user_id)
        user = await self._uow.users.get(ctx.user_id)
        if donor is None or user is None:
            raise PermissionDeniedError()
        if user.status != "active":
            raise DonorNotVerifiedError()
        return donor.id

    # ------------------------------------------------------------------ management

    async def create(self, ctx: AuthContext, body: CampCreate) -> CampOut:
        if self._network(ctx):
            if body.organizer_facility_id is None:
                raise InvalidCampError("Choose the organizing blood bank.")
            facility_id = body.organizer_facility_id
        elif ctx.has(Permission.CAMP_MANAGE_OWN) and ctx.facility_id is not None:
            if body.organizer_facility_id not in (None, ctx.facility_id):
                raise NotFoundError("Facility not found")
            facility_id = ctx.facility_id
        else:
            raise PermissionDeniedError()
        facility = await self._uow.facilities.get(facility_id)
        if facility is None or facility.type != "BLOOD_BANK" or facility.status != "active":
            raise NotFoundError("Blood bank not found")
        _check_window(body.starts_at, body.ends_at)
        now = self._clock.now()
        camp = Camp(
            id=uuid7(),
            code=new_camp_code(),
            title=body.title,
            organizer_facility_id=facility_id,
            venue=body.venue,
            city=body.city,
            state=body.state,
            starts_at=body.starts_at,
            ends_at=body.ends_at,
            capacity=body.capacity,
            registered_count=0,
            status="planned",
            description=body.description,
            contact_name=body.contact_name,
            contact_phone=body.contact_phone,
            contact_email=body.contact_email,
            created_by=ctx.user_id,
            created_at=now,
            updated_at=now,
        )
        await self._uow.camps.add(camp)
        await self._audit(ctx, "camp.created", "camp", camp.id, code=camp.code)
        await self._emit(camp, "created")
        await self._uow.commit()
        return await self.camp_out(camp)

    async def update(self, ctx: AuthContext, camp_id: UUID, body: CampUpdate) -> CampOut:
        camp = await self._managed(ctx, camp_id, lock=True)
        if camp.status not in EDITABLE:
            raise CampNotEditableError(f"A '{camp.status}' camp can't be edited.")
        changes = body.model_dump(exclude_unset=True)
        for required in ("title", "venue", "city", "state", "starts_at", "ends_at", "capacity",
                         "contact_name"):  # fmt: skip
            if required in changes and changes[required] is None:
                raise InvalidCampError(f"{required} can't be empty.")
        starts = changes.get("starts_at", camp.starts_at)
        ends = changes.get("ends_at", camp.ends_at)
        _check_window(starts, ends)
        if "capacity" in changes and changes["capacity"] < camp.registered_count:
            raise InvalidCampError(
                f"Capacity can't be below the {camp.registered_count} current registrations."
            )
        for key, value in changes.items():
            setattr(camp, key, value)
        camp.updated_at = self._clock.now()
        await self._audit(ctx, "camp.updated", "camp", camp.id, fields=",".join(sorted(changes)))
        await self._emit(camp, "updated")
        await self._uow.commit()
        return await self.camp_out(camp)

    async def transition(
        self, ctx: AuthContext, camp_id: UUID, action: str, reason: str | None = None
    ) -> CampOut:
        if action not in TRANSITIONS:
            raise NotFoundError("Unknown camp action")
        camp = await self._managed(ctx, camp_id, lock=True)
        allowed_from, to_status, audit_action = TRANSITIONS[action]
        if camp.status not in allowed_from:
            raise InvalidCampTransitionError(f"A '{camp.status}' camp can't {action}.")
        now = self._clock.now()
        regs = await self._uow.camps.registrations(camp.id)
        if action == "complete":
            for r in regs:  # never confirmed by staff → no-show (not a medical decision)
                if r.status == "registered":
                    r.status, r.updated_at = "no_show", now
        if action == "cancel":
            camp.cancel_reason = reason
            for r in regs:
                if r.status == "registered":
                    r.status, r.cancelled_at, r.updated_at = "cancelled", now, now
            camp.registered_count = 0
        camp.status = to_status
        camp.updated_at = now
        await self._audit(ctx, audit_action, "camp", camp.id, code=camp.code)
        await self._emit(camp, action)
        await self._uow.commit()
        return await self.camp_out(camp)

    async def list_managed(self, ctx: AuthContext, status: str | None) -> CampList:
        network = self._network(ctx)
        if not network and not ctx.has(Permission.CAMP_MANAGE_OWN):
            raise PermissionDeniedError()
        if not network and ctx.facility_id is None:
            raise PermissionDeniedError()
        camps = await self._uow.camps.list_camps(
            organizer_facility_id=None if network else ctx.facility_id,
            statuses=(status,) if status else None,
            limit=200,
        )
        return CampList(
            scope="network" if network else "facility",
            camps=[await self.camp_out(c) for c in camps],
        )

    async def get_managed(self, ctx: AuthContext, camp_id: UUID) -> CampOut:
        return await self.camp_out(await self._managed(ctx, camp_id))

    async def dashboard(self, ctx: AuthContext) -> CampDashboard:
        listing = await self.list_managed(ctx, None)
        camps = listing.camps
        upcoming = [c for c in camps if c.status in ("planned", "published", "registration_open")]
        return CampDashboard(
            scope=listing.scope,
            upcoming=len(upcoming),
            active=sum(c.status == "ongoing" for c in camps),
            completed=sum(c.status == "completed" for c in camps),
            cancelled=sum(c.status == "cancelled" for c in camps),
            total_capacity=sum(c.capacity for c in camps if c.status != "cancelled"),
            total_registered=sum(c.stats.registered + c.stats.attended for c in camps),
            total_attended=sum(c.stats.attended for c in camps),
            donations_recorded=sum(c.stats.donations_recorded for c in camps),
            bags_collected=sum(c.stats.bags_collected for c in camps),
            next_camps=sorted(
                [c for c in camps if c.status in ("published", "registration_open", "ongoing")],
                key=lambda c: c.starts_at,
            )[:5],
        )

    async def registrations(self, ctx: AuthContext, camp_id: UUID) -> RegistrationList:
        camp = await self._managed(ctx, camp_id)
        out = []
        for r in await self._uow.camps.registrations(camp.id):
            donor = await self._uow.donors.get(r.donor_id)
            user = await self._uow.users.get(donor.user_id) if donor else None
            out.append(
                RegistrationOut(
                    id=r.id,
                    donor_id=r.donor_id,
                    donor_name=user.full_name if user else "Unknown donor",
                    mobile_masked=mask_mobile(user.mobile) if user else "******",
                    status=r.status,
                    registered_at=r.registered_at,
                    cancelled_at=r.cancelled_at,
                    attended_at=r.attended_at,
                    donation_id=r.donation_id,
                )
            )
        return RegistrationList(camp_id=camp.id, code=camp.code, registrations=out)

    async def confirm_attendance(
        self, ctx: AuthContext, camp_id: UUID, registration_id: UUID
    ) -> RegistrationList:
        camp = await self._managed(ctx, camp_id, lock=True)
        reg = await self._uow.camps.get_registration(registration_id)
        if reg is None or reg.camp_id != camp.id:
            raise NotFoundError("Registration not found")
        if camp.status != "ongoing":
            raise InvalidCampTransitionError("Attendance is confirmed while the camp is ongoing.")
        if reg.status != "registered":
            raise InvalidRegistrationStateError(f"A '{reg.status}' registration can't attend.")
        now = self._clock.now()
        reg.status, reg.attended_at, reg.attendance_confirmed_by = "attended", now, ctx.user_id
        reg.updated_at = now
        await self._audit(
            ctx, "camp.attendance_confirmed", "camp_registration", reg.id, camp_id=camp.id
        )
        await self._uow.commit()
        return await self.registrations(ctx, camp.id)

    # ------------------------------------------------------------------ donors / public

    async def public_list(
        self, ctx: AuthContext, *, q: str | None, city: str | None, status: str | None
    ) -> PublicCampList:
        statuses = (status,) if status in LISTED_STATUSES else LISTED_STATUSES
        camps = await self._uow.camps.list_camps(
            organizer_facility_id=None, statuses=statuses, limit=200
        )
        mine: dict[UUID, str] = {}
        if ctx.has(Permission.CAMP_REGISTER_SELF):
            donor = await self._uow.donors.get_by_user_id(ctx.user_id)
            if donor is not None:
                mine = {
                    r.camp_id: r.status
                    for r in await self._uow.camps.registrations_for_donor(donor.id)
                }
        needle = (q or "").strip().lower()
        out = []
        for c in camps:
            hay = f"{c.title} {c.venue} {c.city} {c.state} {c.code}".lower()
            if needle and needle not in hay:
                continue
            if city and c.city.lower() != city.strip().lower():
                continue
            out.append(await self.public_out(c, mine.get(c.id)))
        return PublicCampList(camps=out)

    async def public_get(self, ctx: AuthContext, camp_id: UUID) -> PublicCampOut:
        camp = await self._uow.camps.get(camp_id)
        if camp is None or camp.status not in PUBLIC_STATUSES:
            raise NotFoundError("Camp not found")
        my: str | None = None
        if ctx.has(Permission.CAMP_REGISTER_SELF):
            donor = await self._uow.donors.get_by_user_id(ctx.user_id)
            reg = await self._uow.camps.registration_for(camp.id, donor.id) if donor else None
            my = reg.status if reg else None
        return await self.public_out(camp, my)

    async def register(self, ctx: AuthContext, camp_id: UUID) -> MyRegistration:
        donor_id = await self._donor(ctx)
        camp = await self._uow.camps.get(camp_id, lock=True)
        if camp is None or camp.status not in PUBLIC_STATUSES:
            raise NotFoundError("Camp not found")
        if camp.status != "registration_open":
            raise RegistrationClosedError(f"Registration isn't open (camp is '{camp.status}').")
        now = self._clock.now()
        reg = await self._uow.camps.registration_for(camp.id, donor_id)
        if reg is not None and reg.status in ACTIVE_REG:
            raise AlreadyRegisteredError()
        if camp.registered_count >= camp.capacity:
            raise CampFullError(f"All {camp.capacity} places are taken.")
        if reg is None:
            reg = CampRegistration(
                id=uuid7(),
                camp_id=camp.id,
                donor_id=donor_id,
                status="registered",
                registered_at=now,
                updated_at=now,
            )
            await self._uow.camps.add_registration(reg)
        else:  # re-register after an earlier cancellation (one row per donor and camp)
            reg.status, reg.registered_at, reg.cancelled_at, reg.updated_at = (
                "registered",
                now,
                None,
                now,
            )
        camp.registered_count += 1
        camp.updated_at = now
        await self._audit(ctx, "camp.registration_created", "camp_registration", reg.id,
                          camp_id=camp.id)  # fmt: skip
        await self._emit(camp, "registration")
        await self._uow.commit()
        return await self._mine(reg, camp)

    async def cancel_registration(self, ctx: AuthContext, camp_id: UUID) -> MyRegistration:
        donor_id = await self._donor(ctx)
        camp = await self._uow.camps.get(camp_id, lock=True)
        reg = await self._uow.camps.registration_for(camp_id, donor_id) if camp else None
        if camp is None or reg is None:
            raise NotFoundError("Registration not found")
        if reg.status != "registered" or camp.status not in DONOR_CANCELLABLE_CAMP:
            raise InvalidRegistrationStateError(
                "Only an active registration for an upcoming or ongoing camp can be cancelled."
            )
        now = self._clock.now()
        reg.status, reg.cancelled_at, reg.updated_at = "cancelled", now, now
        camp.registered_count = max(camp.registered_count - 1, 0)
        camp.updated_at = now
        await self._audit(ctx, "camp.registration_cancelled", "camp_registration", reg.id,
                          camp_id=camp.id)  # fmt: skip
        await self._emit(camp, "registration_cancelled")
        await self._uow.commit()
        return await self._mine(reg, camp)

    async def _mine(self, reg: CampRegistration, camp: Camp) -> MyRegistration:
        return MyRegistration(
            id=reg.id,
            status=reg.status,
            registered_at=reg.registered_at,
            cancelled_at=reg.cancelled_at,
            attended_at=reg.attended_at,
            donation_recorded=reg.donation_id is not None,
            can_cancel=reg.status == "registered" and camp.status in DONOR_CANCELLABLE_CAMP,
            camp=await self.public_out(camp, reg.status),
        )

    async def my_registrations(self, ctx: AuthContext) -> MyRegistrations:
        if not ctx.has(Permission.CAMP_REGISTER_SELF):
            raise PermissionDeniedError()
        donor = await self._uow.donors.get_by_user_id(ctx.user_id)
        if donor is None:
            return MyRegistrations(registrations=[])
        out = []
        for reg in await self._uow.camps.registrations_for_donor(donor.id):
            camp = await self._uow.camps.get(reg.camp_id)
            if camp is not None:
                out.append(await self._mine(reg, camp))
        return MyRegistrations(registrations=out)
