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
from .models import (
    AirconSettings,
    Appliance,
    Device,
    LightState,
    RateLimit,
    TVState,
    User,
)

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

        async with response:
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

    async def get_appliances(self) -> list[Appliance]:
        """Return all appliances on the account."""
        data = await self._request("GET", "/1/appliances")
        return [Appliance.from_dict(item) for item in data]

    async def set_aircon_settings(
        self,
        appliance_id: str,
        *,
        operation_mode: str | None = None,
        temperature: str | None = None,
        air_volume: str | None = None,
        air_direction: str | None = None,
        air_direction_h: str | None = None,
        button: str | None = None,
        temperature_unit: str | None = None,
    ) -> AirconSettings:
        """Update AC settings; only provided fields are sent."""
        params = {
            "operation_mode": operation_mode,
            "temperature": temperature,
            "air_volume": air_volume,
            "air_direction": air_direction,
            "air_direction_h": air_direction_h,
            "button": button,
            "temperature_unit": temperature_unit,
        }
        data = await self._request(
            "POST",
            f"/1/appliances/{appliance_id}/aircon_settings",
            data={key: value for key, value in params.items() if value is not None},
        )
        return AirconSettings.from_dict(data or {})

    async def send_tv_button(self, appliance_id: str, button: str) -> TVState:
        """Press a TV button and return the new TV state."""
        data = await self._request(
            "POST", f"/1/appliances/{appliance_id}/tv", data={"button": button}
        )
        return TVState.from_dict(data or {})

    async def send_light_button(self, appliance_id: str, button: str) -> LightState:
        """Press a light button and return the new light state."""
        data = await self._request(
            "POST", f"/1/appliances/{appliance_id}/light", data={"button": button}
        )
        return LightState.from_dict(data or {})

    async def send_signal(self, signal_id: str) -> None:
        """Send a learned IR signal."""
        await self._request("POST", f"/1/signals/{signal_id}/send")
