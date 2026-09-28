from __future__ import annotations

from app.core.clock import Clock
from app.core.errors import NotFoundError
from app.core.rbac import AuthContext
from app.modules.audit.service import record
from app.modules.donors.models import Donor
from app.modules.donors.schemas import DonorProfile, UpdateDonorProfileRequest
from app.modules.identity.models import User
from app.persistence.repositories import UnitOfWork


class DonorService:
    def __init__(self, uow: UnitOfWork, clock: Clock) -> None:
        self._uow = uow
        self._clock = clock

    async def _load_own(self, ctx: AuthContext) -> tuple[User, Donor]:
        # Scope: a donor can only ever load the profile linked to their own user id.
        user = await self._uow.users.get(ctx.user_id)
        donor = await self._uow.donors.get_by_user_id(ctx.user_id)
        if user is None or donor is None:
            raise NotFoundError("Donor profile not found")
        return user, donor

    async def get_own_profile(self, ctx: AuthContext) -> DonorProfile:
        user, donor = await self._load_own(ctx)
        return _profile(user, donor)

    async def update_own_profile(
        self, ctx: AuthContext, req: UpdateDonorProfileRequest
    ) -> DonorProfile:
        user, donor = await self._load_own(ctx)
        changes = req.model_dump(exclude_none=True)
        now = self._clock.now()
        if "full_name" in changes:
            user.full_name = changes.pop("full_name")
            user.updated_at = now
        for field, value in changes.items():
            setattr(donor, field, value)
        if changes or req.full_name is not None:
            donor.updated_at = now
            await record(
                self._uow,
                self._clock,
                action="donor.profile_updated",
                resource="donor",
                resource_id=donor.id,
                actor_id=ctx.user_id,
                meta={"fields": sorted(req.model_dump(exclude_none=True))},
            )
            await self._uow.commit()
        return _profile(user, donor)


def _profile(user: User, donor: Donor) -> DonorProfile:
    return DonorProfile(
        id=donor.id,
        user_id=user.id,
        full_name=user.full_name,
        email=user.email,
        mobile=user.mobile,
        blood_group=donor.blood_group,
        blood_group_status="confirmed" if donor.blood_group_confirmed_at else "self_declared",
        address=donor.address,
        city=donor.city,
        state=donor.state,
        pin_code=donor.pin_code,
        verified_at=user.verified_at,
        created_at=donor.created_at,
        updated_at=donor.updated_at,
    )
