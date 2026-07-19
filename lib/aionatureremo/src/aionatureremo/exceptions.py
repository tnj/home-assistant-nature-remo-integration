"""Exceptions raised by aionatureremo."""

from __future__ import annotations


class NatureRemoError(Exception):
    """Base exception for all aionatureremo errors."""


class NatureRemoConnectionError(NatureRemoError):
    """Raised when the API cannot be reached."""


class NatureRemoApiError(NatureRemoError):
    """Raised when the API returns an error status."""

    def __init__(self, status: int, message: str) -> None:
        """Initialize with the HTTP status and a short message."""
        super().__init__(f"HTTP {status}: {message}")
        self.status = status
        self.message = message


class NatureRemoAuthError(NatureRemoApiError):
    """Raised when the access token is invalid or revoked (HTTP 401)."""


class NatureRemoRateLimitError(NatureRemoApiError):
    """Raised when the API rate limit is exceeded (HTTP 429)."""

    def __init__(self, status: int, message: str, *, reset: int | None = None) -> None:
        """Initialize with the epoch second at which the limit resets."""
        super().__init__(status, message)
        self.reset = reset
