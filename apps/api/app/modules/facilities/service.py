from __future__ import annotations

from datetime import timedelta
from typing import Literal
from uuid import UUID

from app.core.clock import Clock
from app.core.errors import ConflictError, NotFoundError, PermissionDeniedError
from app.core.ids import uuid7
from app.core.rbac import AuthContext, Permission
from app.core.security import hash_token, new_opaque_token
from app.modules.audit.service import record
from app.modules.facilities.models import Facility
from app.modules.facilities.schemas import (
    CreatedInvite,
    CreateFacilityRequest,
    FacilityOut,
    InviteDelivery,
    InviteOut,
)
from app.modules.identity.models import FacilityInvite
from app.persistence.repositories import UnitOfWork

INVITE_TTL = timedelta(hours=72)
DEMO_DELIVERY_NOTE = (
    "Demo delivery: no email is sent. Share this one-time link with the invitee. "
    "It is shown only once."
)


def facility_out(f: Facility) -> FacilityOut:
    return FacilityOut(
        id=f.id,
        type=f.type,
        name=f.name,
        registration_number=f.registration_number,
        address=f.address,
        city=f.city,
        state=f.state,
        pin_code=f.pin_code,
        provider_kind=f.provider_kind,
        is_simulated=f.is_simulated,
        status=f.status,
        created_at=f.created_at,
    )


class FacilityService:
    def __init__(self, uow: UnitOfWork, clock: Clock) -> None:
        self._uow = uow
        self._clock = clock

    async def create(self, ctx: AuthContext, req: CreateFacilityRequest) -> FacilityOut:
        if req.registration_number and await self._uow.facilities.get_by_registration_number(
            req.registration_number
        ):
            raise ConflictError("A facility with this registration number already exists")
        now = self._clock.now()
        facility = Facility(
            id=uuid7(),
            type=req.type,
            name=req.name,
            registration_number=req.registration_number,
            address=req.address,
            city=req.city,
            state=req.state,
            pin_code=req.pin_code,
            provider_kind="internal",
            is_simulated=False,
            status="active",
            created_at=now,
            updated_at=now,
        )
        await self._uow.facilities.add(facility)
        await record(
            self._uow,
            self._clock,
            action="facility.created",
            resource="facility",
            resource_id=facility.id,
            actor_id=ctx.user_id,
            meta={"type": facility.type},
        )
        await self._uow.commit()
        return facility_out(facility)

    async def list_page(self, *, limit: int, offset: int) -> tuple[list[FacilityOut], int]:
        rows, total = await self._uow.facilities.list_page(limit=limit, offset=offset)
        return [facility_out(f) for f in rows], total

    async def get_own(self, ctx: AuthContext) -> FacilityOut:
        # Scope: facility users only ever see the facility they belong to.
        if ctx.facility_id is None:
            raise NotFoundError("You are not linked to a facility")
        facility = await self._uow.facilities.get(ctx.facility_id)
        if facility is None:
            raise NotFoundError("Facility not found")
        return facility_out(facility)

    async def create_invite(self, ctx: AuthContext, facility_id: UUID, email: str) -> CreatedInvite:
        if not ctx.has(Permission.FACILITY_MANAGE):
            raise PermissionDeniedError()
        facility = await self._uow.facilities.get(facility_id)
        if facility is None:
            raise NotFoundError("Facility not found")
        if await self._uow.users.get_by_email(email):
            raise ConflictError("An account with this email already exists")
        now = self._clock.now()
        token = new_opaque_token()
        invite = FacilityInvite(
            id=uuid7(),
            facility_id=facility.id,
            email=email,
            role=facility.type,  # HOSPITAL or BLOOD_BANK, from the facility itself
            token_hash=hash_token(token),
            invited_by=ctx.user_id,
            expires_at=now + INVITE_TTL,
            accepted_at=None,
            accepted_user_id=None,
            revoked_at=None,
            created_at=now,
        )
        await self._uow.invites.add(invite)
        await record(
            self._uow,
            self._clock,
            action="facility.invite_created",
            resource="facility_invite",
            resource_id=invite.id,
            actor_id=ctx.user_id,
            meta={"facility_id": str(facility.id), "role": invite.role},
        )
        await self._uow.commit()
        base = self._invite_out(invite)
        return CreatedInvite(
            **base.model_dump(),
            accept_path=f"/invite/{token}",
            delivery=InviteDelivery(mode="demo_link", note=DEMO_DELIVERY_NOTE),
        )

    async def list_invites(self, facility_id: UUID) -> list[InviteOut]:
        if await self._uow.facilities.get(facility_id) is None:
            raise NotFoundError("Facility not found")
        return [self._invite_out(i) for i in await self._uow.invites.list_for_facility(facility_id)]

    def _invite_out(self, invite: FacilityInvite) -> InviteOut:
        now = self._clock.now()
        status: Literal["pending", "accepted", "expired", "revoked"]
        if invite.accepted_at is not None:
            status = "accepted"
        elif invite.revoked_at is not None:
            status = "revoked"
        elif invite.expires_at <= now:
            status = "expired"
        else:
            status = "pending"
        return InviteOut(
            id=invite.id,
            facility_id=invite.facility_id,
            email=invite.email,
            role=invite.role,
            status=status,
            expires_at=invite.expires_at,
            created_at=invite.created_at,
        )
