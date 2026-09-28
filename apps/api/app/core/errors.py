"""Error model: every error leaves the API as RFC 9457 ``application/problem+json``.

Services raise ``AppError`` subclasses. Stack traces and internal messages are
never returned to clients; unexpected errors are logged with the request id.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.request_context import current_request_id

logger = logging.getLogger("veyra.errors")

PROBLEM_JSON = "application/problem+json"
PROBLEM_BASE = "https://veyra.dev/problems/"


class AppError(Exception):
    status: int = 400
    code: str = "bad_request"
    title: str = "Bad request"

    def __init__(self, detail: str | None = None, *, errors: list[dict[str, Any]] | None = None):
        super().__init__(detail or self.title)
        self.detail = detail or self.title
        self.errors = errors or []


class NotFoundError(AppError):
    status, code, title = 404, "not_found", "Resource not found"


class ConflictError(AppError):
    status, code, title = 409, "conflict", "Conflict"


class PermissionDeniedError(AppError):
    status, code, title = 403, "forbidden", "Permission denied"


class UnauthenticatedError(AppError):
    status, code, title = 401, "unauthenticated", "Authentication required"


def problem(
    status: int,
    code: str,
    title: str,
    detail: str | None = None,
    errors: list[dict[str, Any]] | None = None,
    *,
    request_id: str | None = None,
) -> JSONResponse:
    rid = request_id or current_request_id()
    body: dict[str, Any] = {
        "type": PROBLEM_BASE + code,
        "title": title,
        "status": status,
        "code": code,
        "detail": detail or title,
        "request_id": rid,
    }
    if errors:
        body["errors"] = errors
    headers = {"x-request-id": rid} if rid and request_id else None
    return JSONResponse(body, status_code=status, media_type=PROBLEM_JSON, headers=headers)


_HTTP_CODES = {
    400: "bad_request",
    401: "unauthenticated",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    429: "rate_limited",
}


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError) -> JSONResponse:
        return problem(exc.status, exc.code, exc.title, exc.detail, exc.errors)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        errors = [
            {"loc": list(e.get("loc", [])), "msg": e.get("msg", ""), "type": e.get("type", "")}
            for e in exc.errors()
        ]  # input values are deliberately not echoed back
        return problem(422, "validation_error", "Validation failed", "Request is invalid", errors)

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = _HTTP_CODES.get(exc.status_code, "http_error")
        title = str(exc.detail) if exc.status_code < 500 else "Internal server error"
        return problem(exc.status_code, code, title)

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        rid = request.scope.get("state", {}).get("request_id")
        logger.exception("unhandled_error", exc_info=exc, extra={"extra_fields": {"rid": rid}})
        return problem(500, "internal_error", "Internal server error", request_id=rid)
