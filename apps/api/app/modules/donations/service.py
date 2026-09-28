"""Donation desk (blood bank) and the donor's own donation history."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.core.clock import Clock
from app.core.errors import AppError, NotFoundError
from app.core.ids import uuid7
from app.core.rbac import AuthContext
from app.modules.audit.service import record
from app.modules.bags.domain import (
    COMPONENT_SPECS,
    BagEventType,
    BagStatus,
    Component,
    expiry_for,
    new_bag_public_id,
)
from app.modules.bags.models import BloodBag
from app.modules.bags.service import BagService, append_event, require_facility
from app.modules.donations.models import Donation
from app.modules.donations.schemas import (
    DonationOut,
    DonorLookupResult,
    MyDonation,
    MyDonations,
    RecordDonationRequest,
)
from app.modules.outbox.service import emit
from app.persistence.repositories import UnitOfWork

BACKDATE_LIMIT = timedelta(hours=48)


class DonorNotEligibleError(AppError):
    status, code, title = 409, "donor_not_eligible", "Donor is not eligible to donate yet"


class InvalidCollectionTimeError(AppError):
    status, code, title = 422, "invalid_collection_time", "Invalid collection time"


def mask_mobile(mobile: str) -> str:
    return f"{mobile[:3]}******{mobile[-4:]}" if len(mobile) >= 7 else "******"


class DonationService:
    def __init__(self, uow: UnitOfWork, clock: Clock, *, interval_days: int) -> None:
        self._uow = uow
        self._clock = clock
        self._interval = timedelta(days=interval_days)
        self._interval_days = interval_days
        self._bags = BagService(uow, clock)

    def _eligible_from(self, last: datetime | None, now: datetime) -> datetime | None:
        if last is None or last + self._interval <= now:
            return None
        return last + self._interval

    async def lookup(self, ctx: AuthContext, mobile: str) -> DonorLookupResult:
        require_facility(ctx)
        user = await self._uow.users.get_by_mobile(mobile)
        donor = await self._uow.donors.get_by_user_id(user.id) if user else None
        if user is None or donor is None or user.status != "active":
            raise NotFoundError("No verified donor with this mobile number")
        last = await self._uow.donations.last_collected_at(donor.id)
        eligible_from = self._eligible_from(last, self._clock.now())
        await record(
            self._uow,
            self._clock,
            action="donor.looked_up",
            resource="donor",
            resource_id=donor.id,
            actor_id=ctx.user_id,
            meta={"facility_id": str(ctx.facility_id)},
        )
        await self._uow.commit()
        return DonorLookupResult(
            donor_id=donor.id,
            full_name=user.full_name,
            mobile_masked=mask_mobile(user.mobile),
            blood_group=donor.blood_group,
            blood_group_status="confirmed" if donor.blood_group_confirmed_at else "self_declared",
            last_donation_at=last,
            eligible_from=eligible_from,
            eligible_now=eligible_from is None,
        )

    async def _donation_out(self, donation: Donation) -> DonationOut:
        donor = await self._uow.donors.get(donation.donor_id)
        user = await self._uow.users.get(donor.user_id) if donor else None
        bags = await self._uow.bags.list_for_donation(donation.id)
        return DonationOut(
            id=donation.id,
            donor_id=donation.donor_id,
            donor_name=user.full_name if user else "Unknown donor",
            blood_group=donation.blood_group,
            volume_ml=donation.volume_ml,
            collected_at=donation.collected_at,
            status=donation.status,
            notes=donation.notes,
            bags=[await self._bags.bag_out(b) for b in bags],
        )

    async def record_donation(self, ctx: AuthContext, req: RecordDonationRequest) -> DonationOut:
        facility_id = require_facility(ctx)
        now = self._clock.now()
        collected_at = req.collected_at or now
        if collected_at.tzinfo is None:
            raise InvalidCollectionTimeError("collected_at must include a timezone")
        collected_at = collected_at.astimezone(UTC)
        if collected_at > now + timedelta(minutes=5) or collected_at < now - BACKDATE_LIMIT:
            raise InvalidCollectionTimeError(
                "Collection time can't be in the future or more than 48 hours ago."
            )
        donor = await self._uow.donors.get(req.donor_id)
        user = await self._uow.users.get(donor.user_id) if donor else None
        if donor is None or user is None or user.status != "active":
            raise NotFoundError("Donor not found")
        last = await self._uow.donations.last_collected_at(donor.id)
        eligible_from = self._eligible_from(last, collected_at)
        if eligible_from is not None:
            raise DonorNotEligibleError(
                f"The minimum interval between donations is {self._interval_days} days; "
                f"this donor is eligible from {eligible_from.date().isoformat()}."
            )

        donation = Donation(
            id=uuid7(),
            donor_id=donor.id,
            collection_facility_id=facility_id,
            blood_group=req.blood_group,
            volume_ml=req.volume_ml,
            collected_at=collected_at,
            status="collected",
            recorded_by=ctx.user_id,
            notes=req.notes,
            created_at=now,
        )
        await self._uow.donations.add(donation)
        for component in req.components:
            spec = COMPONENT_SPECS[component]
            whole = component is Component.WHOLE_BLOOD
            bag = BloodBag(
                id=uuid7(),
                public_id=new_bag_public_id(),
                donation_id=donation.id,
                blood_group=req.blood_group,
                component=component.value,
                volume_ml=req.volume_ml if whole else spec.default_volume_ml,
                collected_at=collected_at,
                expires_at=expiry_for(component, collected_at),
                status=BagStatus.AVAILABLE.value,
                current_facility_id=facility_id,
                created_at=now,
                updated_at=now,
            )
            await self._uow.bags.add(bag)
            await append_event(
                self._uow,
                bag,
                BagEventType.COLLECTED,
                at=collected_at,
                actor_id=ctx.user_id,
                from_facility_id=None,
                to_facility_id=facility_id,
                meta={"component": component.value},
            )

        # The blood bank's typing is authoritative over the self-declared group.
        group_changed = donor.blood_group != req.blood_group
        donor.blood_group = req.blood_group
        donor.blood_group_confirmed_at = donor.blood_group_confirmed_at or now
        donor.updated_at = now

        await emit(
            self._uow,
            self._clock,
            topic="inventory.updated",
            aggregate_type="facility",
            aggregate_id=str(facility_id),
            audience=[facility_id],
            payload={"reason": "donation_recorded", "bags_added": len(req.components)},
        )
        await record(
            self._uow,
            self._clock,
            action="donation.recorded",
            resource="donation",
            resource_id=donation.id,
            actor_id=ctx.user_id,
            meta={"bags": len(req.components), "blood_group_corrected": group_changed},
        )
        await self._uow.commit()
        return await self._donation_out(donation)

    async def list_for_facility(
        self, ctx: AuthContext, *, limit: int, offset: int
    ) -> tuple[list[DonationOut], int]:
        facility_id = require_facility(ctx)
        rows, total = await self._uow.donations.list_for_facility(
            facility_id, limit=limit, offset=offset
        )
        return [await self._donation_out(d) for d in rows], total

    async def my_donations(self, ctx: AuthContext) -> MyDonations:
        donor = await self._uow.donors.get_by_user_id(ctx.user_id)
        if donor is None:
            raise NotFoundError("Donor profile not found")
        donations = await self._uow.donations.list_for_donor(donor.id)
        out: list[MyDonation] = []
        for d in donations:
            facility = await self._uow.facilities.get(d.collection_facility_id)
            bags = await self._uow.bags.list_for_donation(d.id)
            statuses = [b.status for b in bags]
            out.append(
                MyDonation(
                    id=d.id,
                    collected_at=d.collected_at,
                    facility_name=facility.name if facility else "Blood bank",
                    facility_city=facility.city if facility else "",
                    volume_ml=d.volume_ml,
                    components=[COMPONENT_SPECS[Component(b.component)].label for b in bags],
                    bags_total=len(bags),
                    bags_in_stock=statuses.count(BagStatus.AVAILABLE.value),
                    bags_sent_to_hospitals=statuses.count(BagStatus.IN_TRANSIT.value)
                    + statuses.count(BagStatus.RECEIVED.value),
                    bags_discarded=statuses.count(BagStatus.DISCARDED.value),
                )
            )
        last = max((d.collected_at for d in donations), default=None)
        eligible_from = self._eligible_from(last, self._clock.now())
        return MyDonations(
            donations=out,
            last_donation_at=last,
            eligible_from=eligible_from,
            eligible_now=eligible_from is None,
            interval_days=self._interval_days,
        )
