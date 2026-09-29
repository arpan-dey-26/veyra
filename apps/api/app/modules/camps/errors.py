from __future__ import annotations

from app.core.errors import AppError


class InvalidCampTransitionError(AppError):
    status, code, title = 409, "invalid_camp_transition", "This camp can't move to that state"


class CampNotEditableError(AppError):
    status, code, title = 409, "camp_not_editable", "This camp can no longer be edited"


class CampFullError(AppError):
    status, code, title = 409, "camp_full", "This camp is full"


class RegistrationClosedError(AppError):
    status, code, title = 409, "registration_closed", "Registration is not open for this camp"


class AlreadyRegisteredError(AppError):
    status, code, title = 409, "already_registered", "You are already registered for this camp"


class InvalidRegistrationStateError(AppError):
    status, code, title = (
        409,
        "invalid_registration_state",
        "This registration can't be changed that way",
    )


class DonorNotVerifiedError(AppError):
    status, code, title = 403, "donor_not_verified", "Verify your account before registering"


class InvalidCampError(AppError):
    status, code, title = 422, "invalid_camp", "Invalid camp details"
