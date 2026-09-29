"""Role-based access control: roles → permission strings, always combined with a scope check.

Permissions follow ``resource:action[:scope]``. A route declares the permission it needs
(`require(Permission.X)`); the service then applies the scope (own record / own facility).
Being authenticated never implies access by itself. This is a frozen foundation contract.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID


class Role(StrEnum):
    DONOR = "DONOR"
    HOSPITAL = "HOSPITAL"
    BLOOD_BANK = "BLOOD_BANK"
    ADMIN = "ADMIN"


FACILITY_ROLES = frozenset({Role.HOSPITAL, Role.BLOOD_BANK})


class Permission(StrEnum):
    # Donor (self-scoped)
    DONOR_PROFILE_READ_SELF = "donor_profile:read:self"
    DONOR_PROFILE_UPDATE_SELF = "donor_profile:update:self"
    DONATION_READ_SELF = "donation:read:self"
    ELIGIBILITY_READ_SELF = "eligibility:read:self"
    # Any signed-in user (self-scoped)
    NOTIFICATION_READ_SELF = "notification:read:self"
    # Facility users (scoped to their own facility)
    FACILITY_READ_OWN = "facility:read:own_facility"
    INVENTORY_READ_OWN = "inventory:read:own_facility"
    INVENTORY_UPDATE_OWN = "inventory:update:own_facility"
    FORECAST_READ_OWN = "forecast:read:own_facility"
    REPORT_READ_OWN = "report:read:own_facility"
    BLOOD_REQUEST_READ_OWN = "blood_request:read:own_facility"
    BAG_TRACE_READ = "bag_trace:read:scoped"  # bags the caller's facility holds or has held
    EVENTS_SUBSCRIBE = "events:subscribe:scoped"
    # Hospital
    BLOOD_REQUEST_CREATE = "blood_request:create"
    EMERGENCY_CREATE = "emergency:create"
    BAG_RECEIVE = "bag:receive:own_facility"
    NETWORK_AVAILABILITY_READ = "availability:read:network"  # banded, never exact stock
    # Blood bank
    BLOOD_REQUEST_RESPOND = "blood_request:respond"
    BAG_TRANSITION = "bag:transition"
    DONATION_RECORD = "donation:record:own_facility"
    # Phase 5: drive the SIMULATED telemetry of bags the facility currently holds (demo only)
    TELEMETRY_SIMULATE = "telemetry:simulate:own_facility"
    # Phase 6: operational views (own requests / own facility; admins use NETWORK_READ)
    OPERATIONS_READ = "operations:read:scoped"
    # Phase 6: bag allocation recommendations for requests targeted at the caller's bank
    ALLOCATION_RECOMMEND = "allocation:recommend:own_facility"
    TRANSPORT_READ = "transport:read"
    # Admin
    USER_READ = "user:read"
    USER_MANAGE = "user:manage"
    FACILITY_MANAGE = "facility:manage"
    AUDIT_READ = "audit:read"
    CONFIG_MANAGE = "config:manage"
    NETWORK_READ = "network:read"


_P = Permission

ROLE_PERMISSIONS: dict[Role, frozenset[Permission]] = {
    Role.DONOR: frozenset(
        {
            _P.DONOR_PROFILE_READ_SELF,
            _P.DONOR_PROFILE_UPDATE_SELF,
            _P.DONATION_READ_SELF,
            _P.ELIGIBILITY_READ_SELF,
            _P.NOTIFICATION_READ_SELF,
        }
    ),
    Role.HOSPITAL: frozenset(
        {
            _P.FACILITY_READ_OWN,
            _P.INVENTORY_READ_OWN,
            _P.INVENTORY_UPDATE_OWN,
            _P.FORECAST_READ_OWN,
            _P.REPORT_READ_OWN,
            _P.BLOOD_REQUEST_CREATE,
            _P.BLOOD_REQUEST_READ_OWN,
            _P.EMERGENCY_CREATE,
            _P.BAG_RECEIVE,
            _P.TELEMETRY_SIMULATE,
            _P.OPERATIONS_READ,
            _P.BAG_TRACE_READ,
            _P.NETWORK_AVAILABILITY_READ,
            _P.EVENTS_SUBSCRIBE,
            _P.NOTIFICATION_READ_SELF,
        }
    ),
    Role.BLOOD_BANK: frozenset(
        {
            _P.FACILITY_READ_OWN,
            _P.INVENTORY_READ_OWN,
            _P.INVENTORY_UPDATE_OWN,
            _P.FORECAST_READ_OWN,
            _P.REPORT_READ_OWN,
            _P.BLOOD_REQUEST_RESPOND,
            _P.BLOOD_REQUEST_READ_OWN,
            _P.BAG_TRANSITION,
            _P.BAG_TRACE_READ,
            _P.DONATION_RECORD,
            _P.TELEMETRY_SIMULATE,
            _P.OPERATIONS_READ,
            _P.ALLOCATION_RECOMMEND,
            _P.TRANSPORT_READ,
            _P.EVENTS_SUBSCRIBE,
            _P.NOTIFICATION_READ_SELF,
        }
    ),
    Role.ADMIN: frozenset(
        {
            _P.USER_READ,
            _P.USER_MANAGE,
            _P.FACILITY_MANAGE,
            _P.AUDIT_READ,
            _P.CONFIG_MANAGE,
            _P.NETWORK_READ,
            _P.BAG_TRACE_READ,
            _P.EVENTS_SUBSCRIBE,
            _P.NOTIFICATION_READ_SELF,
        }
    ),
}


def permissions_for(role: Role) -> frozenset[Permission]:
    return ROLE_PERMISSIONS[role]


@dataclass(frozen=True)
class AuthContext:
    """Who is calling. Built only from a verified access token + an active server session."""

    user_id: UUID
    role: Role
    session_id: UUID
    facility_id: UUID | None = None

    @property
    def permissions(self) -> frozenset[Permission]:
        return permissions_for(self.role)

    def has(self, permission: Permission) -> bool:
        return permission in self.permissions
