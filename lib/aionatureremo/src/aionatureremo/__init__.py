"""Asynchronous Python client for the Nature Remo Cloud API."""

from .client import API_BASE_URL, NatureRemoClient
from .exceptions import (
    NatureRemoApiError,
    NatureRemoAuthError,
    NatureRemoConnectionError,
    NatureRemoError,
    NatureRemoRateLimitError,
)
from .models import (
    EVENT_HUMIDITY,
    EVENT_ILLUMINATION,
    EVENT_MOVEMENT,
    EVENT_TEMPERATURE,
    Device,
    RateLimit,
    SensorValue,
    User,
)

__version__ = "0.1.0"

__all__ = [
    "API_BASE_URL",
    "EVENT_HUMIDITY",
    "EVENT_ILLUMINATION",
    "EVENT_MOVEMENT",
    "EVENT_TEMPERATURE",
    "Device",
    "NatureRemoApiError",
    "NatureRemoAuthError",
    "NatureRemoClient",
    "NatureRemoConnectionError",
    "NatureRemoError",
    "NatureRemoRateLimitError",
    "RateLimit",
    "SensorValue",
    "User",
]
