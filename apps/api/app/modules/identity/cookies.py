"""Session cookies.

- ``veyra_access``  httpOnly, path=/            short-lived JWT
- ``veyra_refresh`` httpOnly, path=<prefix>/auth rotating opaque token (never sent elsewhere)
- ``veyra_csrf``    readable by JS, path=/      double-submit token → ``X-CSRF-Token`` header
All are SameSite=Lax and Secure in production. The browser reaches the API same-origin
through the Next.js proxy, so these are first-party cookies.
"""

from __future__ import annotations

from fastapi import Response

from app.core.config import Settings
from app.modules.identity.service import IssuedSession

ACCESS_COOKIE = "veyra_access"
REFRESH_COOKIE = "veyra_refresh"
CSRF_COOKIE = "veyra_csrf"
CSRF_HEADER = "x-csrf-token"


def _refresh_path(settings: Settings) -> str:
    return f"{settings.api_prefix}/auth"


def set_session_cookies(response: Response, issued: IssuedSession, settings: Settings) -> None:
    secure = settings.secure_cookies
    response.set_cookie(
        ACCESS_COOKIE,
        issued.access_token,
        max_age=settings.access_token_ttl_seconds,
        path="/",
        httponly=True,
        secure=secure,
        samesite="lax",
    )
    response.set_cookie(
        REFRESH_COOKIE,
        issued.refresh_token,
        max_age=settings.refresh_token_ttl_seconds,
        path=_refresh_path(settings),
        httponly=True,
        secure=secure,
        samesite="lax",
    )
    response.set_cookie(
        CSRF_COOKIE,
        issued.csrf_token,
        max_age=settings.refresh_token_ttl_seconds,
        path="/",
        httponly=False,
        secure=secure,
        samesite="lax",
    )


def clear_session_cookies(response: Response, settings: Settings) -> None:
    secure = settings.secure_cookies
    response.delete_cookie(ACCESS_COOKIE, path="/", secure=secure, httponly=True, samesite="lax")
    response.delete_cookie(
        REFRESH_COOKIE, path=_refresh_path(settings), secure=secure, httponly=True, samesite="lax"
    )
    response.delete_cookie(CSRF_COOKIE, path="/", secure=secure, samesite="lax")
