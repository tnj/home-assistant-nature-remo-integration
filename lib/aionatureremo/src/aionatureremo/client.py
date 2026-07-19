"""Asynchronous client for the Nature Remo Cloud API."""

from __future__ import annotations

import json
from typing import Any

import aiohttp
from multidict import CIMultiDictProxy

from .exceptions import (
    NatureRemoApiError,
    NatureRemoAuthError,
    NatureRemoConnectionError,
    NatureRemoRateLimitError,
)
from .models import Device, RateLimit, User

API_BASE_URL = "https://api.nature.global"
_TIMEOUT = aiohttp.ClientTimeout(total=30)


class NatureRemoClient:
    """Client for api.nature.global using an injected aiohttp session."""

    def __init__(
        self,
        access_token: str,
        session: aiohttp.ClientSession,
        *,
        base_url: str = API_BASE_URL,
    ) -> None:
        """Initialize the client with a personal access token."""
        self._access_token = access_token
        self._session = session
        self._base_url = base_url.rstrip("/")
        self.rate_limit = RateLimit(limit=None, remaining=None, reset=None)

    async def _request(
        self, method: str, path: str, data: dict[str, str] | None = None
    ) -> Any:
        """Perform a request; POST bodies are form-urlencoded per the API."""
        try:
            response = await self._session.request(
                method,
                f"{self._base_url}{path}",
                headers={
                    "Authorization": f"Bearer {self._access_token}",
                    "Accept": "application/json",
                },
                data=data,
                timeout=_TIMEOUT,
            )
        except (aiohttp.ClientError, TimeoutError) as err:
            raise NatureRemoConnectionError(
                f"Error connecting to the Nature API: {err}"
            ) from err

        self._track_rate_limit(response.headers)

        if response.status == 401:
            raise NatureRemoAuthError(response.status, "Invalid access token")
        if response.status == 429:
            raise NatureRemoRateLimitError(
                response.status,
                "API rate limit exceeded",
                reset=self.rate_limit.reset,
            )
        if response.status >= 400:
            body = await response.text()
            raise NatureRemoApiError(response.status, body[:200])

        text = await response.text()
        return json.loads(text) if text else None

    def _track_rate_limit(self, headers: CIMultiDictProxy[str]) -> None:
        """Update rate limit state from response headers, if present."""

        def _int_header(name: str) -> int | None:
            try:
                return int(headers[name])
            except (KeyError, ValueError):
                return None

        limit = _int_header("X-Rate-Limit-Limit")
        remaining = _int_header("X-Rate-Limit-Remaining")
        reset = _int_header("X-Rate-Limit-Reset")
        if limit is not None or remaining is not None or reset is not None:
            self.rate_limit = RateLimit(limit=limit, remaining=remaining, reset=reset)

    async def get_user(self) -> User:
        """Return the account that owns the access token."""
        return User.from_dict(await self._request("GET", "/1/users/me"))

    async def get_devices(self) -> list[Device]:
        """Return all Nature Remo devices on the account."""
        data = await self._request("GET", "/1/devices")
        return [Device.from_dict(item) for item in data]

    async def set_temperature_offset(self, device_id: str, offset: int) -> Device:
        """Set the temperature offset (device-specific integer steps)."""
        data = await self._request(
            "POST",
            f"/1/devices/{device_id}/temperature_offset",
            data={"offset": str(offset)},
        )
        return Device.from_dict(data)

    async def set_humidity_offset(self, device_id: str, offset: int) -> Device:
        """Set the humidity offset (device-specific integer steps)."""
        data = await self._request(
            "POST",
            f"/1/devices/{device_id}/humidity_offset",
            data={"offset": str(offset)},
        )
        return Device.from_dict(data)
