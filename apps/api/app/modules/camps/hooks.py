"""Donation-desk integration for camps (imported by the donations service; no cycles)."""

from __future__ import annotations

from uuid import UUID

from app.core.clock import Clock
from app.core.errors import NotFoundError
from app.core.rbac import AuthContext
from app.modules.audit.service import record
from app.modules.camps.errors import InvalidCampTransitionError, InvalidRegistrationStateError
from app.modules.camps.models import CampRegistration
from app.persistence.repositories import UnitOfWork


async def check_camp_donation(
    uow: UnitOfWork, ctx: AuthContext, registration_id: UUID, donor_id: UUID
) -> CampRegistration:
    """Validate BEFORE the donation is written: the desk still applies every normal control."""
    reg = await uow.camps.get_registration(registration_id)
    camp = await uow.camps.get(reg.camp_id, lock=True) if reg else None
    if reg is None or camp is None or camp.organizer_facility_id != ctx.facility_id:
        raise NotFoundError("Camp registration not found")
    if camp.status != "ongoing":
        raise InvalidCampTransitionError("Camp donations are recorded while the camp is ongoing.")
    if reg.donor_id != donor_id:
        raise InvalidRegistrationStateError("This registration belongs to a different donor.")
    if reg.status != "attended":
        raise InvalidRegistrationStateError("Confirm the donor's attendance first.")
    if reg.donation_id is not None:
        raise InvalidRegistrationStateError("A donation is already linked to this registration.")
    return reg


async def link_camp_donation(
    uow: UnitOfWork, clock: Clock, ctx: AuthContext, reg: CampRegistration, donation_id: UUID
) -> None:
    reg.donation_id = donation_id
    reg.updated_at = clock.now()
    await record(
        uow,
        clock,
        action="camp.donation_linked",
        resource="camp_registration",
        resource_id=reg.id,
        actor_id=ctx.user_id,
        meta={"camp_id": str(reg.camp_id), "donation_id": str(donation_id)},
    )
