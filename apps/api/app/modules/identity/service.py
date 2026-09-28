"""Authentication service: registration, phone verification, sessions.

Rules enforced here (not in routers):
- passwords are Argon2id-hashed; unknown-account logins spend equal work;
- verification attempts and failed logins are counted and committed *before* the error;
- refresh tokens rotate on every use; replaying a rotated token revokes the whole family;
- an access token is only honoured while its server-side session is active.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from app.core.clock import Clock
from app.core.config import Settings
from app.core.ids import uuid7
from app.core.rbac import FACILITY_ROLES, AuthContext, Role
from app.core.security import (
    AccessTokenCodec,
    PasswordHasher,
    TokenError,
    hash_token,
    new_opaque_token,
)
from app.core.validation import validate_new_password
from app.modules.audit.service import record
from app.modules.donors.models import Donor
from app.modules.facilities.models import FacilityMembership
from app.modules.identity.errors import (
    AccountDisabledError,
    AccountLockedError,
    ChallengeExpiredError,
    ChallengeNotFoundError,
    EmailTakenError,
    InvalidCodeError,
    InvalidCredentialsError,
    InviteInvalidError,
    MobileTakenError,
    SessionInvalidError,
    TooManyAttemptsError,
    VerificationRequiredError,
    WeakPasswordError,
)
from app.modules.identity.models import AuthSession, FacilityInvite, User, VerificationChallenge
from app.modules.identity.schemas import AcceptInviteRequest, LoginRequest, RegisterDonorRequest
from app.persistence.repositories import UnitOfWork
from app.providers.verification import VerificationProvider

STATUS_PENDING = "pending_verification"
STATUS_ACTIVE = "active"
STATUS_DISABLED = "disabled"


@dataclass(frozen=True)
class ClientInfo:
    ip: str | None = None
    user_agent: str | None = None


@dataclass(frozen=True)
class IssuedSession:
    user: User
    session: AuthSession
    access_token: str
    refresh_token: str
    csrf_token: str


@dataclass(frozen=True)
class ChallengeInfo:
    challenge: VerificationChallenge
    destination_hint: str


class AuthService:
    def __init__(
        self,
        uow: UnitOfWork,
        *,
        settings: Settings,
        clock: Clock,
        hasher: PasswordHasher,
        tokens: AccessTokenCodec,
        verification: VerificationProvider,
    ) -> None:
        self._uow = uow
        self._settings = settings
        self._clock = clock
        self._hasher = hasher
        self._tokens = tokens
        self._verification = verification

    # ------------------------------------------------------------------ registration
    async def register_donor(
        self, req: RegisterDonorRequest, client: ClientInfo
    ) -> tuple[User, ChallengeInfo]:
        if await self._uow.users.get_by_email(req.email):
            raise EmailTakenError()
        if await self._uow.users.get_by_mobile(req.mobile):
            raise MobileTakenError()

        now = self._clock.now()
        user = User(
            id=uuid7(),
            email=req.email,
            mobile=req.mobile,
            full_name=req.full_name,
            password_hash=self._hasher.hash(req.password),
            role=Role.DONOR.value,
            status=STATUS_PENDING,
            is_demo=False,
            verified_at=None,
            failed_login_count=0,
            locked_until=None,
            last_login_at=None,
            created_at=now,
            updated_at=now,
        )
        await self._uow.users.add(user)
        await self._uow.donors.add(
            Donor(
                id=uuid7(),
                user_id=user.id,
                blood_group=req.blood_group,
                address=req.address,
                city=req.city,
                state=req.state,
                pin_code=req.pin_code,
                created_at=now,
                updated_at=now,
            )
        )
        info = await self._new_challenge(user, now)
        await record(
            self._uow,
            self._clock,
            action="auth.register",
            resource="user",
            resource_id=user.id,
            actor_id=user.id,
            ip=client.ip,
            meta={"role": user.role, "verification_provider": self._verification.name},
        )
        await self._uow.commit()
        return user, info

    async def restart_verification(self, req: LoginRequest) -> tuple[User, ChallengeInfo]:
        """Issue a fresh challenge for a pending account (password required: no enumeration)."""
        user = await self._check_password(req.email, req.password, count_failure=False)
        if user.status != STATUS_PENDING:
            raise InvalidCredentialsError()
        info = await self._new_challenge(user, self._clock.now())
        await self._uow.commit()
        return user, info

    async def _new_challenge(self, user: User, now: datetime) -> ChallengeInfo:
        started = await self._verification.start(mobile=user.mobile)
        challenge = VerificationChallenge(
            id=uuid7(),
            user_id=user.id,
            purpose="registration",
            provider=self._verification.name,
            code_hash=started.code_hash,
            attempts=0,
            max_attempts=self._settings.verification_max_attempts,
            expires_at=now + timedelta(seconds=self._settings.verification_ttl_seconds),
            consumed_at=None,
            created_at=now,
        )
        await self._uow.challenges.add(challenge)
        return ChallengeInfo(challenge=challenge, destination_hint=started.destination_hint)

    async def verify(self, challenge_id: UUID, code: str, client: ClientInfo) -> IssuedSession:
        now = self._clock.now()
        challenge = await self._uow.challenges.get(challenge_id)
        if challenge is None or challenge.consumed_at is not None:
            raise ChallengeNotFoundError()
        if challenge.expires_at <= now:
            raise ChallengeExpiredError()
        if challenge.attempts >= challenge.max_attempts:
            raise TooManyAttemptsError()
        user = await self._uow.users.get(challenge.user_id)
        if user is None:
            raise ChallengeNotFoundError()

        if not self._verification.check(
            mobile=user.mobile, code_hash=challenge.code_hash, code=code
        ):
            challenge.attempts += 1
            remaining = challenge.max_attempts - challenge.attempts
            await self._uow.commit()  # persist the failed attempt before raising
            if remaining <= 0:
                raise TooManyAttemptsError()
            plural = "s" if remaining != 1 else ""
            raise InvalidCodeError(f"Incorrect code. {remaining} attempt{plural} remaining.")

        challenge.consumed_at = now
        if user.status == STATUS_PENDING:
            user.status = STATUS_ACTIVE
            user.verified_at = now
            user.updated_at = now
        await record(
            self._uow,
            self._clock,
            action="auth.verify",
            resource="user",
            resource_id=user.id,
            actor_id=user.id,
            ip=client.ip,
            meta={"provider": challenge.provider, "demo": self._verification.is_demo},
        )
        issued = await self._issue(user, client, family_id=None)
        await self._uow.commit()
        return issued

    # ------------------------------------------------------------------ facility invites
    async def get_open_invite(self, token: str) -> FacilityInvite:
        invite = await self._uow.invites.get_by_token_hash(hash_token(token))
        now = self._clock.now()
        if (
            invite is None
            or invite.accepted_at is not None
            or invite.revoked_at is not None
            or invite.expires_at <= now
        ):
            raise InviteInvalidError()
        return invite

    async def accept_invite(self, req: AcceptInviteRequest, client: ClientInfo) -> IssuedSession:
        invite = await self.get_open_invite(req.token)
        facility = await self._uow.facilities.get(invite.facility_id)
        if facility is None or facility.status != "active":
            raise InviteInvalidError()
        if await self._uow.users.get_by_email(invite.email):
            raise EmailTakenError()
        if await self._uow.users.get_by_mobile(req.mobile):
            raise MobileTakenError()
        try:  # the email is only known from the invite, so this rule is checked here
            validate_new_password(req.password, email=invite.email)
        except ValueError as exc:
            raise WeakPasswordError(
                "Request is invalid",
                errors=[{"loc": ["body", "password"], "msg": str(exc), "type": "value_error"}],
            ) from exc
        now = self._clock.now()
        user = User(
            id=uuid7(),
            email=invite.email,
            mobile=req.mobile,
            full_name=req.full_name,
            password_hash=self._hasher.hash(req.password),
            role=invite.role,
            # Possession of the single-use invite link proves control of the invited address.
            status=STATUS_ACTIVE,
            is_demo=False,
            verified_at=now,
            failed_login_count=0,
            locked_until=None,
            last_login_at=now,
            created_at=now,
            updated_at=now,
        )
        await self._uow.users.add(user)
        await self._uow.facilities.add_membership(
            FacilityMembership(user_id=user.id, facility_id=facility.id, created_at=now)
        )
        invite.accepted_at = now
        invite.accepted_user_id = user.id
        await record(
            self._uow,
            self._clock,
            action="auth.invite_accepted",
            resource="facility_invite",
            resource_id=invite.id,
            actor_id=user.id,
            ip=client.ip,
            meta={"facility_id": str(facility.id), "role": invite.role},
        )
        issued = await self._issue(user, client, family_id=None)
        await self._uow.commit()
        return issued

    # ------------------------------------------------------------------ sessions
    async def login(self, req: LoginRequest, client: ClientInfo) -> IssuedSession:
        user = await self._check_password(req.email, req.password, count_failure=True, ip=client.ip)
        if user.status == STATUS_DISABLED:
            raise AccountDisabledError()
        if user.status == STATUS_PENDING:
            raise VerificationRequiredError()
        now = self._clock.now()
        user.failed_login_count = 0
        user.locked_until = None
        user.last_login_at = now
        if self._hasher.needs_rehash(user.password_hash):
            user.password_hash = self._hasher.hash(req.password)
        await record(
            self._uow,
            self._clock,
            action="auth.login",
            resource="user",
            resource_id=user.id,
            actor_id=user.id,
            ip=client.ip,
        )
        issued = await self._issue(user, client, family_id=None)
        await self._uow.commit()
        return issued

    async def _check_password(
        self, email: str, password: str, *, count_failure: bool, ip: str | None = None
    ) -> User:
        now = self._clock.now()
        user = await self._uow.users.get_by_email(email)
        if user is None:
            self._hasher.verify_dummy(password)
            raise InvalidCredentialsError()
        if user.locked_until is not None and user.locked_until > now:
            raise AccountLockedError("Too many failed sign-in attempts. Try again later.")
        if not self._hasher.verify(password, user.password_hash):
            if count_failure:
                user.failed_login_count += 1
                if user.failed_login_count >= self._settings.login_max_failures:
                    user.failed_login_count = 0
                    user.locked_until = now + timedelta(
                        seconds=self._settings.login_lockout_seconds
                    )
                    await record(
                        self._uow,
                        self._clock,
                        action="auth.lockout",
                        resource="user",
                        resource_id=user.id,
                        actor_type="system",
                        ip=ip,
                    )
                await self._uow.commit()
            raise InvalidCredentialsError()
        return user

    async def refresh(self, refresh_token: str, client: ClientInfo) -> IssuedSession:
        now = self._clock.now()
        current = await self._uow.sessions.get_by_refresh_hash(hash_token(refresh_token))
        if current is None:
            raise SessionInvalidError()
        if current.revoked_at is not None:
            if current.revoked_reason == "rotated":
                # A rotated token was replayed: assume theft, end every session in the family.
                await self._revoke_family(current.family_id, now, "reuse_detected")
                await record(
                    self._uow,
                    self._clock,
                    action="auth.refresh_reuse_detected",
                    resource="session",
                    resource_id=current.family_id,
                    actor_id=current.user_id,
                    actor_type="system",
                    ip=client.ip,
                )
                await self._uow.commit()
            raise SessionInvalidError()
        if current.expires_at <= now:
            raise SessionInvalidError()
        user = await self._uow.users.get(current.user_id)
        if user is None or user.status != STATUS_ACTIVE:
            raise SessionInvalidError()

        issued = await self._issue(user, client, family_id=current.family_id)
        current.revoked_at = now
        current.revoked_reason = "rotated"
        current.replaced_by = issued.session.id
        await self._uow.commit()
        return issued

    async def logout(self, session_id: UUID) -> None:
        session = await self._uow.sessions.get(session_id)
        if session is not None and session.revoked_at is None:
            session.revoked_at = self._clock.now()
            session.revoked_reason = "logout"
            await record(
                self._uow,
                self._clock,
                action="auth.logout",
                resource="session",
                resource_id=session.id,
                actor_id=session.user_id,
            )
            await self._uow.commit()

    async def _revoke_family(self, family_id: UUID, now: datetime, reason: str) -> None:
        for s in await self._uow.sessions.list_family(family_id):
            if s.revoked_at is None:
                s.revoked_at = now
                s.revoked_reason = reason

    async def _issue(
        self, user: User, client: ClientInfo, *, family_id: UUID | None
    ) -> IssuedSession:
        now = self._clock.now()
        refresh_token = new_opaque_token()
        session = AuthSession(
            id=uuid7(),
            user_id=user.id,
            family_id=family_id or uuid7(),
            refresh_token_hash=hash_token(refresh_token),
            expires_at=now + timedelta(seconds=self._settings.refresh_token_ttl_seconds),
            revoked_at=None,
            revoked_reason=None,
            replaced_by=None,
            user_agent=(client.user_agent or "")[:255] or None,
            ip=client.ip,
            created_at=now,
        )
        await self._uow.sessions.add(session)
        access = self._tokens.encode(
            user_id=user.id, session_id=session.id, role=user.role, now=now
        )
        return IssuedSession(
            user=user,
            session=session,
            access_token=access,
            refresh_token=refresh_token,
            csrf_token=new_opaque_token(),
        )

    # ------------------------------------------------------------------ request auth
    async def authenticate(self, access_token: str) -> AuthContext:
        now = self._clock.now()
        try:
            claims = self._tokens.decode(access_token, now=now)
        except TokenError as exc:
            raise SessionInvalidError() from exc
        session = await self._uow.sessions.get(claims.session_id)
        if (
            session is None
            or session.user_id != claims.user_id
            or session.revoked_at is not None
            or session.expires_at <= now
        ):
            raise SessionInvalidError()
        user = await self._uow.users.get(claims.user_id)
        if user is None or user.status != STATUS_ACTIVE:
            raise SessionInvalidError()
        role = Role(user.role)  # the database, not the token, is authoritative for the role
        facility_id: UUID | None = None
        if role in FACILITY_ROLES:
            membership = await self._uow.facilities.get_membership(user.id)
            facility_id = membership.facility_id if membership else None
        return AuthContext(
            user_id=user.id, role=role, session_id=session.id, facility_id=facility_id
        )
