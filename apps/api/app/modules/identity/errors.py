"""Identity/auth error types. Each maps to an RFC 9457 problem with a stable ``code``."""

from __future__ import annotations

from app.core.errors import AppError


class EmailTakenError(AppError):
    status, code, title = 409, "email_taken", "An account with this email already exists"


class MobileTakenError(AppError):
    status, code, title = 409, "mobile_taken", "An account with this mobile number already exists"


class InvalidCredentialsError(AppError):
    status, code, title = 401, "invalid_credentials", "Incorrect email or password"


class AccountLockedError(AppError):
    status, code, title = 423, "account_locked", "Too many failed sign-in attempts"


class AccountDisabledError(AppError):
    status, code, title = 403, "account_disabled", "This account is disabled"


class VerificationRequiredError(AppError):
    status, code, title = 403, "verification_required", "Verify your mobile number to continue"


class ChallengeNotFoundError(AppError):
    status, code, title = 404, "challenge_not_found", "Verification request not found"


class ChallengeExpiredError(AppError):
    status, code, title = 410, "challenge_expired", "This verification request has expired"


class InvalidCodeError(AppError):
    status, code, title = 400, "invalid_code", "Incorrect verification code"


class TooManyAttemptsError(AppError):
    status, code, title = 429, "too_many_attempts", "Too many incorrect attempts"


class SessionInvalidError(AppError):
    status, code, title = 401, "session_invalid", "Your session has ended. Please sign in again"


class CsrfError(AppError):
    status, code, title = 403, "csrf_failed", "Security check failed. Refresh the page and retry"


class InviteInvalidError(AppError):
    status, code, title = 404, "invite_invalid", "This invitation is invalid or has expired"


class WeakPasswordError(AppError):
    status, code, title = 422, "validation_error", "Validation failed"
