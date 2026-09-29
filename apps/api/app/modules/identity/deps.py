"""Request-level auth dependencies shared by every module.

- ``current_context``   → AuthContext or 401 (cookie or ``Authorization: Bearer``)
- ``require(p)``        → AuthContext with permission ``p`` or 403
- ``csrf_protect``      → double-submit check for cookie-authenticated unsafe requests
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from fastapi import Depends, Request

from app.core.clock import Clock, SystemClock
from app.core.config import Settings, get_settings
from app.core.errors import PermissionDeniedError, UnauthenticatedError
from app.core.rbac import AuthContext, Permission
from app.core.security import AccessTokenCodec, PasswordHasher, constant_time_equals
from app.modules.identity.cookies import ACCESS_COOKIE, CSRF_COOKIE, CSRF_HEADER
from app.modules.identity.errors import CsrfError, SessionInvalidError
from app.modules.identity.service import AuthService, ClientInfo
from app.persistence.deps import get_uow
from app.persistence.repositories import UnitOfWork
from app.providers.verification import VerificationProvider, build_verification_provider


def get_clock(request: Request) -> Clock:
    clock: Clock = getattr(request.app.state, "clock", None) or SystemClock()
    return clock


def get_verification_provider(
    request: Request, settings: Settings = Depends(get_settings)
) -> VerificationProvider:
    provider: VerificationProvider | None = getattr(request.app.state, "verification", None)
    if provider is None:
        provider = build_verification_provider(settings)
        request.app.state.verification = provider
    return provider


def get_auth_service(
    request: Request,
    uow: UnitOfWork = Depends(get_uow),
    settings: Settings = Depends(get_settings),
    clock: Clock = Depends(get_clock),
    verification: VerificationProvider = Depends(get_verification_provider),
) -> AuthService:
    hasher: PasswordHasher = request.app.state.hasher
    tokens: AccessTokenCodec = request.app.state.tokens
    return AuthService(
        uow,
        settings=settings,
        clock=clock,
        hasher=hasher,
        tokens=tokens,
        verification=verification,
    )


def client_info(request: Request) -> ClientInfo:
    return ClientInfo(
        ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )


def _bearer(request: Request) -> str | None:
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    return token.strip() if scheme.lower() == "bearer" and token.strip() else None


async def current_context(
    request: Request, auth: AuthService = Depends(get_auth_service)
) -> AuthContext:
    token = _bearer(request) or request.cookies.get(ACCESS_COOKIE)
    if not token:
        raise UnauthenticatedError()
    try:
        ctx = await auth.authenticate(token)
    except SessionInvalidError as exc:
        raise UnauthenticatedError("Your session has ended. Please sign in again") from exc
    request.state.auth = ctx
    return ctx


def require(permission: Permission) -> Callable[..., Awaitable[AuthContext]]:
    async def _dependency(ctx: AuthContext = Depends(current_context)) -> AuthContext:
        if not ctx.has(permission):
            raise PermissionDeniedError()
        return ctx

    _dependency.__name__ = f"require_{permission.name.lower()}"
    return _dependency


def require_any(*permissions: Permission) -> Callable[..., Awaitable[AuthContext]]:
    """AuthContext holding at least one of ``permissions`` or 403 (the service applies scope)."""

    async def _dependency(ctx: AuthContext = Depends(current_context)) -> AuthContext:
        if not any(ctx.has(p) for p in permissions):
            raise PermissionDeniedError()
        return ctx

    _dependency.__name__ = "require_any_" + "_".join(p.name.lower() for p in permissions)
    return _dependency


async def csrf_protect(request: Request) -> None:
    """Unsafe requests authenticated by cookie must echo the CSRF cookie in a header.

    Bearer-token clients are not exposed to CSRF (browsers never attach the header).
    """
    if request.method in ("GET", "HEAD", "OPTIONS") or _bearer(request):
        return
    has_session_cookie = any(name in request.cookies for name in (ACCESS_COOKIE, "veyra_refresh"))
    if not has_session_cookie:
        return
    cookie = request.cookies.get(CSRF_COOKIE, "")
    header = request.headers.get(CSRF_HEADER, "")
    if not cookie or not header or not constant_time_equals(cookie, header):
        raise CsrfError()
