from __future__ import annotations

from app.core.errors import AppError


class DeviceAlreadyAttachedError(AppError):
    status, code, title = 409, "device_already_attached", "This bag already has a device"


class NoDeviceError(AppError):
    status, code, title = 404, "no_device", "No simulated device is attached to this bag"


class SimulatorDisabledError(AppError):
    status, code, title = 403, "simulator_disabled", "The telemetry simulator is disabled"


class DeviceUnavailableError(AppError):
    status, code, title = 409, "device_unavailable", "The device can't take readings now"
