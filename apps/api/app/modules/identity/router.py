from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response, status
from fastapi.responses import JSONResponse

from app.core.config import Settings, get_settings
from app.core.errors import UnauthenticatedError, problem
from app.core.rbac import AuthContext
from app.core.security import hash_token
from app.modules.identity.cookies import (
    ACCESS_COOKIE,
    REFRESH_COOKIE,
    clear_session_cookies,
    set_session_cookies,
)
from app.modules.identity.deps import (
    client_info,
    csrf_protect,
    current_context,
    get_auth_service,
    get_verification_provider,
)
from app.modules.identity.errors import InviteInvalidError, SessionInvalidError
from app.modules.identity.presenter import (
    build_me,
    facility_summary,
    user_out,
    verification_out,
)
from app.modules.identity.schemas import (
    AcceptInviteRequest,
    InvitePreview,
    LoginRequest,
    MeResponse,
    RegisterDonorRequest,
    RegisterResponse,
    VerificationOut,
    VerifyRequest,
)
from app.modules.identity.service import AuthService
from app.persistence.deps import get_uow
from app.persistence.repositories import UnitOfWork
from app.providers.verification import VerificationProvider

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post(
    "/register",
    response_model=RegisterResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a donor account (then verify the mobile number)",
)
async def register(
    body: RegisterDonorRequest,
    request: Request,
    auth: AuthService = Depends(get_auth_service),
    provider: VerificationProvider = Depends(get_verification_provider),
) -> RegisterResponse:
    user, info = await auth.register_donor(body, client_info(request))
    return RegisterResponse(user=user_out(user), verification=verification_out(info, provider))


@router.post(
    "/verify/start",
    response_model=VerificationOut,
    summary="Start a new verification for a pending account (requires the password)",
)
async def verify_start(
    body: LoginRequest,
    auth: AuthService = Depends(get_auth_service),
    provider: VerificationProvider = Depends(get_verification_provider),
) -> VerificationOut:
    _, info = await auth.restart_verification(body)
    return verification_out(info, provider)


@router.post("/verify", response_model=MeResponse, summary="Verify the mobile number and sign in")
async def verify(
    body: VerifyRequest,
    request: Request,
    response: Response,
    auth: AuthService = Depends(get_auth_service),
    uow: UnitOfWork = Depends(get_uow),
    settings: Settings = Depends(get_settings),
) -> MeResponse:
    issued = await auth.verify(body.challenge_id, body.code, client_info(request))
    set_session_cookies(response, issued, settings)
    return await build_me(uow, issued.user)


@router.post("/login", response_model=MeResponse, summary="Sign in with email and password")
async def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    auth: AuthService = Depends(get_auth_service),
    uow: UnitOfWork = Depends(get_uow),
    settings: Settings = Depends(get_settings),
) -> MeResponse:
    issued = await auth.login(body, client_info(request))
    set_session_cookies(response, issued, settings)
    return await build_me(uow, issued.user)


@router.post(
    "/refresh",
    response_model=MeResponse,
    dependencies=[Depends(csrf_protect)],
    summary="Rotate the refresh token and issue a new access token",
)
async def refresh(
    request: Request,
    response: Response,
    auth: AuthService = Depends(get_auth_service),
    uow: UnitOfWork = Depends(get_uow),
    settings: Settings = Depends(get_settings),
) -> MeResponse | JSONResponse:
    token = request.cookies.get(REFRESH_COOKIE)
    if not token:
        raise UnauthenticatedError()
    try:
        issued = await auth.refresh(token, client_info(request))
    except SessionInvalidError as exc:
        # Return the problem directly so the stale cookies are cleared on this response.
        failed = problem(exc.status, exc.code, exc.title, exc.detail)
        clear_session_cookies(failed, settings)
        return failed
    set_session_cookies(response, issued, settings)
    return await build_me(uow, issued.user)


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(csrf_protect)],
    summary="End the current session",
)
async def logout(
    request: Request,
    auth: AuthService = Depends(get_auth_service),
    uow: UnitOfWork = Depends(get_uow),
    settings: Settings = Depends(get_settings),
) -> Response:
    session_id = None
    access = request.cookies.get(ACCESS_COOKIE)
    if access:
        try:
            session_id = (await auth.authenticate(access)).session_id
        except SessionInvalidError:
            session_id = None
    refresh_token = request.cookies.get(REFRESH_COOKIE)
    if session_id is None and refresh_token:
        session = await uow.sessions.get_by_refresh_hash(hash_token(refresh_token))
        session_id = session.id if session else None
    if session_id is not None:
        await auth.logout(session_id)
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    clear_session_cookies(response, settings)
    return response


@router.get("/me", response_model=MeResponse, summary="The signed-in user")
async def me(
    ctx: AuthContext = Depends(current_context), uow: UnitOfWork = Depends(get_uow)
) -> MeResponse:
    user = await uow.users.get(ctx.user_id)
    if user is None:
        raise UnauthenticatedError()
    return await build_me(uow, user)


@router.get(
    "/invites/{token}",
    response_model=InvitePreview,
    summary="Preview a facility invitation (public, token-gated)",
)
async def invite_preview(
    token: str, auth: AuthService = Depends(get_auth_service), uow: UnitOfWork = Depends(get_uow)
) -> InvitePreview:
    invite = await auth.get_open_invite(token)
    facility = await uow.facilities.get(invite.facility_id)
    if facility is None:
        raise InviteInvalidError()
    return InvitePreview(
        email=invite.email,
        role=invite.role,
        facility=facility_summary(facility),
        expires_at=invite.expires_at,
    )


@router.post(
    "/invites/accept",
    response_model=MeResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Accept a facility invitation, create the account and sign in",
)
async def accept_invite(
    body: AcceptInviteRequest,
    request: Request,
    response: Response,
    auth: AuthService = Depends(get_auth_service),
    uow: UnitOfWork = Depends(get_uow),
    settings: Settings = Depends(get_settings),
) -> MeResponse:
    issued = await auth.accept_invite(body, client_info(request))
    set_session_cookies(response, issued, settings)
    return await build_me(uow, issued.user)
