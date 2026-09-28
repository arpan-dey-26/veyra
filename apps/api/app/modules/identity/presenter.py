"""Build response models from ORM rows. Role-specific: only what that role may see."""

from __future__ import annotations

from app.core.rbac import FACILITY_ROLES, Role, permissions_for
from app.modules.facilities.models import Facility
from app.modules.identity.models import User
from app.modules.identity.schemas import (
    DonorSummary,
    FacilitySummary,
    MeResponse,
    UserOut,
    VerificationOut,
)
from app.modules.identity.service import ChallengeInfo
from app.persistence.repositories import UnitOfWork
from app.providers.verification import VerificationProvider


def user_out(user: User) -> UserOut:
    return UserOut(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        mobile=user.mobile,
        role=user.role,
        status=user.status,
        is_demo=user.is_demo,
        verified_at=user.verified_at,
        created_at=user.created_at,
    )


def facility_summary(facility: Facility) -> FacilitySummary:
    return FacilitySummary(
        id=facility.id,
        name=facility.name,
        type=facility.type,
        city=facility.city,
        state=facility.state,
        is_simulated=facility.is_simulated,
    )


def verification_out(info: ChallengeInfo, provider: VerificationProvider) -> VerificationOut:
    c = info.challenge
    return VerificationOut(
        challenge_id=c.id,
        mode="demo" if provider.is_demo else "otp",
        provider=provider.name,
        channel=provider.channel,
        destination_hint=info.destination_hint,
        expires_at=c.expires_at,
        attempts_remaining=max(c.max_attempts - c.attempts, 0),
        disclaimer=provider.disclaimer,
    )


async def build_me(uow: UnitOfWork, user: User) -> MeResponse:
    role = Role(user.role)
    me = MeResponse(user=user_out(user), permissions=sorted(p.value for p in permissions_for(role)))
    if role is Role.DONOR:
        donor = await uow.donors.get_by_user_id(user.id)
        if donor is not None:
            me.donor = DonorSummary(
                blood_group=donor.blood_group, city=donor.city, state=donor.state
            )
    elif role in FACILITY_ROLES:
        membership = await uow.facilities.get_membership(user.id)
        facility = await uow.facilities.get(membership.facility_id) if membership else None
        if facility is not None:
            me.facility = facility_summary(facility)
    return me
